"""False-positive / error cluster analysis for the failure-mode taxonomy.

Clusters the swarm's committed-wrong answers by ODMI dimension, answerability
class (web / self_report / catalogue, the subjective-vs-objective proxy), and
ODMI assessor decision (confirm / complement / change). Writes a markdown
findings file plus a per-pair CSV to evaluation/results/fp_cluster/.

Primary source: the d50_neg_licence_confirm `baseline_full` arm (NL 52 + MT 45,
binary, claude-sonnet-4-6, production config) - the freshest on-config dev data.
Cross-check source: main/NULL runs on dev countries (older, config-mixed).

FP (false positive) = swarm commits `yes`, gold is `no` (claims a capability
the country does not have). FN = swarm commits `no`, gold is `yes`.

Run: uv run python evaluation/fp_cluster.py
No dispatch, no API, read-only against data/odmi.db.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "odmi.db"
OUTDIR = REPO / "evaluation" / "results" / "fp_cluster"
ANSWERABILITY = REPO / "data" / "questions" / "answerability.json"

DIMS = ["Policy", "Portal", "Quality", "Impact"]
ACLS = ["web", "self_report", "catalogue"]


def norm(a: str) -> str:
    a = (a or "").strip().lower()
    if a in ("inconclusive", ""):
        return "abstain"
    if a.startswith("yes"):
        return "yes"
    if a == "no":
        return "no"
    return "other"


def goldnorm(g: str) -> str:
    g = (g or "").strip().lower()
    return "no" if g == "no" else ("yes" if g.startswith("yes") else "other")


def load_meta() -> dict:
    ans = json.load(open(ANSWERABILITY))
    return {q["question_id"]: q for q in ans["questions"]}


def d50_baseline_rows(c) -> list:
    """Canonical latest final per (q, country) for the baseline_full arm."""
    return c.execute(
        """
        WITH base AS (
          SELECT f.question_id, f.country_code, f.final_answer, f.created_at
          FROM phase2_final f
          JOIN phase2_researcher_runs r ON r.pair_run_id = f.pair_run_id
          WHERE f.experiment_id = 'd50_neg_licence_confirm'
            AND r.condition_label = 'baseline_full'),
        latest AS (
          SELECT question_id, country_code, final_answer,
                 ROW_NUMBER() OVER (PARTITION BY question_id, country_code
                                    ORDER BY created_at DESC) rn
          FROM base)
        SELECT l.question_id, l.country_code, l.final_answer, g.response, g.decision
        FROM latest l
        JOIN ground_truth g ON g.question_id = l.question_id
                            AND g.country_code = l.country_code
        WHERE l.rn = 1
        """
    ).fetchall()


def main_null_rows(c) -> list:
    return c.execute(
        """
        WITH latest AS (
          SELECT f.question_id, f.country_code, f.final_answer,
                 ROW_NUMBER() OVER (PARTITION BY f.question_id, f.country_code
                                    ORDER BY f.created_at DESC) rn
          FROM phase2_final f
          WHERE f.experiment_id IS NULL
            AND f.country_code IN ('NO','MT','FR','NL','AL'))
        SELECT l.question_id, l.country_code, l.final_answer, g.response, g.decision
        FROM latest l
        JOIN ground_truth g ON g.question_id = l.question_id
                            AND g.country_code = l.country_code
        WHERE l.rn = 1
        """
    ).fetchall()


def classify(rows, meta):
    """Return per-pair records + aggregate counters."""
    recs = []
    agg = {
        "committed": 0, "match": 0, "abstain": 0, "fp": [], "fn": [],
        "dim_fp": Counter(), "dim_neg": Counter(), "dim_committed": Counter(),
        "acls_fp": Counter(), "acls_neg": Counter(), "acls_committed": Counter(),
        "dec_fp": Counter(), "dec_neg": Counter(), "dec_committed": Counter(),
    }
    for qid, cc, fa, gold, dec in rows:
        m = meta.get(qid, {})
        dim, acls = m.get("dimension", "?"), m.get("answerability", "?")
        dec = dec or "?"
        a, g = norm(fa), goldnorm(gold)
        if g == "no":
            agg["dim_neg"][dim] += 1
            agg["acls_neg"][acls] += 1
            agg["dec_neg"][dec] += 1
        outcome = "abstain"
        if a == "abstain":
            agg["abstain"] += 1
        elif a == "other":
            outcome = "other"
        else:
            agg["committed"] += 1
            agg["dim_committed"][dim] += 1
            agg["acls_committed"][acls] += 1
            agg["dec_committed"][dec] += 1
            if a == g:
                outcome, agg["match"] = "match", agg["match"] + 1
            elif g == "no" and a == "yes":
                outcome = "FP"
                agg["fp"].append((qid, cc, dim, acls, dec))
                agg["dim_fp"][dim] += 1
                agg["acls_fp"][acls] += 1
                agg["dec_fp"][dec] += 1
            elif g == "yes" and a == "no":
                outcome = "FN"
                agg["fn"].append((qid, cc, dim, acls, dec))
            else:
                outcome = "differ_other"
        recs.append({
            "question_id": qid, "country": cc, "dimension": dim,
            "answerability": acls, "decision": dec,
            "swarm": a, "gold": g, "outcome": outcome,
        })
    return recs, agg


def rate(n, d):
    return f"{n}/{d} = {n / d:.2f}" if d else f"{n}/0 = n/a"


def render(agg, meta, question_text) -> str:
    fp, fn = agg["fp"], agg["fn"]
    L = []
    L.append(f"- Committed binary pairs: {agg['committed']}  |  match {agg['match']}"
             f"  |  abstained {agg['abstain']}")
    L.append(f"- False positives (yes / gold no): **{len(fp)}**"
             f"  |  false negatives (no / gold yes): **{len(fn)}**")
    if agg["committed"]:
        L.append(f"- Commit accuracy: {rate(agg['match'], agg['committed'])}")
    L.append("")
    L.append("**FP by ODMI dimension** (FP / negative golds in dimension):")
    for d in DIMS:
        L.append(f"- {d}: {rate(agg['dim_fp'][d], agg['dim_neg'][d])}"
                 f"  (committed {agg['dim_committed'][d]})")
    L.append("")
    L.append("**FP by answerability** (subjective/objective proxy):")
    for k in ACLS:
        L.append(f"- {k}: {rate(agg['acls_fp'][k], agg['acls_neg'][k])}"
                 f"  (committed {agg['acls_committed'][k]})")
    L.append("")
    L.append("**FP by ODMI decision:**")
    for k in sorted(agg["dec_committed"]):
        L.append(f"- {k}: {rate(agg['dec_fp'][k], agg['dec_neg'][k])}"
                 f"  (committed {agg['dec_committed'][k]})")
    L.append("")
    L.append("**FP question list** (id:country - dimension / answerability / decision):")
    for qid, cc, dim, acls, dec in fp:
        txt = (question_text.get(qid, "") or "")[:90].replace("\n", " ")
        L.append(f"- `{qid}:{cc}` - {dim} / {acls} / {dec} - \"{txt}\"")
    return "\n".join(L)


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    meta = load_meta()
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()
    qtext = dict(c.execute("SELECT question_id, question_text FROM questions").fetchall())

    d50_rows = d50_baseline_rows(c)
    main_rows = main_null_rows(c)
    d50_recs, d50_agg = classify(d50_rows, meta)
    main_recs, main_agg = classify(main_rows, meta)

    md = []
    md.append("# False-positive / error cluster analysis")
    md.append("")
    md.append("Failure-mode taxonomy input. Generated by `evaluation/fp_cluster.py` "
              "(re-run to refresh). Read-only over `data/odmi.db`.")
    md.append("")
    md.append("FP = swarm commits `yes`, ODMI gold is `no` (claims a capability the "
              "country lacks). FN = swarm commits `no`, gold is `yes`.")
    md.append("")
    md.append("## Primary source: on-config dev data")
    md.append("")
    md.append("`d50_neg_licence_confirm` **baseline_full** arm - NL 52 + MT 45 binary "
              "pairs, claude-sonnet-4-6, production config (picker on, "
              "verifier_search always, narrow_then_wide, DIY). The freshest data on "
              "the exact frozen configuration.")
    md.append("")
    md.append(render(d50_agg, meta, qtext))
    md.append("")
    md.append("## Cross-check source: main/NULL dev runs (older, config-mixed)")
    md.append("")
    md.append("Accumulated production runs, `experiment_id IS NULL`, dev countries "
              "NO+MT+FR+NL+AL. Pre-D62 transport, mixed config; directional only. FR "
              "is ~all-yes so contributes almost no negative golds.")
    md.append("")
    md.append(render(main_agg, meta, qtext))
    md.append("")
    md.append("## Reading (facts, not write-up)")
    md.append("")
    md.append("- FPs are on **objective existence questions** (does the portal offer "
              "X, is impact data available), not subjective ones. `web`-answerable "
              "questions carry the FPs; `self_report` mostly abstains so cannot "
              "become an FP; `catalogue` questions bypass the LLM commit path.")
    md.append("- Mechanism: the specific feature is absent but a **related general "
              "artefact exists** (the portal, a strategy doc); the swarm reads "
              "presence-of-general as confirmation-of-specific (adjacent-evidence "
              "over-read; inability to prove absence).")
    md.append("- FPs concentrate on `confirm`-decision negative golds in **both** the "
              "on-config and the older cross-check source - the one pattern that "
              "survives the config change.")
    md.append("- Country effect: the on-config FPs are almost all Netherlands; Malta "
              "abstains on its negative golds instead of committing, so its failure "
              "mode is over-abstention, not over-commitment.")
    md.append("- Config-era contrast: older main/NULL data is FN-heavy (conservative); "
              "the current config is FP-heavy. Error *direction* is config-dependent; "
              "the confirm-cluster and over-read mechanism are not.")
    md.append("")
    md.append("## Caveats")
    md.append("")
    md.append("- Modest n; on-config FP set is NL-dominated.")
    md.append("- Held-out preview data (expC_held, exp21) excluded - voided per D57.")
    md.append("- `self_report` is a keyword first-pass tag (`answerability.json`), not "
              "hand-verified.")
    md.append("- main/NULL mixes configs and countries; directional cross-check only.")
    md.append("")

    md_path = OUTDIR / "fp_cluster_analysis.md"
    md_path.write_text("\n".join(md))

    for name, recs in [("d50_baseline_full", d50_recs), ("main_null_dev", main_recs)]:
        csv_path = OUTDIR / f"fp_cluster_pairs_{name}.csv"
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
            w.writeheader()
            w.writerows(recs)

    print(f"wrote {md_path}")
    print(f"wrote {OUTDIR}/fp_cluster_pairs_d50_baseline_full.csv "
          f"({len(d50_recs)} pairs)")
    print(f"wrote {OUTDIR}/fp_cluster_pairs_main_null_dev.csv "
          f"({len(main_recs)} pairs)")
    print(f"\nD50 baseline_full: {len(d50_agg['fp'])} FP, {len(d50_agg['fn'])} FN, "
          f"{d50_agg['committed']} committed")
    print(f"main/NULL dev: {len(main_agg['fp'])} FP, {len(main_agg['fn'])} FN, "
          f"{main_agg['committed']} committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
