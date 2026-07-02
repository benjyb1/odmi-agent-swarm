# Cost surface

Rebuilt over the canonical DB (`data/odmi.db`), superseding the June Malta-only cost figures. Figures in `docs/figures/`.

Total spend across all logged LLM calls: £836.51 (111,210 calls, 2026-05-12T17:42:21Z to 2026-07-02T14:23:18Z).

## a. Cost-accuracy frontier (`cost_frontier.svg`)

Method: committed pairs per experiment arm (`condition_label` from `phase2_researcher_runs`, retry_count 0) and per main-run country with n >= 20 finals, joined to ground truth. Accuracy is match / (match + near_match + differ + abstained). Excludes still-running arms (exp18/19/20), exp21 (voided, D57), exp28/29 (absent or not requested), and smoke/aborted/stalled runs (smoke_nl, smoketest-001, retry_chaining_mt_v1_aborted, model_variants_mt).

| Arm | n | n scored | mean cost/pair (GBP) | accuracy |
|---|---|---|---|---|
| exp14_verifier_search_nl/always | 67 | 67 | £0.0547 | 37.3% |
| exp14_verifier_search_nl/never | 52 | 52 | £0.0444 | 53.8% |
| exp16_adjudicator_selection_nl/free | 52 | 52 | £0.0535 | 50.0% |
| exp16_adjudicator_selection_nl/standard | 52 | 52 | £0.0504 | 51.9% |
| exp17_breadth_nl/baseline_r5 | 52 | 52 | £0.0518 | 46.2% |
| exp17_breadth_nl/breadth_r10 | 51 | 51 | £0.0608 | 56.9% |
| exp17_picker_nl/picker_off | 51 | 51 | £0.0766 | 47.1% |
| exp17_picker_nl/picker_on | 51 | 51 | £0.0488 | 54.9% |
| exp22_foreign_lang_al/bilingual | 43 | 42 | £0.0608 | 31.0% |
| exp22_foreign_lang_al/en | 47 | 46 | £0.0615 | 30.4% |
| expA_calibration_anchors/baseline_full | 50 | 50 | £0.4037 | 44.0% |
| expA_calibration_anchors/calibrated | 52 | 52 | £0.1537 | 38.5% |
| expB_verifier_fit_check/baseline_disprove | 52 | 52 | £0.1355 | 44.2% |
| expB_verifier_fit_check/structured_fit | 52 | 52 | £0.1572 | 32.7% |
| expC_neg_evidence_licence/baseline_full | 52 | 52 | £0.1470 | 38.5% |
| expC_neg_evidence_licence/neg_licence | 48 | 48 | £0.1560 | 43.8% |
| retry_chaining_mt_v1/baseline | 37 | 37 | £0.0639 | 16.2% |
| retry_chaining_mt_v1/chained | 28 | 28 | £0.0761 | 32.1% |

| Country (main run) | n | n scored | mean cost/pair (GBP) | accuracy |
|---|---|---|---|---|
| FR | 124 | 119 | £0.0823 | 73.1% |
| MT | 60 | 60 | £0.0672 | 53.3% |
| NO | 143 | 138 | £0.0564 | 69.6% |

## b. Spend share by role (`cost_role_share.svg`)

Method: every row in `claude_usage_log`, grouped by context prefix (role). `verifier_<strategy>` rows collapse to `verifier`. Legacy `exp6_*` rows excluded. Role totals do not require a `subtrio_id` join, so this table covers `snippet_pick` and `search_adjudicate` calls that the per-arm/per-country/per-dimension tables below cannot reach (those calls carry no subtrio_id).

| Role | total cost (GBP) | share |
|---|---|---|
| snippet_pick | £614.72 | 73.6% |
| researcher | £110.83 | 13.3% |
| verifier | £58.82 | 7.0% |
| researcher_query_gen | £22.72 | 2.7% |
| adjudicator | £16.32 | 2.0% |
| verifier_query_gen | £8.92 | 1.1% |
| search_adjudicate | £3.33 | 0.4% |

## c. Cost per committed-correct answer, by country (`cost_per_correct_country.svg`)

Method: main runs only (`experiment_id IS NULL`), countries with n >= 20 finals. Cost per correct = total `cumulative_cost_usd` for the country divided by the number of committed matches.

| Country | n finals | n scored | n match | total cost (GBP) | cost per correct (GBP) |
|---|---|---|---|---|---|
| FR | 124 | 119 | 87 | £10.20 | £0.12 |
| MT | 60 | 60 | 32 | £4.03 | £0.13 |
| NO | 143 | 138 | 96 | £8.07 | £0.08 |

## d. Mean cost per pair by ODMI dimension (`cost_by_dimension.svg`)

Method: main runs only, joined to `questions.dimension`. Mean of `cumulative_cost_usd` per finalised pair in that dimension.

| Dimension | n | mean cost/pair (GBP) | accuracy |
|---|---|---|---|
| Impact | 98 | £0.0775 | 73.2% |
| Policy | 78 | £0.0693 | 70.3% |
| Portal | 118 | £0.0614 | 67.8% |
| Quality | 60 | £0.0712 | 44.8% |

## Caveats

Costs are notional subscription-equivalent pricing, not billed spend (D12/Q9); Opus pricing was backfilled 2026-06-25; rows before 2026-07-01 are Sonnet 4.6 era, not Sonnet 5. Model pins are constant within an experiment but vary across experiments: the expA/B/C arms ran during the Sonnet-exhaustion window partly or wholly on Opus 4.6 (hence £0.14 to £0.40 per pair), so cross-experiment cost comparisons in the frontier cross model families; EXP-32/33 will give clean same-battery frontier points on current models.

