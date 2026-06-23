# Handover

A self-contained prompt for a fresh agent (or new session) picking up this
project cold, with no prior conversation. Paste it in, or read it yourself.

---

You are taking over the WHO/Europe speech-writer project. This brief is
self-contained. Read `who_speech/README.md` and the project memory note first,
then continue from "Next steps".

## The project
A proof-of-concept for a contact at the WHO Regional Office for Europe (EURO):
an agent that produces fast, defensible, sourced speaking points about what WHO
has done with a given country, for reporting to countries and stakeholders. It
is a parallel side project to the ODMI MSc dissertation in this repo and
deliberately reuses that swarm's architecture (researcher / verifier /
adjudicator, honest abstention, quote-level provenance). It does not touch the
ODMI code. It lives in the `who_speech/` package and reuses
`agents.tools.llm.call_for_structured` for LLM calls and receipts.

## Pipeline
IRIS (EURO subtree) -> Docling extraction with page/char provenance -> LanceDB
hybrid retrieval -> planner -> researcher (drafts a verbatim quote) ->
deterministic quote-gate -> verifier -> adjudicator -> briefing pack of
verbatim, cited, licence-cleared points.

Modules: `iris.py` (DSpace REST client + CC-licence gate), `extract.py`
(Docling, do_ocr=False, provenance + content hash), `index.py` (provenance
chunking + LanceDB/BGE-M3 build), `search.py` (dense+BM25+RRF+reranker,
abstention floor), `prompts.py` + `swarm.py` (the agents, `orchestrate()`,
`quote_in_passage()` the gate, `QUERIES` the five demo queries), `demo.py` (one
query), `run_all.py` (all five; indexes cached at /tmp/who_idx).

## Locked decisions (do not relitigate; see config.py)
- Corpus = EURO subtree of IRIS (scope fb66a624-a5dc-4576-8b6b-929639e552d8,
  ~23k items).
- Country = MeSH heading (f.mesh=<heading>,equals), not free text. Watch
  non-obvious headings: "Republic of North Macedonia", "Georgia (Republic)";
  Belarus is split across two headings.
- Quote verbatim only; quote only CC-licensed items (IrisItem.quotable);
  no-licence items are indexable but not quotable. Licence plus the quote-gate
  are the defensibility spine.
- Extraction: Docling do_ocr=False (born-digital corpus; also avoids a RapidOCR
  init crash), deterministic under pinned versions.
- Retrieval: BGE-M3 (MIT) + BM25 + RRF k=60 + BGE-reranker-v2-m3, top-5, abstain
  below reranker probability 0.5.
- Anchor doc classes: Country Cooperation Strategy + WHO Country Office annual
  reports + HiT reviews. The BCA is not deposited in IRIS.
- Bulk-harvesting IRIS needs WHO sign-off (robots.txt Crawl-delay 10 plus
  licensing). The PoC fetches bounded, polite, per-item slices only.

## Current state
All five demo queries (Ukraine, Kazakhstan, Kyrgyzstan, North Macedonia,
Tajikistan) run end to end. The last run produced 9 verified points from 30
attempted sub-topics; the verifier and quote-gate rejected the rest. Five
sampled quotes were independently confirmed real (four via IRIS's own full-text
search, one by re-extracting the PDF with pypdf). Tajikistan, Kyrgyzstan and
North Macedonia gave strong, specific, on-target points. Two issues stand:
- Ukraine: the single surviving point cites "lessons from the Red Cross response
  to the conflict in Ukraine", faithful to its quote but describing the Red
  Cross's action, not WHO's. Drop or reframe.
- Design gap: the verifier checks faithfulness (quote supports point) but not
  relevance/attribution (is the actor WHO; does the point answer the query). The
  Ukraine point passed for that reason.

## Gotchas (these will bite you)
- Worktree env: this is a git worktree; the gitignored .env (API keys, including
  the proxy's ANTHROPIC_API_KEY/ANTHROPIC_BASE_URL) was copied from
  /Users/benjyb/Desktop/MscProject/.env. A fresh worktree will not have it; copy
  it in.
- LLM proxy: swarm calls route through CLIProxyAPI on localhost:8317 (a local
  service). If it is down, every call fails. Smoke test:
  `uv run python -c "from who_speech.swarm import plan_research, QUERIES; print(plan_research(QUERIES['kyrgyzstan_financing']))"`
- Heavy deps are not in pyproject.toml; run with
  `uv run --with docling --with lancedb --with sentence-transformers ...`.
  iris.py needs only httpx (already a project dep).
- Apple Silicon MPS: keep the embedder at max_seq_length=512, small batch, and
  hard-cap chunk size, or it OOMs.
- LanceDB list_tables() returns a paginated object, not a list; probe existence
  with open_table.
- IRIS drops connections intermittently; iris._get/download already retry
  transport errors. /tmp caches (indexes, PDFs) are ephemeral.

## Run commands
- Stage 0 (no heavy deps): `uv run python -m who_speech.iris`
- One query: `uv run --with docling --with lancedb --with sentence-transformers python -m who_speech.swarm kyrgyzstan_financing`
- All five: `uv run --with docling --with lancedb --with sentence-transformers python -m who_speech.run_all`

## Next steps (pick up here)
1. (Recommended) Add a relevance/attribution check to the verifier or planner:
   confirm the point's actor is WHO and that it answers the query, not just that
   the quote supports it. Re-run Ukraine.
2. Verify all nine points (only five were sampled) before anything reaches the
   WHO contact.
3. Decide the Ukraine point (drop or reframe) and, if Ukraine stays a demo
   country, build a deeper index than the 8-document English slice.
4. Not yet built: the faithfulness evaluation harness (atomic-claim, three-way
   supported/contradicted/not-addressed, quote-anchored, plus a cross-family
   Mistral check) and a briefing-pack UI.

Follow CLAUDE.md: UK English, no em dashes, worktree isolation for file changes,
commit small and often.
