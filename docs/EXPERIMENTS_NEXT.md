# Next experiments: pre-registered designs

Four designs, written before any run so the analysis plan is fixed blind (R1).
Three are confirmatory re-tests of decisions that were made on a thin or
unrepresentative sample; the fourth is the whole-system evaluation. All are
DIY-only (provider is closed, D43); none compares search providers. All draw
from the dev set (NL, MT, NO, FR, AL) except the headline run, which is the
held-out set by design.

Dev-country binary base rates (negative golds), used for the datasets below:
NL 26, MT 30, AL 22, NO 9, FR 1 (degenerate, easy tail only).

A note on cost: all four need a dispatch, so none is free. They are the queue
for when Claude budget allows. EXP-18 and EXP-19 are the two to spend on first.

---

## EXP-18: Retrieval breadth, multi-country confirmation

**Lineage.** EXP-17 breadth found results/query 5 -> 10 lifts candidate recall on
NL (n=52, single run, no significance test) and is currently "favoured, not
switched". Switching the default raises search cost ~17% on every query, across
all 36 countries, so it should not turn on a single small run.

**Question.** Does widening retrieval from 5 to 10 results/query raise candidate
recall enough to justify the cost, and does the gain hold where the web is thin?

**Dataset.** FR non-Quality web-answerable (the data-rich case where recall
responds to funnel changes) + AL (thin-web, low-resource, where breadth may
matter more or not at all). NL r5/r10 already exist (`exp17_breadth_nl`) and fold
in as a third stratum. Target ~90 FR + ~50 AL pairs.

**Arms (one variable).** `baseline_r5` (max_results_per_query 5) vs `breadth_r10`
(10). `type: retrieval`, cache forced off.

**Endpoints.** Primary: candidate recall (gold answer in any Researcher attempt),
pooled and per stratum. Secondary: commit accuracy, and cost per pair with
retries counted (R9).

**Adoption rule (fixed now).** Switch the production default to r10 only if
pooled candidate recall improves by >= +0.05 absolute AND the gain does not
reverse on the thin-web AL stratum (AL recall at r10 >= AL recall at r5).
Otherwise keep r5. The +17% cost is accepted only for a recall gain that clears
the margin on more than the easy country.

---

## EXP-19: Verifier counter-search, multi-country

**Lineage.** EXP-14 kept the Verifier's own web counter-search (`always`) over
`never` on NL (n=51), and the decision turned on a 0.62 vs 0.58 false-positive
margin: 4 points, inside noise at that n, on one country. The counter-search is a
real recurring cost (a web search every verifier round, every pair).

**Question.** Does dropping the Verifier's own counter-search hold commit accuracy
AND not raise the false-positive rate, across balanced multi-country data rather
than one NL run?

**Dataset.** NL + MT + AL (~78 negative golds across a data-rich Western, an
official-bilingual, and a thin-web low-resource country). The negative-gold mass
is what makes the deciding metric measurable beyond NL.

**Arms (one variable).** `always` (production) vs `never`. `type: retrieval`,
cache off. The owed `elective` arm (Verifier given search as a tool it chooses
after reading the evidence) is a separate build and is NOT in this re-test; it is
logged as a follow-on once the never-vs-always question is settled at scale.

**Endpoints.** Co-primary: pooled commit accuracy and pooled false-positive rate
on negative golds. Secondary: coverage, per-class recall with Wilson CIs, cost
per pair. Paired McNemar per country and pooled.

**Adoption rule (fixed now).** Adopt `never` (drop the counter-search) only if
pooled commit accuracy is non-inferior (drops by <= 0.02) AND pooled negative-gold
false-positive rate does not rise by more than 0.03, at strictly lower cost per
pair. Otherwise keep `always`. The margins are pre-set so a thin sample cannot be
read as a win.

---

## EXP-20: Retry chaining, on countries that commit

**Lineage.** EXP-7 adopted chaining (carry evidence across retries) as the
"optimisation baseline" on Malta (40 pairs/arm), but the run was underpowered:
recovery McNemar p = 0.375 under Malta's 72-80% abstention ceiling, so recoveries
were barely observable. A whole family of future cost experiments builds on this
baseline.

**Question.** Does chaining recover more correct answers per call than independent
retries, without raising false positives, on countries that commit often enough
for recoveries to show?

**Dataset.** NL + AL: both commit far more than Malta, so the recovery signal is
visible. Class-balanced draw, ~80 pairs/arm/country.

**Arms (one variable).** `baseline` (independent retries, production) vs `chained`
(`--chained`). `type: retrieval`, cache off (both arms search; carried evidence is
the treatment).

**Endpoints.** Co-primary: balanced accuracy (per-class recovery vs ground truth)
and false-positive rate. Secondary: abstention rate, calls per resolved pair.
Paired McNemar (recovery) and Wilcoxon (calls), now powered.

**Adoption rule (fixed now).** Promote `chained` from baseline to the production
default only if pooled balanced accuracy increases AND the false-positive rate
does not rise AND calls per resolved pair do not increase by more than 10%, with
the recovery McNemar p < 0.05. A null leaves chaining as the baseline (status
quo), not the default.

---

## EXP-21: Frozen headline whole-system evaluation

The whole-system test: not a single-knob ablation but the entire production
architecture, end to end, on countries it has never seen. This is the result the
dissertation reports.

**Precondition (hard).** Freeze the architecture first. `ARCHITECTURE.md` is the
manifest; freeze = a git tag pinning every adopted value (DIY-only search, floor
0.65, verifier counter-search always, picker on, adjudicator standard, 3
independent retries, the catalogue route). No held-out country may be touched
before the freeze, and nothing is tuned against the held-out results afterwards.
Also a build precondition: the eight held-out countries need their language codes
and any portal-discovery routes added to `run_coordinator.py` before dispatch.

**Dataset.** The D47 held-out set, frozen until now: BA, MK, ME, BG (stratum A,
negative-rich low/mid-resource) and FI, HR, SE, BE (stratum B, higher-resource
balanced). All 143 questions x 8 countries ~= 1,144 pairs, ~368 negative golds.
This is the largest single spend in the programme.

**Endpoints (D47 / D38 R4, all pre-set).** Balance-aware: per-class recall,
balanced accuracy, Youden's J against the majority-class baseline. Three-outcome:
commit-accuracy, coverage, false-positive rate, plus a risk-coverage curve over
the 0.65 floor. Stratified by ODMI dimension (Policy / Portal / Quality / Impact)
and by the A/B language-resource strata. Swarm-vs-ODMI disagreements pass through
the D22 staleness-adjudication band (ODMI gold can be one cycle old) before being
counted as errors. France is reported alongside as the labelled degenerate dev
contrast.

**No adoption rule.** This is not an ablation; there is nothing to adopt. The
output is the headline number and its breakdown. The discipline is that the
config, the country list, the metrics, and the staleness procedure are all fixed
before the run, so no choice is made after seeing the held-out answers.

**Reading it against the re-tests.** EXP-18/19/20 may change three knobs (breadth,
verifier search, chaining) before the freeze. The freeze must happen after those
land (or after they are explicitly deferred), so the headline run evaluates one
declared configuration, not a moving target.

---

## Status

All four are designs only, pre-registered here. Registered in the `experiments`
table so they are dispatch-ready and the analysis plan is locked, but open to
revision before any spend (revising a design before any run does not break
pre-registration; changing it after seeing results would). Spec files for
EXP-18/19/20 are in `evaluation/specs/`. EXP-21 has no spec until the freeze and
the held-out country build land.
