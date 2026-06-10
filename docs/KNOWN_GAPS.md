# Known Gaps

This file is **operational** deferrals: things that break a run (resume,
CAPTCHA, the human queue). For **correctness** failure modes (ways the swarm
commits a wrong answer while looking confident), see `docs/FAILURE_MODES.md` —
that is the false-positive register and the attack list.

Forward-looking failure modes that haven't bitten yet, with the
observable symptom and the ~hour cost to fix when they do.

These are deliberate deferrals, not bugs. Each was triaged in the
2026-05-12 contract audit and judged speculative: building the fix
without seeing the real trigger would mean guessing at the right
shape. The point of this file is so when something *does* go wrong,
the path from symptom to triage is short.

Last reviewed: 2026-05-13.

---

## 1. Resume from interruption (D22-D25)

**Trigger condition.** An in-flight subtrio is interrupted by:
- a Claude rate-limit (429) mid-pair (exit code 42 from the coordinator),
- the dispatcher being SIGKILLed (laptop closed, terminal crash, etc.),
- a Python crash inside the coordinator before terminal state.

**Symptom you'll see.**
- A `subtrio_status` row stuck in `stage IN ('queued', 'researching', 'verifying', 'adjudicating')` or with `stage='interrupted_rate_limit'`.
- `phase2_researcher_runs` / `phase2_verifier_runs` rows may exist for the pair, but no `phase2_final` row.
- The Run Console card shows the pair as "active" (blue/amber border) but nothing is actually running.
- After ~10 minutes `scripts/cleanup_subtrios.py` will mark the row `orphaned`.

**Workaround today.** Manually re-release the same `(question, country)` from the Run Console; the original interrupted row stays in the audit trail with `stage=orphaned`, and a fresh subtrio runs from scratch. You'll pay for the Researcher / Verifier work twice.

**What to build when it happens.** A resume helper in `scripts/run_coordinator.py`. Detect at start whether there's an open `subtrio_status` row for `(question, country)` with rows already in `phase2_researcher_runs` / `phase2_verifier_runs` but no `phase2_final`. Reconstruct state from those rows. Seven dispatch cases (researcher exists but no verifier → resume at verifier; both exist but verifier failed and retry_count < max → resume at retry researcher; etc.). Estimated ~150 lines plus tests.

**Why deferred.** I haven't hit a rate limit yet. Pre-flight refusal (D20) makes mid-batch hits unlikely in the v1 budget envelope. Building the seven-case decision tree without seeing a real case risks designing for the wrong combinations.

---

## 2. CAPTCHA / 403 detection

**Trigger condition.** The Researcher's or Verifier's `fetch_url` call returns a 403, a CAPTCHA page, or any "you've been blocked" interstitial. The portal blocks our user-agent or our IP.

**Symptom you'll see.**
- A Researcher row with `failure_mode=null` but a clearly nonsense answer (e.g. the model invented something to satisfy the schema).
- The Verifier's substring check passes against the CAPTCHA page text rather than the real source.
- Repeated runs on the same `(question, country)` produce different and degenerate answers.

The fingerprint: open the Researcher's `source_url` in your browser. If it shows a CAPTCHA, a Cloudflare interstitial, a 403 page, or an empty-after-strip body, the portal is blocking us.

**Workaround today.** None. The pair will produce garbage rows that look superficially valid.

**What to build when it happens.**
- In `agents/tools/fetch.py`: detect a known block-marker set (Cloudflare strings, reCAPTCHA, "Access Denied", "Bot detected", body-length < 200 chars after HTML stripping).
- Mark the `FetchResult.failure_mode` with `"captcha_or_block"`.
- In `agents/researcher.py` and `agents/verifier.py`: when this failure mode bubbles up, set `notes="captcha/block"`.
- In `scripts/run_coordinator.py`: detect `notes` containing `"captcha/block"` and route the pair to `terminal_status="escalated_captcha"`. Combine with Gap #3 (CSV).

Estimated ~100 lines across three files.

**Why deferred.** Six pilot countries (FR/RO/DE/NL/HU/EE) tested so far — none block the public pages we hit. Speculative until proven otherwise.

---

## 3. Human-queue CSV writer

**Trigger condition.** The Coordinator writes a `phase2_final` row with `terminal_status IN ('escalated_captcha', 'escalated_adjudicator')`. Currently nothing else happens.

**Symptom you'll see.**
- The Home page's "Human queue" widget lists the pair but offers no way to act on it.
- There's no per-batch artefact to hand off to the human reviewer.
- The full history (researcher attempts, verifier counter-evidence, adjudicator reasoning) lives in five different tables and has to be reassembled by SQL.

**Workaround today.** Ad hoc SQL against `phase2_final` joined to `phase2_researcher_runs` / `phase2_verifier_runs` / `phase2_adjudications`. Tedious but works.

**What to build when it happens.** A writer that fires on the escalation branches in `coordinate()`:
- Append one row to `data/human_queue/<batch_id>.csv` with: question_id, country_code, terminal_status, all Researcher attempts (concatenated), all Verifier counter-positions, Adjudicator reasoning if present, the suggested next action.
- A "Human queue" section on the Home page that reads the latest CSV and renders each pending case with the source URLs as clickable links.

Estimated ~50 lines plus the dashboard view. Easy once the column shape is decided, which requires actually seeing the first escalation to know what's useful.

**Why deferred.** No `escalated_*` row exists yet. The P1/FR coordinator pass landed on `accepted_by_adjudicator`. Build the first time the Adjudicator escalates or the first captcha appears.

---

## How to use this file

When a run produces unexpected behaviour, check the symptom list above first. If it matches, the fix path is documented. If it doesn't match, it's a real bug, not a known gap — open an issue / write a SPEC.md entry.

Update this file when:
- A known gap actually triggers and is implemented (move the entry to a "Resolved" section with the commit SHA).
- A new failure mode is anticipated during another audit.
- An item proves more or less critical than originally judged.
