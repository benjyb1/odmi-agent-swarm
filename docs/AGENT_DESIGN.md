# Agent Design

Atomic specifications for every agent in the ODMI swarm. One agent, one job.
Each agent has a clear remit, typed inputs and outputs, an explicit set of
tools, success criteria, and named fallbacks for everything that can go
wrong. No code is written until the contract is locked.

Read this before touching any agent code. Changes require a numbered decision
in `docs/SPEC.md`.

Last reviewed: 2026-05-11.

---

## 1. Design principles

These are the rules every agent obeys.

1. **One agent, one job.** If an agent has two responsibilities, it
   becomes two agents.
2. **Typed contracts.** Every agent has a Pydantic model for its input
   and another for its output. The signature is the agent. No dictionary
   smuggling.
3. **Explicit success criterion.** An agent is "done" when its output
   passes validation against its output model and its post-conditions
   (e.g., the cited source URL returns HTTP 200 and contains the quoted
   evidence).
4. **Bounded effort.** Every agent has a token budget and a wall-clock
   timeout. Exceeding either is a failure mode, not a silent failure.
5. **Receipts on every call.** Every LLM call records `input_tokens`,
   `output_tokens`, `wall_clock_ms`, the model version, and the prompt
   version. No exceptions. This is the basis of RQ5 (per D12).
6. **Named fallbacks for every failure mode.** Each agent enumerates the
   ways it can fail, with a deterministic handler for each. Failures
   produce a row, not an exception.
7. **LangGraph idioms for orchestration.** StateGraph with typed state,
   conditional edges, the Command API for dynamic routing (per D3).

---

## 2. Agent inventory

Three primary agents make up the swarm.

| Agent | Status |
|---|---|
| Researcher | Designed below. Build first. |
| Adversarial Verifier | Designed below. Build second. |
| Coordinator | Designed below. Build third. |

Two optional or deferred agents:

| Agent | Status |
|---|---|
| Translator helper | Phase B; deferred design |
| Classifier (post-hoc) | Off critical path per D8 |

---

## 3. The Researcher

### 3.1 Remit

Given a (question, country), find authoritative evidence on the public
web and produce a structured candidate answer with a verifiable source.
The Researcher is not the final say; the Verifier reviews. The
Researcher's job is to make its best attempt at retrieval and reasoning,
then hand off.

### 3.2 Inputs

```python
class ResearcherInput(BaseModel):
    question_id: str                       # e.g. "P1"
    question_text: str                     # the literal question
    dimension: str                         # Policy / Portal / Quality / Impact
    indicator: str                         # e.g. policy_framework
    response_scoring: str                  # ODMI's official scoring rule
    country_code: str                      # ISO 3166-1 alpha-2 (e.g. "FR")
    country_name: str                      # e.g. "France"
    country_language: str                  # ISO 639-1 (e.g. "fr")
    portal_url: Optional[str] = None       # known national portal if available
    verifier_feedback: Optional[VerifierFeedback] = None   # only on retries
```

`VerifierFeedback` is populated when the Coordinator re-dispatches a pair
after a Verifier rejection:

```python
class VerifierFeedback(BaseModel):
    rejection_reason: str
    suggested_search_query: Optional[str] = None
    failed_source_url: Optional[HttpUrl] = None
```

### 3.3 Outputs

```python
class ResearcherOutput(BaseModel):
    answer: Literal["yes", "no", "other", "not_applicable"]
    answer_explanation: str                # one sentence in English
    evidence_quote: str                    # literal substring from a source
    source_url: HttpUrl                    # must return HTTP 200
    retrieval_confidence: float            # 0.0-1.0
    answer_confidence: float               # 0.0-1.0
    search_queries_used: list[str]
    fetched_urls: list[HttpUrl]            # what Playwright actually fetched
    domain_trust_score: Optional[float] = None    # from source validator
    language_route_used: Literal["native", "deepl", "human_required"]
    notes: Optional[str] = None
```

### 3.4 Tools and capabilities

- **Tavily web search.** Up to 3 queries per call, top 5 results each.
  Snippets returned to the model.
- **Playwright browser fetch.** Used when a snippet is insufficient and
  the model wants the full page. Fetched content capped at 4000 chars
  by default (configurable for the `retrieval-tight` optimisation
  variant per D12).
- **Source validator.** Checks the cited domain against a per-country
  trusted-domains list (`data/trusted_domains/<country>.json`). Returns
  a 0-1 score. Not a gate; the score is passed to the Verifier.
- **Language router.** Reads `country_language`. If the language is in
  the native-capable set (populated by Phase B pilot), the model reads
  source content directly. Otherwise the content is passed through
  DeepL via the Translator helper. If both fail, route is set to
  `human_required` and the pair is flagged.
- **Claude call** via CLIProxyAPI (per D1). Native tool use enabled.
  The model can call `web_search` and `fetch_url` directly; Python
  implements both as actual API calls.

### 3.5 Success criteria

The Researcher's run succeeds when all of:

1. The output validates against `ResearcherOutput`.
2. `source_url` resolves to HTTP 200 (verified by a separate `httpx`
   HEAD request after the Claude call returns).
3. `evidence_quote` is a non-empty string of at least 10 characters.
4. `answer_confidence >= 0.5` OR `answer == "other"`. Low-confidence
   answers are allowed but must be marked.
5. The full agent run (search, fetch, model loop, validation) stays
   inside the token budget (10,000 input + 1500 output) and the
   wall-clock budget (60 seconds).

If any post-condition fails, the row is written anyway with the
failure mode in `notes`. The Verifier then sees the failure and either
catches it or passes through.

### 3.6 Fallbacks (failure modes)

Every failure has a deterministic handler. The handler runs in Python,
not in the model.

| Code | Trigger | Handler |
|---|---|---|
| `search_empty` | All Tavily queries return zero results | Set `answer="other"`, `retrieval_confidence=0.0`, `notes="no search results"`. Do not call Claude. |
| `url_unreachable` | Cited `source_url` returns 4xx/5xx | Mark `retrieval_confidence=0.0`, set `notes="cited URL unreachable"`. Pass to Verifier anyway. |
| `quote_not_in_source` | Model claims a quote that does not appear in the fetched content | Retry the Claude call once with stricter "quote literally" prompt. If still fails, set `answer_confidence` to at most 0.3 and `notes="quote not verified in source"`. |
| `schema_invalid` | Model response is not valid JSON or fails Pydantic | One retry with a stricter "JSON only" prompt. If second attempt fails, write a row with `answer="other"`, `answer_confidence=0.0`, `notes="schema invalid"`. |
| `token_budget_exceeded` | Cumulative tokens over the cap | Cap the response, log it, set `notes="truncated"`. |
| `timeout` | Wall-clock over 60 seconds | Kill the call. Write a row with whatever fields were populated and `notes="timeout"`. |
| `domain_untrusted` | Source validator returns a score below threshold | Do not reject. Pass the score along to the Verifier and set `notes="untrusted domain"`. |
| `language_failure` | DeepL returns garbage or rejects the content | Fall back to native Claude reading. If still bad, set `language_route_used="human_required"`. |
| `tool_loop` | Model calls the same tool with the same args twice consecutively | Reject the third identical call, force a final-answer prompt. |
| `max_tool_calls` | More than 5 tool calls in one run | Force a final-answer prompt. |
| `captcha_or_block` | Playwright detects CAPTCHA or 403 | Set `notes="captcha/block"`. The Coordinator escalates this pair to the human queue. |

### 3.7 Prompt template (v1)

The literal text sent to Claude on each attempt. Curly-brace placeholders
get filled in by Python.

```
You are evaluating a question from the EU Open Data Maturity Index (ODMI)
for the country: {country_name} ({country_code}).

The question is:
{question_text}

The official ODMI scoring rule for this question is:
{response_scoring}

You have access to two tools:
- web_search(query, max_results=5): returns Tavily snippets for the query
- fetch_url(url): returns the first 4000 characters of the page at the URL

Use these tools to find evidence, then produce a final structured answer.

Your job:
1. Determine whether the evidence supports an answer of "yes", "no",
   "other", or "not_applicable" for this question and this country.
2. Quote a specific passage from a source that supports your answer.
   Quote literally; do not paraphrase.
3. Choose the single source URL that best supports your answer.
4. Report two confidence scores in [0.0, 1.0]:
   - retrieval_confidence: how confident you are that the cited source
     is real, legitimate, and current.
   - answer_confidence: how confident you are that the quoted evidence
     supports the specific claim implied by your answer.
5. If the evidence is insufficient, return "other" with low confidence
   and say so in answer_explanation. Do not invent evidence.

{verifier_feedback_block}   # populated only on retries

Return your answer as JSON matching the ResearcherOutput schema.
```

`verifier_feedback_block` is empty on the first attempt. On a retry it
includes the rejection_reason and (if provided) the
suggested_search_query from the Verifier's previous rejection.

Every prompt version is logged to `prompt_versions` in SQLite (per D5).
The text above is `phase2_researcher`, version 1.

### 3.8 Worked walkthrough: P1 / France

Inputs:

```python
ResearcherInput(
    question_id="P1",
    question_text="Is there a national open data policy in your country and, if your country is an EU Member State, does this include a national legislation for the transposition of the Open Data Directive?",
    dimension="Policy",
    indicator="policy_framework",
    response_scoring="{'yes': 40, 'no': 0, 'other': 40}",
    country_code="FR",
    country_name="France",
    country_language="fr",
    portal_url="https://www.data.gouv.fr/",
    verifier_feedback=None,
)
```

Tool loop (typical):

1. Claude calls `web_search("France Open Data Directive transposition national policy", max_results=5)`.
2. Python returns Tavily snippets (digital-strategy.ec.europa.eu,
   legifrance.gouv.fr, data.gouv.fr documentation).
3. Claude calls `fetch_url("https://digital-strategy.ec.europa.eu/en/policies/legislation-open-data")` to get the full content of the most promising snippet.
4. Python returns the first 4000 characters of that page.
5. Claude produces a final answer.

Expected final output:

```json
{
  "answer": "yes",
  "answer_explanation": "France has a national open data policy and has transposed the EU Open Data Directive via Law 2016-1321 (Loi pour une République numérique).",
  "evidence_quote": "France has transposed the Open Data Directive through Law 2016-1321 (Loi pour une République numérique).",
  "source_url": "https://digital-strategy.ec.europa.eu/en/policies/legislation-open-data",
  "retrieval_confidence": 0.9,
  "answer_confidence": 0.9,
  "search_queries_used": ["France Open Data Directive transposition national policy"],
  "fetched_urls": ["https://digital-strategy.ec.europa.eu/en/policies/legislation-open-data"],
  "domain_trust_score": 0.95,
  "language_route_used": "native",
  "notes": null
}
```

Post-call validation by Python:

1. JSON parses against `ResearcherOutput`. Pass.
2. `httpx.head(source_url)` returns 200. Pass.
3. `evidence_quote` length >= 10. Pass.
4. `answer_confidence >= 0.5`. Pass.
5. Within token / wall-clock budgets. Pass.

Researcher hands the output to the Verifier.

---

## 4. The Adversarial Verifier

### 4.1 Remit

Given the Researcher's claim and citation, independently fetch the cited
URL to confirm the evidence quote is real, run an independent search for
counter-evidence, and return either a pass (accept the Researcher's
answer) or a fail (with specific, actionable feedback for the Researcher
to retry).

The Verifier is prompted to disprove, not confirm. Its default stance is
scepticism. This is the project's principal hallucination mitigation.

### 4.2 Inputs

```python
class VerifierInput(BaseModel):
    question_id: str
    question_text: str                     # repeated for context
    country_code: str
    country_name: str
    researcher_output: ResearcherOutput    # the claim being verified
```

### 4.3 Outputs

```python
class VerifierOutput(BaseModel):
    verdict: Literal["pass", "fail"]
    verifier_answer: Literal["yes", "no", "other", "not_applicable"]
    verifier_confidence: float             # 0.0-1.0

    substring_check_result: Literal["pass", "fail", "not_attempted"]
    substring_check_notes: Optional[str] = None

    independent_search_queries: list[str]  # different from the Researcher's
    independent_evidence_snippets: list[str]

    rejection_reason: Optional[str] = None         # required if verdict==fail
    counter_evidence_quote: Optional[str] = None   # required if verdict==fail
    counter_source_url: Optional[HttpUrl] = None   # required if verdict==fail
    suggested_search_query: Optional[str] = None   # hint for retry
```

### 4.4 Tools and capabilities

- **httpx fetch.** Independent fetch of the Researcher's `source_url`.
  Used for the substring check, not for general reading.
- **Playwright fetch.** Fallback when httpx returns dynamic-rendering
  failure (JS-heavy pages).
- **Tavily web search.** Independent queries. Constraint: the
  Verifier may not reuse any of `researcher_output.search_queries_used`
  or `researcher_output.fetched_urls`. Implemented as a deny-list
  filter in Python before the call.
- **Claude call** via CLIProxyAPI. The Verifier has its own prompt
  and its own row in `prompt_versions`.

### 4.5 Success criteria

The Verifier's run succeeds when all of:

1. Output validates against `VerifierOutput`.
2. The substring check has been attempted (the result is one of `pass`,
   `fail`, `not_attempted`, with a non-empty note in the last case
   explaining why).
3. At least one independent search has been performed and at least one
   snippet returned (or a failure mode is named in `notes`).
4. If `verdict == "fail"`, then `rejection_reason`,
   `counter_evidence_quote` (or `counter_source_url`), and
   `suggested_search_query` are all populated.
5. Within token budget (5000 input + 1000 output) and wall-clock
   budget (45 seconds).

### 4.6 Fallbacks

| Code | Trigger | Handler |
|---|---|---|
| `researcher_url_unreachable` | Cannot fetch `researcher_output.source_url` | Mark `substring_check_result="not_attempted"` with the HTTP status in the note. Proceed to independent search. The Verifier then judges on independent evidence alone. |
| `substring_not_found` | The Researcher's `evidence_quote` is not a substring of the fetched page | Mark `substring_check_result="fail"`. Strong signal toward `verdict="fail"`, but the model still considers independent evidence. |
| `independent_search_empty` | All independent queries return zero hits | Mark in `notes`. If the substring check passed, the Verifier may still pass (low-confidence). If the substring check failed too, `verdict="fail"` with `rejection_reason="no corroborating evidence"`. |
| `verifier_disagrees` | Claude's independent reasoning concludes a different answer | `verdict="fail"`, `verifier_answer` is the Verifier's own answer, `rejection_reason` explains the disagreement, `suggested_search_query` proposes how the Researcher should approach the next attempt. |
| `query_overlap` | The model proposes an independent query that matches one the Researcher used | Python filters before calling Tavily, returns a "try a different query" notice to the model. |
| `schema_invalid` | Model response fails Pydantic | One retry with stricter prompt. If still fails, write a row with `verdict="fail"`, `rejection_reason="verifier schema invalid"`. The Coordinator treats this as a fail and retries up to 3. |
| `timeout` | Wall-clock over 45 seconds | Kill the call. Write a row with `verdict="fail"`, `rejection_reason="verifier timeout"`. |

### 4.7 Prompt template (v1)

```
You are an adversarial verifier reviewing a Researcher's claim for the
EU Open Data Maturity Index. Your default stance is scepticism: your
job is to find a reason the answer is wrong, not to agree.

The question is:
{question_text}

The country is {country_name} ({country_code}).

The Researcher's claim:
- answer: {researcher_output.answer}
- evidence quote: "{researcher_output.evidence_quote}"
- source URL: {researcher_output.source_url}
- Researcher's retrieval confidence: {researcher_output.retrieval_confidence}
- Researcher's answer confidence: {researcher_output.answer_confidence}

Independent verification already run by Python:

1. Substring check: the evidence quote {substring_check_phrasing}
   found in the page at the cited URL.
2. Independent web search using queries different from the Researcher's:
   {independent_evidence_block}

Your task:
1. Decide whether the Researcher's answer should be accepted.
2. If you reject, you must provide:
   - a specific reason (not "I disagree")
   - a counter-evidence quote OR a counter-source URL
   - a suggested search query the Researcher should try next
3. Report your own verdict_confidence in [0.0, 1.0].

If you accept, your verifier_answer must match the Researcher's answer.

Return your verdict as JSON matching the VerifierOutput schema.
```

Logged as `phase2_verifier`, version 1.

### 4.8 Worked walkthrough: P1 / France, accept path

Inputs:

The `VerifierInput` carries the `ResearcherOutput` from Section 3.8.

Python pre-work:

1. `httpx.get("https://digital-strategy.ec.europa.eu/en/policies/legislation-open-data")` returns 200 with HTML body.
2. Check whether the evidence quote "France has transposed the Open Data Directive through Law 2016-1321 (Loi pour une République numérique)." appears as a substring. Pass.
3. Run two independent Tavily queries excluding the Researcher's:
   - "loi république numérique 2016-1321 open data"
   - "France Directive 2019/1024 mise en oeuvre"
4. Snippets returned from legifrance.gouv.fr (the actual text of Law 2016-1321) and a Senate report on the transposition.

Expected Verifier output:

```json
{
  "verdict": "pass",
  "verifier_answer": "yes",
  "verifier_confidence": 0.95,
  "substring_check_result": "pass",
  "substring_check_notes": null,
  "independent_search_queries": [
    "loi république numérique 2016-1321 open data",
    "France Directive 2019/1024 mise en oeuvre"
  ],
  "independent_evidence_snippets": [
    "Loi n° 2016-1321 du 7 octobre 2016 pour une République numérique...",
    "La France a transposé la Directive (UE) 2019/1024..."
  ],
  "rejection_reason": null,
  "counter_evidence_quote": null,
  "counter_source_url": null,
  "suggested_search_query": null
}
```

The Coordinator marks the pair as accepted and writes the final row.

### 4.9 Worked walkthrough: P1 / France, reject path (illustrative)

Suppose the Researcher had cited a fabricated quote that does not appear
on the page:

- Substring check fails.
- Independent search finds the real evidence, contradicting the
  fabricated quote.
- Verifier returns `verdict="fail"`, `rejection_reason="evidence quote not found in cited source; independent evidence supports the same yes answer but from a different quote"`, `counter_evidence_quote=...`, `suggested_search_query="loi 2016-1321 République numérique"`.
- Coordinator increments `retry_count`, re-dispatches to the
  Researcher with this feedback.

---

## 5. The Coordinator

### 5.1 Remit

Orchestrate the Researcher → Verifier loop for each (question, country)
pair. Manage retries up to 3. Escalate access blocks to the human
queue. Track cumulative cost. Log every step. Write the final accepted
answer.

The Coordinator is the only stateful agent. The other two are
stateless given their inputs.

### 5.2 State

```python
class SwarmState(TypedDict):
    # immutable inputs
    question_id: str
    country_code: str
    rubric_tier: Optional[str]              # from hand_marks if available
    run_id: str                             # UUID for this batch run

    # mutable
    retry_count: int                        # 0 to 3
    researcher_output: Optional[ResearcherOutput]
    verifier_output: Optional[VerifierOutput]
    last_rejection_feedback: Optional[VerifierFeedback]
    captcha_escalated: bool

    # accumulators
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    cumulative_wall_clock_ms: int

    # terminal
    final_accepted: bool
    final_output: Optional[ResearcherOutput]
    final_failure_reason: Optional[str]
```

### 5.3 Graph edges

```
START → researcher
researcher → verifier
verifier → END                  if verdict=="pass"
verifier → researcher           if verdict=="fail" AND retry_count<3
verifier → END                  if verdict=="fail" AND retry_count==3
researcher → human_queue        if captcha_or_block detected
human_queue → END               (always terminal for this pair)
```

Conditional edges are expressed in LangGraph with the Command API.

### 5.4 Inputs

A queue of `ResearcherInput` objects, typically one per (question,
country) pair for a batch. Phase A queue is roughly 30-50 pairs for
France.

### 5.5 Outputs

For each pair, the Coordinator writes:

- One row per Researcher attempt to `phase2_researcher_runs`.
- One row per Verifier attempt to `phase2_verifier_runs`.
- One row per pair to `phase2_final` with the accepted answer, the
  cumulative cost, the retry count, and the terminal status.

### 5.6 Tools and capabilities

- **LangGraph StateGraph.** Typed state, conditional edges, Command
  API.
- **Researcher and Verifier agents** as LangGraph nodes.
- **SQLite logger.** Implements the three write paths above.
- **Human queue writer.** Appends to a `data/human_queue/<run_id>.csv`
  for any pair that hits a CAPTCHA or access block. Does not block
  other pairs.

### 5.7 Success criteria

The Coordinator's run on a batch succeeds when every pair in the queue
reaches a terminal state. A pair's terminal state is one of:

- `accepted`: Verifier verdict was pass within 3 retries.
- `rejected_max_retries`: Verifier rejected on attempt 3.
- `escalated`: Researcher signalled CAPTCHA or access block.
- `agent_failure`: any other failure mode that prevented termination.

No infinite loops. No pair leaks past 3 retries.

### 5.8 Fallbacks

| Code | Trigger | Handler |
|---|---|---|
| `researcher_failure` | Researcher returns an unrecoverable error (e.g. schema_invalid after retry, timeout) | Treat as Verifier fail. Increment retry_count. Continue. |
| `verifier_failure` | Verifier returns an unrecoverable error | Treat as Verifier fail. Increment retry_count. Continue. |
| `max_retries_reached` | retry_count hits 3 with no accepted answer | Mark final_accepted=False, final_failure_reason="max retries". Write the rejected row. |
| `captcha_or_block` | Researcher's notes contain the CAPTCHA marker | Mark captcha_escalated=True. Write the pair to the human queue. Mark final_failure_reason="escalated". |
| `coordinator_crash` | Out of scope at this version | Manual rerun. A resume-from-state mechanism is deferred. |

### 5.9 Worked walkthrough: P1 / France, accept path

1. Coordinator pulls (P1, FR) from the queue.
2. State initialised: retry_count=0, run_id=UUID(), all outputs None.
3. Edge START → researcher.
4. Researcher node runs. Returns the output from Section 3.8.
5. State updated. Edge researcher → verifier.
6. Verifier node runs. Returns the pass output from Section 4.8.
7. State.final_accepted=True, state.final_output=researcher_output.
8. Edge verifier → END.
9. SQLite write paths fire: one row to phase2_researcher_runs, one to
   phase2_verifier_runs, one to phase2_final.
10. Coordinator pulls next pair from the queue.

### 5.10 Worked walkthrough: P1 / France, reject-then-accept path

1. As above, but the first Verifier verdict is fail.
2. Verifier's rejection_reason and suggested_search_query are written
   into state.last_rejection_feedback.
3. retry_count incremented to 1.
4. Edge verifier → researcher.
5. Researcher node runs again, this time with verifier_feedback
   populated in its input. Different query, possibly different source.
6. New Researcher output written. Edge researcher → verifier.
7. Verifier passes this time. Edge verifier → END.
8. Two Researcher rows, two Verifier rows, one final row written.

---

## 6. Translator helper (Phase B, deferred)

Wraps DeepL. Called by the Researcher's language router when
`country_language` is not in the native-capable set. Inputs a chunk of
source text, outputs an English translation with a confidence score.
Out of scope for Phase A. Designed in detail when Phase B begins.

---

## 7. Classifier as post-hoc tool (optional, off critical path)

Per D8, the classifier is not a runtime stage. As a post-hoc
experiment, `agents/classifier.py` may be run against the same
(question, country) pairs as hand-marked. The output is a prediction of
the rubric scores; we compare against the locked hand-marks to test
whether the rubric can be automated. This is a secondary finding,
written up only if the primary swarm work is on schedule.

---

## 8. Build order

Researcher first. Then Verifier (with the substring check). Then
Coordinator (the LangGraph wrapper). Within each, the order is:

1. Schema migration for the agent's database table.
2. Pydantic models for input and output.
3. Prompt template inserted into `prompt_versions`.
4. Python harness that calls the agent and validates.
5. One end-to-end run on P1 / France.
6. Run on the three failure-scenario probes: I1 (subjective Impact),
   Q1 (quality), P10-a vs P10-b (multi-part).
7. Commit with the worked outputs in the commit message.

Only when an agent passes step 6 cleanly do we move to the next.

---

## 9. Open design questions

- **Q7:** `phase2_final` table or `final` boolean on a single
  `phase2_runs` table? Probably separate tables for query simplicity.
  Decide before the schema migration.
- **Q8:** Tavily `topic` parameter default. `general` is the right
  starting position; revisit if ODMI policy questions need
  `news`-style results.
- **Q9:** How to compute `estimated_cost_usd` under the CLIProxyAPI
  flat-rate subscription. Use published Anthropic rates as the
  arithmetic equivalent; footnote it.
- **Q10:** Where to store the trusted-domain list for the source
  validator. Per-country JSON files under `data/trusted_domains/`
  is the leaning answer.
- **Q11:** The substring check's tolerance for whitespace and
  punctuation. Strict literal match is brittle. A normalised match
  (collapse whitespace, lowercase, strip punctuation) is probably
  right. Decide before building the Verifier.
