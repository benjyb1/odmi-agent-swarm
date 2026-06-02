"""Validate the catalogue-metrics tool against ODMI ground truth (D30).

Computes the nine in-scope metrics for a country from its national
catalogue and compares each computed band to ODMI's recorded answer.

LEAKAGE GUARD. `ground_truth` is read ONLY to score the output, AFTER the
band has been computed. ODMI's answer never feeds the computation: the
band comes from the harvested metadata and the question's own
allowed_answers. The comparison here is a separate read-only step.

France first (D4): FR self-reported the top band on nearly every Quality
question, so an exact match is expected on some and a lower band on
others. A one-band miss is the D28 near_match case and is a finding to
report, not to hide.

Usage:
    uv run python evaluation/validate_catalogue_fr.py FR
    uv run python evaluation/validate_catalogue_fr.py FR --max-pages 100 --delay 0.3
    uv run python evaluation/validate_catalogue_fr.py FR --from-cache
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.tools import answer_shapes
from agents.tools.catalogue import compute as catalogue_compute
from agents.tools.catalogue.compute import COMPUTABLE_QUESTIONS
from agents.tools.catalogue.harvest import harvest_country, load_cached_snapshot
from agents.tools.db import connect

# Stable display order: licence, conformance, URLs, deployment.
QUESTION_ORDER = ["Q12", "Q13", "Q16", "Q17", "Q18", "Q21", "Q22", "Q25", "Q27"]


def _ground_truth(question_id: str, country_code: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT response FROM ground_truth WHERE question_id = ? AND country_code = ?",
            (question_id, country_code.upper()),
        ).fetchone()
    return row[0] if row else None


def _classify(computed: str, gold: str | None, allowed: tuple[str, ...]) -> str:
    if gold is None:
        return "no_ground_truth"
    if computed == gold:
        return "exact"
    dist = answer_shapes.band_distance(computed, gold, list(allowed))
    if dist == 1:
        return "near_match"
    if dist is None:
        return "differ"
    return f"differ(+{dist})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate catalogue metrics vs ODMI GT.")
    parser.add_argument("country_code", nargs="?", default="FR")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Cap the harvest (representative sample; disclosed).")
    parser.add_argument("--delay", type=float, default=None,
                        help="Override the per-request delay for this run.")
    parser.add_argument("--from-cache", action="store_true",
                        help="Use the latest cached snapshot, do not re-harvest.")
    args = parser.parse_args()
    cc = args.country_code.upper()

    print(f"=== Catalogue validation: {cc} ===\n")

    if args.from_cache:
        snapshot = load_cached_snapshot(cc)
        if snapshot is None:
            print(f"No cache for {cc}. Run without --from-cache to harvest.")
            return 1
    else:
        print(f"Harvesting {cc} (max_pages={args.max_pages}, delay={args.delay})...")
        snapshot = harvest_country(cc, max_pages=args.max_pages, delay_s=args.delay)

    note = " [PARTIAL]" if snapshot.partial else ""
    print(
        f"snapshot {snapshot.snapshot_id}: {snapshot.dataset_count:,} datasets, "
        f"{snapshot.page_count} pages{note}\n"
    )

    header = f"{'Q':<5}{'computed':<12}{'ODMI':<12}{'verdict':<14}breakdown"
    print(header)
    print("-" * len(header))

    tally = {"exact": 0, "near_match": 0, "differ": 0, "other": 0}
    for qid in QUESTION_ORDER:
        if qid not in COMPUTABLE_QUESTIONS:
            continue
        shape = answer_shapes.load_question_shape(qid)
        comp = catalogue_compute.compute(qid, cc, snapshot=snapshot)
        if comp is None:
            print(f"{qid:<5}{'(n/a)':<12}{'':<12}{'unavailable':<14}")
            continue
        gold = _ground_truth(qid, cc)
        verdict = _classify(comp.band, gold, shape.allowed_answers)
        bucket = (
            "exact" if verdict == "exact"
            else "near_match" if verdict == "near_match"
            else "differ" if verdict.startswith("differ")
            else "other"
        )
        tally[bucket] += 1
        print(
            f"{qid:<5}{comp.band:<12}{str(gold):<12}{verdict:<14}{comp.evidence_quote}"
        )

    print()
    print(
        f"exact={tally['exact']}  near_match={tally['near_match']}  "
        f"differ={tally['differ']}  other={tally['other']}"
    )
    print(
        "\nReminder: ground_truth was read only to score the output. The bands "
        "were computed from harvested metadata alone."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
