# Agent Design

Atomic specifications for every agent in the ODMI swarm. One agent, one job.
Each agent has a clear remit, typed inputs and outputs, an explicit set of
tools, success criteria, and named fallbacks for everything that can go
wrong. No code is written until the contract is locked.

Read this before touching any agent code. Changes require a numbered decision
in `docs/SPEC.md`.

Last reviewed: 2026-06-23.

> **Search-provider note (2026-06-23).** This document predates D43. Where the
> text below says "Tavily", read it as the original design; the shipped system
> is DIY-only (Serper SERP + trafilatura), with Tavily and Brave retired and no
> provider fallback. The agent remits, contracts, and control flow still hold;
> only the search backend differs. See `docs/ARCHITECTURE.md` for the live config.

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
7. **Explicit state-machine orchestration.** Typed state, conditional
   transitions, and dynamic routing between agents (per D3). Implemented as a
   plain Python state machine in `scripts/run_coordinator.py`, not a graph
   framework. See the §5 note.

---

## 2. Agent inventory

Three primary agents make up the swarm, plus an Adjudicator that
fires only when the swarm fails to converge.

| Agent | Status |
|---|---|
| Researcher | Designed below. Build first. |
| Adversarial Verifier | Designed below. Build second. Has four prompt strategies tested as an experimental condition (Section 4.10). |
| Coordinator | Designed below. Build third. Includes the Adjudicator sub-component. |
| Adjudicator (Coordinator sub-component) | Fires when retry_count == 3 with no convergence. Section 5.11. |

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
    language_route_used: Literal["native", "deepl", "unsupported"]
    notes: Optional[str] = None
```

### 3.4 Tools and capabilities

- **DIY web search (Serper SERP + trafilatura extraction, per D43).** Up to 3
  queries per call, top results each, snippets selected by the picker funnel and
  returned to the model.
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
  `unsupported` (D53) and the pair abstains; there is no
  human-translation stage.
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
| `language_failure` | DeepL returns garbage or rejects the content | Fall back to native Claude reading. If still bad, set `language_route_used="unsupported"` (D53) and abstain. |
| `tool_loop` | Model calls the same tool with the same args twice consecutively | Reject the third identical call, force a final-answer prompt. |
| `max_tool_calls` | More than 5 tool calls in one run | Force a final-answer prompt. |
| `captcha_or_block` | Playwright detects CAPTCHA or 403 | Set `notes="captcha/block"`. The Coordinator finalises this pair as an abstention (`abstained_captcha`, D52). |

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

Given the Researcher's claim and citation, attempt to disprove it. The
Verifier's value is cognitive: it deliberately inverts the LLM's
natural optimism bias to cancel out hallucinations. It is not required
to find different sources; many ODMI questions (e.g. "does the
government portal expose an API?") have a single authoritative source
that the Researcher and Verifier will both find. The Verifier's
contribution is the adversarial framing, not source independence.

Concretely, the Verifier:

1. Confirms the evidence quote is actually present at the cited URL
   (substring check). Pure hallucinations die here.
2. Reasons over the evidence under a disprove-the-claim framing,
   running its own searches as needed (which may overlap with the
   Researcher's). The interesting failures are cases where the source
   is real and the quote is real, but the interpretation is wrong.
3. Returns pass, or fail with specific, actionable feedback for the
   Researcher.

This is the project's principal hallucination mitigation.

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
- **Tavily web search.** May overlap with the Researcher's queries
  and URLs. The Verifier's strategic difference is its prompt (see
  Section 4.10), not a deny-list on retrieval.
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
| `schema_invalid` | Model response fails Pydantic | One retry with stricter prompt. If still fails, write a row with `verdict="fail"`, `rejection_reason="verifier schema invalid"`. The Coordinator treats this as a fail and retries up to 3. |
| `timeout` | Wall-clock over 45 seconds | Kill the call. Write a row with `verdict="fail"`, `rejection_reason="verifier timeout"`. |

### 4.7 Default prompt template (strategy: "disprove")

The Verifier has multiple prompt strategies that we plan to compare as
an experimental condition (see Section 4.10). The default below is the
"disprove" strategy.

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
2. Web search using your own queries (may overlap with the Researcher's
   if the same source is the relevant one for this question):
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

Logged as `phase2_verifier_disprove`, version 1.

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

### 4.10 Verifier prompt strategies (experimental condition)

The Verifier's prompt is itself an experimental variable. We test four
strategies on the same hand-marked set and report which catches the
most hallucinations without producing false rejections. This connects
directly to RQ4 (which questions resist automation) and RQ5 (cost
versus quality).

Each strategy is a separate row in `prompt_versions` and produces a
distinct `condition_label` in the run logs (per D12).

**Strategy A: "disprove" (default, Section 4.7).**
Tells the Verifier the Researcher's claim and explicitly asks it to
find disproof. Default-rejection stance. Cheapest to implement,
strongest prior on rejection.

**Strategy B: "negation".**
Reformulates the Researcher's question into its logical negation and
asks the Verifier to answer the negation. If the Verifier confidently
answers the negation in the affirmative, the Researcher's answer is
wrong. For yes/no questions this is clean; for "other"-typed answers
it needs adaptation.

```
The Researcher answered "{researcher.answer}" to:
{question_text}

Your task: find evidence that the answer is the OPPOSITE.
That is, find evidence that for {country_name} the answer is NOT
"{researcher.answer}". You may use the same sources the Researcher
used.

Return your verdict according to whether you found such evidence.
```

**Strategy C: "steelman then attack".**
First articulate the strongest case for the Researcher's answer, then
look for evidence that contradicts even the strongest case. This
costs more tokens (two-step reasoning) and is intended to catch the
case where the surface claim is plausible but the supporting evidence
is weak.

```
The Researcher claims "{researcher.answer}" for:
{question_text}

Step 1: Articulate the single strongest piece of evidence that
supports this claim. Quote it from the source.

Step 2: Now search for evidence that contradicts even your steelman.
Look specifically for:
- A more recent source that supersedes the Researcher's
- A specific exception or carve-out
- A definitional ambiguity the Researcher glossed over

Return verdict and full reasoning.
```

**Strategy D: "blind then compare".**
The Verifier never sees the Researcher's answer. It sees the question,
the URL, and the quote, and is asked to form its own answer. Python
compares. If the answers differ, that's grounds for rejection. The
Verifier's bias toward agreement is structurally removed.

```
{question_text}

For the country {country_name}, here is a quote from {source_url}:
"{evidence_quote}"

Based on this quote and any additional research you wish to do, what
is the answer to the question for this country?

(You are not told the answer anyone else has produced. Form your own
position.)
```

#### Experimental design

For the first comparison, run the same N hand-marked questions through
the Researcher once, then through the Verifier four times (one per
strategy). Each strategy produces a verdict. Compare:

- Hallucination catch rate: of the cases where the hand-mark disagrees
  with the Researcher, which Verifier strategies reject?
- False rejection rate: of the cases where the hand-mark agrees with
  the Researcher, which Verifier strategies still reject?
- Cost: tokens per Verifier run, by strategy.
- Disagreement clustering: do strategies agree with each other, or
  catch different errors?

The pilot answers Q12 in SPEC.md: which strategy do we run by default
in the swarm.

#### Practical notes

- Strategy A is the default and the simplest to implement first. The
  comparison experiment happens once the swarm runs cleanly end-to-end
  on a small set.
- Strategy D needs care: the Verifier still receives the source_url
  and the quote (those are part of "what's being verified"), but not
  the answer label. The prompt above does this.
- Strategy C has the highest token cost; report it as an
  optimisation-relevant data point.

---

## 5. The Coordinator

> **Implementation note (2026-06-02).** This section was written as the
> original design and describes a graph-based orchestration. The shipped
> Coordinator is a plain Python state machine in `scripts/run_coordinator.py`
> (per the amended D3). The state, transitions, and edges below still hold as a
> description of the control flow; only the runtime differs. Read "graph",
> "node", and "edge" below as the equivalent plain-Python constructs.

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
    researcher_outputs: list[ResearcherOutput]   # all attempts, ordered
    verifier_outputs: list[VerifierOutput]       # all attempts, ordered
    last_rejection_feedback: Optional[VerifierFeedback]
    captcha_escalated: bool

    # accumulators
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    cumulative_wall_clock_ms: int

    # adjudicator outcomes (only populated if the adjudicator fires)
    adjudicator_output: Optional[AdjudicatorOutput]

    # terminal
    final_accepted: bool
    final_output: Optional[ResearcherOutput]
    final_failure_reason: Optional[str]
```

The state keeps the full history of Researcher and Verifier attempts in
ordered lists. The Adjudicator (Section 5.10) needs the full history
when retries exhaust without convergence.

### 5.3 Graph edges

```
START → researcher
researcher → verifier
verifier → END                  if verdict=="pass"
verifier → researcher           if verdict=="fail" AND retry_count<3
verifier → adjudicator          if verdict=="fail" AND retry_count==3
adjudicator → END               if adjudicator_verdict in {researcher_correct, verifier_correct, neither}
adjudicator → abstain           if adjudicator_verdict=="abstain"   # D51: renamed from escalate_human
researcher → abstain            if captcha_or_block detected
abstain → END                   (always terminal for this pair; D52: no human queue)
```

These conditional transitions are expressed as plain Python branches in
`run_coordinator.py`.

The adjudicator (Section 5.10) replaces the previous "fail at retry 3 →
END" terminal. The Coordinator now has a tiebreaker step when the
Researcher and Verifier cannot converge.

### 5.4 Inputs

A queue of `ResearcherInput` objects, typically one per (question,
country) pair for a batch. Phase A queue is roughly 30-50 pairs for
France.

### 5.5 Outputs

For each pair, the Coordinator writes:

- One row per Researcher attempt to `phase2_researcher_runs`.
- One row per Verifier attempt to `phase2_verifier_runs`.
- One row per adjudication (if any) to `phase2_adjudications`.
- One row per pair to `phase2_final` with the accepted answer, the
  cumulative cost, the retry count, whether the adjudicator was
  involved, and the terminal status.

### 5.6 Tools and capabilities

- **Plain Python state machine.** Typed state, conditional transitions,
  dynamic routing between agents.
- **Researcher, Verifier, Adjudicator** as state-machine steps.
- **SQLite logger.** Implements the four write paths above.
- **Abstention recorder.** A pair that hits a CAPTCHA, an access block,
  or an Adjudicator abstention finalises as an abstention: its
  `phase2_final` row carries the matching `abstained_*` terminal status
  and an `inconclusive` answer (D52). There is no human-review stage and
  no queue; abstaining does not block other pairs.

### 5.7 Success criteria

The Coordinator's run on a batch succeeds when every pair in the queue
reaches a terminal state. A pair's terminal state is one of:

- `accepted_by_verifier`: Verifier verdict was pass within 3 retries.
- `accepted_by_adjudicator`: Adjudicator picked a winner after retries
  exhausted.
- `abstained_captcha`: Researcher signalled CAPTCHA or access block (D52,
  formerly `escalated_captcha`).
- `abstained_adjudicator`: Adjudicator could not pick a winner with
  enough confidence (D52, formerly `escalated_adjudicator`).
- `agent_failure`: any other failure mode that prevented termination.

No infinite loops. No pair leaks past 3 retries (after which the
adjudicator decides or escalates).

### 5.8 Fallbacks

| Code | Trigger | Handler |
|---|---|---|
| `researcher_failure` | Researcher returns an unrecoverable error (e.g. schema_invalid after retry, timeout) | Treat as Verifier fail. Increment retry_count. Continue. |
| `verifier_failure` | Verifier returns an unrecoverable error | Treat as Verifier fail. Increment retry_count. Continue. |
| `max_retries_reached` | retry_count hits 3 with no accepted answer | Hand off to the Adjudicator (Section 5.10), not directly to END. |
| `adjudicator_failure` | Adjudicator returns an unrecoverable error | Finalise as `agent_failure` with `final_failure_reason="adjudicator_failure"`. |
| `adjudicator_low_confidence` | Adjudicator returns `abstain` (D51, formerly `escalate_human`) | Finalise as an abstention: `abstained_adjudicator` terminal status, `inconclusive` answer (D52). |
| `captcha_or_block` | Researcher's notes contain the CAPTCHA marker | Mark captcha_escalated=True. Finalise as `abstained_captcha` (D52). |
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

### 5.11 The Adjudicator (Coordinator sub-component)

When the Researcher and Verifier disagree across all three retries, the
Coordinator hands the case to the Adjudicator. The Adjudicator does not
run new searches. Its job is to weigh the evidence already gathered and
either pick a winner or abstain.

The Adjudicator is implemented as a Coordinator-internal LLM call, not
as a separately-versioned agent file. It lives in the Coordinator
module and uses the same DB conventions for prompt versioning and cost
logging.

#### 5.11.1 Remit

After three rounds of Researcher and Verifier disagreement, decide
whether the Researcher was correct, the Verifier was correct, neither
was correct, or the case is too uncertain to settle without a human.

#### 5.11.2 Inputs

```python
class AdjudicatorInput(BaseModel):
    question_id: str
    question_text: str
    country_code: str
    country_name: str
    researcher_outputs: list[ResearcherOutput]   # all 3 attempts
    verifier_outputs: list[VerifierOutput]       # all 3 attempts
```

#### 5.11.3 Outputs

```python
class AdjudicatorOutput(BaseModel):
    adjudicator_verdict: Literal[
        "researcher_correct",
        "verifier_correct",
        "neither",
        "abstain",                # D51: renamed from escalate_human
    ]
    adjudicator_answer: Optional[Literal["yes", "no", "other", "not_applicable"]]
    adjudicator_confidence: float            # 0.0-1.0
    adjudicator_reasoning: str               # at least 50 chars
    chosen_source_url: Optional[HttpUrl] = None
    chosen_evidence_quote: Optional[str] = None
```

#### 5.11.4 Tools

- Claude single call via CLIProxyAPI. No web search. No browser fetch.
  The point of the Adjudicator is to weigh evidence already collected,
  not to gather new evidence.

#### 5.11.5 Success criteria

1. Output validates against `AdjudicatorOutput`.
2. `adjudicator_reasoning` is at least 50 characters.
3. If `adjudicator_verdict` is one of `researcher_correct`,
   `verifier_correct`, or `neither`, then `adjudicator_answer`,
   `chosen_source_url`, and `chosen_evidence_quote` are populated.
4. If `adjudicator_confidence < 0.6`, the verdict is auto-promoted to
   `abstain` (D51, formerly `escalate_human`) regardless of the model's
   nominal choice.
5. Within token budget (5000 input + 800 output) and wall-clock 30s.

#### 5.11.6 Fallbacks

| Code | Trigger | Handler |
|---|---|---|
| `schema_invalid` | Output fails Pydantic | One retry; if still fails, force `abstain`. |
| `low_confidence` | adjudicator_confidence below 0.6 | Promote to `abstain`. |
| `timeout` | 30 seconds | Force `abstain`. |

#### 5.11.7 Prompt template (v1)

```
You are an adjudicator. A Researcher and a Verifier have failed to
agree on the answer to an ODMI question after three attempts. Decide
which of them is correct based on the evidence they collected, or
abstain if you cannot be confident.

Question:
{question_text}

Country: {country_name} ({country_code})

The Researcher's final position:
- Answer: {researcher_outputs[-1].answer}
- Evidence quote: "{researcher_outputs[-1].evidence_quote}"
- Source URL: {researcher_outputs[-1].source_url}
- Confidence: {researcher_outputs[-1].answer_confidence}

The Verifier's final position:
- Verdict: fail
- Counter-evidence: "{verifier_outputs[-1].counter_evidence_quote}"
- Counter-source: {verifier_outputs[-1].counter_source_url}
- Rejection reason: {verifier_outputs[-1].rejection_reason}

Full history of the loop (all attempts):
{history_block}

Decide one of:
- researcher_correct: the Researcher's final answer should stand.
- verifier_correct: the Verifier's counter-position is the right answer.
- neither: both are wrong; the correct answer is something else (and
  you must say what).
- abstain: the case is too uncertain to settle on the evidence
  gathered.

Report adjudicator_confidence in [0.0, 1.0]. If your confidence is
below 0.6 your verdict will be auto-promoted to abstain.

Return JSON matching AdjudicatorOutput.
```

Logged as `phase2_adjudicator`, version 1.

### 5.12 Worked walkthrough: adjudicator path

Suppose for I1 / France (a subjective Impact question on the definition
of open-data reuse) the loop plays out as:

1. Researcher attempt 1: answer "yes", cites a Capgemini consultancy
   summary. Verifier rejects: source is not authoritative for a
   definition question.
2. Researcher attempt 2: answer "yes", cites a French academic paper.
   Verifier rejects: paper proposes one definition among several.
3. Researcher attempt 3: answer "other", cites the data.gouv.fr glossary.
   Verifier rejects: glossary entry is short and arguably matches an
   official definition that would justify "yes".

retry_count == 3. Edge verifier → adjudicator.

The Adjudicator sees all three Researcher answers, all three Verifier
counter-positions, and the question. It reasons that:

- The Researcher's third attempt and the Verifier's most coherent
  counter-position both have some merit.
- Confidence in either side is moderate, not high.
- adjudicator_confidence = 0.55, below 0.6.

Verdict auto-promoted to `abstain` (D51, formerly `escalate_human`). The
pair finalises as `inconclusive` under the D37 floor, with terminal
status `abstained_adjudicator` (D52) and the full history logged.

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
Coordinator (the plain Python state machine). Within each, the order is:

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
