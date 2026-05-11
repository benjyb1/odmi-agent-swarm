# Agent Design

Atomic specifications for every agent in the ODMI swarm. One agent, one job.
Read this before touching any agent code. Changes require a numbered decision
in `docs/SPEC.md`.

Last reviewed: 2026-05-11.

---

## 1. Design principles

These are the rules every agent obeys. They exist because the project's
contribution is honest measurement, and honest measurement requires that an
examiner can trace every output back to a specific agent doing a specific
job with specific tools.

1. **One agent, one job.** If an agent has two responsibilities, it becomes
   two agents. Coordination is a separate concern from research, which is a
   separate concern from verification.
2. **Typed contracts.** Every agent has a Pydantic model for its input and
   another for its output. The signature is the agent. No dictionary
   smuggling.
3. **Explicit success criterion.** An agent is "done" when its output passes
   validation against its output model and its post-conditions (e.g., the
   cited source URL returns HTTP 200 and contains the quoted evidence).
4. **Bounded effort.** Every agent has a token budget and a wall-clock
   timeout. Exceeding either is itself a failure mode, logged and
   surfaced, not silently ignored.
5. **Receipts on every call.** Every LLM call records `input_tokens`,
   `output_tokens`, `wall_clock_ms`, the model version, and the prompt
   version. No exceptions. This is the basis of RQ5 (per D12).
6. **Native LangGraph idioms** (for the eventual swarm): StateGraph with
   typed state, conditional edges for accept/reject/retry, the Command
   API for dynamic routing. Per D3 in SPEC.md.

---

## 2. Agent inventory

The full swarm is four agents. The minimum viable prototype for the 22 May
slide deck is one agent, in the simplest possible form.

| Agent | Version targeted | Status |
|---|---|---|
| Answerer | V0 (single-shot, prototype only) | To build this week |
| Researcher | V1 (Phase A) | After V0 lands |
| Adversarial Verifier | V1 (Phase A) | After Researcher |
| Coordinator | V1 (Phase A) | When the other three exist |
| Translator helper | V2 (Phase B) | Deferred |
| Classifier (post-hoc) | Optional | Off the critical path per D8 |

The progression is V0 → V1, not V0 → swarm in one jump. V0 is a single
function. V1 is the same agent rebuilt as a LangGraph node alongside the
others.

---

## 3. Answerer (V0): minimum viable answering agent

The prototype that produces the first real results for the slide deck.
Skips multi-agent verification. Skips browser automation. Skips
languages other than English / French. Does one thing only: take a
question and a country, look at the web, return a structured answer.

### 3.1 Task in one sentence

Given an ODMI question and a country, find supporting evidence on the
public web and return a structured answer with a verifiable source.

### 3.2 Input contract

```python
class AnswererInput(BaseModel):
    question_id: str                  # e.g. "P1"
    question_text: str                # the literal question
    dimension: str                    # Policy / Portal / Quality / Impact
    indicator: str                    # e.g. policy_framework
    response_scoring: str             # the official scoring rule from ODMI
    country_code: str                 # ISO 3166-1 alpha-2, e.g. "FR"
    country_name: str                 # e.g. "France"
    country_language: str             # ISO 639-1, e.g. "fr"
    portal_url: Optional[str] = None  # known national portal if available
```

### 3.3 Output contract

```python
class AnswererOutput(BaseModel):
    answer: Literal["yes", "no", "other", "not_applicable"]
    answer_explanation: str           # one short sentence in English
    evidence_quote: str               # literal substring from the source
    source_url: HttpUrl               # must return HTTP 200 on validation
    retrieval_confidence: float       # 0.0-1.0, did we get real page content?
    answer_confidence: float          # 0.0-1.0, does the evidence support the claim?
    search_queries_used: list[str]    # for the audit trail
    notes: Optional[str] = None
```

### 3.4 Capabilities

- **Web search:** Tavily client. Max 3 queries per question. Top-5 results
  per query. Snippet only at V0 (no Playwright fetch yet).
- **LLM:** one Claude call via CLIProxyAPI, structured output requested.
- **No tool use loop.** Python orchestrates: it issues the search, gathers
  snippets, passes them to Claude as context, Claude returns structured
  output. We add native tool use later if measurements show it helps.
- **No memory across questions** at V0. Each call is independent.

### 3.5 Success criterion

The agent's run is "successful" if all of:

1. The output validates against `AnswererOutput`.
2. `source_url` resolves to HTTP 200 (validated by a separate `httpx`
   HEAD request after the Claude call returns).
3. `evidence_quote` is a non-empty string of at least 10 characters.
4. `answer_confidence >= 0.5` OR `answer == "other"` (low-confidence
   answers are allowed but must be marked).
5. The LLM call completed within the token budget (1500 input + 500
   output tokens for V0).

If any post-condition fails, the row is logged anyway with the failure
mode recorded in `notes`. Failures are data, not exceptions.

### 3.6 Failure modes (each one logged distinctly)

| Code | Trigger | Handling |
|---|---|---|
| `search_empty` | Tavily returns zero hits for all queries. | Log row with `answer="other"`, confidences 0.0, note "no search results". Do not call the LLM. |
| `url_unreachable` | Cited URL does not return HTTP 200. | Log row, mark `retrieval_confidence=0.0`, do not retry at V0. |
| `quote_not_in_source` | Cited evidence quote does not appear in the fetched URL content (V1 check; V0 trusts the model). | At V0 this check is deferred to V1. Note this is a known weakness of V0 and the headline reason to build the Verifier next. |
| `schema_invalid` | Claude response cannot be parsed into `AnswererOutput`. | One retry with a stricter "JSON only" prompt. If second attempt fails, log a row with `answer="other"` and `notes="schema_invalid"`. |
| `token_budget_exceeded` | LLM call ran over the token cap. | Cap the response, log it, mark `notes="truncated"`. |
| `timeout` | Wall-clock budget (30s) exceeded. | Kill the call. Log row with timing field populated up to the cut-off. |

### 3.7 Prompt template (V0, draft v0.1)

```
You are evaluating a question from the EU Open Data Maturity Index (ODMI)
for the country: {country_name} ({country_code}).

The question is:
{question_text}

The official ODMI scoring rule for this question is:
{response_scoring}

Web search has returned the following candidate evidence snippets:
{search_results_formatted}

Your job:
1. Determine whether the evidence supports an answer of "yes", "no", "other",
   or "not_applicable" for this question and this country.
2. Quote a specific passage from the snippets (or the source URL) that
   supports your answer. Quote literally; do not paraphrase.
3. Choose the single source URL that best supports your answer.
4. Report two confidence scores in [0.0, 1.0]:
   - retrieval_confidence: how confident you are that the snippet content is
     real and from a legitimate source (not fabricated, not stale, not
     unrelated).
   - answer_confidence: how confident you are that the evidence supports the
     specific claim implied by your answer.
5. If the evidence is insufficient, return "other" with low confidence and
   say so in answer_explanation. Do not invent evidence.

Return your answer as JSON matching this schema exactly:
{output_schema_json}

Constraints:
- Quote literally from the provided snippets. Do not write a paraphrase as
  if it were a quote.
- answer_explanation must be a single sentence in English.
- search_queries_used should echo the queries Python ran.
```

This is V0 prompt version 1 in `prompt_versions`. Each subsequent prompt
iteration gets a new row, per D5.

### 3.8 What V0 does NOT do (intentional gaps)

- No native tool use. The search runs in Python, results are pasted in.
- No browser fetch. We trust Tavily snippets at V0.
- No language routing. English-only prompt to Claude; the model handles
  French source content natively.
- No adversarial verification. The same agent that found the evidence
  also decides whether it is good. This is V0's biggest known weakness
  and the reason we need V1.
- No retries (apart from the one schema-invalid retry).
- No prior context across questions.

These gaps are the slide-deck disclaimers.

---

## 4. Researcher (V1)

The Answerer rebuilt as a LangGraph node alongside the others. Same input
and output contracts, plus:

### 4.1 Differences from V0

- Native Claude tool use. The model can call `web_search` and
  `fetch_url` tools directly. Python orchestrates the tools but does not
  pre-fetch.
- Browser fetch via Playwright when the snippet is insufficient. Cap on
  fetched content size (4k chars by default; configurable for the
  `retrieval-tight` optimisation variant).
- Source validator: domain authority check (is this `data.gouv.fr`, or
  is it `randompolicyblog.example.com`?). Returns a domain trust score
  passed to the Verifier.
- Language router. Reads the country's `country_language`; for languages
  outside the native-capable list (built from the language confidence
  table), routes through DeepL.
- Receives optional feedback from the Verifier on retry (the Verifier's
  reject reason becomes part of the next prompt).

### 4.2 Success criterion (additions)

- Source domain is on the trusted list (or, if not, the row is flagged
  for Verifier scrutiny rather than rejected outright).
- Evidence quote is a literal substring of the fetched page content
  (this is the V1 check that V0 deferred).

---

## 5. Adversarial Verifier (V1)

A separate agent that takes the Researcher's output and tries to break it.

### 5.1 Task in one sentence

Given a Researcher answer, independently search for counter-evidence and
return either an approval (with the same answer) or a rejection (with
specific, actionable feedback for a retry).

### 5.2 Input contract

```python
class VerifierInput(BaseModel):
    question_id: str
    country_code: str
    researcher_output: AnswererOutput  # what the Researcher returned
    domain_trust_score: float          # from the Researcher's source validator
```

### 5.3 Output contract

```python
class VerifierOutput(BaseModel):
    verdict: Literal["pass", "fail"]
    verifier_answer: Literal["yes", "no", "other", "not_applicable"]
    verifier_confidence: float
    counter_evidence_quote: Optional[str] = None  # if fail
    counter_source_url: Optional[HttpUrl] = None  # if fail
    rejection_reason: Optional[str] = None        # if fail
    suggested_search_query: Optional[str] = None  # if fail
```

### 5.4 Capabilities

- **Independent search.** Different Tavily queries from the Researcher.
  Cannot reuse the Researcher's queries or URLs.
- **URL fetch.** Visits the Researcher's cited URL (via Playwright) and
  checks the evidence quote is a literal substring.
- **Independent reasoning.** A separate Claude call with its own prompt,
  given the Researcher's claim and the Verifier's independent evidence.
- **No shared state with the Researcher** beyond the input contract.

### 5.5 Success criterion

- Output validates against `VerifierOutput`.
- If `verdict == "fail"`, then `counter_evidence_quote`,
  `counter_source_url`, and `rejection_reason` are all populated. The
  `suggested_search_query` is populated unless the rejection is "no such
  question is answerable from public sources" in which case the Coordinator
  marks the pair as unanswered after a single retry.
- The Verifier's URL is independently reachable.

### 5.6 Prompted to disprove, not confirm

The prompt is explicit. "Your job is to find a reason this answer is
wrong, not to agree." This adversarial framing is the project's key
hallucination mitigation.

---

## 6. Coordinator (V1)

The LangGraph StateGraph wrapper around the Researcher and Verifier. The
Coordinator is the only stateful agent.

### 6.1 Task in one sentence

Dispatch (question, country) pairs through the Researcher → Verifier
loop, manage retries up to 3, log every step, escalate access blocks to
the human queue, and write the final accepted result to the database.

### 6.2 State

```python
class SwarmState(TypedDict):
    question_id: str
    country_code: str
    rubric_tier: str                    # from hand_marks (D9)
    researcher_output: Optional[AnswererOutput]
    verifier_output: Optional[VerifierOutput]
    retry_count: int
    last_rejection_feedback: Optional[str]
    final_accepted: bool
    final_output: Optional[AnswererOutput]
    captcha_escalated: bool
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    cumulative_wall_clock_ms: int
    run_id: str
```

### 6.3 Edges

```
START → researcher
researcher → verifier
verifier → END                (if pass)
verifier → researcher         (if fail AND retry_count < 3)
verifier → END                (if fail AND retry_count == 3)
researcher → human_queue      (if CAPTCHA / access block)
```

### 6.4 Termination rule

Per D7 of the original design and reaffirmed here: max 3 retries per
pair. Unresolved pairs are written to the database with
`final_accepted=False` and a categorical failure reason. Other pairs
keep running in parallel.

### 6.5 Logging

The Coordinator owns the database write. Each retry produces a row in
`phase2_runs`. Token and wall-clock counters are cumulative across the
swarm run, not per-call (per-call data lives in `prompt_versions`-linked
sub-rows). Final accepted result is duplicated to `phase2_final` for
fast querying. (Q7: do we want a separate `phase2_final` table or just
a `final` boolean on `phase2_runs`? Logged in SPEC.)

---

## 7. Translator helper (Phase B, V2)

Triggered by the Researcher's language router when the country's
language is not on the native-capable list. Wraps DeepL. Input is a
chunk of source text; output is the English translation plus a
confidence score. Out of scope until Phase B.

---

## 8. Classifier (optional, post-hoc, off-critical-path)

Under D8 the classifier is not a runtime stage. As a post-hoc
experiment, the existing `agents/classifier.py` may be run against the
same (question, country) pairs as hand-marked. The output is a
prediction of the rubric scores; we compare against the locked
hand-marks to test whether the rubric can be automated. This is a
secondary finding, written up only if the primary swarm work is on
schedule.

---

## 9. Build order

V0 (this week):
1. Schema migration: add `input_tokens`, `output_tokens`,
   `wall_clock_ms`, `estimated_cost_usd` to `phase2_runs` and the new
   `phase1_runs` (or `answerer_v0_runs`) table. Resolves Q6.
2. CLIProxyAPI helper: one function that wraps the Anthropic client,
   logs the usage block to the DB, returns the parsed response.
3. Tavily client setup: API key check, simple search wrapper.
4. Answerer V0 function: stitches the above plus the prompt template,
   produces `AnswererOutput`.
5. Validation pass on P1 / France: one question, walk through the
   output manually, sanity-check the row in SQLite.
6. Scale to 5-10 France questions for slide content.

V1 (next two weeks, Phase A proper):
7. Researcher with native tool use, Playwright fetch, source validator.
8. Adversarial Verifier with the substring check on the cited URL.
9. Coordinator in LangGraph.
10. End-to-end run on the full hand-marked Phase A sample.

V2 (Phase B):
11. Language confidence table population by pilot run.
12. Translator helper integrated into the Researcher.
13. Six-country run.

---

## 10. Worked walkthrough: Answerer V0 on P1 / France

See section 11. Read it before building.

---

## 11. P1 / France walkthrough (paper run)

To make sure the V0 design is right before writing code, here is what
the V0 run for P1 / France looks like end-to-end.

### 11.1 Inputs

```python
AnswererInput(
    question_id="P1",
    question_text=(
        "Is there a national open data policy in your country and, if your "
        "country is an EU Member State, does this include a national "
        "legislation for the transposition of the Open Data Directive?"
    ),
    dimension="Policy",
    indicator="policy_framework",
    response_scoring="{'yes': 40, 'no': 0, 'other': 40}",
    country_code="FR",
    country_name="France",
    country_language="fr",
    portal_url="https://www.data.gouv.fr/",
)
```

### 11.2 Search queries Python issues

Python templates three queries:

1. `"France national open data policy Open Data Directive transposition"`
2. `"France loi pour une République numérique données ouvertes"`
3. `"data.gouv.fr national policy"`

Tavily is called once per query with `max_results=5`. We deduplicate by
URL and keep the union.

### 11.3 Likely returned snippets

(These are illustrative; actual results vary.)

- digital-strategy.ec.europa.eu, page on France's transposition of the
  Open Data Directive. Snippet states "France has transposed the Open
  Data Directive through Law 2016-1321 ..."
- legifrance.gouv.fr, the text of Law 2016-1321 ("Loi pour une
  République numérique").
- data.gouv.fr documentation page on France's open data strategy.
- Capgemini ODMI 2024 country profile for France.

### 11.4 Prompt assembled by Python

The literal prompt sent to Claude is a concatenation of:

- The V0 prompt template from §3.7 above.
- A formatted block of the deduplicated search results (title, URL, snippet
  for each).
- The JSON Schema for `AnswererOutput`.

Total input tokens: roughly 1,100 (template 350, results 600, schema 150).

### 11.5 Expected Claude response (target shape)

```json
{
  "answer": "yes",
  "answer_explanation": "France has a national open data policy that includes legislation transposing the EU Open Data Directive.",
  "evidence_quote": "France has transposed the Open Data Directive through Law 2016-1321 (Loi pour une République numérique).",
  "source_url": "https://digital-strategy.ec.europa.eu/en/policies/legislation-open-data",
  "retrieval_confidence": 0.9,
  "answer_confidence": 0.9,
  "search_queries_used": [
    "France national open data policy Open Data Directive transposition",
    "France loi pour une République numérique données ouvertes",
    "data.gouv.fr national policy"
  ],
  "notes": null
}
```

Total output tokens: roughly 250.

### 11.6 Post-call validation by Python

1. Parse JSON against `AnswererOutput`. ✓
2. `httpx.head(source_url)` returns 200. ✓
3. `evidence_quote` length >= 10 chars. ✓
4. `answer_confidence >= 0.5`. ✓
5. Total wall-clock from search start to validated output. Target
   under 10 seconds.

### 11.7 Row written to SQLite

In the new `answerer_v0_runs` table (to be created in step 1 of build
order):

| column | value |
|---|---|
| `id` | autoincrement |
| `question_id` | P1 |
| `country_code` | FR |
| `answer` | yes |
| `answer_explanation` | ...  |
| `evidence_quote` | ... |
| `source_url` | https://digital-strategy.ec.europa.eu/... |
| `retrieval_confidence` | 0.9 |
| `answer_confidence` | 0.9 |
| `search_queries_used` | JSON list, three queries |
| `input_tokens` | ~1100 |
| `output_tokens` | ~250 |
| `wall_clock_ms` | ~7500 |
| `estimated_cost_usd` | computed from Anthropic published rate |
| `model_version` | claude-sonnet-4-... |
| `prompt_version_id` | FK to row in prompt_versions |
| `run_id` | UUID per slide-deck run |
| `failure_mode` | NULL |
| `created_at` | ISO 8601 |

### 11.8 Compare to the hand-mark

The hand-mark for P1 / France (locked in commit `96dad99`) says
`answer_obtained = "Yes"`, sources include the same EU policy page.
The V0 output agrees. Answer match: yes. Source overlap: yes. This is
the success path for the slide.

### 11.9 Failure scenarios to test before scaling

- **Hard question:** try I1 (Impact dimension, definition of open data
  reuse). Expected: lower confidence, possibly "other".
- **Quality question:** Q1 (currency of metadata). Expected: the agent
  may not find a clean source; should produce "other" with low
  confidence, not fabricate.
- **Multi-part question:** P10-a vs P10-b. V0 treats them as separate
  rows.

If V0 handles these three plus P1 cleanly, scale to the rest of the
slide-deck sample.

---

## 12. Open design questions

- **Q7:** `phase2_final` table or `final` boolean on `phase2_runs`?
- **Q8:** Should Tavily's `topic` parameter be set to `news` or `general`?
  The ODMI questions span both regimes. Probably general by default,
  overridden per question dimension. Decide after V0 pilot.
- **Q9:** How to compute `estimated_cost_usd` when CLIProxyAPI routes
  through a flat-rate subscription? Use published Anthropic rates for the
  model variant; note in the report that this is the arithmetic
  equivalent, not the marginal cost.
- **Q10:** Where to store the trusted-domain list for the V1 source
  validator? Probably a `trusted_domains` JSON file in the repo, keyed
  by country. Refined during Phase A.
