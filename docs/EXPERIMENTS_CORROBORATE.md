# EXP-38: corroborative vs adversarial verifier framing (frozen-ladder replay)

Pre-registered 2026-07-16, before any run (R1). Registered as
`exp38_verifier_corroborate` in the `experiments` table.

## Why this experiment exists

Dissertation section 2.5 argues that a corroborative check (SAFE-style: seek
support for the claim) is the wrong shape for a thin-evidence setting, because
an optimistic support-seeker passes claims on adjacent evidence, and that
opposition (the incumbent `disprove` framing) is what the setting requires.
Feng et al. (2024) pull the other way: their Cooperate architecture beat
Compete. No arm in the programme has ever tested a corroborative framing
directly; the closest datum is EXP-11's tristate verdict collapsing to
always-confirm (J = 0.03), which changed the verdict taxonomy, not the stance.
This replay supplies the missing direct contrast at near-zero cost.

## Design

Search-free replay over the frozen EXP-11 stage-1 candidate set: 150
candidates (MT 30 + NO 120; 121 `should_pass`, 29 `should_fail`) stored as
`"kind":"freeze"` records in
`evaluation/results/verifier_redesign_verifier_tristate_v1.jsonl`. Candidates
are reconstructed from the freeze records themselves, never from a live
`build_candidates()` query (the live DB has drifted: a rebuild today yields
161 candidates with 13 mis-pairings; the freeze is the locked sample).

Two arms, identical user message per candidate, identical `VerifierOutput`
contract, identical model (`claude-sonnet-4-6` via CLIProxyAPI, D62
transport). The system prompt is the only variable:

- `disprove_replay`: the production `verifier-disprove` system prompt,
  re-scored. Re-baselining is required because the historical J = 0.41 was
  measured on the June model/transport; deltas are read against this fresh
  arm, not the June number (the comparator-artefact lesson).
- `corroborate_replay`: new `verifier-corroborate` strategy. Same structure,
  register and length discipline as disprove; the stance flips from "what is
  specifically wrong with this claim?" to "can this claim be positively
  supported?". Verdict rule stays within the binary contract: pass when the
  cited source or an independent snippet supports the claim, fail only on
  specific counter-evidence. No instruction to pass under uncertainty is
  included: the optimism, if it exists, must come from the framing, not from
  a planted rule, or the test is a straw man.

Both arms see the frozen adversarial snippets (the evidence block is byte
identical). ~300 LLM calls total, no web search, no dispatch.

## Endpoints (fixed now)

- Primary: Youden's J per arm (positive class = `should_fail`, prediction
  positive = `fail`, per `_binarise`), with the J delta between arms.
- Secondary: sensitivity on the 29 `should_fail` (the adversarial catch),
  false-rejection rate on the 121 `should_pass` with Wilson 95% CI, MCC,
  balanced accuracy, mean `verifier_confidence` by gold class.
- Paired test: exact McNemar on the 150 paired binarised verdicts.

## Hypothesis (directional, stated before the run)

Corroborate scores lower J than disprove, driven by a sensitivity collapse on
`should_fail` candidates (it passes bad claims it finds adjacent support for),
mirroring the tristate collapse. If corroborate instead matches or beats
disprove, that is a reportable negative for the section 2.5 argument and is
written up as such (R12); it would not flip production without a powered
end-to-end run (D45 framing).

## Rules compliance

R1 this document + registry row; R2 identical candidates per arm; R4 the
ladder metric is balance-aware by construction (J, per-class rates; the 121/29
skew is why raw accuracy is not reported); R8 stats fixed above; R11 n = 150,
no extension; R12 JSONL receipts per call in `evaluation/results/`.
Limitation: dev-burned candidates (MT+NO), evaluation-only apparatus, no
end-to-end retry loop; stated in the writeup alongside the result.
