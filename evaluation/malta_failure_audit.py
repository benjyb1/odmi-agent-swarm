"""EXP-10: Malta failure-mode audit and targeted recovery.

Pre-registered in docs/EXPERIMENTS_MALTA_FAILURES.md. Two phases:

  Phase A (diagnostic): code every Malta non-match against ODMI ground truth to
  one primary cause from a fixed taxonomy (fetch 4xx/5xx, no source, substring
  gate, below-floor abstention, wrong answer, near-miss band, self-report /
  deny-list ceiling, stale ground truth), deterministically where the DB signal
  is unambiguous, with an optional Opus pass over FROZEN evidence only for the
  genuine-error vs stale-gold residual (--llm; off by default so the audit needs
  no quota and does not contend with a live dispatch).

  Phase B (recovery): replay the finalisation commit rule at floors
  {0.65, 0.55, 0.50} on the already-stored Researcher/Adjudicator confidences.
  No dispatch, no API. Reports the recovery-precision trade-off and applies the
  pre-registered decision rule (adopt a lower floor only if recovered-answer
  precision >= 0.80 and the false-positive rate on negative golds rises by no
  more than 0.05).

The audit treats a `final_answer` of `inconclusive` as ABSTAIN, its own cause
category; the headline _MATCH_STATUS_SQL folds that into `differ`. That is the
one deliberate divergence and it is the point of the audit.

Usage:
  uv run python evaluation/malta_failure_audit.py                 # MT, deterministic
  uv run python evaluation/malta_failure_audit.py --llm           # add the residual judge
  uv run python evaluation/malta_failure_audit.py --country NL    # the secondary country
  uv run python evaluation/malta_failure_audit.py --analyse-only PATH.jsonl
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import evaluation.stats as stats

# Mirrors COMMIT_CONFIDENCE_FLOOR in scripts/run_coordinator.py (D37). A unit
# test asserts the two stay in sync.
BASELINE_FLOOR = 0.65
DEFAULT_FLOORS = [0.65, 0.55, 0.50]
ABSTENTIONS = {"inconclusive", "not_applicable", ""}
EXPERIMENT_ID = "malta_failure_audit_v1"
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"

# Cause -> class. The order of this dict is the priority order for coding.
CAUSE_CLASS = {
    "fetch_4xx_5xx": "fixable",
    "no_source_found": "fixable",
    "substring_gate": "fixable",
    "below_floor": "fixable",
    "abstain_other": "fixable",
    "near_band": "error",
    "wrong_answer": "error",
    "selfreport_denylist_ceiling": "structural",
    "stale_ground_truth": "structural",
    "match": "none",
    "no_ground_truth": "n/a",
}


# ============================================================
# Pure logic (unit-tested, no DB or network)
# ============================================================

def classify_match(final_answer, gold, allowed_answers=None, answer_shape=None) -> str:
    """Mirror _MATCH_STATUS_SQL, but split the `inconclusive` abstention literal
    out of `differ` into its own `abstain` status (the audit's whole point).

    Returns: no_ground_truth | no_swarm_answer | abstain | match | near_match | differ.
    """
    g = (gold or "").strip()
    if g == "":
        return "no_ground_truth"
    fa = (final_answer or "").strip()
    if fa == "":
        return "no_swarm_answer"
    fal, gl = fa.lower(), g.lower()
    if fal in ABSTENTIONS:
        return "abstain"
    if fal == gl:
        return "match"
    if fal == "yes" and gl.startswith("yes"):
        return "match"
    if fal == "no" and gl == "no":
        return "match"
    if answer_shape in ("percentage_band", "ordinal_magnitude", "count_band") and allowed_answers:
        labels = [str(x).strip().lower() for x in allowed_answers]
        if fal in labels and gl in labels and abs(labels.index(fal) - labels.index(gl)) == 1:
            return "near_match"
    return "differ"


def answer_matches_gold(answer, gold) -> bool:
    """The binary correctness check used for a recovered candidate answer,
    mirroring the match branches of _MATCH_STATUS_SQL (exact / yes-prefix / no)."""
    a = (answer or "").strip().lower()
    g = (gold or "").strip().lower()
    if not a or not g or a in ABSTENTIONS:
        return False
    return a == g or (a == "yes" and g.startswith("yes")) or (a == "no" and g == "no")


def code_cause(p: dict) -> str:
    """Assign one primary failure cause to a non-match pair, deterministically.

    `p` carries the pre-extracted signals: match_status, notes, has_source,
    has_snippets, substring_failed, candidate_is_definite, candidate_confidence,
    is_structural_gold. Priority order = the order of the checks below (an
    upstream cause wins, e.g. a fetch failure that also lands below the floor is
    coded as the fetch failure).
    """
    ms = p["match_status"]
    if ms == "match":
        return "match"
    if ms == "no_ground_truth":
        return "no_ground_truth"
    if ms == "near_match":
        return "near_band"
    if ms in ("abstain", "no_swarm_answer"):
        # both are the swarm declining to commit: an `inconclusive` literal or an
        # empty final answer. Same cause logic applies.
        notes = (p.get("notes") or "").lower()
        if any(s in notes for s in ("403", "status 4", "status 5", "captcha", "blocked", "forbidden")):
            return "fetch_4xx_5xx"
        if not p.get("has_source") and not p.get("has_snippets"):
            return "no_source_found"
        if p.get("substring_failed"):
            return "substring_gate"
        conf = p.get("candidate_confidence")
        if p.get("candidate_is_definite") and conf is not None and conf < BASELINE_FLOOR:
            return "below_floor"
        return "abstain_other"
    # differ
    if p.get("is_structural_gold"):
        return "selfreport_denylist_ceiling"
    return "wrong_answer"  # the --llm residual may reassign to stale_ground_truth


def floor_sweep(pairs: list, floors: list) -> dict:
    """Replay the commit decision at each floor. `pairs` carry candidate_answer,
    candidate_confidence, candidate_is_definite, candidate_correct, is_negative_gold.

    Returns per-floor: committed, correct, recovered (vs the highest/baseline
    floor), recovered_correct, recovered_fp, recovery_precision, and the
    false-positive rate on negative golds.
    """
    baseline = max(floors)

    def committed_at(p, f):
        # A pair that actually committed stays committed at any swept (lower)
        # floor; this also captures adjudicator commits, which bypass the floor.
        # Only an abstention is floor-recoverable, via its candidate confidence.
        if p.get("committed_real"):
            return True
        return bool(p["candidate_is_definite"] and p["candidate_confidence"] is not None
                    and p["candidate_confidence"] >= f)

    base_commit = {id(p): committed_at(p, baseline) for p in pairs}
    out = {}
    for f in floors:
        committed = correct = 0
        recovered = rec_correct = rec_fp = 0
        neg_total = neg_fp = 0
        for p in pairs:
            c = committed_at(p, f)
            if p["is_negative_gold"]:
                neg_total += 1
                if c and not p["candidate_correct"]:
                    neg_fp += 1
            if c:
                committed += 1
                if p["candidate_correct"]:
                    correct += 1
                if not base_commit[id(p)]:  # newly committed at this lower floor
                    recovered += 1
                    if p["candidate_correct"]:
                        rec_correct += 1
                    else:
                        rec_fp += 1
        out[f] = dict(
            committed=committed, correct=correct,
            recovered=recovered, recovered_correct=rec_correct, recovered_fp=rec_fp,
            recovery_precision=(rec_correct / recovered if recovered else None),
            neg_golds=neg_total, neg_false_positives=neg_fp,
            fpr_neg=(neg_fp / neg_total if neg_total else None),
        )
    return out


def decide_floor(sweep: dict, baseline: float,
                 min_precision: float = 0.80, max_fpr_increase: float = 0.05) -> dict:
    """Apply the pre-registered adopt-a-lower-floor rule. Returns the recommended
    floor and the per-floor pass/fail against the rule."""
    base_fpr = sweep[baseline]["fpr_neg"] or 0.0
    verdicts = {}
    eligible = []
    for f, r in sweep.items():
        if f >= baseline:
            continue
        prec = r["recovery_precision"]
        fpr = r["fpr_neg"] or 0.0
        prec_ok = (r["recovered"] == 0) or (prec is not None and prec >= min_precision)
        fpr_ok = (fpr - base_fpr) <= max_fpr_increase
        passes = bool(r["recovered"] > 0 and prec_ok and fpr_ok)
        verdicts[f] = dict(passes=passes, precision_ok=prec_ok, fpr_ok=fpr_ok,
                           recovered=r["recovered"])
        if passes:
            eligible.append((r["recovered"], f))
    recommended = baseline
    if eligible:
        # most recovery wins; on a tie keep the HIGHER (more conservative) floor,
        # since a lower floor that recovers no more only adds risk.
        recommended = max(eligible, key=lambda t: (t[0], t[1]))[1]
    return dict(recommended_floor=recommended, baseline=baseline, verdicts=verdicts)


# ============================================================
# DB load
# ============================================================

def _connect(db_path: Optional[str]):
    p = db_path or str(REPO_ROOT / "data" / "odmi.db")
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


def _substring_failed(val) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("fail", "failed", "not_found", "no", "false", "0", "missing", "mismatch")


def load_pairs(conn, country: str = "MT", experiment_id: Optional[str] = None) -> list:
    """One record per finalised pair for `country`, with every signal the coder
    and the floor sweep need."""
    qmeta = {r["question_id"]: dict(dim=r["dimension"], shape=r["answer_shape"] or "binary",
                                    allowed=json.loads(r["allowed_answers"]) if r["allowed_answers"] else ["yes", "no"])
             for r in conn.execute("select question_id,dimension,answer_shape,allowed_answers from questions")}
    gold = {r["question_id"]: (r["response"] or "")
            for r in conn.execute("select question_id,response from ground_truth where country_code=?", (country,))}

    # Canonical row per (question, country). The dispatch can write more than one
    # phase2_final row per pair (a stale agent_failure superseded by a real
    # finalisation, or two concurrent re-runs of the same pair), so counting every
    # row double-counts questions and corrupts the negative-gold denominator the
    # floor sweep depends on. Mirror the dashboard's rule verbatim
    # (dashboard/lib/db.py match matrix): keep the highest-id (latest) row per
    # pair, answer-blind. Main runs are experiment_id IS NULL (D27
    # MAIN_RUNS_FILTER); a specific experiment is selected explicitly.
    if experiment_id is not None:
        exp_filter, exp_args = "experiment_id = ?", [experiment_id]
    else:
        exp_filter, exp_args = "experiment_id IS NULL", []
    finals = [dict(r) for r in conn.execute(
        f"""
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY question_id, country_code ORDER BY id DESC
            ) AS _canon_rn
            FROM phase2_final
            WHERE country_code = ? AND {exp_filter}
        )
        SELECT * FROM ranked WHERE _canon_rn = 1
        """, [country, *exp_args])]

    # group the stage rows by pair_run_id
    rruns, vruns, adjs = defaultdict(list), defaultdict(list), {}
    for r in conn.execute("select * from phase2_researcher_runs where country_code=?", (country,)):
        rruns[r["pair_run_id"]].append(dict(r))
    for r in conn.execute("select * from phase2_verifier_runs where country_code=?", (country,)):
        vruns[r["pair_run_id"]].append(dict(r))
    for r in conn.execute("select * from phase2_adjudications where country_code=?", (country,)):
        adjs[r["pair_run_id"]] = dict(r)

    pairs = []
    for f in finals:
        prid = f["pair_run_id"]
        qid = f["question_id"]
        meta = qmeta.get(qid, dict(dim="?", shape="binary", allowed=["yes", "no"]))
        g = gold.get(qid, "")
        rs = sorted(rruns.get(prid, []), key=lambda x: (x.get("retry_count") or 0, x["id"]))
        vs = vruns.get(prid, [])
        adj = adjs.get(prid)

        # Candidate the floor would have judged. For a committed pair it is the
        # final answer and the confidence that actually gated, so replay at the
        # baseline floor reproduces the real commit. For an abstained pair it is
        # the best pre-abstention candidate (adjudicator if it ran, else the
        # latest Researcher run carrying a definite answer).
        final_ans = f.get("final_answer")
        final_definite = bool(final_ans) and final_ans.strip().lower() not in ABSTENTIONS
        if final_definite:
            cand_ans, cand_conf = final_ans, f.get("final_answer_confidence")
        else:
            cand_ans, cand_conf = None, None
            if adj and (adj.get("adjudicator_answer") or "").strip().lower() not in ABSTENTIONS:
                cand_ans, cand_conf = adj["adjudicator_answer"], adj.get("adjudicator_confidence")
            else:
                for r in reversed(rs):
                    if (r.get("answer") or "").strip().lower() not in ABSTENTIONS:
                        cand_ans, cand_conf = r["answer"], r.get("answer_confidence")
                        break
        cand_definite = cand_ans is not None

        notes = " ".join((r.get("notes") or "") for r in rs)
        has_source = any(str(r.get("source_url") or "").startswith("http") for r in rs)
        has_snippets = any((r.get("search_snippets") or "").strip() not in ("", "[]", "null") for r in rs)
        substring_failed = any(_substring_failed(v.get("substring_check_result")) for v in vs)

        ms = classify_match(f.get("final_answer"), g, meta["allowed"], meta["shape"])
        # structural-gold heuristic: a deny-listed / self-report Quality band question.
        is_structural = (meta["dim"] == "Quality" and meta["shape"] in
                         ("percentage_band", "count_band", "ordinal_magnitude"))

        pairs.append(dict(
            pair_run_id=prid, question_id=qid, country_code=country, dimension=meta["dim"],
            answer_shape=meta["shape"], gold=g, final_answer=f.get("final_answer"),
            final_confidence=f.get("final_answer_confidence"),
            match_status=ms, notes=notes, has_source=has_source, has_snippets=has_snippets,
            substring_failed=substring_failed,
            candidate_answer=cand_ans, candidate_confidence=cand_conf,
            candidate_is_definite=cand_definite, committed_real=final_definite,
            candidate_correct=answer_matches_gold(cand_ans, g),
            is_negative_gold=(g.strip().lower() == "no"),
            is_structural_gold=is_structural,
        ))
    return pairs


# ============================================================
# Optional LLM residual (genuine error vs stale gold)
# ============================================================

def review_differ(pair: dict) -> dict:
    """Opus judge over the frozen evidence: is this `differ` a genuine swarm error
    or a stale-gold disagreement? Imported lazily so the deterministic path needs
    no LLM dependency."""
    from agents.tools.llm import call_for_structured
    from pydantic import BaseModel, Field

    class Verdict(BaseModel):
        call: str = Field(description="one of: genuine_error, stale_gold, unclear")
        reason: str

    system = ("You audit an open-data assessment swarm against published ground "
              "truth. Decide whether a disagreement is a genuine swarm error or a "
              "case where the swarm is plausibly right and the published answer is "
              "stale (it can be one assessment cycle old). Answer unclear if you "
              "cannot tell from the evidence. Be sceptical; default to genuine_error "
              "unless the evidence positively supports the swarm.")
    user = (f"Question {pair['question_id']} ({pair['country_code']}).\n"
            f"Swarm answer: {pair.get('candidate_answer')!r}\n"
            f"Published ground truth: {pair['gold']!r}\n"
            f"Swarm evidence (frozen): {(pair.get('notes') or '')[:1500]}")
    try:
        out, _ = call_for_structured(system=system, user_message=user, output_schema=Verdict,
                                     max_tokens=400, temperature=0.0,
                                     condition_label=EXPERIMENT_ID,
                                     usage_context=f"exp10_differ:{pair['question_id']}:{pair['country_code']}")
        return dict(call=out.call, reason=out.reason[:300])
    except Exception as e:  # noqa: BLE001
        return dict(call="unclear", reason=f"judge error: {type(e).__name__}")


# ============================================================
# Run / analyse
# ============================================================

def run(country: str = "MT", experiment_id: Optional[str] = None,
        floors: Optional[list] = None, use_llm: bool = False,
        db_path: Optional[str] = None) -> Path:
    floors = floors or DEFAULT_FLOORS
    conn = _connect(db_path)
    pairs = load_pairs(conn, country=country, experiment_id=experiment_id)
    conn.close()

    for p in pairs:
        p["cause"] = code_cause(p)
        p["cause_class"] = CAUSE_CLASS.get(p["cause"], "unknown")
    if use_llm:
        for p in pairs:
            if p["cause"] == "wrong_answer":
                v = review_differ(p)
                p["llm_review"] = v
                if v["call"] == "stale_gold":
                    p["cause"], p["cause_class"] = "stale_ground_truth", "structural"

    sweep = floor_sweep(pairs, floors)
    decision = decide_floor(sweep, baseline=max(floors))

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"malta_failure_audit_{country}.jsonl"
    with out_path.open("w") as fh:
        fh.write(json.dumps(dict(_record="header", experiment_id=EXPERIMENT_ID,
                                 country=country, source_experiment_id=experiment_id,
                                 floors=floors, n_pairs=len(pairs), used_llm=use_llm)) + "\n")
        for p in pairs:
            fh.write(json.dumps({"_record": "pair", **{k: v for k, v in p.items() if k != "notes"}}) + "\n")
        fh.write(json.dumps(dict(_record="floor_sweep", sweep={str(k): v for k, v in sweep.items()},
                                 decision={**decision, "verdicts": {str(k): v for k, v in decision["verdicts"].items()}})) + "\n")
    _report(pairs, sweep, decision, country)
    return out_path


def _report(pairs, sweep, decision, country):
    print("\n" + "=" * 74)
    print(f"EXP-10 MALTA FAILURE AUDIT  —  {country}  (n={len(pairs)} finalised pairs)")
    print("=" * 74)
    ms = Counter(p["match_status"] for p in pairs)
    print(f"Match status: {dict(ms)}")
    print("\n--- Phase A: failure-mode taxonomy (non-match pairs) ---")
    causes = Counter(p["cause"] for p in pairs if p["cause"] not in ("match", "no_ground_truth"))
    n = len(pairs)
    print(f"  {'cause':28s} {'class':10s} {'n':>3s} {'share[95% CI]':>20s}")
    for cause, k in causes.most_common():
        lo, hi = stats.wilson_interval(k, n)
        print(f"  {cause:28s} {CAUSE_CLASS.get(cause,'?'):10s} {k:>3d}  {k/n:.2f}[{lo:.2f},{hi:.2f}]")
    fixable = sum(k for c, k in causes.items() if CAUSE_CLASS.get(c) == "fixable")
    structural = sum(k for c, k in causes.items() if CAUSE_CLASS.get(c) == "structural")
    errors = sum(k for c, k in causes.items() if CAUSE_CLASS.get(c) == "error")
    print(f"  -> fixable {fixable}, error {errors}, structural {structural}")

    # Faithfulness: an abstained pair should not already carry a candidate at or
    # above the baseline floor (it would have committed). A non-zero count flags a
    # candidate-extraction gap. Committed pairs include adjudicator commits, which
    # bypass the floor, so they are credited as committed regardless of confidence.
    base = max(sweep)
    inconsistent = sum(1 for p in pairs
                       if not p.get("committed_real") and p["candidate_is_definite"]
                       and p["candidate_confidence"] is not None and p["candidate_confidence"] >= base)
    print(f"\nReplay faithfulness @ {base}: {inconsistent} abstained pair(s) carry a candidate "
          f">= baseline" + (" (expected 0)" if inconsistent == 0 else " -- investigate"))

    print("\n--- Phase B: confidence-floor sweep ---")
    print(f"  {'floor':>6s} {'committed':>10s} {'correct':>8s} {'recovered':>10s} "
          f"{'rec_correct':>11s} {'rec_fp':>7s} {'rec_prec':>9s} {'fpr_neg':>8s}")
    for f in sorted(sweep, reverse=True):
        r = sweep[f]
        rp = "  n/a" if r["recovery_precision"] is None else f"{r['recovery_precision']:.2f}"
        fn = "  n/a" if r["fpr_neg"] is None else f"{r['fpr_neg']:.2f}"
        print(f"  {f:6.2f} {r['committed']:>10d} {r['correct']:>8d} {r['recovered']:>10d} "
              f"{r['recovered_correct']:>11d} {r['recovered_fp']:>7d} {rp:>9s} {fn:>8s}")
    print(f"\n  Decision rule (precision>=0.80, fpr rise<=0.05): "
          f"recommended floor = {decision['recommended_floor']}")
    for f, v in sorted(decision["verdicts"].items(), reverse=True):
        print(f"    floor {f}: {'ADOPT' if v['passes'] else 'reject'} "
              f"(recovered {v['recovered']}, precision_ok={v['precision_ok']}, fpr_ok={v['fpr_ok']})")
    print("=" * 74)


def analyse(path):
    path = Path(path)
    pairs, sweep_rec, dec = [], None, None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("_record") == "pair":
            pairs.append(o)
        elif o.get("_record") == "floor_sweep":
            sweep_rec = {float(k): v for k, v in o["sweep"].items()}
            dec = o["decision"]
            dec["verdicts"] = {float(k): v for k, v in dec["verdicts"].items()}
    country = pairs[0]["country_code"] if pairs else "?"
    _report(pairs, sweep_rec, dec, country)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="MT")
    ap.add_argument("--experiment-id", default=None,
                    help="scope to one phase2_final.experiment_id (default: all main rows for the country)")
    ap.add_argument("--floors", type=float, nargs="+", default=None)
    ap.add_argument("--llm", action="store_true", help="run the genuine-error vs stale-gold residual judge")
    ap.add_argument("--db", default=None)
    ap.add_argument("--analyse-only", default=None)
    args = ap.parse_args()
    if args.analyse_only:
        analyse(args.analyse_only)
    else:
        out = run(country=args.country, experiment_id=args.experiment_id,
                  floors=args.floors, use_llm=args.llm, db_path=args.db)
        print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
