"""Register the four EXP-41 experiments in the `experiments` table (R1, D27).

`run_experiments.py` hard-fails preflight on any experiment_id absent from this
table, so nothing dispatches until these rows exist. Idempotent.

Four rows rather than one because each replicate needs its own experiment_id:
`arm_health` computes blocker_rate scoped by experiment_id alone
(`run_experiments.py`), so three replicates sharing an id would pool their
blockers and trip a spurious health pause on the later runs.

  uv run python scripts/register_exp41.py --db data/odmi.db
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

_BATTERY = (
    "156-pair development battery (MT 60 + NL 52 + AL 44, 78 negative golds), "
    "identical sample to EXP-34 and EXP-40. Frozen configuration, every knob "
    "pinned explicitly by scripts/gen_exp41_specs.py: claude-sonnet-4-6 for "
    "researcher / verifier / adjudicator / picker (D59); DIY search (D43); "
    "search_strategy wide_only (EXP-34); 5 results per query (EXP-18); "
    "3 queries; 3 retries; bilingual queries; verifier counter-search always "
    "(EXP-19); adjudicator_selection standard (EXP-16); full Researcher prompt, "
    "neg_licence off (D50); snippet picker on, 600 chars, 3 chunks, 16000-char "
    "page cap; abstention floor 0.65 (D37); no_cache (R9). No attempt-1 seed. "
    "Search cache archived and purged before every run. No adoption rule: "
    "production is unchanged (D45)."
)

_PREREG = "Pre-registration: docs/EXPERIMENTS_RUN_STABILITY.md."

ROWS = [
    (
        "exp41_cooperative_rerun",
        "EXP-41A Cooperative arm re-run (repairs the S4.2 ablation ladder)",
        "Live re-run of the EXP-40 cooperative arm: corroborative verifier, "
        "consensus commit, no adjudicator. The 2026-07-19 original left no "
        "row-level receipts in any database on disk, so the primary contrast "
        "reported in dissertation S4.2 (no_adjudicator vs cooperative, McNemar "
        "p = 1.00) cannot be regenerated; running the committed analysis script "
        "against the canonical DB returns n = 0 for all four arms. This restores "
        "the arm with receipts. One deliberate change from EXP-40: the attempt-1 "
        "seed off exp34 is dropped, so all 156 pairs run their own attempt 1 and "
        "the arm is self-contained. Endpoint: three-outcome and balance-aware "
        "per arm, primary contrast no_adjudicator vs cooperative on committed "
        "correctness by exact McNemar. The re-run may or may not reproduce the "
        "original null; either outcome is accepted in advance and reported "
        "(R12). " + _BATTERY + " " + _PREREG,
        "Single live arm cooperative_s46, pipeline_mode=cooperative; the three "
        "adversarial arms are decision-layer replays off exp41_stability_rep1.",
    ),
    (
        "exp41_stability_rep1",
        "EXP-41B Run-to-run stability, replicate 1 of 3",
        "First of three fresh dispatches of the incumbent trio under one frozen "
        "configuration, measuring the second condition of the Reproducibility "
        "criterion in dissertation S2.2 (evidence that a repeat run returns the "
        "same answers), which S4.7 currently leaves open. Also serves as the "
        "live trio arm of the S4.2 ladder, replacing the exp34 replay so every "
        "arm in that table derives from one campaign. Endpoints: three-way "
        "outcome unanimity with Fleiss' kappa, per-run marginal commit rate and "
        "its spread, label agreement restricted to unanimously committed pairs, "
        "both decomposed by gold class, and the share of unanimously committed "
        "pairs citing more than one distinct source URL across the three runs. "
        + _BATTERY + " " + _PREREG,
        "Single arm trio_s46, pipeline_mode=trio. Replicate 1 of 3; identical "
        "knobs to replicates 2 and 3.",
    ),
    (
        "exp41_stability_rep2",
        "EXP-41B Run-to-run stability, replicate 2 of 3",
        "Second fresh dispatch, knob-identical to replicate 1. Dispatched only "
        "after the search cache has been archived and purged, so it shares no "
        "retrieved evidence with replicate 1: a repeat reading the first run's "
        "cache would hold the evidence fixed and measure sampling variance "
        "alone, which is the opposite of the quantity of interest. "
        + _BATTERY + " " + _PREREG,
        "Single arm trio_s46, pipeline_mode=trio. Replicate 2 of 3.",
    ),
    (
        "exp41_stability_rep3",
        "EXP-41B Run-to-run stability, replicate 3 of 3",
        "Third fresh dispatch, knob-identical to replicates 1 and 2. Three "
        "replicates rather than two: two give a pairwise agreement rate and "
        "nothing else, while three separate a consistently unstable pair from "
        "one flaky run and are the minimum for any variance estimate. "
        + _BATTERY + " " + _PREREG,
        "Single arm trio_s46, pipeline_mode=trio. Replicate 3 of 3.",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="DB the dispatch will use.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: {db} does not exist")
        return 2

    conn = sqlite3.connect(str(db))
    try:
        for eid, name, description, conditions in ROWS:
            existing = conn.execute(
                "SELECT experiment_id FROM experiments WHERE experiment_id = ?",
                (eid,),
            ).fetchone()
            if existing:
                print(f"{eid} already registered; unchanged.")
                continue
            conn.execute(
                "INSERT INTO experiments (experiment_id, name, description, conditions) "
                "VALUES (?, ?, ?, ?)",
                (eid, name, description, conditions),
            )
            print(f"registered {eid}")
        conn.commit()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
