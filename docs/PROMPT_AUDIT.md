# Prompt audit (first pass)

Descriptive inventory of every LLM prompt that fires in a single
(question, country) pair, plus the surfaces in each prompt that can be
tuned. This is the catalogue the second-pass agent will design A/Bs
against; it deliberately proposes no rewrites.

Built on 2026-06-24 from the code (`agents/prompts/`, `agents/researcher.py`,
`agents/verifier.py`, `agents/adjudicator.py`, `agents/tools/snippet_picker.py`)
cross-checked against the `prompt_versions` table in `data/odmi.db`.

Eight prompt names appear in `prompt_versions`; another six are defined in
code but have never been registered (so they have never run end-to-end in
a production pair). Both lists are below. The search adjudicator
(`search_adjudicator` v1, v2, v4) lives in evaluation harnesses only and
is excluded from the production inventory; it is recorded in the
"defined but out of scope" section at the end.

---

## 1. Inventory

### 1.1 Reachable from a production pair

Rows 1, 2, 4, 5, 6 and 8 are registered in `prompt_versions`. Row 3
(`phase2_researcher_compressed` v1) is defined in code and dispatchable
via the EXP-8 prompt-variant flag but has not yet been logged (no row in
`prompt_versions` as of 2026-06-24); it will register on first use.
Row 7 (`phase2_adjudicator_free` v1) is registered.

| # | Prompt name | Ver | Role | Defined at | Call site | Input variables | Output schema | Downstream consumer |
|---|---|---|---|---|---|---|---|---|
| 1 | `phase2_researcher_query_gen` | 2 | user | [agents/researcher.py:47](agents/researcher.py:47) (NAME/VERSION/SYSTEM) | [agents/researcher.py:137](agents/researcher.py:137) (`call_for_structured`, `max_tokens=200`) | `country_name`, `country_code`, `country_language`, `portal_url`, `question_text`, `verifier_feedback` (rejection_reason, suggested_search_query, counter_evidence_quote), `previous_search_queries` | `_Queries` (1 to 3 strings, [agents/researcher.py:43](agents/researcher.py:43)) | `search_many(queries, ...)` in [agents/researcher.py:377](agents/researcher.py:377) |
| 2 | `phase2_researcher` (full) | 3 | system | [agents/prompts/researcher.py:21](agents/prompts/researcher.py:21) (NAME, VERSION 3, SYSTEM 35-117) | [agents/researcher.py:441](agents/researcher.py:441) (`call_for_structured`, `max_tokens=2000`) | `question_id`, `dimension`, `indicator`, `question_text`, `response_scoring`, `answer_shape`, `allowed_answers`, `country_name`, `country_code`, `country_language`, `portal_url`, queries, search snippets (truncated to 600 chars each), `verifier_feedback`, `prior_evidence` (EXP-7) | `ResearcherOutput` ([agents/models.py:192](agents/models.py:192)) | Verifier substring gate, then [`_should_accept_verifier_pass`](scripts/run_coordinator.py) |
| 3 | `phase2_researcher_compressed` | 1 | system | [agents/prompts/researcher.py:253](agents/prompts/researcher.py:253) (NAME, VERSION 1, COMPRESSED_SYSTEM 262-292) | same call site as #2 when `prompt_variant="compressed"` (EXP-8) | same inputs as #2 | `ResearcherOutput` | same as #2 |
| 4 | `phase2_verifier_query_gen` | 2 | user | [agents/verifier.py:92](agents/verifier.py:92) (NAME/VERSION/SYSTEM 102-124) | [agents/verifier.py:158](agents/verifier.py:158) (`call_for_structured`, `max_tokens=200`) | `question_text`, `country_name`, `country_code`, `country_language`, `answer_shape`, `allowed_answers`, `researcher_output.answer`, `researcher_output.answer_explanation` | `_Queries` (1 to 3 strings, [agents/verifier.py:81](agents/verifier.py:81)) | `search_many(queries)` at [agents/verifier.py:600](agents/verifier.py:600); skipped when `verifier_search="never"` (EXP-14) |
| 5 | `phase2_verifier_disprove` | 3 | system | [agents/prompts/verifier.py:257](agents/prompts/verifier.py:257) (_DISPROVE_NAME, VERSION 3, SYSTEM 260-307) | [agents/verifier.py:642](agents/verifier.py:642) (`call_for_structured`, `max_tokens=1500`) | `question_text`, `country_name`, `country_code`, `researcher_output` (answer + quote + url + confidences), substring result (`pass`/`fail`/`not_attempted`) + notes, independent queries, independent snippets (top 8 at 300 chars each), `answer_shape`, `allowed_answers`, optional "no independent search" note when `verifier_search="never"` | `VerifierOutput` ([agents/models.py:235](agents/models.py:235)) | Python override of pass-with-failed-substring at [agents/verifier.py:707](agents/verifier.py:707); coordinator's pass-gate + 0.65 floor |
| 6 | `phase2_adjudicator` (standard) | 4 | system | [agents/prompts/adjudicator.py:23](agents/prompts/adjudicator.py:23) (NAME, VERSION 4, SYSTEM 38-135) | [agents/adjudicator.py:135](agents/adjudicator.py:135) (`call_for_structured`, `max_tokens=1200`) | `question_id`, `country_name`, `country_code`, `question_text`, `answer_shape`, `allowed_answers`, full Researcher history (up to 4 attempts), full Verifier history (up to 4 attempts), optional `evidence_corpus` (EXP-7) | `AdjudicatorOutput` ([agents/models.py:372](agents/models.py:372)) | Python auto-promotion of confidence < 0.6 to `escalate_human` at [agents/adjudicator.py:178](agents/adjudicator.py:178); coordinator finalisation |
| 7 | `phase2_adjudicator_free` | 1 | system | [agents/prompts/adjudicator.py:146](agents/prompts/adjudicator.py:146) (FREE_NAME, FREE_VERSION 1, SYSTEM_FREE 161-198) | [agents/adjudicator.py:135](agents/adjudicator.py:135) when `selection="free"` (EXP-16) | same as #6 plus the per-call free-selection note ([agents/prompts/adjudicator.py:201](agents/prompts/adjudicator.py:201)) | `AdjudicatorOutput` extended with `chosen_attempt` | same as #6 |
| 8 | `snippet_picker` | 2 | system | [agents/prompts/snippet_picker.py:15](agents/prompts/snippet_picker.py:15) (NAME, VERSION 2, SYSTEM 34-61) | [agents/tools/snippet_picker.py:96](agents/tools/snippet_picker.py:96) (`call_for_structured`, `max_tokens=1500`) | `query`, page `url`, cleaned `page_text` truncated to `PAGE_TEXT_CAP=16000` chars ([agents/prompts/snippet_picker.py:32](agents/prompts/snippet_picker.py:32)) | `_ChunksOut` (up to 3 `PickedChunk` with score in [0, 1], [agents/tools/snippet_picker.py:54](agents/tools/snippet_picker.py:54)) | DIY search aggregation: `aggregate_snippet` joins chunks with " ... "; top-chunk threshold 0.7 returns only the top one |

For one default-production pair the LLM call sequence is:

1. one `phase2_researcher_query_gen` per Researcher attempt (1 to 4)
2. one `snippet_picker` per fetched DIY page during search (variable; one page per result, capped by `max_results_per_query=5` and the trusted-domain narrow-then-widen at [agents/researcher.py:377](agents/researcher.py:377))
3. one `phase2_researcher` per Researcher attempt
4. one `phase2_verifier_query_gen` per Verifier attempt (skipped when `verifier_search="never"`)
5. one `phase2_verifier_disprove` per Verifier attempt
6. zero or one `phase2_adjudicator` at the end (only when retries exhaust without a pass + floor commit)

`phase2_researcher_compressed` swaps in for `phase2_researcher` under
EXP-8; `phase2_adjudicator_free` swaps in for `phase2_adjudicator` under
EXP-16. The catalogue route ([agents/researcher.py:234](agents/researcher.py:234))
short-circuits the LLM path with zero LLM calls and a deterministic
recompute on the Verifier side ([agents/verifier.py:395](agents/verifier.py:395)).

### 1.2 Defined in code but never logged in `prompt_versions`

These are ablation arms or partially-built experimental paths. None has a
row in `prompt_versions` as of 2026-06-24, so none has ever fired against
a real pair.

| Prompt name | Ver | Defined at | Status |
|---|---|---|---|
| `phase2_verifier_negation` | 3 | [agents/prompts/verifier.py:314](agents/prompts/verifier.py:314) | Registered in `STRATEGIES`. `phase2_verifier_runs.strategy_label` has 2,662 disprove rows and zero of these. Not used in production. |
| `phase2_verifier_steelman` | 3 | [agents/prompts/verifier.py:376](agents/prompts/verifier.py:376) | Same status. |
| `phase2_verifier_blind` | 3 | [agents/prompts/verifier.py:428](agents/prompts/verifier.py:428) | Same status. Has a downstream Python answer-disagreement override at [agents/verifier.py:733](agents/verifier.py:733) that would fire if it were dispatched. |
| `phase2_verifier_tristate` | 1 | [agents/prompts/verifier.py:543](agents/prompts/verifier.py:543) (EXP-11) | Not used by `run_verifier`; evaluation harness `evaluation/verifier_redesign.py` registers it. |
| `phase2_verifier_tristate_probes` | 1 | [agents/prompts/verifier.py:590](agents/prompts/verifier.py:590) (EXP-11) | Same status. |
| `phase2_verifier_probe_gen` | 1 | [agents/verifier.py:180](agents/verifier.py:180) (EXP-11 P2) | Defined and registered via `generate_confirmation_probes`, called only from evaluation harnesses. |

### 1.3 Out of scope (evaluation only, not in a production pair)

`search_adjudicator` v1, v2, v4 ([agents/prompts/search_adjudicator.py:32](agents/prompts/search_adjudicator.py:32))
is the blind pairwise judge of DIY versus Tavily evidence; it is
evaluation-only and obsolete in production now that the swarm is DIY-only
(D43). Variants in `agents/tools/search_adjudicator_mistral.py`,
`search_adjudicator_groq.py`, `search_adjudicator_gemini.py` register
under the same prompt name with the cross-family models for EXP-1's
reliability check.

---

## 2. Per-prompt surface map

Each block lists HARD CONSTRAINTS (rules the prompt enforces), SOFT
GUIDANCE (style, ordering, examples) and OUTPUT CONTROL (schema, length,
JSON), with the line at which the rule sits. Numeric thresholds and
"be conservative" phrases buried in prose are tagged inline as
**KNOB**.

### 2.1 `phase2_researcher_query_gen` v2

System at [agents/researcher.py:55](agents/researcher.py:55).

- HARD CONSTRAINTS
  - On retries the queries "MUST be DIFFERENT from the ones already
    tried" and not paraphrase them ([agents/researcher.py:70](agents/researcher.py:70)).
- SOFT GUIDANCE
  - "Prefer 5-10 word queries" (**KNOB**, length band).
  - "One query in English. If the country's national language is not
    English, add a second query in the local language." This is the bilingual
    rule that anchors every non-English country's recall ([agents/researcher.py:61](agents/researcher.py:61)).
  - Optional third query targets the national portal "when relevant"
    ([agents/researcher.py:63](agents/researcher.py:63)).
  - On retry, "pursue the rejection reason and any suggested query by
    targeting different sources, phrasings, or angles" with four examples
    listed ([agents/researcher.py:71](agents/researcher.py:71)).
  - "Do not invent organisations. Use the country's actual government
    bodies and known portal names."
- OUTPUT CONTROL
  - `_Queries` schema enforces `min_length=1, max_length=3`
    ([agents/researcher.py:43](agents/researcher.py:43)).
  - `max_tokens=200` at the call site.
- v2 lineage. v1 lacked the retry-divergence block; v2 adds it and the
  verifier-feedback ingestion (description in `prompt_versions`).

### 2.2 `phase2_researcher` v3 (full) and `phase2_researcher_compressed` v1

System at [agents/prompts/researcher.py:35](agents/prompts/researcher.py:35).
The compressed system at [agents/prompts/researcher.py:262](agents/prompts/researcher.py:262)
collapses the worked examples and trims the instructions; rule numbering
and intent are unchanged.

- HARD CONSTRAINTS (numbered 1 to 10 in the prompt)
  - Rule 1. `answer` must be exactly one label from the per-question
    allowed list, or `inconclusive`, or `not_applicable`. No paraphrasing
    of band labels. Worked example "82% maps to 71-90%, not around 80%"
    ([agents/prompts/researcher.py:59](agents/prompts/researcher.py:59)).
  - Rule 2. `inconclusive` is forced when evidence is insufficient,
    ambiguous or contradictory; when the only support is forbidden; when
    there is no verbatim quote; **or when `answer_confidence` would fall
    below 0.5** (**KNOB**, the in-prompt abstention threshold, mirrors
    REAS-5 in `DECISION_SURFACE.md`). `inconclusive` must not be
    collapsed to `other` ([agents/prompts/researcher.py:66](agents/prompts/researcher.py:66)).
  - Rule 3. `not_applicable` is reserved for country-question
    inapplicability.
  - Rule 4. Verbatim quote requirement: "Do not paraphrase as if you
    were quoting" ([agents/prompts/researcher.py:80](agents/prompts/researcher.py:80)).
    The verifier's substring gate is the deterministic check on this.
  - Rule 5. Cite one URL, and only one that appears in the snippets.
  - Rule 6. Forbidden sources (the D24 firewall). The list names
    `data.europa.eu`, `publications.europa.eu`, `op.europa.eu`,
    `europeandataportal.eu`, `web.archive.org`, `archive.today`, and any
    URL containing `open-data-maturity`, `odmi`, `merged_responses`, or
    `odm-questionnaire` ([agents/prompts/researcher.py:88](agents/prompts/researcher.py:88)).
    Action when only forbidden support exists: return `inconclusive`.
  - Rule 7. No memorised ODMI rankings or prior-year answers; answer only
    from the snippets.
  - Rule 8. Two confidences in `[0, 1]`: `retrieval_confidence` (source is
    real, current, authoritative) and `answer_confidence` (quote supports
    the chosen label).
  - Rule 11 (in `ResearcherOutput`, [agents/models.py:180](agents/models.py:180)):
    quote min length 10 chars.
- SOFT GUIDANCE
  - Rule 9. `answer_explanation` is "a single sentence in English".
  - Rule 10. `search_queries_used` echoes the Python-supplied queries.
  - The verifier-feedback block ([agents/prompts/researcher.py:126](agents/prompts/researcher.py:126))
    tells the model "take it into account on this attempt" without
    forcing a particular use, and surfaces `counter_evidence_quote` only
    in the EXP-7 chained arm.
  - The prior-evidence block ([agents/prompts/researcher.py:154](agents/prompts/researcher.py:154))
    is rendered only when EXP-7 is on; system prompt unchanged.
- OUTPUT CONTROL
  - JSON matching `ResearcherOutput` ([agents/models.py:192](agents/models.py:192)).
  - `max_tokens=2000`.
  - Snippet block is built by `format_for_prompt` at
    [agents/tools/search.py:353](agents/tools/search.py:353) with
    `max_chars_per_snippet=600` (**KNOB**, SNIP-1 in `DECISION_SURFACE.md`).
- v1/v2/v3 lineage.
  - v1 to v2: added the forbidden-source rule (D24).
  - v2 to v3: shape-aware answer space replaced the fixed
    `yes/no/other/NA` literal with a per-question allowed list (D28).
  - `phase2_researcher_compressed` v1 is an EXP-8 cost arm: examples
    dropped, instructions terser, otherwise identical rules.

### 2.3 `phase2_verifier_query_gen` v2

System at [agents/verifier.py:102](agents/verifier.py:102).

- HARD CONSTRAINTS
  - Queries are "specifically designed to find evidence AGAINST the
    Researcher's answer" ([agents/verifier.py:104](agents/verifier.py:104)).
  - Shape-aware inversion (binary, percentage_band, ordinal_magnitude,
    count_band, categorical) at [agents/verifier.py:110](agents/verifier.py:110).
    On `inconclusive`, "search for a more definitive source".
  - "Include at least one query in the country's national language".
  - "Do not repeat the Researcher's own queries verbatim; approach the
    question from a different angle".
  - "Target official government, legislative, and regulatory sources".
- SOFT GUIDANCE
  - "Prefer 5-10 word queries" (**KNOB**).
- OUTPUT CONTROL
  - `_Queries` schema with `max_length=3`.
  - `max_tokens=200`.
- v1/v2 lineage. v1 was uniform across shapes; v2 makes the inversion
  shape-aware.

### 2.4 `phase2_verifier_disprove` v3

System at [agents/prompts/verifier.py:260](agents/prompts/verifier.py:260)
plus the shared `_SCHEMA_NOTE` at
[agents/prompts/verifier.py:55](agents/prompts/verifier.py:55).

- HARD CONSTRAINTS
  - "Default stance is scepticism. Before you consider accepting the
    claim, ask yourself: what specific reason is there to reject it?"
    (this is the prompt-level optimism-bias cancellation,
    [agents/prompts/verifier.py:263](agents/prompts/verifier.py:263)).
  - Four-step reasoning (substring, source authority, evidence fit,
    counter-evidence), then a verdict ([agents/prompts/verifier.py:272](agents/prompts/verifier.py:272)).
  - Step 1: a failed substring check is "strong evidence of fabrication
    or misquoting; **weight it heavily toward rejecting**" (**KNOB**, soft
    phrasing of a hard intent). Python overrides a `pass` to `fail` on a
    substring `fail` at [agents/verifier.py:707](agents/verifier.py:707),
    so the prompt's "weight heavily" is redundant against a substring
    fail but operative on `not_attempted`.
  - Step 2: forbidden sources mirror the Researcher's D24 list. Action:
    `rejection_reason="forbidden_odmi_source"`.
  - Step 4: "For ordered-band questions, an adjacent-band miss counts as
    counter-evidence" ([agents/prompts/verifier.py:296](agents/prompts/verifier.py:296)).
    This is the explicit no-near-match rule and it interacts with
    SCORE-7 (near-match scoring).
  - Step 5: "Reject only when the evidence is materially wrong,
    unverifiable, or insufficient for the specific question. Do not
    reject for stylistic reasons" ([agents/prompts/verifier.py:305](agents/prompts/verifier.py:305)).
  - Schema-note rules: `verifier_answer` from the allowed list, an
    ordered-band one-step miss is still `fail`, `rejection_reason` must
    be "a specific factual statement, not a generic disagreement", a
    `fail` requires at least one of `counter_evidence_quote` or
    `counter_source_url` ([agents/prompts/verifier.py:75](agents/prompts/verifier.py:75)).
- SOFT GUIDANCE
  - "A blog post or consultancy summary is weaker than a government
    portal or official legislation" ([agents/prompts/verifier.py:280](agents/prompts/verifier.py:280)).
  - "A quote that describes a planned policy does not confirm an enacted
    one" (paraphrase guardrail).
  - The answer-space block ([agents/prompts/verifier.py:167](agents/prompts/verifier.py:167))
    tells the model the labels are listed highest to lowest for ordered
    shapes and "Look for evidence that the correct label is adjacent to
    (or further from) the Researcher's pick".
  - When `verifier_search="never"`, the user message swaps the
    independent-snippets block for "absence of a counter-source here is
    not, on its own, corroboration" ([agents/prompts/verifier.py:159](agents/prompts/verifier.py:159))
    so the prompt version is unchanged across arms.
  - Independent snippets are previewed as 8 results at 300 chars
    ([agents/prompts/verifier.py:143](agents/prompts/verifier.py:143))
    (**KNOB**, VER-14).
- OUTPUT CONTROL
  - JSON matching `VerifierOutput` ([agents/models.py:235](agents/models.py:235)).
  - `max_tokens=1500`.
- v1/v2/v3 lineage. The `prompt_versions` description text is unchanged
  across versions, so the lineage is recorded as separate rows whose
  bodies were edited in line with `_SCHEMA_NOTE` and answer-space
  changes; the registered prompt body shown in `prompt_versions` is the
  authoritative trail.

### 2.5 `phase2_adjudicator` v4 and `phase2_adjudicator_free` v1

System at [agents/prompts/adjudicator.py:38](agents/prompts/adjudicator.py:38).
Free variant constructed by string replacement at
[agents/prompts/adjudicator.py:161](agents/prompts/adjudicator.py:161).

- HARD CONSTRAINTS
  - Four verdicts (standard) or five (free): `researcher_correct`,
    `verifier_correct`, `neither`, `escalate_human`, plus
    `attempt_correct` in the free arm ([agents/prompts/adjudicator.py:46](agents/prompts/adjudicator.py:46)).
  - Self-stated confidence floor: "if your confidence in your verdict is
    below 0.6, your verdict will be auto-promoted to escalate_human"
    (**KNOB**, prompt-stated). Python enforces this at
    [agents/adjudicator.py:178](agents/adjudicator.py:178).
  - "adjudicator_answer must be exactly one of the labels in the Answer
    space block, or `inconclusive`, or `not_applicable`. Do not
    paraphrase band labels".
  - "For ordered band shapes, a single adjacent-band miss is still a real
    disagreement; do not split the difference"
    ([agents/prompts/adjudicator.py:96](agents/prompts/adjudicator.py:96)).
  - `chosen_source_url` and `chosen_evidence_quote` "must come from the
    evidence already gathered by the Researcher or Verifier; do not
    invent new ones".
  - D44 rule, new in v4 (`prompt_versions` description): "If the evidence
    gathered by the two agents does not support a confident label, set
    adjudicator_answer to 'inconclusive' rather than guessing a label to
    break the tie. An honest 'inconclusive' is preferred over a
    low-confidence commit" ([agents/prompts/adjudicator.py:103](agents/prompts/adjudicator.py:103)).
  - Absence-of-evidence rule, also in v4: "Absence of evidence is not
    evidence of `no`. Only answer a negative label when the evidence
    positively shows the thing is absent or false ... Never convert
    `we could not find it` into `no`" ([agents/prompts/adjudicator.py:108](agents/prompts/adjudicator.py:108)).
    This is the choke point for the "no" asymmetry in
    `docs/ABSTENTION_TAXONOMY.md`.
  - Forbidden-source rule: ODMI publications and the EU Data Portal are
    void; route via `neither` with independent evidence, or
    `escalate_human` if none exists ([agents/prompts/adjudicator.py:122](agents/prompts/adjudicator.py:122)).
  - "Do not rely on memorised ODMI rankings, country scores, or
    prior-year answers".
- SOFT GUIDANCE
  - Reading instructions: "Pay particular attention to" the substring
    result, whether the Verifier's counter-evidence is material or
    compatible, and whether confidence trended up or down across retries
    ([agents/prompts/adjudicator.py:115](agents/prompts/adjudicator.py:115)).
  - Free-arm per-call note ([agents/prompts/adjudicator.py:201](agents/prompts/adjudicator.py:201))
    is a soft instruction telling the model how to use the new verdict.
- OUTPUT CONTROL
  - JSON matching `AdjudicatorOutput` ([agents/models.py:372](agents/models.py:372)).
  - `adjudicator_reasoning` "at least 50 chars" (**KNOB**, prompt-stated
    length floor).
  - `max_tokens=1200`.
- Lineage. v1 baseline; v2 added the D24 ban on memorised ODMI; v3 made
  the answer space per-question (D28); v4 added the honest-abstention
  preference (D36/D37) and the absence-of-evidence rule. The free arm is
  EXP-16's `attempt_correct` extension to v4.

### 2.6 `snippet_picker` v2

System at [agents/prompts/snippet_picker.py:34](agents/prompts/snippet_picker.py:34).

- HARD CONSTRAINTS
  - "Copy each passage character-for-character from the page text. Do
    not summarise, paraphrase, or stitch separated sentences"
    ([agents/prompts/snippet_picker.py:46](agents/prompts/snippet_picker.py:46)).
  - "Each passage is one contiguous run of consecutive sentences, not
    fragments from different parts of the page".
  - "If the page contains no passage that addresses the query, return an
    empty list. Do not force a match" ([agents/prompts/snippet_picker.py:51](agents/prompts/snippet_picker.py:51)).
  - "Ignore boilerplate: cookie banners, navigation menus, footers,
    repeated legal text, breadcrumbs".
  - "The page may be in any language. Pick the best passages in their
    original language; do not translate".
- SOFT GUIDANCE
  - Four-band scoring rubric (**KNOB**, SNIP-7 in `DECISION_SURFACE.md`):
    0.8-1.0 direct answer, 0.5-0.7 on-topic, 0.2-0.4 tangential, 0.0-0.1
    omit ([agents/prompts/snippet_picker.py:56](agents/prompts/snippet_picker.py:56)).
- OUTPUT CONTROL
  - `_ChunksOut` with `max_length=3` chunks, each chunk's text validated
    to `MAX_CHUNK_CHARS=500` via a Pydantic validator that silently
    truncates over-runs ([agents/tools/snippet_picker.py:31](agents/tools/snippet_picker.py:31),
    [agents/tools/snippet_picker.py:42](agents/tools/snippet_picker.py:42)).
  - `PAGE_TEXT_CAP=16000` chars per call (**KNOB**, SNIP-3).
  - `max_tokens=1500`.
  - Downstream Python applies a `TOP_CHUNK_THRESHOLD=0.7` cutoff: if the
    top chunk scores at or above 0.7 only that single chunk is returned,
    else up to 3 ([agents/tools/snippet_picker.py:124](agents/tools/snippet_picker.py:124)).
    The threshold is in code, not in the prompt, but it interacts with
    the prompt's scoring rubric and so belongs in the audit.
- v1/v2 lineage. v2 raised `PAGE_TEXT_CAP` from a smaller value to
  16000 once extraction moved to running trafilatura on raw HTML
  upstream; the system prompt itself is unchanged.

---

## 3. Failure-mode map

The mapping below uses the `docs/ABSTENTION_TAXONOMY.md` letter codes
for the 580-pair non-committed population and the FM-* numbering from
`docs/FAILURE_MODES.md` for the false-positive register.

### 3.1 Abstention categories to the prompt that decides them

| Code | Category | n (% union) | Choke-point prompt(s) | The rule that decides it |
|---|---|---|---|---|
| E | Verifier relevance rejection (quote on page, ruled off-target) | 163 (28.1%) | `phase2_verifier_disprove` v3 | Step 3 "evidence fit", [agents/prompts/verifier.py:288](agents/prompts/verifier.py:288). The Verifier judges the quote does not entail the answer and fails it across retries. Median Researcher answer-confidence in this bucket is 0.65, right on the floor, so these are not low-confidence collapses but confident answers the Verifier finds off-target. |
| G | Below confidence floor 0.65 | 146 (25.2%) | `phase2_researcher` v3 | Rule 2 (`inconclusive` if `answer_confidence` would be below 0.5, [agents/prompts/researcher.py:66](agents/prompts/researcher.py:66)) sets the lower bound; the 0.65 commit floor in code (LOOP-7) is the gate. The prompt does not set the 0.65 floor itself; the prompt-stated threshold is 0.5. |
| I | Researcher never committed (only `inconclusive` / `other`) | 73 (12.6%) | `phase2_researcher` v3 | Same Rule 2 plus Rule 4's verbatim-quote requirement. The Researcher reaches no quotable evidence across attempts and abstains. |
| D | Evidence ungrounded, substring gate fail | 66 (11.4%) | `phase2_researcher` v3 (Rule 4) + the deterministic substring gate ([agents/tools/substring.py](agents/tools/substring.py)) | Rule 4 (verbatim quote) is the in-prompt half; Python is the gate. A quote not present in any single snippet fails. |
| B | Fetch error | 51 (8.8%) | None (operational, not a prompt issue) | The 403 wall on `data.gov.mt` is the headline; the prompt-level FM-26 floor mitigates but does not fix. |
| A | Thin web | 38 (6.6%) | None directly; `phase2_researcher_query_gen` v2 (recall) | Diverts via QRY-4 (bilingual rule) and the trusted-domain narrow-then-widen. |
| F3 | Search-empty hard failure | 21 (3.6%) | None (operational) | Same upstream cause as A. |
| C | Deny-listed / MQA source contact | 8 (1.4%) | `phase2_researcher` v3 (Rule 6) | The D24 firewall fires correctly; the answer is fenced off. |
| F1 | Schema-invalid hard failure | 5 (0.9%) | `phase2_researcher` v3 (output structure) | Pydantic validation on `ResearcherOutput`. |

Two clusters do most of the work: E and G together account for 53% of
all abstentions, and both reduce to the same thing. The Researcher
reached a candidate answer the gates would not certify. E is the
Verifier ruling the evidence off-target. G is the answer-confidence
staying under the floor. The system is conservative by construction and
that conservatism is where the abstention mass sits.

### 3.2 The "no" asymmetry choke point

279 of the 580 abstentions sit on a ground-truth `no` answer (more than
the 243 GT-`yes`). The taxonomy traces this to the prompt-level rule
that the swarm cannot assert a negative from absence of evidence:

- `phase2_researcher` v3 Rule 2 forces `inconclusive` when "evidence is
  insufficient", which on portal-feature questions reads as
  "I could not find the feature" rather than "the feature is absent".
- `phase2_adjudicator` v4's absence-of-evidence rule
  ([agents/prompts/adjudicator.py:108](agents/prompts/adjudicator.py:108))
  hard-codes the same default: "Never convert `we could not find it`
  into `no`".

The dissertation framing in `docs/ABSTENTION_TAXONOMY.md` is that this
is a structural recall ceiling. The audit's contribution is to identify
exactly two prompts where the rule lives, so any future relaxation has
a tractable surface to test.

### 3.3 The leans-yes-on-no-golds false-positive choke points

`docs/FAILURE_MODES.md` Part B lists the LLM-only false-positive modes
that survive deterministic gates and depend on the Verifier prompt's
reasoning. The brief calls this cluster the "false-positive yes on
negative golds" finding. The quantified figures in `docs/EXPERIMENTS.md`
sit at neg-FPR of 0.13 to 0.25 across arms; the 70% colloquial in the
brief is a high-water mark on Malta-specific runs where the WAF wall
inflates the rate.

The prompt-level choke points:

| FM | Mode | Choke-point prompt | The rule that ought to catch it but does not always |
|---|---|---|---|
| FM-01 | Quote present but does not entail the answer | `phase2_verifier_disprove` Step 3 (evidence fit) | "Does the quoted passage actually answer the question asked?" The prompt asks; the model can still rationalise a pass. |
| FM-03 | Planned policy quoted to confirm enacted one | same Step 3 | "A quote that describes a planned policy does not confirm an enacted one." Soft, not enforced. |
| FM-04 | Wrong scope or entity (regional vs national) | same | "A quote about open-data strategy in general does not confirm a specific legal transposition." |
| FM-06 | Quantitative or band misread (82% read as `>90%`) | `phase2_researcher` Rule 1 worked example + `phase2_verifier_disprove` Step 4 + answer-space "ordered" note | The Researcher's worked example for bands is in the full prompt only ([agents/prompts/researcher.py:59](agents/prompts/researcher.py:59)); the compressed variant has the rule but the example is condensed. |
| FM-07 | Wrong metric | `phase2_verifier_disprove` Step 3 | Same evidence-fit step. |
| FM-15 | Non-authoritative source stated as fact | `phase2_verifier_disprove` Step 2 (source authority) | "A blog post or consultancy summary is weaker than a government portal." Soft guidance. |
| FM-20 | Default `disprove` strategy rubber-stamps (agreement bias) | `phase2_verifier_disprove` system stance | "Default stance is scepticism" is the prompt-level mitigation. Production has used disprove for all 2,662 verifier runs, so the alternative-strategy ablations (negation, steelman, blind) are unmeasured at scale. |
| FM-22 | Verifier confidently wrong, confidence uncalibrated | `phase2_verifier_disprove` schema-note rule on `verifier_confidence` | The prompt specifies confidence is "in your own verdict", but there is no in-prompt calibration. |
| FM-26 | Commit-floor gaming: confident-wrong answer at 0.65 or above | `phase2_researcher` Rule 8 (two confidences) | The Researcher's `answer_confidence` is uncalibrated and the prompt gives no anchor for what a 0.7 means. |

Reading down the column, the same prompt repeatedly carries the load:
the production Verifier (`phase2_verifier_disprove` v3) is the choke
point on six of the nine LLM-only false-positive modes. Its evidence-fit
step is the closest thing the swarm has to a relevance gate, and it is a
prose instruction interpreted by the model, not a deterministic check.

### 3.4 Where the prompts touch failure modes that are structural, not LLM-only

`phase2_researcher` Rule 5 ("cite one URL ... that appears in the search
snippets") is the prompt-level mitigation for FM-10 (quote-URL
mismatch); the deterministic gate is the validator's "source_url not
among search snippets" note at [agents/researcher.py:533](agents/researcher.py:533).
The prompt makes the rule visible but does not enforce it.

`phase2_researcher` Rule 6 and `phase2_verifier_disprove` Step 2 mirror
the deny-list code (`agents/tools/blocked_domains.py`) for FM-12 to
FM-14. The prompts are one of the six enforcement layers documented in
`docs/FAILURE_MODES.md` and they catch the case the deny-list misses by
substring (third-party republications on allowed domains, FM-14).

---

## 4. Testable hypotheses for the second pass

Five prompt-level variables that look most likely to move the
false-positive rate on `no` golds without overhauling the architecture.
Each is named, not designed; the second-pass agent will specify metric,
dev set, power, and the held-out test the dev sweep does not touch.

1. **Verifier evidence-fit strictness**. The `phase2_verifier_disprove`
   Step 3 "evidence fit" instruction
   ([agents/prompts/verifier.py:288](agents/prompts/verifier.py:288)) is
   the choke point on six LLM-only false-positive modes. Test a tighter
   variant that requires the verifier to state, in a structured field,
   the specific proposition the quote supports versus the question's
   proposition, and to fail if those differ on scope, entity, tense, or
   metric. Variable: the strictness clause and the schema field. Expected
   sign: lower neg-FPR, higher abstention rate.

2. **Researcher in-prompt abstention threshold**. The current 0.5
   threshold ("if your answer_confidence would otherwise be below 0.5,
   return `inconclusive`",
   [agents/prompts/researcher.py:66](agents/prompts/researcher.py:66))
   sits below the 0.65 commit floor in code. Two thresholds with no
   shared rationale; the prompt-level one is the looser. Test raising it
   to 0.65 so the prompt and the floor agree, and separately removing it
   so the floor is the only gate. Variable: the in-prompt threshold.
   Expected sign: changes the distribution of `inconclusive` cases
   between LLM-decided and code-decided abstentions; should not move the
   final commit rate if the model is well-calibrated, will move it if not.

3. **Negative-evidence licensing in the Researcher prompt**. Rule 2 plus
   the adjudicator's absence-of-evidence rule pin the swarm to the "no"
   asymmetry described in `ABSTENTION_TAXONOMY.md`. Test a guarded
   variant of Rule 2 that licenses a `no` answer after a documented
   exhaustive non-discovery (a fixed set of "does X exist" probes all
   returning nothing), with the substring gate and forbidden-source rule
   still in force. Variable: the licensing clause and the probe schema.
   Expected sign: higher commit rate on `no` golds, requires careful
   measurement of false `yes` to `no` flips. The taxonomy explicitly
   flags this as the prototype-worthy fix.

4. **Source-authority rubric vs free-text guidance**. The verifier's
   Step 2 currently lists "a blog post or consultancy summary is weaker
   than a government portal" as prose
   ([agents/prompts/verifier.py:280](agents/prompts/verifier.py:280)).
   Replace it with a structured per-domain tier the model copies into an
   output field, and bind a "fail if tier below X and no second source"
   rule. Variable: tier rubric and threshold. Expected sign: lower
   FM-15 incidence at unknown cost to abstention.

5. **Researcher worked example for ordered-band shapes**. Rule 1's
   "82% maps to 71-90%" example
   ([agents/prompts/researcher.py:59](agents/prompts/researcher.py:59))
   is the full-variant prompt's only concrete band-shape demonstration
   and is condensed in the compressed variant. Test whether multi-shot
   examples covering the boundary cases (one exactly at the band edge,
   one mid-band, one near the next band's edge) reduce FM-06
   band-misread rates without inflating tokens past the EXP-8 cost
   threshold. Variable: number and content of band-shape examples.
   Expected sign: lower FM-06 incidence on percentage and count bands;
   tractable to test on the catalogue-recompute set since the truth is
   computed.

---

## 5. Do next

The second-pass agent will design A/Bs against this inventory. This
pass is the inventory: every prompt registered in `prompt_versions` has
been traced to a file, a line, a call site, an input set, an output
schema, and a downstream gate; every prompt defined in code but not yet
registered has been flagged; the surface map separates rules the prompt
enforces from the prose the model interprets; and the failure-mode
table identifies which prompt sits on which gate.

What this pass deliberately does not do:

- propose any prompt rewrite,
- recommend a particular threshold value,
- decide which hypothesis from section 4 to test first,
- design the dev set, the power calculation, or the held-out evaluation
  for any of them,
- touch any code or the DB.

The second pass should start from the cluster identified in section
3.3: six of the nine LLM-only false-positive modes route through
`phase2_verifier_disprove` v3's Step 3 evidence-fit instruction, and the
production Verifier has been the same disprove strategy for all 2,662
runs in the DB. That concentration is what makes the verifier prompt
the highest-leverage surface in the inventory, and section 4's
hypotheses 1 and 4 are the two cleanest tests against it.
