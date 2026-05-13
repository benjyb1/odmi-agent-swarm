# Hand-Marking Protocol

> **Superseded by D22 on 2026-05-13.** ODMI's `merged_responses`
> sheet ships per-country answers for all 5,148 (question, country)
> pairs. Evaluation now compares the swarm's `final_answer` against
> that ground truth directly. The custom three-dimension rubric and
> the hand-marking workflow described below are retained as historical
> record only. The two existing France hand-marks (P1, PT4) remain in
> the `hand_marks` SQLite table as inert audit-trail history. No new
> hand-marks are needed.
>
> See `docs/METHODOLOGY.md` Section 6 for the live evaluation
> methodology.

---

## Original protocol (historical record)

How to score a (question, country) pair against the answerability rubric so
that another evaluator could reproduce the result. This protocol was locked.

Version 1, dated 2026-05-11.

---

## When to mark

Hand-marking happens before any swarm run on the same (question, country)
pair. Per D9 in SPEC.md, a hand-mark is locked only when it has been
committed to git. Uncommitted marks are not eligible to be used as
stratification ground truth.

## Inputs you may use

- The question text from `data/questions/odmi_2025_questions.json`.
- The 2024 official answer for the country, where available (e.g. the
  France 2024 column in `data/questions/2025_odm_questionnaire_france.xlsx`).
  This is for context. It is not a substitute for performing the search.
- Ordinary web search through a normal browser. Google, Bing, DuckDuckGo,
  the national portal directly. Whatever a human evaluator would use.

## Inputs you may not use

- LLM-assisted reasoning, including ChatGPT, Claude, Gemini, or any agentic
  search tool, at any stage of scoring.
- The classifier code (`agents/classifier.py`) or any of its prompts. The
  classifier is reserved for a possible post-hoc experiment, not for marking.

The rule is strict because the hand-marks are the methodological reference
point against which the swarm is judged. Any LLM contamination here weakens
the evaluation.

## Procedure

For each (question, country) pair:

1. Open the question. Read it carefully. If the question has a multi-part
   structure (e.g. P10-a, P10-b), each sub-part is a separate hand-mark row.
2. Spend at most 10 minutes attempting to find the evidence by hand. Record:
   - The search queries you used.
   - The sources you found, with URLs.
   - Whether you successfully reached a defensible answer.
3. Score each dimension on the 0-3 scale defined in `docs/METHODOLOGY.md`,
   with a one-sentence justification per dimension. Be specific. "Found on
   data.gouv.fr's sparql endpoint" is acceptable; "easy" is not.
4. Compute the composite (sum of three scores) and read the tier off the
   table in METHODOLOGY.md.
5. Append a row to `data/hand_marks/<country>_handmarks.csv` (one file per
   country). Use the schema in the next section.
6. Commit the file. The commit message should reference the question IDs
   being added: `hand-marks: France P1, P7, PT4 — Phase A pilot`.
7. Optional but encouraged: log a short note in Notion's Country
   Observations page if the marking revealed anything notable about the
   portal or the question's phrasing.

## CSV schema

One row per (question_id, country) pair. Columns:

| Column | Type | Meaning |
|---|---|---|
| `question_id` | text | Matches the IDs in `odmi_2025_questions.json`. e.g. `P1`, `PT4`, `Q15`, `I3`. |
| `country` | text | ISO 3166-1 alpha-2. `FR`, `DE`, `NL`, `RO`, `HU`, `EE`. |
| `evidence_score` | int 0-3 | EA dimension score. |
| `evidence_justification` | text | One sentence. Includes URL if applicable. |
| `determinism_score` | int 0-3 | AD dimension score. |
| `determinism_justification` | text | One sentence. |
| `complexity_score` | int 0-3 | SC dimension score. |
| `complexity_justification` | text | One sentence. |
| `composite_score` | int 0-9 | Sum of the three above. |
| `tier` | text | One of `Highly Likely`, `Likely`, `Unlikely`, `Very Unlikely`. |
| `search_queries` | text | The literal search queries used, pipe-separated. |
| `sources_found` | text | URLs, pipe-separated. |
| `answer_obtained` | text | A short note on the answer you actually reached, or "not reached". |
| `marker` | text | Initials of the person who marked. `BB` for Benjy. |
| `marked_at` | ISO 8601 datetime | Local time of marking. |
| `notes` | text | Optional. Anything an examiner should know. |

Quote any field that contains commas, newlines, or quote characters per RFC
4180. UTF-8 throughout.

## Mirroring to SQLite

Once a hand-mark CSV has been committed, run
`uv run python scripts/sync_hand_marks.py <csv-path>`
(to be written) to insert the rows into the `hand_marks` SQLite table along
with the commit SHA in `locked_by_commit`. The SQLite mirror is the source
of truth for joins against swarm runs; the CSV is the human-editable
workspace.

## Re-marking

If a hand-mark turns out to be wrong on review, do not edit the original row.
Add a new row for the same (question_id, country) with `marked_at` updated.
Mark the previous row as superseded by adding `superseded_by` to the notes
field. The audit trail must remain complete.

## Existing partial marks (carryover)

Two France marks exist from the April 2026 pilot:

- `P1`, composite 9, Highly Likely.
- `PT4`, composite 9, Highly Likely.

These were captured in the Word document `data/ODMI_2025_Questions.docx`.
They must be migrated to this CSV format with the same scores, the same
justifications, the original `marked_at` (use 2026-04-01 if not recorded
more precisely), and a note that they were carried over from the Word
template. They are then re-locked on the next commit.
