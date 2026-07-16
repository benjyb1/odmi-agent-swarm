"""EXP-36 post-run analysis pack: the frozen headline read.

Pre-registered in `docs/EXPERIMENTS_EXP36_PREREG.md` (D64). This script is the
analysis half of the pre-registration: it reads the finalised pairs the
dispatch already wrote and computes the registered endpoints, nothing else. It
makes no LLM calls; every figure is replay arithmetic over the DB, so an
examiner can recompute the JSON from the SQLite file alone.

Endpoints (per the prereg, no adoption rule):

1. Balance-aware headline on binary-gold pairs: per-class recall with Wilson
   95% intervals, balanced accuracy, Youden's J against the majority-class
   baseline (R4).
2. Three-outcome read over all pairs: commit-accuracy / coverage /
   negative-gold false-positive rate.
3. Stratified breakdowns: ODMI dimension, D47 resource stratum, ODMI assessor
   decision (confirm / complement / change), answer shape, and country.
4. RQ3 language read: stratum A vs stratum B contrast on negative-gold FP
   rate, abstention rate and commit accuracy, with Wilson intervals and a
   two-proportion comparison per endpoint.
5. Calibration: 10-bin equal-width reliability curve over the final
   confidence of committed answers vs the empirical match rate, plus the
   expected calibration error (ECE), with bin counts for a later figure.
6. Risk-coverage sweep over the D37 confidence floor (0.50 to 0.90 in steps
   of 0.05): coverage (share committed) vs risk (error rate among committed).
7. D22 disagreement bracket support: the differ register and the lower-bound
   commit accuracy. The upper bound needs the human staleness review of each
   disagreement, so it is emitted as pending, never fabricated.

Two layers, matching `chaining_analysis.py`, so the statistics are
unit-testable without a database:

- a **pure layer** (PairRow, the classifiers, the summary / calibration /
  sweep / dedup functions) that depends only on its arguments and the
  estimators in `evaluation/stats.py`;
- a thin **DB layer** (`load_rows`) that reads `phase2_final` joined to
  `ground_truth` and `questions`, classifying each pair with the dashboard's
  `_MATCH_STATUS_SQL` verbatim so match / differ means the same thing here as
  everywhere else in the project.

Canonical-row rule (docs/EXPERIMENT_RUNBOOK.md): the reported row for a pair
is the latest `phase2_final` per (question_id, country_code, condition_label)
within the experiment; earlier duplicates are superseded, never summed.

Usage:
    uv run python evaluation/exp36_analysis.py \
        --db data/odmi.db \
        --experiment-id exp36_frozen_headline \
        --out evaluation/results/exp36_analysis.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.stats import two_proportion_test, wilson_interval  # noqa: E402

# ---------------------------------------------------------------------------
# Pre-registered constants. Nothing else in this file is hardcoded: every
# other number is recomputed from the DB on each run.
# ---------------------------------------------------------------------------

# D47 resource strata of the held-out eight. Stratum A is the low/mid-resource,
# negative-rich half; stratum B is the higher-resource half (the no-confound
# countries per R4c).
STRATUM_A = ("BA", "MK", "ME", "BG")
STRATUM_B = ("FI", "HR", "SE", "BE")

# The pre-registered risk-coverage sweep grid over the D37 commit floor:
# 0.50 to 0.90 in steps of 0.05.
FLOOR_GRID = [round(0.50 + 0.05 * i, 2) for i in range(9)]
PRODUCTION_FLOOR = 0.65  # D37: the floor the run actually committed under.

# Reliability curve: 10 equal-width bins over [0, 1] (pre-registered).
N_CALIBRATION_BINS = 10

# Terminal statuses that mean a real answer was committed under the trio
# pipeline (D54), as opposed to an honest abstention or a failure. Mirrors
# `chaining_analysis._COMMITTED_STATUSES` and the coordinator's finalisation.
_COMMITTED_STATUSES = {"accepted_by_verifier", "accepted_by_adjudicator"}

# Match statuses that can enter an accuracy denominator. `flag_review`
# (committed answer against an ODMI `not applicable` gold) and
# `no_ground_truth` rows cannot be scored, so they are excluded and counted.
_SCOREABLE = {"match", "near_match", "differ"}

PREREGISTERED_RQ3_READ = (
    "Flat FP across strata supports language driving abstention not error; "
    "a rise in stratum A is the headline negative result."
)


# ---------------------------------------------------------------------------
# Pure layer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PairRow:
    """One `phase2_final` row for one (question, country) pair.

    `match_status` is the dashboard's classification (`match` / `near_match` /
    `differ` / `abstained` / `flag_review` / `no_ground_truth` /
    `no_swarm_answer`), computed by the same SQL, so accuracy here means the
    same thing as everywhere else in the project. `row_id` is the
    `phase2_final.id`, used only by the canonical-row dedup.
    """

    row_id: int
    question_id: str
    country_code: str
    condition_label: str
    terminal_status: str
    final_answer: Optional[str]
    final_confidence: Optional[float]
    gold_answer: Optional[str]
    gold_decision: Optional[str]
    dimension: Optional[str]
    answer_shape: Optional[str]
    match_status: str


def norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def is_abstention(answer: Optional[str]) -> bool:
    """True for the `inconclusive` abstention literal only. Mirrors the
    coordinator's `_is_abstention`; `not_applicable` is a determination,
    not an abstention."""
    return norm(answer) == "inconclusive"


def is_committed(row: PairRow) -> bool:
    """A pair committed a real answer iff it reached a committed terminal
    status with a non-abstention final answer (D37)."""
    return (
        row.terminal_status in _COMMITTED_STATUSES
        and bool(row.final_answer)
        and not is_abstention(row.final_answer)
    )


def is_failed(row: PairRow) -> bool:
    return row.terminal_status == "agent_failure"


def is_scoreable(row: PairRow) -> bool:
    return row.match_status in _SCOREABLE


def is_match(row: PairRow) -> bool:
    return row.match_status == "match"


def is_negative_gold(row: PairRow) -> bool:
    """Binary question whose ODMI gold is `no`: the class where a committed
    wrong answer is a visible false positive (R4)."""
    return norm(row.answer_shape) == "binary" and norm(row.gold_answer) == "no"


def is_binary_gold(row: PairRow) -> bool:
    return (
        norm(row.answer_shape) == "binary"
        and norm(row.gold_answer) in ("yes", "no")
    )


def resource_stratum(country_code: str) -> str:
    if country_code in STRATUM_A:
        return "A"
    if country_code in STRATUM_B:
        return "B"
    return "other"


def decision_class(decision: Optional[str]) -> str:
    d = norm(decision)
    return d if d in ("confirm", "complement", "change") else "unknown"


def dedup_canonical(rows: list[PairRow]) -> tuple[list[PairRow], int]:
    """Canonical-row rule (docs/EXPERIMENT_RUNBOOK.md): keep the latest
    `phase2_final` (highest id) per (question_id, country_code,
    condition_label); earlier duplicates are superseded, never summed.

    Returns (canonical rows, count of superseded duplicates). Order of the
    returned rows is deterministic: sorted by (country, question, label).
    """
    canon: dict[tuple[str, str, str], PairRow] = {}
    for row in rows:
        key = (row.question_id, row.country_code, row.condition_label)
        held = canon.get(key)
        if held is None or row.row_id > held.row_id:
            canon[key] = row
    kept = sorted(
        canon.values(),
        key=lambda r: (r.country_code, r.question_id, r.condition_label),
    )
    return kept, len(rows) - len(kept)


def _rate(successes: int, n: int) -> dict:
    """Proportion with its Wilson 95% interval (R8: the interval, not the
    point, is the result)."""
    lo, hi = wilson_interval(successes, n)
    return {
        "successes": successes,
        "n": n,
        "rate": (successes / n) if n else None,
        "wilson_95": [lo, hi],
    }


def binary_headline(rows: list[PairRow]) -> dict:
    """Balance-aware headline on binary-gold pairs (R4).

    Per-class recall = committed-and-matching over ALL pairs of that gold
    class, so an abstention counts against recall (a pair the swarm did not
    answer is not recovered). Balanced accuracy is the mean of the two class
    recalls and Youden's J their sum minus one; both are defined only when
    both classes are present. The majority-class constant predictor scores
    its class share as raw accuracy and exactly J = 0, which is the baseline
    the headline must beat.
    """
    binary = [r for r in rows if is_binary_gold(r)]
    yes = [r for r in binary if norm(r.gold_answer) == "yes"]
    no = [r for r in binary if norm(r.gold_answer) == "no"]

    def recovered(items: list[PairRow]) -> int:
        return sum(1 for r in items if is_committed(r) and is_match(r))

    yes_recall = _rate(recovered(yes), len(yes))
    no_recall = _rate(recovered(no), len(no))
    both_present = bool(yes) and bool(no)
    balanced = (
        (yes_recall["rate"] + no_recall["rate"]) / 2 if both_present else None
    )
    youden = (
        yes_recall["rate"] + no_recall["rate"] - 1.0 if both_present else None
    )

    n = len(binary)
    majority_class = None
    majority_share = None
    if n:
        majority_class = "yes" if len(yes) >= len(no) else "no"
        majority_share = max(len(yes), len(no)) / n
    raw_accuracy = _rate(recovered(binary), n)

    return {
        "n_binary_gold_pairs": n,
        "n_yes_gold": len(yes),
        "n_no_gold": len(no),
        "n_committed": sum(1 for r in binary if is_committed(r)),
        "per_class_recall": {"yes": yes_recall, "no": no_recall},
        "balanced_accuracy": balanced,
        "youden_j": youden,
        "majority_class": majority_class,
        "majority_baseline_accuracy": majority_share,
        "majority_baseline_youden_j": 0.0 if n else None,
        "raw_accuracy": raw_accuracy,
        "beats_majority_baseline": (
            None if (not n or raw_accuracy["rate"] is None)
            else raw_accuracy["rate"] > majority_share
        ),
    }


def three_outcome(rows: list[PairRow]) -> dict:
    """The three-outcome read (D38 R4, D47): commit-accuracy / coverage /
    negative-gold false-positive rate, all with Wilson intervals.

    - coverage = committed / all pairs; the complement is the abstention
      rate, within which honest abstentions and agent failures are counted
      separately (a pair that never commits is an abstention per D37, but
      the split is disclosed).
    - commit accuracy = strict matches over scoreable committed pairs.
      `near_match` (adjacent band, D28) is reported separately, never folded
      in. Committed pairs that cannot be scored (`flag_review` on an ODMI
      n/a gold, or no ground truth) are excluded from the denominator and
      counted.
    - negative-gold FP rate = committed-but-wrong on a binary `no` gold,
      over ALL binary `no` golds (the same denominator as the EXP-34 / D50
      reads and `malta_failure_audit.floor_sweep`).
    """
    n = len(rows)
    committed = [r for r in rows if is_committed(r)]
    failed = [r for r in rows if is_failed(r)]
    abstained = [r for r in rows if not is_committed(r) and not is_failed(r)]

    scoreable = [r for r in committed if is_scoreable(r)]
    n_match = sum(1 for r in scoreable if is_match(r))
    n_near = sum(1 for r in scoreable if r.match_status == "near_match")
    n_flag = sum(1 for r in committed if r.match_status == "flag_review")
    n_no_gt = sum(1 for r in committed if r.match_status == "no_ground_truth")

    neg = [r for r in rows if is_negative_gold(r)]
    neg_fp = sum(1 for r in neg if is_committed(r) and not is_match(r))

    return {
        "n": n,
        "n_committed": len(committed),
        "n_abstained": len(abstained),
        "n_failed": len(failed),
        "coverage": _rate(len(committed), n),
        "abstention_rate": _rate(n - len(committed), n),
        "commit_accuracy": _rate(n_match, len(scoreable)),
        "n_near_match": n_near,
        "n_committed_unscoreable": {
            "flag_review": n_flag,
            "no_ground_truth": n_no_gt,
        },
        "negative_golds": {
            "n": len(neg),
            "n_committed": sum(1 for r in neg if is_committed(r)),
            "false_positives": neg_fp,
            "fp_rate": _rate(neg_fp, len(neg)),
        },
    }


def stratified(rows: list[PairRow]) -> dict:
    """The pre-registered stratifications: ODMI dimension, D47 resource
    stratum, ODMI assessor decision, answer shape, plus country (the
    project's standing stratification axis). Each cell is a full
    three-outcome read on its subset."""

    def by(key_fn) -> dict:
        groups: dict[str, list[PairRow]] = {}
        for row in rows:
            groups.setdefault(key_fn(row), []).append(row)
        return {k: three_outcome(v) for k, v in sorted(groups.items())}

    return {
        "by_dimension": by(lambda r: r.dimension or "unknown"),
        "by_resource_stratum": by(lambda r: resource_stratum(r.country_code)),
        "by_decision": by(lambda r: decision_class(r.gold_decision)),
        "by_answer_shape": by(lambda r: norm(r.answer_shape) or "unknown"),
        "by_country": by(lambda r: r.country_code),
    }


def rq3_language_read(rows: list[PairRow]) -> dict:
    """RQ3: the stratum A vs B contrast. Per stratum: negative-gold FP rate,
    abstention rate and commit accuracy with Wilson intervals; then a
    two-proportion comparison (pooled z, Newcombe interval on the
    difference) per endpoint. The pre-registered read is carried verbatim so
    the interpretation cannot drift after the numbers exist."""
    a_rows = [r for r in rows if resource_stratum(r.country_code) == "A"]
    b_rows = [r for r in rows if resource_stratum(r.country_code) == "B"]
    a = three_outcome(a_rows)
    b = three_outcome(b_rows)

    def contrast(pick) -> dict:
        ka, na = pick(a)
        kb, nb = pick(b)
        return two_proportion_test(ka, na, kb, nb)

    return {
        "stratum_a": {"countries": list(STRATUM_A), **a},
        "stratum_b": {"countries": list(STRATUM_B), **b},
        "contrasts_a_vs_b": {
            "negative_gold_fp_rate": contrast(
                lambda s: (s["negative_golds"]["false_positives"],
                           s["negative_golds"]["n"])
            ),
            "abstention_rate": contrast(
                lambda s: (s["abstention_rate"]["successes"],
                           s["abstention_rate"]["n"])
            ),
            "commit_accuracy": contrast(
                lambda s: (s["commit_accuracy"]["successes"],
                           s["commit_accuracy"]["n"])
            ),
        },
        "preregistered_read": PREREGISTERED_RQ3_READ,
    }


def calibration(rows: list[PairRow],
                n_bins: int = N_CALIBRATION_BINS) -> dict:
    """Reliability curve and expected calibration error over committed
    answers.

    Bins are equal-width over [0, 1]; a confidence of exactly 1.0 falls into
    the top bin. Only committed, scoreable pairs with a logged confidence
    enter; exclusions are counted. Per bin: count, mean confidence, empirical
    match rate and the absolute gap. ECE is the bin-count-weighted mean
    absolute gap. Empty bins are emitted with n = 0 and null rates so a
    figure can be drawn from the JSON without re-deriving the grid.
    """
    committed = [r for r in rows if is_committed(r)]
    missing_conf = [r for r in committed if r.final_confidence is None]
    unscoreable = [
        r for r in committed
        if r.final_confidence is not None and not is_scoreable(r)
    ]
    scored = [
        r for r in committed
        if r.final_confidence is not None and is_scoreable(r)
    ]

    bins: list[dict] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        members = [
            r for r in scored
            if (lo <= r.final_confidence < hi)
            or (i == n_bins - 1 and r.final_confidence == 1.0)
        ]
        n_b = len(members)
        matches = sum(1 for r in members if is_match(r))
        mean_conf = (
            sum(r.final_confidence for r in members) / n_b if n_b else None
        )
        match_rate = matches / n_b if n_b else None
        bins.append({
            "lo": round(lo, 2),
            "hi": round(hi, 2),
            "n": n_b,
            "n_match": matches,
            "mean_confidence": mean_conf,
            "match_rate": match_rate,
            "abs_gap": (
                abs(match_rate - mean_conf) if n_b else None
            ),
        })

    n_scored = len(scored)
    ece = (
        sum(b["n"] * b["abs_gap"] for b in bins if b["n"]) / n_scored
        if n_scored else None
    )
    return {
        "n_scored": n_scored,
        "n_committed_excluded": {
            "missing_confidence": len(missing_conf),
            "unscoreable": len(unscoreable),
        },
        "n_bins": n_bins,
        "bins": bins,
        "ece": ece,
    }


def floor_sweep(rows: list[PairRow],
                floors: list[float] = FLOOR_GRID) -> dict:
    """Risk-coverage sweep over the D37 commit floor. Replay arithmetic only.

    At floor t a pair counts as committed iff it committed in production AND
    its logged final confidence is at or above t. Coverage is committed over
    all pairs; risk is the non-match share among scoreable committed pairs.
    Two properties of the replay are disclosed rather than hidden:

    - floors below the production 0.65 cannot resurrect pairs the run
      abstained on (their sub-floor candidates were discarded at dispatch),
      so coverage below 0.65 moves only through adjudicator commits, which
      bypass the floor and can carry confidence under 0.65;
    - a committed pair with no logged confidence never passes any swept
      floor; the count is reported.
    """
    n = len(rows)
    committed = [r for r in rows if is_committed(r)]
    missing_conf = sum(1 for r in committed if r.final_confidence is None)

    table: list[dict] = []
    for floor in floors:
        at_floor = [
            r for r in committed
            if r.final_confidence is not None and r.final_confidence >= floor
        ]
        scoreable = [r for r in at_floor if is_scoreable(r)]
        n_match = sum(1 for r in scoreable if is_match(r))
        n_wrong = len(scoreable) - n_match
        table.append({
            "floor": floor,
            "is_production_floor": floor == PRODUCTION_FLOOR,
            "n_committed": len(at_floor),
            "coverage": len(at_floor) / n if n else None,
            "n_scoreable": len(scoreable),
            "n_match": n_match,
            "n_wrong": n_wrong,
            "risk": (n_wrong / len(scoreable)) if scoreable else None,
        })
    return {
        "n": n,
        "production_floor": PRODUCTION_FLOOR,
        "n_committed_missing_confidence": missing_conf,
        "floors": table,
        "note": (
            "Floors below the production 0.65 cannot recover pairs the run "
            "abstained on; sub-floor coverage moves only through adjudicator "
            "commits, which bypass the floor (D37)."
        ),
    }


def disagreement_bracket(rows: list[PairRow]) -> dict:
    """Support for the D22 staleness band. ODMI gold can be one cycle old,
    so a swarm-vs-ODMI disagreement is not automatically a swarm error. The
    lower bound treats every disagreement as a swarm error (it equals the
    strict commit accuracy); the upper bound excludes confirmed-stale gold,
    which needs the human review of each register entry, so it is emitted as
    pending rather than computed. The register lists every strict
    disagreement with the fields the review needs."""
    scoreable = [r for r in rows if is_committed(r) and is_scoreable(r)]
    n_match = sum(1 for r in scoreable if is_match(r))
    n_near = sum(1 for r in scoreable if r.match_status == "near_match")
    differ = [r for r in scoreable if r.match_status == "differ"]

    register = [
        {
            "question_id": r.question_id,
            "country_code": r.country_code,
            "condition_label": r.condition_label,
            "dimension": r.dimension,
            "decision": decision_class(r.gold_decision),
            "final_answer": r.final_answer,
            "gold_answer": r.gold_answer,
            "final_confidence": r.final_confidence,
        }
        for r in sorted(differ, key=lambda r: (r.country_code, r.question_id))
    ]
    return {
        "n_committed_scoreable": len(scoreable),
        "n_match": n_match,
        "n_near_match": n_near,
        "n_differ": len(differ),
        "commit_accuracy_lower_bound": _rate(n_match, len(scoreable)),
        "commit_accuracy_upper_bound": None,
        "upper_bound_note": (
            "Pending the D22 staleness review: the upper bound recomputes as "
            "(n_match + confirmed_stale_differ) / n_committed_scoreable once "
            "each register entry is reviewed."
        ),
        "differ_register": register,
    }


def analyse(rows: list[PairRow], n_raw: int) -> dict:
    """The full report over the canonical rows. Pure: DB-free and
    deterministic given the rows."""
    by_country: dict[str, int] = {}
    labels: set[str] = set()
    for r in rows:
        by_country[r.country_code] = by_country.get(r.country_code, 0) + 1
        labels.add(r.condition_label)

    return {
        "row_counts": {
            "raw_final_rows": n_raw,
            "canonical_pairs": len(rows),
            "superseded_duplicates": n_raw - len(rows),
            "by_country_canonical": dict(sorted(by_country.items())),
            "condition_labels": sorted(labels),
        },
        "headline": {
            "binary_balance_aware": binary_headline(rows),
            "three_outcome": three_outcome(rows),
        },
        "strata": stratified(rows),
        "rq3_language_read": rq3_language_read(rows),
        "calibration": calibration(rows),
        "risk_coverage_sweep": floor_sweep(rows),
        "disagreement_bracket": disagreement_bracket(rows),
    }


# ---------------------------------------------------------------------------
# DB layer (thin; the pure layer above carries the logic)
# ---------------------------------------------------------------------------

def load_rows(conn: sqlite3.Connection, experiment_id: str) -> list[PairRow]:
    """Every `phase2_final` row for the experiment, classified with the
    dashboard's `_MATCH_STATUS_SQL` verbatim. The arm (`condition_label`)
    lives on `phase2_researcher_runs`, not on `phase2_final`, so it is read
    back via the pair_run_id (first attempt wins, deterministically). Dedup
    to the canonical row happens in the pure layer, so the rule is
    unit-testable."""
    from dashboard.lib.db import _MATCH_STATUS_SQL

    query = f"""
        SELECT
            f.id                       AS row_id,
            f.question_id              AS question_id,
            f.country_code             AS country_code,
            COALESCE((
                SELECT r.condition_label
                FROM phase2_researcher_runs r
                WHERE r.pair_run_id = f.pair_run_id
                  AND r.condition_label IS NOT NULL
                ORDER BY r.retry_count ASC, r.id ASC
                LIMIT 1
            ), 'unlabelled')           AS condition_label,
            f.terminal_status          AS terminal_status,
            f.final_answer             AS final_answer,
            f.final_answer_confidence  AS final_confidence,
            gt.response                AS gold_answer,
            gt.decision                AS gold_decision,
            q.dimension                AS dimension,
            q.answer_shape             AS answer_shape,
            {_MATCH_STATUS_SQL}        AS match_status
        FROM phase2_final f
        LEFT JOIN ground_truth gt
          ON gt.question_id = f.question_id
         AND gt.country_code = f.country_code
        LEFT JOIN questions q ON q.question_id = f.question_id
        WHERE f.experiment_id = ?
    """
    conn.row_factory = sqlite3.Row
    return [
        PairRow(
            row_id=r["row_id"],
            question_id=r["question_id"],
            country_code=r["country_code"],
            condition_label=r["condition_label"],
            terminal_status=r["terminal_status"],
            final_answer=r["final_answer"],
            final_confidence=r["final_confidence"],
            gold_answer=r["gold_answer"],
            gold_decision=r["gold_decision"],
            dimension=r["dimension"],
            answer_shape=r["answer_shape"],
            match_status=r["match_status"],
        )
        for r in conn.execute(query, (experiment_id,)).fetchall()
    ]


def model_version_audit(conn: sqlite3.Connection,
                        experiment_id: str) -> dict:
    """Distinct model versions per agent table for the experiment. The
    frozen config pins every role to one model (D59), so anything other
    than a single version per table is a freeze violation to disclose."""
    audit = {}
    for table in ("phase2_researcher_runs", "phase2_verifier_runs",
                  "phase2_adjudications"):
        rows = conn.execute(
            f"SELECT model_version, COUNT(*) FROM {table} "
            "WHERE experiment_id = ? GROUP BY model_version",
            (experiment_id,),
        ).fetchall()
        audit[table] = {r[0]: r[1] for r in rows}
    return audit


def questions_in_bank(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt_rate(block: dict) -> str:
    if block["rate"] is None:
        return "-"
    lo, hi = block["wilson_95"]
    return (f"{block['rate']:.3f} [{lo:.3f}, {hi:.3f}] "
            f"({block['successes']}/{block['n']})")


def _print_summary(report: dict) -> None:
    rc = report["row_counts"]
    print(f"\n=== EXP-36 analysis: {report['experiment_id']} ===")
    print(f"  raw finals {rc['raw_final_rows']}, canonical pairs "
          f"{rc['canonical_pairs']} "
          f"(superseded {rc['superseded_duplicates']}), countries "
          f"{', '.join(f'{k}={v}' for k, v in rc['by_country_canonical'].items())}")

    b = report["headline"]["binary_balance_aware"]
    print(f"\n  Binary balance-aware (n={b['n_binary_gold_pairs']}, "
          f"yes={b['n_yes_gold']}, no={b['n_no_gold']}):")
    print(f"    yes recall      {_fmt_rate(b['per_class_recall']['yes'])}")
    print(f"    no recall       {_fmt_rate(b['per_class_recall']['no'])}")
    ba = b["balanced_accuracy"]
    yj = b["youden_j"]
    print(f"    balanced acc    {ba if ba is None else format(ba, '.3f')}   "
          f"Youden J {yj if yj is None else format(yj, '.3f')} "
          f"(majority baseline J=0)")
    mb = b["majority_baseline_accuracy"]
    ra = b["raw_accuracy"]["rate"]
    print(f"    raw acc {ra if ra is None else format(ra, '.3f')} vs majority "
          f"baseline {mb if mb is None else format(mb, '.3f')} "
          f"({b['majority_class']}), beats it: {b['beats_majority_baseline']}")

    t = report["headline"]["three_outcome"]
    print(f"\n  Three-outcome (n={t['n']}):")
    print(f"    coverage        {_fmt_rate(t['coverage'])}")
    print(f"    commit accuracy {_fmt_rate(t['commit_accuracy'])} "
          f"(near_match {t['n_near_match']} separate)")
    print(f"    neg-gold FP     {_fmt_rate(t['negative_golds']['fp_rate'])}")
    print(f"    abstained {t['n_abstained']}, failed {t['n_failed']}, "
          f"committed-unscoreable {t['n_committed_unscoreable']}")

    rq3 = report["rq3_language_read"]
    print("\n  RQ3 stratum contrast (A = low/mid-resource, B = higher):")
    for name, key in (("neg-gold FP", "negative_gold_fp_rate"),
                      ("abstention", "abstention_rate"),
                      ("commit acc", "commit_accuracy")):
        c = rq3["contrasts_a_vs_b"][key]
        d = c["delta"]
        print(f"    {name:11s} A={c['p1'] if c['p1'] is None else format(c['p1'], '.3f')} "
              f"B={c['p2'] if c['p2'] is None else format(c['p2'], '.3f')} "
              f"delta={d if d is None else format(d, '+.3f')} "
              f"p={c['p_value']:.3f}")

    cal = report["calibration"]
    ece = cal["ece"]
    print(f"\n  Calibration: n_scored={cal['n_scored']}, "
          f"ECE={ece if ece is None else format(ece, '.4f')}")

    print("\n  Risk-coverage sweep (D37 floor):")
    print(f"    {'floor':>6} {'coverage':>9} {'committed':>10} {'risk':>7}")
    for fl in report["risk_coverage_sweep"]["floors"]:
        cov = fl["coverage"]
        risk = fl["risk"]
        mark = " <- production" if fl["is_production_floor"] else ""
        print(f"    {fl['floor']:>6.2f} "
              f"{cov if cov is None else format(cov, '.3f'):>9} "
              f"{fl['n_committed']:>10} "
              f"{risk if risk is None else format(risk, '.3f'):>7}{mark}")

    br = report["disagreement_bracket"]
    print(f"\n  D22 bracket: {br['n_differ']} disagreements registered; "
          f"lower-bound commit accuracy "
          f"{_fmt_rate(br['commit_accuracy_lower_bound'])}; upper bound "
          f"pending staleness review.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="EXP-36 frozen headline analysis (pre-registered "
                    "endpoints, replay arithmetic only)."
    )
    parser.add_argument(
        "--db", type=Path, default=REPO_ROOT / "data" / "odmi.db",
        help="Path to the SQLite database (the canonical DB for the report).",
    )
    parser.add_argument(
        "--experiment-id", default="exp36_frozen_headline",
        help="The experiment_id tagged on the finalised pairs.",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Where to write the result JSON. Default: "
             "evaluation/results/exp36_analysis_<experiment_id>.json",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: {args.db} does not exist")
        return 2

    conn = sqlite3.connect(str(args.db))
    try:
        raw = load_rows(conn, args.experiment_id)
        if not raw:
            print(f"ERROR: no phase2_final rows carry "
                  f"experiment_id={args.experiment_id!r} in {args.db}")
            return 1
        audit = model_version_audit(conn, args.experiment_id)
        n_questions = questions_in_bank(conn)
    finally:
        conn.close()

    canonical, _n_superseded = dedup_canonical(raw)
    report = analyse(canonical, n_raw=len(raw))
    report["experiment_id"] = args.experiment_id
    report["db_path"] = str(args.db)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["preregistration"] = "docs/EXPERIMENTS_EXP36_PREREG.md"
    report["row_counts"]["questions_in_bank"] = n_questions
    report["model_version_audit"] = audit

    out_path = args.out or (
        REPO_ROOT / "evaluation" / "results"
        / f"exp36_analysis_{args.experiment_id}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    _print_summary(report)
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
