"""EXP-7 analysis harness: baseline vs chained retry arms.

Pre-registered in `docs/EXPERIMENTS_CHAINING.md`. This computes the section 6
statistics from the two `condition_label` arms (`baseline`, `chained`) of one
experiment_id and writes a result JSONL plus a printed summary. It does NOT
dispatch the swarm; it reads finalised pairs the dispatch already wrote.

Two layers, kept apart so the statistics are reproducible from logs and
unit-testable without a database:

- A **pure layer** (PairOutcome, the summary and paired-comparison functions)
  that depends only on its arguments and the estimators in `evaluation/stats.py`.
- A thin **DB layer** (`load_outcomes`) that builds PairOutcome lists from
  `phase2_final` joined to `ground_truth` (reusing `_MATCH_STATUS_SQL`, so the
  recovery classification is identical to the dashboard's) and to
  `claude_usage_log` for the calls-per-pair figure.

Endpoints, balance-aware per R4 (Malta's binary gold is 69% `yes`):
- recovery: balanced accuracy and the per-class match rates;
- false-positive rate: committed-but-wrong over committed pairs (the co-primary);
- abstention rate;
- calls per resolved pair.

The confirmatory claim is the joint one: balanced-accuracy non-decrease (E1) at a
non-increased false-positive rate (E2). The false-positive decision margin is
fixed at 0.05, mirroring the EXP-1 non-inferiority discipline.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.stats import mcnemar_exact, wilcoxon_signed_rank, wilson_interval

# The pre-registered decision margin for the false-positive co-primary: chaining
# is adopted only if it does not raise the committed-but-wrong rate by more than
# this. Fixed here before any run (R8).
FALSE_POSITIVE_MARGIN = 0.05

# Terminal statuses that mean a real answer was committed (as opposed to an
# honest abstention or a failure). Mirrors the coordinator's finalisation.
_COMMITTED_STATUSES = {"accepted_by_verifier", "accepted_by_adjudicator"}


# ---------------------------------------------------------------------------
# Pure layer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PairOutcome:
    """One finalised (question, country) pair in one arm.

    `match_status` is the dashboard's classification (`match` / `near_match` /
    `differ` / `no_ground_truth` / `no_swarm_answer`), computed by the same SQL
    so recovery here means the same thing as everywhere else in the project.
    `calls` is the number of Claude calls the pair spent.
    """

    question_id: str
    country_code: str
    arm: str
    terminal_status: str
    final_answer: Optional[str]
    gold_answer: Optional[str]
    match_status: str
    calls: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.question_id, self.country_code)


def is_abstention(answer: Optional[str]) -> bool:
    """True for the `inconclusive` abstention literal. Mirrors the coordinator's
    `_is_abstention`; `not_applicable` is a determination, not an abstention."""
    return bool(answer) and answer.strip().lower() == "inconclusive"


def is_committed(outcome: PairOutcome) -> bool:
    """A pair committed a real answer iff it reached a committed terminal status
    with a non-abstention final answer. An escalation or an `inconclusive` is an
    honest abstention, not a commit."""
    return (
        outcome.terminal_status in _COMMITTED_STATUSES
        and bool(outcome.final_answer)
        and not is_abstention(outcome.final_answer)
    )


def recovered(outcome: PairOutcome) -> bool:
    """A pair is recovered iff its committed answer matches the ODMI gold.
    A near_match (one adjacent band off) is reported separately, not as a
    recovery, in line with the band-miss treatment everywhere else."""
    return outcome.match_status == "match"


def is_false_positive(outcome: PairOutcome) -> bool:
    """Committed but wrong: a real answer was finalised and it does not match
    the gold. This is the rate chaining must not raise."""
    return is_committed(outcome) and not recovered(outcome)


def gold_class(gold_answer: Optional[str]) -> str:
    """Coarse class of the gold answer for per-class rates: 'yes', 'no', or
    'other' (bands, categoricals, blanks)."""
    if not gold_answer:
        return "other"
    g = gold_answer.strip().lower()
    if g.startswith("yes"):
        return "yes"
    if g == "no":
        return "no"
    return "other"


def _rate(successes: int, n: int) -> dict:
    lo, hi = wilson_interval(successes, n)
    return {
        "successes": successes,
        "n": n,
        "rate": (successes / n) if n else None,
        "wilson_95": [lo, hi],
    }


def arm_summary(outcomes: list[PairOutcome]) -> dict:
    """Summarise one arm: recovery (balanced accuracy + per-class rates),
    false-positive rate, abstention rate, and calls per resolved pair."""
    n = len(outcomes)
    committed = [o for o in outcomes if is_committed(o)]
    abstained = [o for o in outcomes if not is_committed(o)]
    n_recovered = sum(1 for o in outcomes if recovered(o))
    n_near = sum(1 for o in outcomes if o.match_status == "near_match")

    # Per-class recall (fraction of that gold class that was recovered).
    by_class: dict[str, list[PairOutcome]] = {"yes": [], "no": [], "other": []}
    for o in outcomes:
        by_class[gold_class(o.gold_answer)].append(o)

    per_class = {
        cls: _rate(sum(1 for o in items if recovered(o)), len(items))
        for cls, items in by_class.items()
    }

    # Balanced accuracy is the mean of the two binary per-class recalls, and is
    # defined only when BOTH classes are present. With one class present it
    # would just re-present that class's recall, the majority-class trap R4
    # exists to stop, so it is reported as None instead.
    yes_rate = per_class["yes"]["rate"]
    no_rate = per_class["no"]["rate"]
    balanced_accuracy = (
        (yes_rate + no_rate) / 2
        if yes_rate is not None and no_rate is not None
        else None
    )

    # Calls per resolved pair: resolved = committed (an abstention is not a
    # resolution). Falls back to all pairs if nothing committed, so the figure
    # is always defined.
    resolved = committed if committed else outcomes
    calls_total = sum(o.calls for o in resolved)
    calls_per_resolved = (calls_total / len(resolved)) if resolved else None

    return {
        "n": n,
        "n_committed": len(committed),
        "n_abstained": len(abstained),
        "n_recovered": n_recovered,
        "n_near_match": n_near,
        "recovery_overall": _rate(n_recovered, n),
        "balanced_accuracy": balanced_accuracy,
        "per_class_recall": per_class,
        "false_positive_rate": _rate(
            sum(1 for o in outcomes if is_false_positive(o)), len(committed)
        ),
        "abstention_rate": _rate(len(abstained), n),
        "calls_per_resolved_pair": calls_per_resolved,
        "calls_total": calls_total,
    }


def _align(baseline: list[PairOutcome],
           chained: list[PairOutcome]) -> list[tuple[PairOutcome, PairOutcome]]:
    """Pairs present in both arms, matched on (question_id, country_code).
    Paired design (R2): only pairs both arms ran enter the paired tests."""
    b_by_key = {o.key: o for o in baseline}
    c_by_key = {o.key: o for o in chained}
    common = sorted(set(b_by_key) & set(c_by_key))
    return [(b_by_key[k], c_by_key[k]) for k in common]


def _mcnemar_on(pairs, indicator) -> dict:
    """McNemar's exact test on a paired binary indicator across two arms.

    b = baseline-true & chained-false; c = chained-true & baseline-false.
    The sign of (c - b) reads as the chained-vs-baseline direction.
    """
    b = sum(1 for bo, co in pairs if indicator(bo) and not indicator(co))
    c = sum(1 for bo, co in pairs if indicator(co) and not indicator(bo))
    return {
        "discordant_baseline_only": b,
        "discordant_chained_only": c,
        "p_value": mcnemar_exact(b, c),
    }


def paired_comparison(baseline: list[PairOutcome],
                      chained: list[PairOutcome]) -> dict:
    """The confirmatory comparison: paired McNemar on recovery and on the
    committed-but-wrong indicator, and Wilcoxon on calls per pair."""
    pairs = _align(baseline, chained)
    n_pairs = len(pairs)

    recovery = _mcnemar_on(pairs, recovered)
    false_positive = _mcnemar_on(pairs, is_false_positive)

    # Wilcoxon on per-pair call differences (chained - baseline). Undefined when
    # there are no non-zero differences; report None rather than raise.
    diffs = [co.calls - bo.calls for bo, co in pairs]
    try:
        w_stat, w_p = wilcoxon_signed_rank(diffs)
        calls_test = {"statistic": w_stat, "p_value": w_p}
    except (ValueError, NotImplementedError) as exc:
        calls_test = {"statistic": None, "p_value": None, "note": str(exc)}

    # The joint confirmatory verdict, computed mechanically from the summaries
    # so it cannot be fudged after the fact.
    bs = arm_summary(baseline)
    cs = arm_summary(chained)
    ba_b, ba_c = bs["balanced_accuracy"], cs["balanced_accuracy"]
    fp_b = bs["false_positive_rate"]["rate"]
    fp_c = cs["false_positive_rate"]["rate"]
    ba_non_decrease = (
        ba_b is not None and ba_c is not None and ba_c >= ba_b
    )
    fp_not_raised = (
        fp_b is not None and fp_c is not None
        and (fp_c - fp_b) <= FALSE_POSITIVE_MARGIN
    )

    return {
        "n_paired": n_pairs,
        "recovery_mcnemar": recovery,
        "false_positive_mcnemar": false_positive,
        "calls_wilcoxon": calls_test,
        "median_call_delta": (sorted(diffs)[len(diffs) // 2] if diffs else None),
        "joint_confirmatory": {
            "balanced_accuracy_non_decrease": ba_non_decrease,
            "false_positive_not_raised": fp_not_raised,
            "false_positive_margin": FALSE_POSITIVE_MARGIN,
            "passes": bool(ba_non_decrease and fp_not_raised),
        },
    }


def analyse(arms: dict[str, list[PairOutcome]]) -> dict:
    """Full analysis block for the two arms. Missing arms summarise to empty."""
    baseline = arms.get("baseline", [])
    chained = arms.get("chained", [])
    report = {
        "majority_baseline_note": (
            "Malta binary gold is ~69% yes; the headline is balanced accuracy "
            "and per-class rates, not raw accuracy (R4)."
        ),
        "arms": {
            "baseline": arm_summary(baseline),
            "chained": arm_summary(chained),
        },
    }
    if baseline and chained:
        report["paired"] = paired_comparison(baseline, chained)
    else:
        report["paired"] = {
            "note": "one or both arms empty; paired tests not computed. "
                    "The run is gated on the Malta dispatch and Claude quota."
        }
    return report


# ---------------------------------------------------------------------------
# DB layer (thin; the pure layer above carries the logic)
# ---------------------------------------------------------------------------

def load_outcomes(conn: sqlite3.Connection,
                  experiment_id: str) -> dict[str, list[PairOutcome]]:
    """Build PairOutcome lists per arm from the DB for one experiment_id.

    The arm (`condition_label`) lives on `phase2_researcher_runs`, not on
    `phase2_final`, so we read it back via the pair_run_id. Recovery uses the
    dashboard's `_MATCH_STATUS_SQL` verbatim, so the classification matches the
    rest of the project. Calls per pair come from `claude_usage_log` keyed on
    the subtrio_id (== pair_run_id).
    """
    from dashboard.lib.db import _MATCH_STATUS_SQL

    # The dispatch can write more than one phase2_final row per pair within an arm
    # (retries, or two concurrent re-runs). Keep the canonical row per
    # (question, country, arm) = highest id, the same answer-blind rule the
    # dashboard match matrix uses (dashboard/lib/db.py). Without this, a duplicated
    # pair would be double-counted in one arm and break the paired design (R2).
    query = f"""
        WITH base AS (
            SELECT
                f.rowid                AS _fid,
                f.question_id          AS question_id,
                f.country_code         AS country_code,
                COALESCE((
                    SELECT r.condition_label
                    FROM phase2_researcher_runs r
                    WHERE r.pair_run_id = f.pair_run_id
                      AND r.condition_label IS NOT NULL
                    LIMIT 1
                ), 'baseline')         AS arm,
                f.terminal_status      AS terminal_status,
                f.final_answer         AS final_answer,
                gt.response            AS gold_answer,
                {_MATCH_STATUS_SQL}    AS match_status,
                (
                    SELECT COUNT(*) FROM claude_usage_log u
                    WHERE u.subtrio_id = f.pair_run_id
                )                      AS calls
            FROM phase2_final f
            LEFT JOIN ground_truth gt
              ON gt.question_id = f.question_id
             AND gt.country_code = f.country_code
            WHERE f.experiment_id = ?
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY question_id, country_code, arm ORDER BY _fid DESC
            ) AS _canon_rn
            FROM base
        )
        SELECT question_id, country_code, arm, terminal_status,
               final_answer, gold_answer, match_status, calls
        FROM ranked WHERE _canon_rn = 1
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query, (experiment_id,)).fetchall()

    arms: dict[str, list[PairOutcome]] = {}
    for r in rows:
        outcome = PairOutcome(
            question_id=r["question_id"],
            country_code=r["country_code"],
            arm=r["arm"],
            terminal_status=r["terminal_status"],
            final_answer=r["final_answer"],
            gold_answer=r["gold_answer"],
            match_status=r["match_status"],
            calls=int(r["calls"] or 0),
        )
        arms.setdefault(outcome.arm, []).append(outcome)
    return arms


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyse EXP-7 baseline vs chained retry arms."
    )
    parser.add_argument(
        "--experiment-id", default="retry_chaining_mt_v1",
        help="The experiment_id tagged on both arms' finalised pairs.",
    )
    parser.add_argument(
        "--db", default=str(REPO_ROOT / "data" / "odmi.db"),
        help="Path to the SQLite database.",
    )
    parser.add_argument(
        "--out", default=None,
        help="Where to write the result JSONL. Default: "
             "evaluation/results/chaining_<experiment_id>.json",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        arms = load_outcomes(conn, args.experiment_id)
    finally:
        conn.close()

    report = analyse(arms)
    report["experiment_id"] = args.experiment_id

    out_path = Path(args.out) if args.out else (
        REPO_ROOT / "evaluation" / "results"
        / f"chaining_{args.experiment_id}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    # Human-readable summary.
    print(f"\n=== EXP-7 chaining analysis: {args.experiment_id} ===")
    for arm in ("baseline", "chained"):
        s = report["arms"][arm]
        ba = s["balanced_accuracy"]
        fp = s["false_positive_rate"]["rate"]
        print(
            f"  {arm:9s} n={s['n']:3d} committed={s['n_committed']:3d} "
            f"recovered={s['n_recovered']:3d} "
            f"bal_acc={ba if ba is None else round(ba, 3)} "
            f"fp_rate={fp if fp is None else round(fp, 3)} "
            f"calls/resolved={s['calls_per_resolved_pair']}"
        )
    paired = report.get("paired", {})
    if "joint_confirmatory" in paired:
        jc = paired["joint_confirmatory"]
        print(f"\n  joint confirmatory passes: {jc['passes']} "
              f"(bal_acc non-decrease={jc['balanced_accuracy_non_decrease']}, "
              f"fp not raised={jc['false_positive_not_raised']})")
    else:
        print(f"\n  {paired.get('note', '(no paired comparison)')}")
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
