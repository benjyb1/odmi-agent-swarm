# Quote verification log

Independent verification of every quote in the nine-point briefing pack
produced by the 2026-06-23 run of `run_all.py` (the run recorded in
HANDOVER.md). "Independent" means a mechanism outside the pipeline: either
IRIS's own full-text search index, or re-downloading the source PDF and
re-extracting it with pypdf (a different extractor from the pipeline's
Docling) and string-matching the quote under casefold + alphanumeric-only
normalisation, so line-break hyphenation and whitespace reflow cannot mask a
real match while different wording still fails.

Verification script: session scratchpad `verify_quotes.py` (method described
above); the five 2026-06-23 checks were performed in the session that
produced the pack.

## Status: 9 of 9 quotes independently confirmed real

| # | Point | Source (handle) | Cited page | Method | Date | Outcome |
|---|---|---|---|---|---|---|
| 1 | Ukraine MHPSS channels | 10665/382612 | p.2 | IRIS full-text search (rank 4) | 2026-06-23 | Confirmed. Quote is real, but the point was later rejected on attribution: the document describes the Red Cross response, not WHO's (see note) |
| 2 | Kazakhstan PHC support 2024 | 10665/384587 | p.15 | IRIS full-text search (rank 1) | 2026-06-23 | Confirmed |
| 3 | Kyrgyzstan case-based payment / UHC Partnership | 10665/380642 | p.10 | pypdf re-extraction, normalised string match | 2026-07-02 | Confirmed, found on PDF page 10 |
| 4 | Kyrgyzstan DRG within Manas reform programmes | 10665/380642 | p.16 | IRIS full-text search (rank 3) | 2026-06-23 | Confirmed |
| 5 | Kyrgyzstan OOP 40.7% of health spending (2021) | 10665/380268 | p.7 | pypdf re-extraction, normalised string match | 2026-07-02 | Confirmed, found on PDF page 7 |
| 6 | North Macedonia catastrophic spending 9% in 2024 (7% in 2018; poorest quintile 23% vs 16%) | 10665/384538 | p.14 | pypdf re-extraction, normalised string match | 2026-07-02 | Confirmed, found on PDF page 14 |
| 7 | North Macedonia catastrophic spending higher than many EU countries | 10665/384538 | p.5 | IRIS full-text search (rank 2) on 2026-06-23; repeated by pypdf re-extraction on 2026-07-02 to remove ambiguity about which of the two North Macedonia points was sampled | 2026-06-23 and 2026-07-02 | Confirmed, found on PDF page 5 |
| 8 | Tajikistan 1stop assistive products pilot | 10665/380686 | p.85 | pypdf re-extraction (IRIS search missed on the odd token "1stop") | 2026-06-23 | Confirmed: "1stop", "over 6000" and "4177" all present |
| 9 | Tajikistan in-country rehabilitation assessment | 10665/380686 | p.11 | pypdf re-extraction, normalised string match | 2026-07-02 | Confirmed, found on PDF page 11 |

All five pypdf checks on 2026-07-02 located the quote on exactly the page the
pipeline cited.

## Note on point 1 (Ukraine)

The quote is verbatim and the citation resolves to the right document, so it
passes quote verification. It fails the attribution check added on
2026-07-02: the source document is "Mental health support during crises:
lessons from the Red Cross response to the conflict in Ukraine", so the actor
behind the MHPSS activities is the Red Cross, not WHO. The verifier now
rejects it (attributed=false, relevant=false) and a re-run of the Ukraine
query no longer produces it. Quote verification and attribution are separate
gates; this point is the case that motivated the second gate.
