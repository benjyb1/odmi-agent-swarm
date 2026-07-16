# EXP-39: is language a confound? Two probes without DeepL

Pre-registered 2026-07-16, before any run (R1). Registered as
`exp39_language_probe` in the `experiments` table. DeepL is not used anywhere
in this design (budget constraint, 2026-07-16); the translator is
argostranslate (OPUS-MT models, local CPU, versioned packages, free), which
also fixes the circularity objection to Claude-as-translator: if Claude
translated the evidence and Claude judged it, a null could mean the
comprehension bottleneck rode along inside the translation.

## What is already known, and the gap

- EXP-22 (AL, n=48 answerable): bilingual queries do not raise recall over
  English-only; AL's ceiling is thin web, not query language.
- The 127-case DeepL replay (NL/NO/AL): pre-translating evidence flips ~1
  verdict in 127; comprehension not implicated on Latin-script dev evidence.
- Gap 1: both tests cover Latin-script, dev-set languages. Stratum A of the
  held-out set (BA, MK, ME, BG) includes Cyrillic and lower-resource
  languages; nothing yet tests comprehension there.
- Gap 2: both existing tests are pre-translation designs. The production
  question is on-the-fly comprehension: the verifier reads foreign evidence
  live. A swap probe tests exactly that channel.
- Gap 3 (design-level): the RQ3 confirmatory read is the EXP-36 stratum A/B
  contrast (R7: the stratum design is the confound-breaker). These probes add
  mechanism, they do not replace that read.

## Part A (causal): language-swap replay, `exp39_language_probe`

Take the English-evidence subset of the 150 frozen EXP-11 ladder candidates
(language-ID over the frozen evidence block with langdetect; the achieved n
is reported, expected order tens; if n < 20 the probe is reported as
underpowered and descriptive only, fixed now). For each candidate, machine
translate the full evidence block (evidence quote + frozen snippets):

| arm | rendering |
|---|---|
| `en_replay` | untranslated English (anchor) |
| `en_to_fr` | French: high-resource control, bounds the MT-artefact effect |
| `en_to_bg` | Bulgarian: Cyrillic script, stratum-A analogue |
| `en_to_sq` | Albanian: low-resource Latin, ties to EXP-22's country |

The frozen `verifier-disprove` prompt on `claude-sonnet-4-6` is re-scored on
each rendering. Question text, claim and prompt stay English (production
behaviour: English question, native evidence). Same content, same claim, only
the evidence language moves; verdict changes isolate on-the-fly reading of
that language. ~4n LLM calls, no search, no dispatch.

**Endpoints (fixed now).** Per arm: binarised verdict agreement with
`en_replay` (flip rate), J against the gold labels, mean verifier_confidence.
Paired exact McNemar per language vs `en_replay`.

**Inference rule (fixed now).** The MT artefact bound is the `en_to_fr` flip
rate. Comprehension is implicated for language X only if
J(en_replay) - J(en_to_X) exceeds J(en_replay) - J(en_to_fr) by >= 0.10, or
the X flip rate exceeds the fr flip rate with McNemar p < 0.05. Below that:
consistent with comprehension not binding, stated as "consistent with" (R7).
Translationese biases toward finding degradation, so a null is strong
evidence of no comprehension limit; a positive is checked against 10
hand-inspected translations before being claimed (spot-check logged in the
results JSONL).

## Part B (observational): within-country evidence-language contrast

No translation at all. Language-ID the stored evidence (committed quote and
candidate snippets) across finalised dev pairs now, and across the EXP-36
held-out pairs once the headline lands. Within each country, compare commit
accuracy and negative-gold FP rate between pairs resolved on native-language
evidence and pairs resolved on English evidence, stratified by ODMI dimension
(Mantel-Haenszel over dimension strata, Wilson CIs per cell).

Holding country fixed removes the web-estate and base-rate confounds that
make cross-country language comparisons circular. Residual confound, stated
now: which pairs carry native-only evidence is not random (more domestic,
often harder questions), so the result is read as a bracket, not a point
estimate (R7). A flat native-vs-English gap within countries supports
availability over comprehension; a within-country gap concentrated on
native-evidence pairs, surviving the dimension stratification, implicates the
language channel and names where.

## Part A result (2026-07-16, run complete)

English-evidence subset n = 69 (81 of the 150 frozen candidates carry
Norwegian evidence and are excluded). Per arm, J against the gold labels and
verdict-flip rate vs the English anchor:

| arm | n | J | flip rate | McNemar vs en |
|---|---|---|---|---|
| en (anchor, from EXP-38) | 69 | 0.35 | — | — |
| en->fr (MT control) | 67 | 0.38 | 0.13 | p = 1.00 |
| en->bg (Cyrillic) | 68 | 0.31 | 0.22 | p = 0.30 |
| en->sq (low-resource) | 67 | 0.24 | 0.25 | p = 0.049 |

The pre-registered criteria fired for sq (J drop 0.15 beyond the fr
control; flip rate above fr with p < 0.05) and for nothing else. The
mandated 10-sample inspection then found 3/10 sq translations materially
degraded, tracing to mixed-language sources: langdetect over the
concatenated surface called 46 of the 69 "English" candidates English when
at least one snippet part is Norwegian, and the weakest MT pair (en->sq)
garbles those fragments. The quantified sensitivity split
(`evaluation/results/exp39_purity_sensitivity.json`) settles it:

- clean-English sources (n = 23): en J 0.53, fr 0.53, bg 0.47, sq 0.46 —
  sq beyond-control +0.07, bg +0.07, both under the 0.10 margin;
- mixed sources (n = 46): sq beyond-control +0.14 — the whole effect lives
  where the MT input was contaminated.

**Verdict: no comprehension penalty demonstrated.** The sq flag fails the
pre-registered quality gate; the clean-subset read is a null for all three
languages, now including a Cyrillic rendering. This is the third
independent test pointing the same way (EXP-22 query ablation; the
127-case pre-translation replay; this on-the-fly swap probe). Limitations,
stated: the clean subset is small (n = 23); translationese biases toward
finding degradation, which strengthens the null; synthetic translations
are not real stratum-A web prose, so the production-evidence read is Part
B over the EXP-36 rows. Method note for the Language section: language-ID
must run per snippet part, not over concatenated evidence; surface-level
detection mislabelled two-thirds of this subset.

Receipts: `evaluation/results/exp39_language_swap.jsonl`,
`exp39_language_swap_summary.json`, `exp39_sq_spotcheck.json`,
`exp39_source_purity.json`, `exp39_purity_sensitivity.json`.

## What this does not test, and the queued follow-on

Neither part tests whether bilingual querying earns recall on mid and
high-resource countries; the Language section currently asserts it without a
run. That is EXP-40 (`exp40_query_language_multicountry`, sketched, not yet
registered): the EXP-22 design on NO + NL, 2 arms x ~110 pairs, dispatched
after the EXP-28/35 battery clears the queue. EXP-22's own inference rule
already queued this confirmation.

## Rules compliance

R1 this document + registry row; R2 identical items across arms within each
part; R4 J and per-class rates, never bare accuracy; R8 McNemar exact, Wilson
CIs, margins above; R11 the English-evidence subset is whatever n the
language-ID yields, reported, never extended; R12 all raw model outputs and
translations stream to JSONL under `evaluation/results/`.
