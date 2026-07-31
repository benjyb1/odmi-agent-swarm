"""Was the post-D62 commit-accuracy drop a transport regression? No.

The suspected regression: re-running the EXP-28/29 dev battery (156 pairs,
trio_s46, sonnet-4-6, DIY) on the D62 user-turn transport and comparing each
pair against its most recent pre-2026-07-01 result showed coverage up
(0.44 -> 0.54) and commit-accuracy down (0.75 -> 0.64).

This script shows the drop is a comparator-mixture artefact, not a transport
effect. The naive "most recent June row" rule picks whatever ran last in
June, and for all 52 NL pairs that was the late-June Opus-4-6 prompt
experiments (expA/expB/expC), which commit far less and more precisely on NL
than Sonnet has ever done. Holding the comparator model fixed at
claude-sonnet-4-6 makes the June and post-D62 numbers indistinguishable:

    naive June comparator: June cov 0.456 acc 0.758 | now cov 0.551 acc 0.640
    sonnet-4-6 comparator: June cov 0.526 acc 0.646 | now cov 0.532 acc 0.651

Run against a DB that holds the exp29_sonnet5_model trio_s46 rows:

    uv run python evaluation/exp29_transport_regression_check.py --db data/odmi.db
"""
from __future__ import annotations

import argparse
import math
import sqlite3

# Mirrors dashboard/lib/db.py::_MATCH_STATUS_SQL (D22/D28/D35 semantics),
# with f/gt as the aliases bound in the queries below.
MATCH_SQL = """
    CASE
      WHEN gt.response IS NULL OR TRIM(gt.response) = '' THEN 'no_ground_truth'
      WHEN f.final_answer IS NULL OR TRIM(f.final_answer) = '' THEN 'no_swarm_answer'
      WHEN REPLACE(LOWER(TRIM(gt.response)), '_', ' ') IN ('not applicable', 'n/a', 'na')
        THEN CASE
          WHEN LOWER(TRIM(f.final_answer)) = 'inconclusive'
               OR REPLACE(LOWER(TRIM(f.final_answer)), '_', ' ') IN ('not applicable', 'n/a', 'na')
            THEN 'match'
          ELSE 'flag_review'
        END
      WHEN LOWER(TRIM(f.final_answer)) = 'inconclusive' THEN 'abstained'
      WHEN REPLACE(LOWER(TRIM(f.final_answer)), '_', ' ')
           = REPLACE(LOWER(TRIM(gt.response)), '_', ' ') THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'yes'
           AND (LOWER(TRIM(gt.response)) LIKE 'yes%')
           AND EXISTS (SELECT 1 FROM questions q
                       WHERE q.question_id = f.question_id AND q.answer_shape = 'binary')
        THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'no' AND LOWER(TRIM(gt.response)) = 'no' THEN 'match'
      WHEN EXISTS (
        SELECT 1 FROM questions q, json_each(q.allowed_answers) ja_swarm, json_each(q.allowed_answers) ja_gt
        WHERE q.question_id = f.question_id
          AND q.answer_shape IN ('percentage_band','ordinal_magnitude','count_band')
          AND ABS(ja_swarm.key - ja_gt.key) = 1
          AND LOWER(TRIM(ja_swarm.value)) = LOWER(TRIM(f.final_answer))
          AND LOWER(TRIM(ja_gt.value)) = LOWER(TRIM(gt.response))
          AND LOWER(TRIM(ja_swarm.value)) NOT IN ('not applicable','i don''t know','inconclusive','other')
          AND LOWER(TRIM(ja_gt.value)) NOT IN ('not applicable','i don''t know','inconclusive','other')
      ) THEN 'near_match'
      ELSE 'differ'
    END
"""

EXPERIMENT_ID = "exp29_sonnet5_model"
JUNE_CUTOFF = "2026-07-01"
COMMIT = ("match", "near_match", "differ", "flag_review")
ACC_NUM = ("match", "near_match")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (centre - half, centre + half)


def _query(con: sqlite3.Connection, model_filter: str | None) -> list[sqlite3.Row]:
    """One row per battery pair: current match status, June match status.

    model_filter=None reproduces the naive rule (most recent pre-July row of
    any config); a model string restricts the June comparator to that model.
    """
    june_model_join = ""
    june_model_where = ""
    if model_filter:
        june_model_join = "JOIN rmeta r2 ON r2.pair_run_id = f2.pair_run_id"
        june_model_where = f"AND r2.model_version = '{model_filter}'"
    q = f"""
    WITH cur AS (
      SELECT * FROM phase2_final WHERE id IN (
        SELECT id FROM (
          SELECT id, ROW_NUMBER() OVER (
            PARTITION BY question_id, country_code ORDER BY id DESC) rn
          FROM phase2_final WHERE experiment_id = '{EXPERIMENT_ID}') WHERE rn = 1)
    ),
    rmeta AS (
      SELECT pair_run_id, MIN(model_version) AS model_version
      FROM phase2_researcher_runs GROUP BY pair_run_id
    ),
    june AS (
      SELECT f.* FROM phase2_final f
      WHERE f.id IN (
        SELECT id FROM (
          SELECT f2.id, ROW_NUMBER() OVER (
            PARTITION BY f2.question_id, f2.country_code
            ORDER BY f2.created_at DESC, f2.id DESC) rn
          FROM phase2_final f2
          {june_model_join}
          WHERE f2.created_at < '{JUNE_CUTOFF}' {june_model_where}
        ) WHERE rn = 1)
    )
    SELECT c.country_code,
      (SELECT {MATCH_SQL} FROM (SELECT c.final_answer AS final_answer,
                                        c.question_id AS question_id) f) AS cur_match,
      (SELECT {MATCH_SQL} FROM (SELECT j.final_answer AS final_answer,
                                        j.question_id AS question_id) f) AS june_match
    FROM cur c
    JOIN june j ON j.question_id = c.question_id AND j.country_code = c.country_code
    LEFT JOIN ground_truth gt
      ON gt.question_id = c.question_id AND gt.country_code = c.country_code
    WHERE gt.response IS NOT NULL AND TRIM(gt.response) != ''
    """
    return con.execute(q).fetchall()


def _report(rows: list[sqlite3.Row], label: str) -> None:
    print(f"\n=== {label} (n={len(rows)} pairs with June comparator + gold) ===")
    strata = [("ALL", rows)] + [
        (cc, [r for r in rows if r["country_code"] == cc]) for cc in ("MT", "NL", "AL")
    ]
    for name, sub in strata:
        n = len(sub)
        if n == 0:
            continue
        line = [f"  {name:3s} n={n:3d}"]
        for era, col in (("June", "june_match"), ("Now ", "cur_match")):
            commits = [r for r in sub if r[col] in COMMIT]
            acc_den = [r for r in commits if r[col] != "flag_review"]
            acc_num = [r for r in acc_den if r[col] in ACC_NUM]
            clo, chi = wilson(len(commits), n)
            acc = len(acc_num) / len(acc_den) if acc_den else float("nan")
            alo, ahi = wilson(len(acc_num), len(acc_den))
            line.append(
                f"{era} cov {len(commits)/n:.3f} [{clo:.2f}-{chi:.2f}] "
                f"acc {acc:.3f} [{alo:.2f}-{ahi:.2f}] ({len(acc_num)}/{len(acc_den)})"
            )
        print(" | ".join(line))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="data/odmi.db")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    n = con.execute(
        "SELECT COUNT(*) FROM phase2_final WHERE experiment_id = ?", (EXPERIMENT_ID,)
    ).fetchone()[0]
    if n == 0:
        raise SystemExit(f"{args.db} has no {EXPERIMENT_ID} rows; point --db at the run DB")

    _report(_query(con, None), "naive comparator: most recent pre-July row, any config")
    _report(_query(con, "claude-sonnet-4-6"),
            "model held fixed: most recent pre-July claude-sonnet-4-6 row")


if __name__ == "__main__":
    main()
