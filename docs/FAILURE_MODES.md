# Failure Modes — the false-positive surface

The exhaustive register of ways the swarm can **commit a wrong answer while
presenting it as confidently answered** (not abstained). A false positive here
is a correctness failure, distinct from the operational deferrals in
`docs/KNOWN_GAPS.md` (resume, CAPTCHA).

**When the work is "let's start attacking the failure modes", this is the file.**
Start here, pick from the attack list in Part C, and update the Status column as
each is closed.

Built from a five-pass code audit of the Researcher, Verifier, Adjudicator,
coordinator finalisation, deterministic gates, and catalogue path on
2026-06-08. File:line references are approximate and will drift; treat them as
the entry point, not gospel.

---

## How a wrong answer reaches "committed"

A failure mode only matters if it clears a commit gate. The two gates:

- **LLM path.** Researcher produces answer + evidence_quote + source_url. The
  Verifier runs a deterministic substring gate against the snippets the
  Researcher read, an adversarial counter-search, and a verdict. If
  `verdict == "pass"` **and the Researcher's `answer_confidence` >= 0.65**, the
  pair commits as `accepted_by_verifier` with **no Adjudicator**
  (`scripts/run_coordinator.py`, `_should_accept_verifier_pass`). Only a Verifier
  failure sustained across three retries reaches the Adjudicator, which **runs
  no search of its own** and reasons only over what the prior two agents
  gathered. The Adjudicator self-escalates to a human below 0.6 confidence; the
  0.65 commit floor still applies to its answer.
- **Catalogue path.** Nine catalogue-derivable Quality questions bypass the LLM
  entirely: a metric is computed from harvested portal metadata, the Verifier
  "recomputes" the same snapshot, and the pair commits at 0.98.

"Caught" below means caught by one of these gates before commit.

---

## The three-way cut

The organising principle, agreed 2026-06-08:

1. **Caught** — a deterministic gate already stops it. The backbone we trust.
2. **LLM-only** — the deciding evidence is in front of a model and it just has to
   reason well. Discounted as a prompt-tunable risk, not a structural one. We
   accept that sufficient prompting handles these in most cases.
3. **Structural** — prompting cannot fix it, because the model never sees the
   needed evidence, the gate is deterministic and too loose, the adversary is
   correlated or skipped, the confidence is uncalibrated, or there is no model
   in the loop at all. **These are the attack list.**

---

## Triage table

Severity is the product of likelihood and how silently it commits.

| ID | Failure mode | Stage | Class | Severity | Status |
|----|--------------|-------|-------|----------|--------|
| FM-01 | Quote present but doesn't entail the answer (relevance gap) | Verifier | LLM-only | Med | Accepted |
| FM-02 | Negating context sits outside the snippet | Evidence | **Structural** | High | Open |
| FM-03 | Quote proves a related but different proposition (planned≠enacted) | Verifier | LLM-only | Med | Accepted |
| FM-04 | Quote about wrong scope/entity (regional vs national) | Verifier | LLM-only | Med | Accepted |
| FM-05 | Stale evidence; no date or cycle signal supplied | Evidence | **Structural** | High | Open |
| FM-06 | Quantitative/band misread (82% read as >90%) | Verifier | LLM-only | Med | Accepted |
| FM-07 | Quote about the wrong metric | Verifier | LLM-only | Low | Accepted |
| FM-08 | Pure fabricated quote, not in any snippet | Verifier | Caught | — | Mitigated |
| FM-09 | Snippet itself unfaithful to the live page | Evidence | **Structural** | High | Open |
| FM-10 | Quote–URL mismatch (quote from A, URL points to B) | Researcher | **Structural** | Med | Open |
| FM-11 | Substring gate false-match via loose normalisation / short quote | Deterministic | **Structural** | Med | Open |
| FM-12 | Cites the ODMI answer key on a listed domain/path | Deny-list | Caught | — | Mitigated |
| FM-13 | Deny-list evasion (underscore, %-encoding, proxy, IDN) | Deny-list | **Structural** | Med | Open |
| FM-14 | Third-party republication of the answer key on an allowed domain | Deny-list | **Structural** | High | Open |
| FM-15 | Non-authoritative source stated as fact | Verifier | LLM-only | Med | Accepted |
| FM-16 | Answer label typo / case | Deterministic | Caught | — | Mitigated |
| FM-17 | Out-of-set answer flagged but not hard-rejected | Deterministic | **Structural** | Low | Open |
| FM-18 | `not_applicable` chosen when the question does apply | Verifier | LLM-only | Low | Accepted |
| FM-19 | Web-unanswerable: counter-search finds nothing → pass | Verifier | **Structural** | High | Open |
| FM-20 | Default `disprove` strategy rubber-stamps (agreement bias) | Verifier | **Structural** | Med | Open |
| FM-21 | Correlated error: blind Verifier reaches the same wrong answer | Verifier | **Structural** | High | Open |
| FM-22 | Verifier confidently wrong; confidence uncalibrated | Verifier | **Structural** | Med | Open |
| FM-23 | Both agents agree → Adjudicator never invoked | Coordinator | **Structural** | High | Open |
| FM-24 | Adjudicator ratifies a plausible wrong answer | Adjudicator | LLM-only | Med | Accepted |
| FM-25 | Adjudicator overrides a valid Verifier rejection | Adjudicator | LLM-only | Med | Accepted |
| FM-26 | Commit-floor gaming: confident-wrong answer ≥0.65 | Coordinator | **Structural** | High | Open |
| FM-27 | Retry-until-commit within the retry budget | Coordinator | **Structural** | Low | Open |
| FM-28 | Stale catalogue snapshot, no age check | Catalogue | **Structural** | Med | Open |
| FM-29 | Partial harvest computed on an atypical sample | Catalogue | **Structural** | Med | Open |
| FM-30 | Zero denominator → `<10%` band | Catalogue | **Structural** | Med | Open |
| FM-31 | Synthesised-conformance inflation (HU/NL/EE Q16) | Catalogue | **Structural** | Med | Open |
| FM-32 | Verifier recompute is the same code on the same snapshot | Catalogue | **Structural** | High | Open |
| FM-33 | Correlated low-resource-language error across agents | Language | **Structural** | Med | Open |
| FM-34 | Translation flips meaning before the model reads it | Language | **Structural** | Med | Open |

---

## Part A — Caught (the deterministic backbone)

These are stopped before commit. Listed so we don't re-litigate them and so we
know what regression would reopen them.

- **FM-08 Fabricated quote.** The Verifier's substring gate checks the
  evidence_quote against the snippets the Researcher actually read
  (`agents/verifier.py`, `agents/tools/substring.py`). Not present → fail. This
  is the single strongest gate; FM-11 is its weakness.
- **FM-12 ODMI answer-key leakage (exact).** Six enforcement layers on the
  deny-list (`agents/tools/blocked_domains.py`, `search.py`, `fetch.py`,
  `validator.py`, plus the Researcher/Verifier prompts). FM-13/FM-14 are its
  evasion routes.
- **FM-16 Label typo/case.** `normalise_answer` folds case and whitespace to the
  canonical label (`agents/tools/answer_shapes.py`).
- **Dead / hallucinated URL.** `head_ok` liveness check with a Playwright
  fallback (`agents/researcher.py`, `agents/tools/fetch.py`).
- **Low-confidence guess.** The 0.65 commit floor (D37) abstains rather than
  commit. Note this is only half a gate: it catches self-admitted low
  confidence, not confident-wrong (see FM-26).

---

## Part B — LLM-only (accepted, prompt-tunable)

The deciding evidence is in the context window; the model just has to reason
over it. Accepted per the 2026-06-08 decision that sufficient prompting handles
these in most cases. They remain worth a prompt-engineering pass and worth
measuring, but they are **not** on the structural attack list.

- **FM-01** relevance gap, **FM-03** planned≠enacted, **FM-04** wrong scope,
  **FM-06** band/figure misread, **FM-07** wrong metric, **FM-15**
  non-authoritative source, **FM-18** wrong `not_applicable`, **FM-24**
  Adjudicator ratifies, **FM-25** Adjudicator overrides a valid rejection.

Caveat: FM-04 and FM-06 are only LLM-only when the scope cue or the underlying
figure is actually present in the snippet. When it isn't, they degrade into
FM-02 (context outside the snippet). The boundary between Parts B and C is the
context window.

---

## Part C — Structural (the attack list)

Prompting cannot close these. Grouped by root cause, because the cause dictates
the kind of fix. Each carries a proposed mitigation so the work is actionable
the moment we start.

### C1. The model never sees the evidence it would need

- **FM-02 Negating context outside the snippet.** "Germany does *not*…" where the
  ~300-char snippet is the clause after the "not". Neither agent sees enough.
  *Mitigation:* widen the evidence window, or have the Verifier re-read the full
  page (not just snippets) before a pass.
- **FM-05 Staleness.** No publish date or assessment-cycle stamp is ever supplied,
  so neither agent can judge currency. *Mitigation:* extract a source date during
  retrieval and gate / down-weight on it.
- **FM-09 Snippet unfaithful to the live page.** Tavily/Brave can return a
  summarised snippet; the DIY picker can paraphrase. Nothing compares snippet to
  page, so the substring gate (FM-08) is only as faithful as the snippet.
  *Mitigation:* a deterministic snippet-on-page check at verify time.
- **FM-34 Translation flips meaning.** The model reasons over already-wrong
  translated text. *Mitigation:* verify the committed claim against the
  source-language original.

### C2. Deterministic gates that are too loose (code, not prompt)

- **FM-11 Substring gate.** NFKC + casefold + strip-all-punctuation +
  whitespace-collapse, with no minimum quote length. Paraphrases and very short
  strings pass (`agents/tools/substring.py`). *Mitigation:* minimum length,
  exact-phrase mode, gentler normalisation.
- **FM-13 Deny-list evasion.** Underscore-for-hyphen, percent-encoded path, IDN,
  translation proxy, shortener — no URL canonicalisation
  (`agents/tools/blocked_domains.py`). *Mitigation:* canonicalise and percent-
  decode before matching; resolve redirects.
- **FM-10 Quote–URL consistency.** Only "is the URL among the results" is checked,
  not "did the quote come from this URL" (`agents/researcher.py`). *Mitigation:*
  bind each candidate quote to its originating snippet's URL.
- **FM-17 Out-of-set answer.** Flagged as `invalid_answer_shape` but still
  returned (`agents/researcher.py`). *Mitigation:* hard-reject at the coordinator.

### C3. Leakage the system structurally cannot detect

- **FM-14 Third-party republication of the answer key** on an allowed domain
  (consultancy PDF, news write-up). Neither a host/path deny-list nor an LLM can
  reliably know a page is echoing the gold answer. This is the one that can
  silently inflate measured accuracy. *Mitigation:* content-level leakage
  detection (fingerprint the published ODMI answers and flag near-duplicates).

### C4. The adversary collapses through correlation or control flow

This is the cluster that undercuts the "self-verifying" claim most directly: it
is where the verification step structurally cannot do its job.

- **FM-23 Adjudicator skipped on agreement.** If Researcher and Verifier agree,
  no third check runs at all; the Adjudicator only fires after three failed
  retries (`scripts/run_coordinator.py`). *Mitigation:* invoke an independent
  check (e.g. blind or cross-family) even on agreement, at least for a sample or
  for high-stakes pairs.
- **FM-21 Correlated error.** Same model, same misleading snippet → the blind
  Verifier independently reaches the same wrong answer → "agreement" → commit.
  Prompting both identically cannot decorrelate them. *Mitigation:* cross-family
  verification (the EXP-1 direction, Mistral judge).
- **FM-20 Default `disprove` rubber-stamps.** The structural anti-agreement
  strategy (`blind`) exists but is not the production default
  (`agents/prompts/verifier.py`). *Mitigation:* make blind (or a panel) the
  default, or run it alongside disprove.
- **FM-19 Web-unanswerable claims.** When the refuting evidence is not on the open
  web, the counter-search finds nothing and the Verifier passes. *Mitigation:*
  convert "found nothing" from a pass into an abstain / confidence cap; this is a
  policy change, not just a prompt.
- **FM-33 Correlated low-resource-language error.** Both agents mis-read the same
  way. *Mitigation:* cross-family judge and/or back-translation check.

### C5. Confidence is uncalibrated

- **FM-26 Commit-floor gaming.** The 0.65 floor only catches answers the model
  admits are weak; a confident-wrong 0.7 commits, and asking an LLM "are you
  sure?" does not calibrate it. *Mitigation:* empirical calibration of the
  threshold against ground truth; per-shape or per-dimension floors.
- **FM-22 Verifier confidence uncalibrated.** Taken at face value. Same
  mitigation.
- **FM-27 Retry-until-commit.** Bounded at three retries, but the bound does not
  prevent a confident-wrong pass inside it. *Mitigation:* track answer drift
  across retries; treat late high-confidence flips as suspicious.

### C6. The catalogue path has no model and no independent check

By definition there is nothing to prompt here.

- **FM-28 Stale snapshot.** `get_snapshot` has no age check and replays the cache
  indefinitely (`agents/tools/catalogue/harvest.py`). *Mitigation:* snapshot TTL
  and a re-harvest trigger.
- **FM-29 Partial harvest.** A portal error after N% leaves `partial=True` but the
  metric still computes on an atypical sample. *Mitigation:* refuse to commit a
  partial harvest above a missing-data threshold; abstain instead.
- **FM-30 Zero denominator → `<10%`.** `_pct(n, 0)=0.0` yields a confident wrong
  band (`agents/tools/catalogue/metrics.py`). *Mitigation:* treat empty
  denominator as inconclusive, not 0%.
- **FM-31 Synthesised-conformance inflation.** HU/NL/EE Q16 from JSON reads
  artificially high, documented but with no runtime downgrade. *Mitigation:* cap
  confidence or flag the synthesised route at commit.
- **FM-32 Recompute is not independent.** The Verifier reruns the same code on the
  same cached snapshot, so it cannot disagree with a data error
  (`agents/verifier.py` `_verify_catalogue`). *Mitigation:* a second, independent
  computation (different harvest, different parser, or a spot web check).

---

## Suggested attack order

Ranked by severity and by how directly each undermines the dissertation's
central claim of self-verification.

1. **C4 (correlated / skipped adversary): FM-23, FM-21, FM-19, FM-20.** The
   verification step's whole purpose is at stake here.
2. **C6 (catalogue non-independence): FM-32, then FM-28/29/30/31.** A whole answer
   path with no real adversary.
3. **C1 (missing context): FM-09, FM-02, FM-05.** The substring gate's hidden
   dependency on snippet fidelity.
4. **C3 (answer-key leakage): FM-14.** Quietly inflates measured accuracy.
5. **C5 (calibration): FM-26, FM-22.** Needs data, so it pairs naturally with the
   with/without-Verifier ablation.
6. **C2 (loose gates): FM-11, FM-13, FM-10, FM-17.** Cheap, mechanical hardening.

The with/without-Verifier ablation and the four-strategy head-to-head are the
experiments that would *quantify* this surface: they show which of these the
Verifier currently closes and which it lets through.

---

## Change log

| Date | Change |
|---|---|
| 2026-06-08 | File created. Five-pass code audit, 34 failure modes, three-way cut (Caught / LLM-only / Structural). |
