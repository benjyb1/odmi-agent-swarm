# EXP-36 post-run leakage audit (FM-14 fingerprint + deny-list scan)

Run 2026-07-16 against the frozen headline data
(`exp36-run/data/odmi.db`, `exp36_frozen_headline`, 1,144 pairs).
`scripts/check_data_leakage.py` exits 1 (83 violations DB-wide), so the
raw exit is not clean. This note scopes what that means for the headline.

## The load-bearing finding: committed evidence is clean

Of the 83 DB-wide violations, **7 touch EXP-36**, and every one is a
`verifier.counter_source_url` (the Verifier's adversarial counter-search
channel). Direct re-scan of the committed trail with `is_blocked()`:

- committed pairs (736) with a blocked `final_source_url`: **0**
- committed pairs with a blocked researcher `source_url`: **0**

So no committed EXP-36 answer rests on, or was retrieved from, a
deny-listed ODMI source. The accuracy aggregate is computed on
`final_answer` against ground truth over committed pairs whose sources are
leak-free. **The headline stands.**

## The 7 verifier-counter hits, classified

| terminal status | n | committed? | leak direction |
|---|---|---|---|
| abstained_adjudicator | 6 | no | none committed |
| accepted_by_adjudicator (BG, `yes`) | 1 | yes | counter-evidence |

All 7 are the Verifier fetching an ODMI mirror
(`europeandataportal.eu`, `data.europa.eu`) while searching to *disprove*
the Researcher. The single committed case (a BG `yes`) used the mirror as
counter-evidence: it argued against the commit and lost, so the answer
committed on the Researcher's clean evidence. A leak in the counter-search
channel can only bias toward abstention or rejection, never toward
spuriously matching the answer key, so it cannot have inflated a match.
The pair is kept and disclosed, not voided.

## The underlying gap (systematic, pre-existing, not EXP-36-specific)

The same channel is flagged across the DB: 27 hits under
`exp28_arch_ablation`, 13 under `exp19`, and so on. The Verifier's
counter-search does not scrub `BLOCKED_DOMAINS` at fetch the way the
Researcher's search path does (D24 layer 2 covers the Researcher; the
Verifier's independent counter-search reaches `counter_source_url`
without the same guard). This is a real deny-list gap, logged as a
follow-on fix. It does not invalidate any committed-answer accuracy number
because committed sources are separately clean, but it should be closed
before the Verifier counter-search is ever relied on as a positive
evidence channel (it is not today; D45 has it flowing advisory
counter-evidence to the Adjudicator).

## Disposition

- Headline: valid, reported as-is. FM-14 committed-evidence audit: clean.
- Limitation paragraph: discloses the 7 counter-search hits, the 1
  committed BG pair, and the conservative-direction argument.
- Follow-on: close the Verifier counter-search deny-list gap
  (`agents/tools/search.py` / `agents/verifier.py` counter-search path),
  then a fresh audit should show 0 EXP-36 verifier hits. Tracked
  separately; not a headline blocker.
