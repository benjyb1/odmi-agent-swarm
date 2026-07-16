# EXP-28 re-run + EXP-35: config note and pre-run amendments

Dated 2026-07-16, written before dispatch (R1). This note records the deltas
between the July registrations and the run as actually configured. The designs,
endpoints and analysis are unchanged from `docs/EXPERIMENTS_ARCH_ABLATION.md`
(EXP-28) and `docs/EXPERIMENTS_FINAL_PROGRAMME.md` (EXP-35); only the items
below moved, all before any data.

## What runs

One orchestrator spec, four arms, each over the identical 156-pair dev battery
(MT 60 + NL 52 + AL 44, 78 negative golds):

| experiment_id | condition_label | pipeline_mode |
|---|---|---|
| `exp28_s46_rerun` | `trio_s46` | trio (control) |
| `exp28_s46_rerun` | `no_adjudicator_s46` | no_adjudicator |
| `exp28_s46_rerun` | `researcher_only_s46` | researcher_only |
| `exp35_self_critique` | `self_verify_s46` | researcher_self_verify |

All roles and the picker pinned `claude-sonnet-4-6`, provider `diy`, D62
transport. One knob (`pipeline_mode`) varies. Pilot first:
`evaluation/specs/exp28_s46_rerun_5pct.json` (8 pairs x 4 arms,
global_parallel 2, run alongside EXP-36 only because its footprint is small).
Full run: `evaluation/specs/exp28_ablation_s46_full.json`, dispatched only
after EXP-36 finishes (search-side concurrency is the binding constraint, per
the runbook; two orchestrators at full parallel would trip the WAFs).

## Amendments, with reasons

1. **experiment_id.** The full-battery spec previously wrote under
   `exp29_sonnet5_model`, an id already carrying two reconciled registrations
   and 44 stale partial finals in the canonical DB. The re-run uses the clean
   `exp28_s46_rerun` id (registered in the canonical DB 2026-07-09, now also
   in this worktree's registry). Nothing has ever run under it.
2. **search_strategy: `narrow_then_wide` -> `wide_only`.** The July
   registrations pinned `narrow_then_wide` to match the then-planned
   `trio_s46` control. That control chain is void: the original EXP-28 control
   (`trio_s5`) is a banned-model artefact (D59), and the July `trio_s46`
   battery's rows were lost. The ablation's job is to read against the
   architecture the dissertation reports, which is the EXP-36 frozen
   production config, and that is `wide_only` (D64, adopted by EXP-34).
   Pinning the old strategy would make the ladder an ablation of a
   configuration no longer used anywhere.
3. **Consequence for the model-frontier controls.** `exp32_model_haiku` (156
   finals) and `exp36_model_opus` (157 finals) declare `control = exp28
   trio_s5`, which is unusable (D59). Their valid 4.6 comparator on the same
   battery and the same `narrow_then_wide` strategy is EXP-34's
   `baseline_narrow_then_wide` arm; `trio_s46` from this run adds the
   `wide_only` production point. Any Haiku/Opus vs 4.6 comparison in the
   report must either use the EXP-34 baseline arm as the matched control or
   bridge across the EXP-34 measured narrow-vs-wide delta, and must disclose
   which. A knob audit of the Haiku/Opus rows (their specs live in another
   worktree) is owed before that comparison is written.
4. **EXP-35 folded into the same run.** Its registered controls are the
   EXP-28 arms "paired on the same pairs"; running it in the same spec, same
   day, same warm-cache regime is the cleanest execution of that design. Its
   spec-file pin also moves to `wide_only` for the same reason as (2).
5. **Cache.** Type `accuracy`, retrieval knobs identical across arms: the
   shared warm dev cache is benign and matches the EXP-32 precedent. The
   held-out cache is untouched (dev countries only).

## Pilot gates (before the full battery)

- All four arms finalise their 8 pairs without `agent_failure` /
  `auth_unavailable` (the researcher_only arm stalled on the D58 auth bug in
  July; the pilot exists to catch a recurrence early).
- `trio_s46` pilot outcomes eyeballed against the EXP-34 wide_only arm's
  behaviour on overlapping pairs (sanity, not a statistical test).
- EXP-36 throughput not degraded while the pilot runs (baseline 68 finals/hr;
  check before and after).

## Pilot outcome (2026-07-16, pre-full-run addendum; updated live)

All four arms finalised 8/8, healthy, zero `agent_failure` /
`auth_unavailable` (completed 10:04 UTC; the researcher_only D58
recurrence did not appear). The first pilot attempt failed on a missing
worktree `.env` (the failure mode the EXP-36 runbook documents), unrelated
to D58, fixed. Arm mechanics verified: no_adjudicator abstains exactly
where trio adjudicates (I10:AL, I22:MT); researcher_only and self_verify
commit and abstain through their own terminal statuses. Trio pilot
outcomes match the EXP-34 arm on the stable NL/AL pairs; divergence
confined to the known-retry-noisy MT pairs. Gates 1-2: passed.

Gate 3 (EXP-36 throughput), recorded honestly: post-relaunch EXP-36 ran at
roughly 37 finals/hr against the 68/hr pre-stall baseline while the pilot
and the EXP-38/39 replays shared the window. The attribution is confounded
(the window had just recovered from exhaustion), but the direction is
clear enough that the full 4 x 156 run stays queued behind EXP-36
completion rather than running alongside it.

Budget correction from measured pilot cost: the trio arm spent ~37
calls/pair (299 over 8 pairs), against the ~12/pair the July registration
implied. Full-run `budget_calls` raised 13,500 -> 20,000 before dispatch
(156 x 4 arms at a ~30-call blended average plus headroom); the
orchestrator's budget pause remains the hard guard.
