# Task: re-run the Malta pairs affected by the post-baseline fixes

The frozen Malta baseline (60/60, `condition_label` baseline, no `experiment_id`)
predates three fixes: the abstain-floor on the Adjudicator (`ad5b9a5`), the
`head_ok` WAF Playwright fallback (`4d6c568`), and the Playwright hardening
(`ecce68a`). This re-runs the affected pairs under those fixes, **tagged as a
separate experiment so the baseline stays frozen**, then compares.

## The affected subset (43 pairs)
Computed as: every MT pair that either finalised a committed answer below the
0.65 floor (abstain-fix changes it) OR had a `url_unreachable` Researcher attempt
(WAF-fix changes it). Recompute it fresh before running in case the set moved:

```sql
-- sub-floor committed OR url_unreachable, latest finalised per qid
```

The set at 2026-06-03:
I14 I22 I23 I4 I5 I6 I7 I8-a I8-b I8-c I9 I9-b I9-c P18 P21 P4 P5 PT10 PT15 PT16
PT17 PT18 PT19 PT25 PT26 PT27 PT29 PT31 PT39 PT4 PT42 PT44 PT5 PT6 PT9 Q10 Q11
Q15 Q19 Q23 Q4 Q6 Q9

## Run it (tagged, baseline-safe)
```bash
ODMI_SKIP_AUTO_PUBLISH=1 uv run python scripts/dispatch_subtrios.py \
  --pairs I14:MT I22:MT I23:MT I4:MT I5:MT I6:MT I7:MT I8-a:MT I8-b:MT I8-c:MT \
          I9:MT I9-b:MT I9-c:MT P18:MT P21:MT P4:MT P5:MT PT10:MT PT15:MT PT16:MT \
          PT17:MT PT18:MT PT19:MT PT25:MT PT26:MT PT27:MT PT29:MT PT31:MT PT39:MT \
          PT4:MT PT42:MT PT44:MT PT5:MT PT6:MT PT9:MT Q10:MT Q11:MT Q15:MT Q19:MT \
          Q23:MT Q4:MT Q6:MT Q9:MT \
  --parallel 3 --batch-id malta_postfix \
  --experiment-id malta_postfix_v1 --condition-label postfix
```
A 6-pair diagnostic slice (PT29 Q10 Q11 Q4 Q23 Q6) was already run under the same
`experiment_id` on 2026-06-03; resume is clean, so re-running the full set tops it
up. The dispatcher stops cleanly on a Claude 429.

## What to compare (write up the delta)
- Pull the `malta_postfix_v1` finalised rows vs the baseline (NULL experiment_id)
  for the same qids.
- Expected effects: the four 0.45 commits (Q10/Q11/Q6 false-`no`, PT29
  false-`yes`) become `inconclusive` (abstain-floor); the WAF-blocked pairs that
  failed `url_unreachable` now ground on data.gov.mt via the Playwright fallback
  (some recover to a correct commit, some to an honest abstention).
- Report the balance-aware delta (R4): committed accuracy, no-gold false-positive
  count, abstention rate, Youden's J, before vs after. Do NOT overwrite the
  baseline numbers; report `malta_postfix_v1` as a labelled comparison.
- Update SPEC, EXPERIMENTS.md (EXP-10), and the failure-mode taxonomy with the
  measured recovery.
