"""Generate the four EXP-41 specs from one frozen knob set and one pair list.

The campaign's whole claim is that four dispatches ran under an identical
configuration. Hand-writing four spec files would let a knob drift between
them, which is exactly the defect being repaired. So the specs are generated:
one FROZEN_KNOBS dict, one PAIRS list, four outputs that differ only in
`experiment_id`, `condition_label` and `pipeline_mode`.

Pre-registration: docs/EXPERIMENTS_RUN_STABILITY.md.

  uv run python scripts/gen_exp41_specs.py            # write the specs
  uv run python scripts/gen_exp41_specs.py --check    # verify on-disk == generated
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "evaluation" / "specs"

# The 156-pair dev battery (MT 60 + NL 52 + AL 44), taken verbatim from the
# EXP-40 spec so the repair lands on the identical sample the published §4.2
# table was computed over.
SOURCE_SPEC = SPECS / "exp40_cooperative_contrast.json"

# The incumbent production configuration, pinned exhaustively. Reconciled from
# the EXP-36 frozen headline spec and the EXP-34 wide_only arm: those two agree
# on every knob that matters, each simply leaving a different subset implicit
# at its default (EXP-34 omits prompt_variant=full, EXP-36 omits
# adjudicator_selection=standard). Everything either of them left implicit is
# written out here, so no default can drift under the campaign.
FROZEN_KNOBS = {
    # models (D59; never Sonnet 5 -- the model_defaults table still holds a
    # stale claude-sonnet-5 row, so leaving any of these unpinned hard-fails)
    "researcher_model": "claude-sonnet-4-6",
    "verifier_model": "claude-sonnet-4-6",
    "adjudicator_model": "claude-sonnet-4-6",
    "picker_model": "claude-sonnet-4-6",
    # retrieval
    "provider": "diy",                    # D43, DIY-only
    "search_strategy": "wide_only",       # EXP-34
    "max_results_per_query": 5,           # EXP-18
    "num_queries": 3,
    "query_language": "bilingual",
    # pipeline
    "strategy": "verifier-disprove",
    "verifier_prompt_variant": "default",
    "prompt_variant": "full",             # D50, neg_licence rejected
    "verifier_search": "always",          # EXP-19
    "adjudicator_selection": "standard",  # EXP-16
    "max_retries": 3,
    # snippet layer
    "snippet_picker": "on",
    "max_snippet_chars": 600,
    "picker_max_chunks": 3,
    "page_text_cap": 16000,
    # leak guard (R9). Disables cache READS; writes stay on, so the purge in
    # the runbook has to be repeated before every run.
    "no_cache": True,
}

# Deliberately absent, and why:
#   seed_experiment_id / seed_condition_label -- dropped. EXP-40 seeded
#     attempt 1 off exp34; a seeded arm is not independently recomputable,
#     which is the defect under repair.
#   chained -- false (EXP-20).
#   researcher_escalation_model / verifier_escalation_model -- unset, one
#     model throughout (EXP-8 off).
#   query_gen_model -- has no flag_map entry in run_experiments.py and no CLI
#     flag; setting it is a silent no-op. Query-gen follows researcher_model.
#   refresh_catalogue / no_warm_catalogue -- no flag_map entry, cannot be
#     pinned from a spec. Inert here: 0 of the 156 pairs are
#     catalogue-computable (COMPUTABLE_QUESTIONS is Q12/13/16/17/18/21/22/25/27
#     and the battery contains none of them; MT has no portal registry entry
#     at all). Disclosed in the pre-registration rather than claimed as
#     controlled.

# budget_calls per run: CALLS_PER_PAIR_WORST (45) x 156 + headroom.
BUDGET_PER_RUN = 7500

RUNS = [
    {
        "experiment_id": "exp41_cooperative_rerun",
        "condition_label": "cooperative_s46",
        "pipeline_mode": "cooperative",
        "description": (
            "EXP-41A. Live re-run of the EXP-40 cooperative arm on the same "
            "156-pair dev battery. The original run left no row-level receipts "
            "in any database, so the McNemar null reported in dissertation "
            "S4.2 cannot be regenerated; this restores it. One change from the "
            "EXP-40 spec: the attempt-1 seed off exp34 is dropped, so every "
            "pair runs its own attempt 1 and the arm is self-contained. "
            "Prereg: docs/EXPERIMENTS_RUN_STABILITY.md."
        ),
    },
    {
        "experiment_id": "exp41_stability_rep1",
        "condition_label": "trio_s46",
        "pipeline_mode": "trio",
        "description": (
            "EXP-41B replicate 1 of 3. Incumbent trio, frozen config, 156-pair "
            "dev battery. Doubles as the live trio arm of the S4.2 ablation "
            "ladder, replacing the exp34 replay so all four arms derive from "
            "one campaign under one configuration. Distinct experiment_id per "
            "replicate: run_experiments' resume and the coordinator's "
            "_find_resumable_researcher are both scoped on "
            "(experiment_id, condition_label), so replicates sharing a key "
            "would be skipped or would share evidence. "
            "Prereg: docs/EXPERIMENTS_RUN_STABILITY.md."
        ),
    },
    {
        "experiment_id": "exp41_stability_rep2",
        "condition_label": "trio_s46",
        "pipeline_mode": "trio",
        "description": (
            "EXP-41B replicate 2 of 3. Identical to replicate 1 in every knob. "
            "Dispatched only after the search cache has been archived and "
            "purged, so this run shares no retrieved evidence with replicate 1. "
            "Prereg: docs/EXPERIMENTS_RUN_STABILITY.md."
        ),
    },
    {
        "experiment_id": "exp41_stability_rep3",
        "condition_label": "trio_s46",
        "pipeline_mode": "trio",
        "description": (
            "EXP-41B replicate 3 of 3. Identical to replicates 1 and 2. Third "
            "replicate is what makes any variance estimate possible at all: "
            "two runs give a pairwise agreement rate and nothing else. "
            "Prereg: docs/EXPERIMENTS_RUN_STABILITY.md."
        ),
    },
]


def load_pairs() -> list[str]:
    spec = json.loads(SOURCE_SPEC.read_text())
    pairs = spec["experiments"][0]["pairs"]
    if len(pairs) != 156:
        raise SystemExit(f"expected 156 pairs in {SOURCE_SPEC}, found {len(pairs)}")
    return pairs


def build(run: dict, pairs: list[str]) -> dict:
    knobs = dict(FROZEN_KNOBS)
    knobs["pipeline_mode"] = run["pipeline_mode"]
    return {
        "run_id": run["experiment_id"],
        "description": run["description"],
        "headline": False,
        "global_parallel": 4,
        "budget_calls": BUDGET_PER_RUN,
        "experiments": [
            {
                "experiment_id": run["experiment_id"],
                "type": "accuracy",
                "pairs": pairs,
                "baseline_knobs": knobs,
                "arms": [{"condition_label": run["condition_label"], "knobs": {}}],
            }
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="Verify, do not write.")
    args = ap.parse_args()

    pairs = load_pairs()
    drift = []
    for run in RUNS:
        path = SPECS / f"{run['experiment_id']}.json"
        text = json.dumps(build(run, pairs), indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != text:
                drift.append(path.name)
        else:
            path.write_text(text)
            print(f"wrote {path.relative_to(REPO)}")

    if args.check:
        if drift:
            print(f"DRIFT: {drift} differ from the generator; re-run without --check")
            return 1
        print(f"VERIFIED: {len(RUNS)} specs match the generator, {len(pairs)} pairs each")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
