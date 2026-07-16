"""EXP-38: corroborative vs adversarial verifier framing, frozen-ladder replay.

Two arms over the 150 frozen EXP-11 stage-1 candidates, zero web searches:

  disprove_replay     verifier-disprove V4 re-scored (fresh anchor; the
                      historical J=0.41 was a different model/transport era)
  corroborate_replay  verifier-corroborate V1 (the confirmation-seeking
                      mirror; only the system prompt differs)

Candidates are reconstructed from the freeze records themselves, never from
a live build_candidates() query: the DB has drifted since the freeze (a
rebuild today yields 161 candidates with 13 mis-pairings), and the freeze is
the locked sample. Missing researcher fields (answer_explanation,
confidences) are recovered from the original phase2_researcher_runs row by
exact quote+answer match, with a flagged neutral fallback when no row
matches; the reconstruction is arm-invariant either way.

Evidence condition is E0 (researcher evidence + frozen adversarial
snippets), the stage-1 anchor condition. Substring result is the frozen v2.

Endpoints (docs/EXPERIMENTS_CORROBORATE.md): Youden's J per arm (fail =
positive, gold should_fail = positive class), sensitivity, specificity,
false-rejection rate with Wilson 95% CI, exact McNemar on the paired
verdicts. Directional hypothesis: corroborate J < disprove J via sensitivity
collapse.

Resume-safe: completed (cand_id, arm) pairs are skipped on re-run. A window
rate-limit pauses the pool and retries rather than dying (the EXP-36
headline run shares the same Claude window and periodically exhausts it).

  uv run python evaluation/exp38_corroborate_ladder.py --workers 2
  uv run python evaluation/exp38_corroborate_ladder.py --analyse-only
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import ValidationError

from agents.errors import RateLimitedShutdown
from agents.models import ResearcherOutput, VerifierOutput
from agents.prompts import verifier as vp
from agents.tools import db as db_helpers
from agents.tools.llm import StructuredOutputError, call_for_structured

from evaluation import stats

RESULTS = Path(__file__).resolve().parent / "results"
STAGE1 = RESULTS / "verifier_redesign_verifier_tristate_v1.jsonl"
OUT = RESULTS / "exp38_corroborate_ladder.jsonl"
SUMMARY = RESULTS / "exp38_corroborate_summary.json"
DB = Path(__file__).resolve().parent.parent / "data" / "odmi.db"

ARMS = [
    ("disprove_replay", "verifier-disprove"),
    ("corroborate_replay", "verifier-corroborate"),
]

RATE_LIMIT_PAUSE_S = 300
RATE_LIMIT_MAX_WAVES = 24  # up to 2 hours of window outage before giving up

_pause_lock = threading.Lock()
_pause_until = 0.0


def _load_freezes() -> dict[str, dict]:
    fr = {}
    for line in STAGE1.open():
        rec = json.loads(line)
        if rec["kind"] == "freeze":
            fr[rec["cand_id"]] = rec
    return fr


def _question_meta(conn: sqlite3.Connection) -> dict[str, dict]:
    meta = {}
    for row in conn.execute("SELECT question_id, question_text FROM questions"):
        meta[row["question_id"]] = dict(row)
    return meta


def _country_names(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["country_code"]: row["country_name"]
        for row in conn.execute(
            "SELECT DISTINCT country_code, country_name FROM ground_truth"
        )
    }


def _recover_researcher_row(
    conn: sqlite3.Connection, rec: dict
) -> tuple[str, float, float, bool]:
    """Recover answer_explanation and confidences for the frozen candidate.

    Matches the original researcher run by (question_id, country_code,
    answer, evidence_quote). Returns (explanation, retrieval_conf,
    answer_conf, recovered_flag).
    """
    fz = rec["freeze"]
    row = conn.execute(
        "SELECT answer_explanation, retrieval_confidence, answer_confidence "
        "FROM phase2_researcher_runs "
        "WHERE question_id = ? AND country_code = ? AND answer = ? "
        "  AND evidence_quote = ? "
        "ORDER BY id ASC LIMIT 1",
        (
            rec["question_id"],
            rec["country"],
            rec["researcher_answer"],
            fz["evidence_quote"],
        ),
    ).fetchone()
    if row is not None:
        return (
            (row["answer_explanation"] or rec["researcher_answer"])[:2000],
            row["retrieval_confidence"] if row["retrieval_confidence"] is not None else 0.5,
            row["answer_confidence"] if row["answer_confidence"] is not None else 0.5,
            True,
        )
    return rec["researcher_answer"], 0.5, 0.5, False


def _researcher_output(rec: dict, explanation: str, rconf: float, aconf: float):
    fz = rec["freeze"]
    quote = (fz["evidence_quote"] or "").strip()
    if len(quote) < 10:
        quote = (quote + " " + explanation)[:200].strip()
    try:
        return ResearcherOutput(
            answer=rec["researcher_answer"],
            answer_explanation=explanation,
            evidence_quote=quote,
            source_url=fz["researcher_source_url"] or "https://example.invalid/none",
            retrieval_confidence=rconf,
            answer_confidence=aconf,
        )
    except ValidationError:
        return None


def _snip_texts(snips: list[dict]) -> list[str]:
    return [f"{s.get('title', '')} — {s['snippet'][:200]}" for s in snips]


def _wait_out_rate_limit() -> None:
    global _pause_until
    with _pause_lock:
        _pause_until = max(_pause_until, time.time() + RATE_LIMIT_PAUSE_S)
    while time.time() < _pause_until:
        time.sleep(10)


def _run_one(rec, ro, qtext, cname, arm_key, strategy, prompt_id):
    fz = rec["freeze"]
    msg = vp.build_user_message(
        question_text=qtext,
        country_name=cname,
        country_code=rec["country"],
        researcher_output=ro,
        substring_result=fz["substring_v2"],
        substring_notes=None,
        independent_queries=fz["adversarial_queries"],
        independent_snippets=_snip_texts(fz["adversarial_snippets"]),
        strategy=strategy,
        answer_shape=rec["answer_shape"],
        allowed_answers=rec["allowed_answers"],
    )
    spec = vp.STRATEGIES[strategy]
    for wave in range(RATE_LIMIT_MAX_WAVES):
        # Any thread that hit the window pauses every other thread too.
        while time.time() < _pause_until:
            time.sleep(10)
        try:
            out, usage = call_for_structured(
                system=spec.system,
                user_message=msg,
                output_schema=VerifierOutput,
                max_tokens=1500,
                condition_label=f"exp38_{arm_key}",
                prompt_version_id=prompt_id,
                usage_context=f"exp38_{arm_key}:{rec['cand_id']}",
            )
        except RateLimitedShutdown:
            _wait_out_rate_limit()
            continue
        except (StructuredOutputError, ValidationError) as exc:
            return dict(cand_id=rec["cand_id"], arm=arm_key, failed=str(exc)[:160])
        return dict(
            cand_id=rec["cand_id"],
            arm=arm_key,
            verdict=out.verdict,
            verifier_confidence=out.verifier_confidence,
            output=out.model_dump(mode="json"),
        )
    return dict(cand_id=rec["cand_id"], arm=arm_key, failed="rate_limited_out")


def run(workers: int) -> None:
    RESULTS.mkdir(exist_ok=True)
    freezes = _load_freezes()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    qmeta = _question_meta(conn)
    cnames = _country_names(conn)

    prompt_ids = {}
    for _, strategy in ARMS:
        spec = vp.STRATEGIES[strategy]
        prompt_ids[strategy] = db_helpers.ensure_prompt_version(
            spec.name, spec.version, spec.system, spec.description
        )

    done = set()
    if OUT.exists():
        for line in OUT.open():
            r = json.loads(line)
            # Only a clean verdict is final; schema failures and rate-limit
            # exhaustion are stochastic and retried on the next run.
            if "verdict" in r:
                done.add((r["cand_id"], r["arm"]))

    work = []
    skipped = []
    for cid, rec in freezes.items():
        explanation, rconf, aconf, recovered = _recover_researcher_row(conn, rec)
        ro = _researcher_output(rec, explanation, rconf, aconf)
        if ro is None:
            skipped.append(cid)
            continue
        qtext = qmeta.get(rec["question_id"], {}).get("question_text", rec["question_id"])
        cname = cnames.get(rec["country"], rec["country"])
        for arm_key, strategy in ARMS:
            if (cid, arm_key) not in done:
                work.append(
                    (rec, ro, qtext, cname, arm_key, strategy,
                     prompt_ids[strategy], recovered)
                )
    conn.close()

    n_unrecovered = sum(1 for w in work if not w[7])
    print(
        f"{len(freezes)} frozen candidates, {len(ARMS)} arms, {len(work)} calls "
        f"pending ({len(done)} done, {len(skipped)} skipped no-quote, "
        f"{n_unrecovered} calls on fallback researcher fields), workers={workers}"
    )

    fh = OUT.open("a")
    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(_run_one, rec, ro, qt, cn, ak, st, pid): (rec["cand_id"], ak, recov)
            for (rec, ro, qt, cn, ak, st, pid, recov) in work
        }
        for fut in as_completed(futs):
            n += 1
            cid, ak, recov = futs[fut]
            try:
                out_rec = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"  [{n}/{len(work)}] {cid} {ak} ERROR {str(exc)[:80]}")
                continue
            out_rec["researcher_fields_recovered"] = recov
            fh.write(json.dumps(out_rec) + "\n")
            fh.flush()
            if n % 25 == 0 or "failed" in out_rec:
                print(
                    f"  [{n}/{len(work)}] {cid} {ak} -> "
                    f"{out_rec.get('verdict', out_rec.get('failed', '?'))}"
                )
    fh.close()
    print(f"Wrote {OUT}")


def analyse() -> None:
    freezes = _load_freezes()
    verdicts: dict[str, dict[str, str]] = {}
    conf: dict[tuple[str, str], float] = {}
    for line in OUT.open():
        r = json.loads(line)
        if "verdict" in r:
            verdicts.setdefault(r["cand_id"], {})[r["arm"]] = r["verdict"]
            conf[(r["cand_id"], r["arm"])] = r.get("verifier_confidence")

    def metrics(arm: str, predicate=lambda m: True) -> dict:
        tp = fp = tn = fn = 0
        for cid, arms in verdicts.items():
            if arm not in arms:
                continue
            m = freezes[cid]
            if not predicate(m):
                continue
            v = arms[arm]
            gold = m["gold_label"]
            if gold == "should_fail" and v == "fail":
                tp += 1
            elif gold == "should_pass" and v == "fail":
                fp += 1
            elif gold == "should_fail" and v == "pass":
                fn += 1
            else:
                tn += 1
        pos, neg = tp + fn, fp + tn
        sens = tp / pos if pos else float("nan")
        spec = tn / neg if neg else float("nan")
        frr = fp / neg if neg else float("nan")
        j = sens + spec - 1 if pos and neg else float("nan")
        lo, hi = stats.wilson_interval(fp, neg) if neg else (float("nan"),) * 2
        return dict(
            n=tp + fp + tn + fn, tp=tp, fp=fp, tn=tn, fn=fn,
            sensitivity=sens, specificity=spec, frr=frr,
            frr_wilson=[lo, hi], youden_j=j,
        )

    summary = {"arms": {}, "n_candidates": len(verdicts)}
    print(f"\nEXP-38 corroborate ladder ({len(verdicts)} candidates, E0 evidence)")
    print(f"{'arm':20} {'n':>4} {'J':>6} {'sens':>5} {'spec':>5} {'FRR [Wilson95]':>20}")
    for arm_key, _ in ARMS:
        m = metrics(arm_key)
        summary["arms"][arm_key] = m
        print(
            f"{arm_key:20} {m['n']:>4} {m['youden_j']:>6.2f} "
            f"{m['sensitivity']:>5.2f} {m['specificity']:>5.2f} "
            f"{m['frr']:>7.2f} [{m['frr_wilson'][0]:.2f},{m['frr_wilson'][1]:.2f}]"
        )

    print("\nby direction (J):")
    for label, pred in (
        ("no-claims", lambda m: m["absence"]),
        ("yes-claims", lambda m: not m["absence"]),
    ):
        row = f"  {label:11}"
        for arm_key, _ in ARMS:
            row += f" {arm_key}={metrics(arm_key, pred)['youden_j']:.2f}"
        print(row)

    a, b = ARMS[0][0], ARMS[1][0]
    shared = [cid for cid, arms in verdicts.items() if a in arms and b in arms]

    def correct(cid, arm):
        want = "fail" if freezes[cid]["gold_label"] == "should_fail" else "pass"
        return verdicts[cid][arm] == want

    disc_b = sum(1 for cid in shared if correct(cid, a) and not correct(cid, b))
    disc_c = sum(1 for cid in shared if correct(cid, b) and not correct(cid, a))
    p = stats.mcnemar_exact(disc_b, disc_c)
    summary["paired"] = dict(
        shared_n=len(shared), disprove_only_correct=disc_b,
        corroborate_only_correct=disc_c, mcnemar_p=p,
    )
    print(
        f"\nPaired (n={len(shared)}): disprove-only-correct={disc_b}, "
        f"corroborate-only-correct={disc_c}, exact McNemar p={p:.4f}"
    )

    mean_conf = {}
    for arm_key, _ in ARMS:
        for gold in ("should_pass", "should_fail"):
            vals = [
                conf[(cid, arm_key)]
                for cid in verdicts
                if arm_key in verdicts[cid]
                and freezes[cid]["gold_label"] == gold
                and conf.get((cid, arm_key)) is not None
            ]
            mean_conf[f"{arm_key}:{gold}"] = (
                sum(vals) / len(vals) if vals else None
            )
    summary["mean_confidence_by_gold"] = mean_conf

    SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary JSON: {SUMMARY}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--analyse-only", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke: only the first N candidates")
    args = ap.parse_args()
    if args.analyse_only:
        analyse()
        return
    if args.limit:
        global _load_freezes
        orig = _load_freezes

        def limited():
            fr = orig()
            keep = dict(list(sorted(fr.items()))[: args.limit])
            return keep

        _load_freezes = limited
    run(args.workers)
    analyse()


if __name__ == "__main__":
    main()
