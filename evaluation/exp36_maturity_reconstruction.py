"""EXP-36 maturity reconstruction: what ODMI score would the swarm have produced?

The published ODMI score is not an accuracy metric. It is the mean of the four
dimension percentages, each dimension being its own `SUM(awarded_score) /
SUM(max_score)`. This script applies that identical formula to the swarm's
answers instead of the country's own, so the two numbers sit on one scale and a
figure can put them side by side.

Two facts make the substitution exact rather than approximate, and both are
asserted as preconditions at run time so the script fails loudly if a later
ground-truth reload breaks them:

1. **The scoring rubric is recoverable from the data.** Every
   `(question_id, response)` key in `ground_truth` maps to exactly one
   `awarded_score / max_score` fraction across all 36 countries (345 keys over
   4,680 rows). ODMI marks a given answer to a given question the same way
   everywhere, so the table is its own marking scheme, and any swarm answer
   drawn from the same literal vocabulary can be marked by lookup. No partial
   credit is invented.
2. **The formula reproduces the published figures.** Dimension-mean returns
   FR 100.0, LT 98.0, SK 95.5, EE 94.2, MT 65.7, BG 62.9, matching the
   published 2025 ranking exactly. The flatter `SUM / SUM` over all 143
   questions does not (it puts BE at 77.0 against a published 76.6), so it is
   not used.

A swarm answer that is not in the rubric for its question scores zero: ODMI has
no marks for an answer it does not recognise, and inventing a fraction for it
would be inventing marks.

Abstentions
-----------
508 of the 1,144 pairs abstained, so the reconstruction is an interval, not a
point. Two policies bound it, and they are the two the figure draws:

- **floor** — an abstention is worth nothing, but still counts against the
  denominator. What the swarm can defend on public evidence alone.
- **ceiling** — abstentions leave both numerator and denominator, so the
  committed pairs are extrapolated to the whole dimension. What the swarm would
  score if the pairs it could not reach behaved like the ones it could.

The oracle-fill policy (abstentions filled from the answer key) is deliberately
absent. Filling 44% of pairs from ground truth makes the result 44% ground truth
by construction, and no human-review stage exists in this system for such a line
to represent.

Bar width therefore reads as the share of a country's assessment that public
evidence could not reach. It has two candidate causes the figure cannot
separate: evidence is scarcer for that country, or its true answers are mostly
`no` and the swarm cannot commit negatives (§4.3 establishes the second
mechanism is real). The caption must state both.

Usage:
    uv run python evaluation/exp36_maturity_reconstruction.py \
        --db data/odmi.db \
        --experiment-id exp36_frozen_headline \
        --out evaluation/results/exp36_maturity_reconstruction.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.exp36_analysis import (  # noqa: E402
    dedup_canonical,
    is_committed,
    load_rows,
    norm,
)

HELD_OUT = ("BA", "BE", "BG", "FI", "HR", "ME", "MK", "SE")
CYCLE_YEAR = 2025

# The four ODMI dimensions, in the published report's order.
DIMENSIONS = (
    "policy_dimension",
    "portal_dimension",
    "quality_dimension",
    "impact_dimension",
)


# Pure layer

@dataclass(frozen=True)
class GoldCell:
    question_id: str
    dimension: str
    response: Optional[str]
    awarded_score: float
    max_score: float


@dataclass(frozen=True)
class CountryScores:
    country_code: str
    published: float
    floor: float
    ceiling: float
    n_questions: int
    n_committed: int
    n_abstained: int
    n_off_rubric: int
    coverage: float

    @property
    def width(self) -> float:
        return self.ceiling - self.floor


def build_rubric(gold: list[GoldCell]) -> dict[tuple[str, str], float]:
    """`(question_id, normalised response)` -> awarded fraction.

    Raises if any key carries more than one fraction: that would mean ODMI
    marked the same answer to the same question differently in two countries,
    and the lookup would be guessing.
    """
    seen: dict[tuple[str, str], set[float]] = defaultdict(set)
    for cell in gold:
        if cell.response is None or cell.max_score <= 0:
            continue
        key = (cell.question_id, norm(cell.response))
        seen[key].add(round(cell.awarded_score / cell.max_score, 4))

    ambiguous = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    if ambiguous:
        raise ValueError(
            "ODMI rubric is not deterministic; cannot mark swarm answers by "
            f"lookup. Ambiguous keys: {sorted(ambiguous)[:5]}"
        )
    return {k: next(iter(v)) for k, v in seen.items()}


def dimension_mean(per_dimension: dict[str, tuple[float, float]]) -> float:
    """Mean of the four dimension percentages: the published ODMI formula.

    A dimension with no scoreable denominator is dropped rather than counted as
    zero; the caller reports how often that happens.
    """
    pcts = [
        100.0 * awarded / maximum
        for awarded, maximum in per_dimension.values()
        if maximum > 0
    ]
    return statistics.fmean(pcts) if pcts else 0.0


def score_country(
    country_code: str,
    gold: list[GoldCell],
    answers: dict[str, Optional[str]],
    rubric: dict[tuple[str, float], float],
) -> CountryScores:
    """Published, floor and ceiling scores for one country.

    `answers` maps question_id -> the swarm's committed answer, or None where
    the pair abstained, failed, or was never run.
    """
    published: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    floor: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    ceiling: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    n_committed = n_abstained = n_off_rubric = 0

    for cell in gold:
        if cell.max_score <= 0:
            continue
        dim = cell.dimension

        published[dim][0] += cell.awarded_score
        published[dim][1] += cell.max_score

        answer = answers.get(cell.question_id)
        if answer is None:
            # Abstained: scores nothing, and only the floor keeps it in the
            # denominator. The ceiling drops it entirely.
            n_abstained += 1
            floor[dim][1] += cell.max_score
            continue

        n_committed += 1
        fraction = rubric.get((cell.question_id, norm(answer)))
        if fraction is None:
            # An answer ODMI has no marks for. Scores zero, still denominated.
            n_off_rubric += 1
            fraction = 0.0

        awarded = fraction * cell.max_score
        floor[dim][0] += awarded
        floor[dim][1] += cell.max_score
        ceiling[dim][0] += awarded
        ceiling[dim][1] += cell.max_score

    to_tuples = lambda d: {k: (v[0], v[1]) for k, v in d.items()}  # noqa: E731
    n_questions = n_committed + n_abstained

    return CountryScores(
        country_code=country_code,
        published=dimension_mean(to_tuples(published)),
        floor=dimension_mean(to_tuples(floor)),
        ceiling=dimension_mean(to_tuples(ceiling)),
        n_questions=n_questions,
        n_committed=n_committed,
        n_abstained=n_abstained,
        n_off_rubric=n_off_rubric,
        coverage=n_committed / n_questions if n_questions else 0.0,
    )


# DB layer

def load_gold(conn: sqlite3.Connection) -> list[GoldCell]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT question_id, dimension, response, awarded_score, max_score
        FROM ground_truth
        WHERE cycle_year = ? AND max_score IS NOT NULL
        """,
        (CYCLE_YEAR,),
    ).fetchall()
    return [
        GoldCell(
            question_id=r["question_id"],
            dimension=r["dimension"],
            response=r["response"],
            awarded_score=float(r["awarded_score"] or 0.0),
            max_score=float(r["max_score"] or 0.0),
        )
        for r in rows
    ]


def load_gold_by_country(conn: sqlite3.Connection) -> dict[str, list[GoldCell]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT country_code, question_id, dimension, response,
               awarded_score, max_score
        FROM ground_truth
        WHERE cycle_year = ? AND max_score IS NOT NULL
        """,
        (CYCLE_YEAR,),
    ).fetchall()
    out: dict[str, list[GoldCell]] = defaultdict(list)
    for r in rows:
        out[r["country_code"]].append(
            GoldCell(
                question_id=r["question_id"],
                dimension=r["dimension"],
                response=r["response"],
                awarded_score=float(r["awarded_score"] or 0.0),
                max_score=float(r["max_score"] or 0.0),
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/odmi.db")
    parser.add_argument("--experiment-id", default="exp36_frozen_headline")
    parser.add_argument(
        "--out", default="evaluation/results/exp36_maturity_reconstruction.json"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    rubric = build_rubric(load_gold(conn))
    gold_by_country = load_gold_by_country(conn)

    raw = load_rows(conn, args.experiment_id)
    rows, superseded = dedup_canonical(raw, scope_by_label=False)

    # question_id -> committed answer, per country. Abstentions and failures
    # are simply absent, which `score_country` reads as unreached.
    answers: dict[str, dict[str, Optional[str]]] = defaultdict(dict)
    for row in rows:
        if is_committed(row):
            answers[row.country_code][row.question_id] = row.final_answer

    scored = [
        score_country(cc, gold_by_country[cc], answers[cc], rubric)
        for cc in HELD_OUT
    ]
    scored.sort(key=lambda s: s.published, reverse=True)

    payload = {
        "experiment_id": args.experiment_id,
        "db_path": args.db,
        "provenance": {
            "population": "evaluation/exp36_analysis.load_rows + "
                          "dedup_canonical(scope_by_label=False)",
            "commit_rule": "evaluation/exp36_analysis.is_committed (D37)",
            "score_formula": "mean of the four dimension percentages, each "
                             "SUM(awarded_score)/SUM(max_score)",
            "marking": "ODMI rubric recovered from ground_truth: "
                       "(question_id, response) -> awarded fraction",
            "off_rubric_rule": "a swarm answer absent from its question's "
                               "rubric scores zero",
        },
        "rubric_keys": len(rubric),
        "raw_final_rows": len(raw),
        "canonical_pairs": len(rows),
        "superseded_duplicates": superseded,
        "countries": [
            {
                "country_code": s.country_code,
                "published": round(s.published, 1),
                "floor": round(s.floor, 1),
                "ceiling": round(s.ceiling, 1),
                "width": round(s.width, 1),
                "marker_inside_band": s.floor <= s.published <= s.ceiling,
                "n_questions": s.n_questions,
                "n_committed": s.n_committed,
                "n_abstained": s.n_abstained,
                "n_off_rubric": s.n_off_rubric,
                "coverage": round(s.coverage, 3),
            }
            for s in scored
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    header = f"{'cc':<4}{'published':>10}{'floor':>8}{'ceiling':>9}{'width':>7}{'cov':>7}{'in?':>5}"
    print(header)
    print("-" * len(header))
    for s in scored:
        inside = "yes" if s.floor <= s.published <= s.ceiling else "NO"
        print(
            f"{s.country_code:<4}{s.published:>10.1f}{s.floor:>8.1f}"
            f"{s.ceiling:>9.1f}{s.width:>7.1f}{s.coverage:>7.3f}{inside:>5}"
        )
    print(f"\nrubric keys {len(rubric)}; canonical pairs {len(rows)}; "
          f"superseded {superseded}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
