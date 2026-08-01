# Result artefacts

The committed output of every analysis and replay run. These files are the audit
trail behind the numbers in the dissertation. Read them; do not regenerate them
in place. Every script listed here accepts an output flag, so a replay can write
to a scratch path and leave the committed copy alone.

`docs/RESULTS.md` is the register: it states each reported number with its
numerator, denominator, population and source database. This file answers the
other question, which is what each artefact in this directory actually is and
which script produced it.

Producers below were resolved by reading the scripts, not by inferring from
filenames. Where a script builds its output path from a `--tag` or `--experiment-id`
flag, the whole family is listed against that one script. Some older artefacts
were written under a caller-supplied `--out`, so their filename does not appear
in any source file; those say so, and name the script whose output shape matches.
The hand-written markdown has no producer at all and is listed separately.

## Headline

The results chapter rests on these.

| File | Produced by | What it is |
|---|---|---|
| `exp42_ladder.json` | `evaluation/exp42_ladder.py` | The four-rung architecture ladder on the 1,144 held-out pairs. Researcher alone, plus Verifier, full trio, cooperative verifier. Replay arithmetic over stored EXP-36 rows plus the EXP-42 arm B calls. |
| `exp36_headline.json` | `evaluation/exp36_analysis.py` | The pre-registered EXP-36 endpoints: per-class recall with Wilson intervals, balanced accuracy, Youden's J against a majority-class baseline. |
| `exp36_analysis_exp36_frozen_headline.json` | `evaluation/exp36_analysis.py` | The same pack regenerated on 2026-07-31 from canonical `data/odmi.db`. Numerically identical to `exp36_headline.json` at every leaf; the two differ only in `generated_at` and `db_path`. The first run read a worktree copy of the database; this one read canonical `data/odmi.db` and got the same answer, which is why it is committed. |
| `exp40_analysis.json` | `evaluation/exp40_analysis.py` | The same ladder on the 156-pair dev battery, and the source of the section 4.2 ablation table. |
| `exp41_analysis.json` | `evaluation/exp41_analysis.py` | Run-to-run stability across three replicates of one frozen configuration. |
| `exp36_maturity_reconstruction.json` | `evaluation/exp36_maturity_reconstruction.py` | Published 2025 ODMI score against the swarm's reconstructed score, per country. |
| `exp36_subgroup_equity.json`, `.md` | `evaluation/exp36_subgroup_equity.py` | Accuracy broken down by subgroup, with the write-up the script emits alongside the JSON. |

## Written up by hand

No script produces these. They are analysis prose committed next to the data
they discuss.

| File | Discussed in |
|---|---|
| `exp41_final.md` | The three-run EXP-41 stability result, frozen-configuration fingerprint included. |
| `exp41_interim_2run.md` | The two-run interim, superseded by `exp41_final.md`. |
| `EXP41_Stability_Results.md` | The stability write-up. |
| `heldout_fp_audit_*_summary.md` | Summaries emitted by `evaluation/heldout_fp_audit.py` alongside each JSONL. |
| `heldout_fp_audit_verification.md` | Cited from `docs/SPEC.md`. |
| `model_landscape_rows.sql` | The query behind `docs/MODEL_COST_ACCURACY_LANDSCAPE.md`. No producing script. |

## False-positive audits

`evaluation/heldout_fp_audit.py` writes `heldout_fp_audit<tag>.jsonl` and
`heldout_fp_audit<tag>_summary.md`, so every file in this family is that one
script under a different `--tag`. `evaluation/nl_fp_audit.py` does the same with
`nl_fp_audit<tag>.jsonl`.

| File | Notes |
|---|---|
| `heldout_fp_audit_merged94.jsonl` | The canonical merged audit of 94 false positives. Cited in `docs/RESULTS.md`. |
| `heldout_fp_audit.jsonl` | The first pass. Cited in `docs/SPEC.md` and `docs/DEFECTS.md`. |
| `heldout_fp_audit_pilot.jsonl` | Pilot before the full run. |
| `heldout_fp_audit_rerun20260721.jsonl` | Re-run of 2026-07-21, cited in `docs/DEFECTS.md`. |
| `nl_fp_audit.jsonl` | Netherlands audit. |
| `nl_fp_audit_adversarial.jsonl` | `evaluation/nl_fp_audit_adversarial.py`. An advocate is asked to overturn each finding of the first pass. |
| `nl_fp_audit_sonnet.jsonl` | The same audit under a different judge model. |
| `malta_failure_audit_MT.jsonl`, `_NL.jsonl` | `evaluation/malta_failure_audit.py --country`. |

## Verifier and adjudicator replays

Replays reconstruct an outcome from stored rows without calling a model.

| File | Produced by |
|---|---|
| `substring_v2_replay.jsonl` | `evaluation/replay_substring_v2.py` |
| `commit_policy_grid.jsonl` | `evaluation/replay_commit_policy.py` |
| `absence_receipts_replay.jsonl` | `evaluation/replay_absence_receipts.py` |
| `h_h_s_adjonly_replay.jsonl`, `s_s_o_adjonly_replay.jsonl` | `evaluation/replay_adjudicator_escalation.py --which` |
| `exp13a_wiring_replay.jsonl` | `evaluation/exp13a_wiring_replay.py` |
| `confidence_signals_replay.json` | `evaluation/confidence_signals_replay.py` |
| `translate_replay_cases.json` | `evaluation/translate_replay.py` |
| `verifier_counterfactual_20260611.json` | `evaluation/verifier_counterfactual.py` |
| `substring_gate_replay_20260611.json` | `evaluation/substring_gate_replay.py` |
| `adjudicator_commit_policy_20260611.json` | `evaluation/adjudicator_commit_policy.py` |
| `stack_attribution_20260611.json` | `evaluation/stack_attribution.py --out`. Its `A_verifier_discrimination` / `B_retry_dynamics` / `C_adjudicator_value` keys are the three analyses that script's docstring names. |
| `verifier_redesign_verifier_tristate_v1.jsonl` | `evaluation/verifier_redesign.py`, named from its run label. |
| `verifier_strategies_verifier_strategy_disc_v1.jsonl` | `evaluation/verifier_strategies.py`, named from its run label. |

## Confidence and calibration

| File | Produced by |
|---|---|
| `confidence_deepdive.json`, `reliability_diagram.svg` | `evaluation/confidence_deepdive.py` |
| `confidence_gates.jsonl`, `confidence_gates_summary.json` | `evaluation/confidence_gates.py` |
| `floor_sweep_all.jsonl` | `evaluation/floor_sweep_all.py` |
| `fp_cluster` | `evaluation/fp_cluster.py` |

## Language and translation

| File | Produced by |
|---|---|
| `exp39_language_swap.jsonl`, `_summary.json` | `evaluation/exp39_language_swap.py` |
| `exp39_translations.jsonl` | `evaluation/exp39_translate.py` |
| `exp39_partB_main.json`, `exp39_partB_heldout.json` | `evaluation/exp39_evidence_language_contrast.py`, which names the file from `--experiment-id`. |
| `exp39_source_purity.json`, `exp39_purity_sensitivity.json`, `exp39_sq_spotcheck.json` | Written under a caller-supplied `--out`, so the producing script is not recoverable from the filename. The first two carry the same `clean_en` / `mixed` split as the Part B contrast above. Discussed in `docs/EXPERIMENTS_LANGUAGE_PROBE.md`. |

## Search, retrieval and portal discovery

| File | Produced by |
|---|---|
| `diy_vs_tavily_2026*.jsonl` | `evaluation/diy_vs_tavily.py`. Retained for the pre-D43 comparison; both providers are now retired. |
| `discovery_chunk_1..7.json` | The portal-discovery run, one file per chunk. |
| `discovery_report.json` | `evaluation/discovery_table.py`, which merges the chunks (last chunk wins per country). |
| `portal_visibility.json` | `evaluation/portal_visibility_audit.py` |
| `cross_family_exp1.jsonl`, `_mistral.jsonl` | `evaluation/cross_family_backfill.py` |

## Earlier experiments

| File | Produced by |
|---|---|
| `exp12a_premise.jsonl` | `evaluation/exp12a_premise.py` |
| `exp12b_evidence_ladder.jsonl` | `evaluation/exp12b_evidence_ladder.py` |
| `exp25_entailment_smoke.jsonl` | `evaluation/exp25_entailment_smoke.py`. A feasibility smoke on a small balanced sample, never the confirmatory run. |
| `exp38_corroborate_ladder.jsonl`, `exp38_corroborate_summary.json` | `evaluation/exp38_corroborate_ladder.py` |
| `chaining_exp20_chaining_committing.json`, `chaining_retry_chaining_mt_v1.json`, `exp7_pairs_retry_chaining_mt_v1.json` | The EXP-7 and EXP-20 chaining runs, named from their run labels. Discussed in `docs/EXPERIMENTS_CHAINING.md` and `docs/EXPERIMENTS.md`. |
| `exp36_leakage_scan.csv` | `evaluation/leakage_fingerprint_audit.py --csv`. The filename is caller-supplied, so it is not recoverable from the script. `scripts/check_data_leakage.py` writes the same shape and is the other candidate. |

## Reproducing a number

Both headline replays read the database and make no model calls, so they need no
API keys and no network.

```bash
uv run python evaluation/exp42_ladder.py --json /tmp/exp42.json
```

```bash
uv run python evaluation/exp36_analysis.py --out /tmp/exp36.json
```

Write to a scratch path as shown. Passing no flag overwrites the committed copy.
