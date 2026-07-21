"""Gate audit for an EXP-41 replicate. Run at 5%, 40% and 100%.

The experiment's claim is that three dispatches were independent draws from one
frozen configuration. That claim is only worth what it is checked against, so
every check it depends on lives here and runs at every gate, mechanically.

Exit codes:
    0  all hard checks pass
    1  a hard check FAILED -- stop the run, do not continue to the next stage
    2  could not run the audit (missing DB, bad args)

Soft checks (rate comparisons against baseline) never fail the gate on their
own. They print a verdict and a binomial p-value so a human can judge. A rate
that looks wrong on a country-ordered battery is usually just the country block
in flight, which is why every rate here is compared per country.

    uv run python scripts/audit_exp41_gate.py --experiment-id exp41_stability_rep1
    uv run python scripts/audit_exp41_gate.py --experiment-id exp41_stability_rep2 --expect 8
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from math import comb
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"

# D47 held-out eight. Their presence in any arm voids the frozen evaluation.
HELD_OUT = ("BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE")

# D24. The evaluation cycle publishes its own answers; a run that reads them is
# scoring against its own source. Checked over every column that can carry a
# URL, not just the committed one.
DENY_HOSTS = (
    "data.europa.eu", "opendatamaturity", "europeandataportal",
    # Translation mirrors defeat both exact and subdomain matching by mangling
    # the host. Detection only -- the runtime deny-list is not changed
    # mid-campaign, since that would alter the swarm between replicates.
    "data-europa-eu.translate.goog",
)

# Strings that only appear if the evaluation's own published answers were read.
# The deny-list works on hosts; this catches the content arriving by any route.
ODMI_LABEL_TOKENS = (
    "trend-setter", "trend setter", "fast-tracker", "fast tracker",
    "follower", "beginner", "open data maturity index",
)

# The swarm's runtime path. If any of this changes between replicates, the
# three runs are not the same system and the campaign is void. Unrelated work
# elsewhere in the repo (docs, figures, analysis) is allowed and expected --
# other sessions share this checkout -- so the guard fingerprints exactly the
# files that decide swarm behaviour rather than freezing HEAD.
RUNTIME_PATHS = ("agents", "scripts/run_coordinator.py", "scripts/dispatch_subtrios.py")
FINGERPRINT = REPO / "evaluation" / "runs" / "exp41_provenance" / "runtime_fingerprint.txt"

BASELINE_EXP, BASELINE_LABEL = "exp34_retrieval_strategy_s46", "wide_only"
EXPECTED_MODEL = "claude-sonnet-4-6"
REPLICATES = ("exp41_stability_rep1", "exp41_stability_rep2", "exp41_stability_rep3")

FROZEN_EXPECT = {
    "provider": "diy", "search_strategy": "wide_only", "max_results_per_query": 5,
    "num_queries": 3, "query_language": "bilingual", "strategy": "verifier-disprove",
    "verifier_prompt_variant": "default", "prompt_variant": "full",
    "verifier_search": "always", "adjudicator_selection": "standard",
    "max_retries": 3, "snippet_picker": "on", "max_snippet_chars": 600,
    "picker_max_chunks": 3, "page_text_cap": 16000, "no_cache": True,
    "pipeline_mode": "trio", "researcher_model": EXPECTED_MODEL,
    "verifier_model": EXPECTED_MODEL, "adjudicator_model": EXPECTED_MODEL,
    "picker_model": EXPECTED_MODEL,
}

hard_failures: list[str] = []
notes: list[str] = []


def hard(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        hard_failures.append(f"{label}: {detail}")


def soft(label: str, detail: str) -> None:
    print(f"  [ .. ] {label} -- {detail}")
    notes.append(f"{label}: {detail}")


def runtime_fingerprint() -> str:
    """SHA-256 over every file that decides swarm behaviour."""
    h = hashlib.sha256()
    files: list[Path] = []
    for rel in RUNTIME_PATHS:
        p = REPO / rel
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])
    for f in sorted(files):
        if f.exists():
            h.update(f.relative_to(REPO).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def binom_tail(n: int, k: int, p: float) -> float:
    """P(X >= k) under Binomial(n, p). Exact, no scipy dependency."""
    if n == 0 or p <= 0:
        return 1.0
    return min(1.0, sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def canonical_baseline(c: sqlite3.Connection) -> dict[str, dict]:
    """Per-country failure rate and coverage on the pre-EXP-41 incumbent run.

    Per country, because the battery is ordered MT then NL then AL and the three
    behave very differently. A whole-battery rate compared against a part-run
    sample reads Malta's ordinary difficulty as a regression.
    """
    rows = c.execute(
        """WITH canon AS (
             SELECT f.country_code, f.terminal_status,
                    ROW_NUMBER() OVER (PARTITION BY f.question_id||':'||f.country_code
                                       ORDER BY f.id DESC) rn
             FROM phase2_final f
             JOIN phase2_researcher_runs r ON r.pair_run_id = f.pair_run_id
             WHERE f.experiment_id = ? AND r.condition_label = ?)
           SELECT country_code, COUNT(*),
                  SUM(terminal_status = 'agent_failure'),
                  SUM(terminal_status LIKE 'accepted%')
           FROM canon WHERE rn = 1 GROUP BY 1""",
        (BASELINE_EXP, BASELINE_LABEL),
    ).fetchall()
    return {
        cc: {"n": n, "fail_rate": f / n if n else 0.0, "coverage": a / n if n else 0.0}
        for cc, n, f, a in rows
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--experiment-id", required=True)
    ap.add_argument("--expect", type=int, default=None,
                    help="Pairs this stage should have finalised; checked exactly.")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"ERROR: {args.db} not found")
        return 2

    eid = args.experiment_id
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    print(f"\n=== EXP-41 gate audit: {eid} ===\n")

    try:
        n_final = c.execute(
            "SELECT COUNT(*) FROM phase2_final WHERE experiment_id=?", (eid,)
        ).fetchone()[0]
        if n_final == 0:
            print("  no rows yet; nothing to audit")
            return 2
        print(f"  {n_final} pairs finalised\n")

        print("-- hard checks (any FAIL stops the run) --")

        # 1. Frozen evaluation set. A held-out country here voids EXP-36.
        bad_cc = [r[0] for r in c.execute(
            "SELECT DISTINCT country_code FROM phase2_final WHERE experiment_id=?", (eid,))
            if r[0] in HELD_OUT]
        hard(not bad_cc, "no D47 held-out country in the arm", ", ".join(bad_cc))

        # 2. Model pinning. model_defaults still carries a cut Sonnet 5 row, so
        #    an unpinned role would resolve to a banned model.
        for tbl in ("phase2_researcher_runs", "phase2_verifier_runs"):
            models = [r[0] for r in c.execute(
                f"SELECT DISTINCT model_version FROM {tbl} WHERE experiment_id=? "
                f"AND model_version IS NOT NULL", (eid,))]
            wrong = [m for m in models if m != EXPECTED_MODEL]
            hard(not wrong, f"{tbl} model is {EXPECTED_MODEL}", ", ".join(wrong))

        # 3. D24 deny-list, over every column that can carry a URL. The EXP-36
        #    audit found the verifier counter-search bypassing it, so committed
        #    rows alone are not a sufficient check.
        like = " OR ".join(
            f"{col} LIKE '%{h}%'"
            for col in ("final_source_url",) for h in DENY_HOSTS)
        n_deny = c.execute(
            f"SELECT COUNT(*) FROM phase2_final WHERE experiment_id=? AND ({like})",
            (eid,)).fetchone()[0]
        hard(n_deny == 0, "no deny-listed host in any final row", f"{n_deny} rows")

        # The guard is "did the swarm RETRIEVE from a deny-listed host", not "did
        # any page mention the EU portal". A plain substring match over the
        # snippets blob conflates the two and fires on prose: third-party
        # open-data pages routinely say a catalogue "is harvested into
        # data.europa.eu". So URL-bearing fields are matched structurally, and
        # text mentions are counted separately as information, not failure.
        n_url_hits, n_text_hits = 0, 0
        for (surl, furls, snips) in c.execute(
            "SELECT source_url, fetched_urls, search_snippets FROM phase2_researcher_runs "
            "WHERE experiment_id=?", (eid,)
        ):
            urls: list[str] = [surl or ""]
            for blob in (furls, snips):
                if not blob:
                    continue
                try:
                    parsed = json.loads(blob)
                except (ValueError, TypeError):
                    urls.append(str(blob))  # not JSON: fall back to the raw string
                    continue
                stack = [parsed]
                while stack:
                    node = stack.pop()
                    if isinstance(node, dict):
                        for k, v in node.items():
                            if isinstance(v, str) and ("url" in k.lower() or "link" in k.lower()):
                                urls.append(v)
                            elif isinstance(v, (dict, list)):
                                stack.append(v)
                            elif isinstance(v, str) and any(h in v for h in DENY_HOSTS):
                                n_text_hits += 1
                    elif isinstance(node, list):
                        stack.extend(node)
                    elif isinstance(node, str):
                        urls.append(node)
            if any(h in u for u in urls for h in DENY_HOSTS):
                n_url_hits += 1

        hard(n_url_hits == 0, "no deny-listed host in any retrieved URL",
             f"{n_url_hits} researcher rows")
        if n_text_hits:
            soft("deny-listed host mentioned in snippet prose",
                 f"{n_text_hits} occurrences -- benign when retrieved URLs are clean; "
                 f"third-party pages mention the EU portal in passing")

        vcols = {r[1] for r in c.execute("PRAGMA table_info(phase2_verifier_runs)")}
        if "counter_source_url" in vcols:
            vlike = " OR ".join(f"counter_source_url LIKE '%{h}%'" for h in DENY_HOSTS)
            n_deny_v = c.execute(
                f"SELECT COUNT(*) FROM phase2_verifier_runs WHERE experiment_id=? AND ({vlike})",
                (eid,)).fetchone()[0]
            hard(n_deny_v == 0, "no deny-listed host in verifier counter-search",
                 f"{n_deny_v} rows")

        # 4. Independence. A pair_run_id shared with another replicate would mean
        #    one run inherited another's work rather than redoing it.
        others = [e for e in REPLICATES if e != eid]
        shared = c.execute(
            f"""SELECT COUNT(*) FROM phase2_researcher_runs a
                WHERE a.experiment_id = ?
                  AND a.pair_run_id IN (SELECT pair_run_id FROM phase2_researcher_runs
                                        WHERE experiment_id IN ({','.join('?'*len(others))}))""",
            (eid, *others)).fetchone()[0]
        hard(shared == 0, "no pair_run_id shared with another replicate", f"{shared} rows")

        # 5. Sample integrity: exactly the pre-registered battery, nothing extra.
        dupes = c.execute(
            "SELECT COUNT(*) FROM (SELECT question_id, country_code FROM phase2_final "
            "WHERE experiment_id=? GROUP BY 1,2 HAVING COUNT(*) > 1)", (eid,)).fetchone()[0]
        hard(dupes == 0, "no duplicate pair rows", f"{dupes} pairs duplicated")

        spec = REPO / "evaluation" / "specs" / f"{eid}.json"
        if spec.exists():
            want = set(json.loads(spec.read_text())["experiments"][0]["pairs"])
            got = {f"{q}:{cc}" for q, cc in c.execute(
                "SELECT question_id, country_code FROM phase2_final WHERE experiment_id=?",
                (eid,))}
            hard(got <= want, "every finalised pair is in the pre-registered battery",
                 ", ".join(sorted(got - want)[:5]))
            knobs = json.loads(spec.read_text())["experiments"][0]["baseline_knobs"]
            drift = {k: (v, knobs.get(k)) for k, v in FROZEN_EXPECT.items() if knobs.get(k) != v}
            hard(not drift, "spec knobs match the frozen configuration", str(drift))

        if args.expect is not None:
            hard(n_final == args.expect, f"stage size is exactly {args.expect}",
                 f"found {n_final}")

        # 6. Runtime immutability. Other sessions share this checkout, so the
        #    guard is a fingerprint of the swarm path rather than a frozen HEAD:
        #    docs and figures may land, agents/ may not.
        fp_now = runtime_fingerprint()
        if FINGERPRINT.exists():
            fp_at_start = FINGERPRINT.read_text().strip()
            hard(fp_now == fp_at_start, "swarm runtime code unchanged since campaign start",
                 f"fingerprint moved {fp_at_start[:12]} -> {fp_now[:12]}")
        else:
            FINGERPRINT.parent.mkdir(parents=True, exist_ok=True)
            FINGERPRINT.write_text(fp_now + "\n")
            print(f"  [ .. ] runtime fingerprint recorded: {fp_now[:12]}")

        # 7. Researcher-evidence replay. `_find_resumable_researcher` reuses a
        #    prior attempt-1 Researcher row instead of retrieving again, and
        #    marks the superseded subtrio. It is scoped on
        #    (experiment_id, condition_label), which a replicate shares with
        #    itself across any re-dispatch, so a killed or crashed run can leave
        #    pairs whose evidence is replayed rather than redrawn. That is the
        #    EXP-40 seeding mechanism arriving by accident, on the one metric
        #    built to measure redrawn evidence. It has fired before: exp36 (11
        #    pairs) and exp34 (1) carry superseded rows.
        n_sup = c.execute(
            "SELECT COUNT(*) FROM subtrio_status WHERE experiment_id=? AND stage='superseded'",
            (eid,)).fetchone()[0]
        hard(n_sup == 0, "no Researcher evidence replayed within the replicate",
             f"{n_sup} superseded subtrios -- those pairs did not redraw evidence")

        # 8. Content-level answer-key leakage. The deny-list filters hosts; this
        #    catches ODMI's own scoring vocabulary arriving by any other route.
        n_label = 0
        for (q, cc, quote, expl) in c.execute(
            "SELECT question_id, country_code, final_evidence_quote, "
            "final_answer_explanation FROM phase2_final WHERE experiment_id=?", (eid,)
        ):
            blob = f"{quote or ''} {expl or ''}".lower()
            if any(tok in blob for tok in ODMI_LABEL_TOKENS):
                n_label += 1
        hard(n_label == 0, "no ODMI scoring vocabulary in committed evidence",
             f"{n_label} rows")

        # 9. Retrieval actually happened. All-empty evidence would make the run
        #    look stable for the wrong reason.
        n_r, n_snip = c.execute(
            "SELECT COUNT(*), SUM(search_snippets IS NOT NULL AND search_snippets != '') "
            "FROM phase2_researcher_runs WHERE experiment_id=?", (eid,)).fetchone()
        hard((n_snip or 0) > 0, "researcher rows carry retrieved evidence",
             f"{n_snip or 0}/{n_r}")

        print("\n-- soft checks (judgement, never auto-fail) --")

        # Two references. exp34 wide_only is the pre-EXP-41 incumbent, but it
        # predates three run-path changes (B1/B2, the deny-list scrub, and the
        # D7 floor-leak fix), so a deviation from it is expected and not by
        # itself a fault. A completed sibling replicate is the sharper
        # comparison: same code, same config, hours apart, and any gap between
        # them is the quantity this experiment exists to measure.
        base = canonical_baseline(c)
        sibling = next(
            (e for e in REPLICATES if e != eid and c.execute(
                "SELECT COUNT(*) FROM phase2_final WHERE experiment_id=?", (e,)
            ).fetchone()[0] >= 150), None)
        sib = {}
        if sibling:
            sib = {cc: {"n": n, "fail_rate": (f or 0) / n, "coverage": (a or 0) / n}
                   for cc, n, f, a in c.execute(
                       "SELECT country_code, COUNT(*), "
                       "SUM(terminal_status='agent_failure'), "
                       "SUM(terminal_status LIKE 'accepted%') FROM phase2_final "
                       "WHERE experiment_id=? GROUP BY 1", (sibling,)) if n}
            print(f"  (sibling reference: {sibling})")

        per_cc = c.execute(
            "SELECT country_code, COUNT(*), SUM(terminal_status='agent_failure'), "
            "SUM(terminal_status LIKE 'accepted%') FROM phase2_final "
            "WHERE experiment_id=? GROUP BY 1", (eid,)).fetchall()
        for cc, n, nf, na in per_cc:
            b = base.get(cc)
            if not b:
                soft(f"{cc}", f"{n} pairs, no baseline to compare")
                continue
            p = binom_tail(n, nf or 0, b["fail_rate"])
            extra = ""
            if cc in sib:
                ps = binom_tail(n, nf or 0, sib[cc]["fail_rate"])
                extra = (f"; vs sibling {sib[cc]['fail_rate']:.3f}, P = {ps:.3f}"
                         + ("  <-- LOOK" if ps < 0.05 else ""))
            flag = "  <-- LOOK" if p < 0.05 else ""
            soft(f"{cc} failure rate",
                 f"{(nf or 0)}/{n} = {(nf or 0)/n:.3f} vs exp34 {b['fail_rate']:.3f}, "
                 f"P(X>=k) = {p:.3f}{flag}{extra}")
            cov_extra = f"; sibling {sib[cc]['coverage']:.3f}" if cc in sib else ""
            soft(f"{cc} coverage",
                 f"{(na or 0)}/{n} = {(na or 0)/n:.3f} vs exp34 {b['coverage']:.3f}{cov_extra}")

        rows = c.execute(
            "SELECT SUM(final_answer_confidence = 0.65), COUNT(*) FROM phase2_final "
            "WHERE experiment_id=? AND terminal_status LIKE 'accepted%'", (eid,)).fetchone()
        if rows and rows[1]:
            soft("M6 floor pile-up (post-D7-fix)",
                 f"{rows[0] or 0}/{rows[1]} commits at exactly 0.65 "
                 f"(exp34 baseline: 9.4% first-attempt, 32.7% retried)")

        reasons = c.execute(
            "SELECT COALESCE(final_failure_reason,'(none)'), COUNT(*) FROM phase2_final "
            "WHERE experiment_id=? AND terminal_status='agent_failure' GROUP BY 1 "
            "ORDER BY 2 DESC", (eid,)).fetchall()
        if reasons:
            soft("failure reasons", "; ".join(f"{r}={n}" for r, n in reasons))

        print()
        if hard_failures:
            print(f"GATE FAILED -- {len(hard_failures)} hard check(s) failed:")
            for f in hard_failures:
                print(f"  - {f}")
            print("Stop the run. Do not proceed to the next stage.")
            return 1
        print("GATE PASSED -- all hard checks clean. Soft checks above need a human read.")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
