# EXP-24 Phase A: snippet-cap effect (read-only)

The Researcher's reasoning call sees each search snippet truncated to 600
characters by `agents/tools/search.py:format_for_prompt`
(`max_chars_per_snippet=600`). The DIY pipeline extracts up to 16,000 chars per
page and the picker stores an average of about 5,000 chars per row, so the LLM
sees on the order of one-tenth of what was extracted. The 600 value has never
been measured. This is `SNIP-1` in `docs/DECISION_SURFACE.md`, named there as
"the cheapest high-value sweep".

Phase A answers two questions from stored data, with no swarm calls:

1. **Where in its snippet does the cited evidence_quote actually sit?** If
   committed quotes cluster near the cap, the cap is biting on the population
   the swarm gets right.
2. **For pairs the swarm abstained on, does question-relevant content sit past
   the cap in the same snippet the Researcher only saw the first 600 chars of?**
   This is the "hidden answer" question, run as a heuristic.

Plus a cost projection at six candidate caps, so the trade-off space is
visible. Phase B (the replay experiment) is gated on Phase A's hidden-content
rate; if it had been near zero, Phase B would not have been worth running.

## Headline

A nuanced split, not a simple yes/no:

- **The cap is not biting on committed pairs.** Of the cited quotes that locate
  by substring match (82.6% of all citations), **81.7% sit in the first 100
  chars** of their snippet, and only **0.2% sit in the cap-adjacent 500-600
  band**. For the pairs the swarm successfully commits, the 600-char window is
  ample. The snippet picker is doing its job: the best chunk is at the top.
- **The cap may be biting on abstained pairs.** Of the 205 abstained pairs that
  have at least one stored snippet long enough to fit content past 600 (78.5%
  of all 261 abstentions), **80 have a question-relevant keyword cluster past
  position 600 in the same snippet** (39.0%, by heuristic). That is content the
  Researcher physically could not see and that, by signal, plausibly bore on
  the question.
- **The cost is modest.** Raising the cap from 600 to 2,500 adds 232 input
  tokens per call (+12% of baseline input); raising it to 8,000 adds 402 tokens
  (+22%). Not free, far from prohibitive.

The honest reading: the cap protects against irrelevant tail content (which is
why the picker-then-truncate pipeline works at all), but a tail of about a
third of abstentions plausibly lose information they would have used. The
clearest signal is **NL: 81.5% of long-snippet NL abstentions have content past
600 in their snippet**, which is also the country with the highest false-
positive rate. Worth a replay test.

The heuristic is noisy. A manual read of the surfaced examples shows some are
truly relevant (an MT "Malta's 4th National Action Plan" passage on `I8-c/MT`,
an open-data policy inventory on `P22/MT`) and some are tangential (an MT row
where the past-600 content is about Switzerland's portal, not Malta's). The
39% is therefore an upper bound; a 20-pair manual calibration of the heuristic
is the right next step before Phase B is fully sized.

## A1. Where cited quotes sit in their snippet

Per `evaluation/snippet_cap_analysis.py` over 3,952 Researcher rows with both an
`evidence_quote` and a `search_snippets` blob.

| Position in snippet | n | share |
|---|---:|---:|
| 0-100 chars | 2,669 | 81.7% |
| 100-300 | 356 | 10.9% |
| 300-500 | 235 | 7.2% |
| 500-600 (cap-adjacent) | 5 | 0.2% |
| past 600 (data anomaly) | 0 | 0.0% |

3,265 of 3,952 (82.6%) quotes locate by whitespace-normalised case-insensitive
match. The remaining 17.4% are paraphrased or normalised in ways my matcher
does not handle; the production substring gate (D34) accepts these so they did
exist in the snippets. That 17.4% is a separate signal about the gate's
flexibility, not directly about the cap.

The which-snippet-was-cited distribution shows a strong primacy effect:
**snippet[0] accounts for 41.8%** of citations, snippet[1] another 22.5%; by
snippet[5] only 4% of citations originate. The Researcher leans heavily on the
top SERP result, which fits the 0-100 clustering above: the best evidence is at
the top of the top result, and the picker keeps it there.

## A2. Hidden content in abstained-pair snippets

Per the same script. For each of the 261 distinct abstained pairs, walk **all**
its retry runs (not just the latest), pull every individual snippet > 800
chars (the floor to fit a 200-char cluster past 600), and search each long
snippet for the first cluster of two distinct question-content keywords within
a 200-char window. A cluster whose start position is past 600 is recorded as
"plausibly hidden from the Researcher".

| Country | hidden / long-snippet abstentions | rate |
|---|---:|---:|
| **NL** | 22 / 27 | **81.5%** |
| MT | 36 / 71 | 50.7% |
| FI | 7 / 20 | 35.0% |
| SE | 6 / 20 | 30.0% |
| NO | 5 / 27 | 18.5% |
| HR | 3 / 26 | 11.5% |
| AL | 1 / 14 | 7.1% |
| pooled | 80 / 205 | 39.0% |

The country split is meaningful. AL and HR (thin-web, low-resource) sit near
zero, which is consistent with "the answer is not on the Albanian/Croatian web
in the first place"; their abstentions are not a cap problem. NL stands out
strongly, and is also where the false-positive rate is highest, which puts both
findings on the same population: NL has evidence available, the swarm
mis-handles it. MT in between is consistent with the data.gov.mt 403 WAF
confound: snippets exist but the page body is fragmentary.

Sample surfaced clusters (the first 140 chars from the past-600 position):

- `I8-c/MT pos=796`: "Malta's 4th National Action Plan. ... A series of
  workshops were held on 30th November 2023 wherein members of the Forum were
  split up..."
- `P22/MT pos=603`: "public. Governments should conduct an inventory of
  existing data early in the process of open data policy development..."
- `PT23/NO pos=650`: "tools, including Google Analytics, may sample data in
  certain reports or when applying segments, which can lead to noticeable
  discrepancies..."
- `I4/MT pos=744`: "datasets that would anyway not be reused enough. ...
  Besides the Swiss national OGD portal, the national OGD portals from which
  the metadata..." (the heuristic's noise: this passage is about Switzerland,
  not Malta.)

The mix above is exactly what an upper-bound heuristic produces: real
candidates plus a fraction of off-topic matches that share keywords. The
calibration sample below will quantify the noise; pending that, treat 39% as
"up to 39%".

## A3. Cost projection

Per the script. For each stored Researcher row, recompute what
`format_for_prompt` would have shown the LLM at each candidate cap (sum of
`min(len(snippet), cap)` across the row's snippets), and project the input-token
extra at roughly 4 chars per token.

| cap | avg chars shown | extra chars vs 600 | extra tokens | extra % of input |
|---:|---:|---:|---:|---:|
| 600 (baseline) | 1,991 | 0 | 0 | 0.0% |
| 1,000 | 2,507 | +516 | +129 | +6.9% |
| 1,500 | 2,716 | +725 | +181 | +9.7% |
| 2,500 | 2,919 | +929 | +232 | +12.4% |
| 4,000 | 3,157 | +1,166 | +291 | +15.6% |
| 8,000 | 3,599 | +1,608 | +402 | +21.5% |

Baseline Researcher input is ~1,872 tokens per call and wall-clock ~15.6 s. The
curve flattens because each individual snippet only adds extra chars up to its
own length: many snippets are already under the new cap. By cap=8,000 we are
essentially uncapped for all but the longest tail.

A working interpretation: a cap in the 1,500-2,500 region buys most of the
recoverable hidden content at +10-12% input. The 8,000 ceiling captures the
long-tail outliers (~301 individual snippets are >10,000 chars) at +22%, which
is only worth it if Phase B shows the long tail flips outcomes.

## Caveats

- **Heuristic noise on A2.** Two-keyword clusters within 200 chars catch real
  content and incidental matches alike. The MT/I4 Switzerland example shows
  what a false positive looks like. A 20-pair manual calibration before Phase B
  sizing would tighten the 39% to a defensible number.
- **A1 located fraction.** 17.4% of cited quotes could not be located by my
  substring search but were accepted by the production gate (D34), so they did
  exist in the snippets. The position distribution in A1 is therefore over the
  82.6% I can locate, not the full population.
- **Verifier sees the same cap.** This study covers only the Researcher side.
  A Researcher commit on a 2,500-cap snippet would still be reviewed by a
  Verifier at 600. That is a real-world interaction Phase B must measure either
  by replaying both at the same cap or by reporting Researcher-only flips first.
- **Causal claim limited.** A2 shows that relevant-looking content **exists**
  past 600 in a third of abstained pairs. It does not show the Researcher
  **would have** used it. Phase B (replay at higher caps) is the causal test.

## What this means

The cap is not a problem for the swarm's right answers; the picker concentrates
useful content at the top. The cap is plausibly hiding evidence from a tail of
abstained pairs, especially on NL. Cost of raising it is modest. So:

1. **Phase B is worth running**, sized for NL primarily (where the hidden rate
   is 81.5%) and MT secondarily (where the WAF confound is interleaved). AL and
   HR can be excluded from Phase B; their tiny hidden rates mean cap changes
   will not help, which is itself a useful negative result.
2. **Calibrate the A2 heuristic first**, a 20-pair manual read to settle the
   true hidden rate. Free.
3. **Tentative cap candidates for Phase B**: 1,500 (cheap, captures most
   structurally hidden text) and 2,500 (broader recovery for +12% input). 8,000
   only if the long tail matters.

## Reproduce

```bash
uv run python evaluation/snippet_cap_analysis.py
uv run python evaluation/snippet_cap_analysis.py --db /path/to/odmi.db
```

Read-only against `data/odmi.db`. Joins to `questions` (for question text) and
to `ground_truth` (none in this script's joins, kept clean of leakage). No DB
writes; no pipeline contact.

## Phase B result (Opus replay, decisive)

EXP-24 Phase B ran: 25 NL abstained binary pairs, Researcher reasoning replayed
at cap=600 (baseline) and cap=3000 (treatment), every other variable held
constant including the stored snippets and prior queries. Opus pinned across
both arms. Cost: about $8.

Outcome was strictly worse at the higher cap:

| metric | cap=600 | cap=3000 |
|---|---:|---:|
| committed | 12 | 15 |
| correct | 3 | 3 |
| abstain to correct flip | - | 0 |
| abstain to wrong flip | - | 3 |
| correct to abstain flip | - | 0 |

The 3 abstentions that flipped to commit all flipped to a wrong "yes" against a
GT "no". Confidence on already-wrong commits rose with the bigger cap (P7
0.60 to 0.92, I3 0.50 to 0.92, Q4 honest abstain to confident wrong "yes" at
0.75). More context did not help the swarm find the right answer; it fed the
NL false-positive bias and made wrong answers more confident.

**Decision.** Keep `max_chars_per_snippet=600` as the production default. The
cap is doing useful work as an accidental constraint on the false-positive
bleed. Raising it is not the lever; the lever is the FP bias itself
(entailment-confidence work, trusted-domain narrow-then-widen, prompt audit).

The 17.4% un-located quotes from A1 remain a separate, useful signal about
substring-gate flexibility, not pursued here.

## Reproduce Phase B

```bash
uv run python evaluation/snippet_cap_replay.py --n 25 --country NL
```

Reads stored snippets only; no new search or fetch. Pinned to
`claude-opus-4-6`. Writes to `claude_usage_log` with `context LIKE 'exp24:%'`.

## Change log

| Date | Change |
|---|---|
| 2026-06-24 | Phase A landed: A1 quote-position, A2 hidden-content heuristic with per-country split, A3 cost projection across six caps. |
| 2026-06-24 | Phase A heuristic manually calibrated on 20 cases: true hidden rate 15-25%, not 39%; NL strongest at 29%. |
| 2026-06-24 | Phase B replay: cap=3000 vs cap=600 on 25 NL pairs, zero accuracy gain, 3 wrong-direction flips, higher confidence on wrong commits. Keep 600. EXP-24 closed. |
