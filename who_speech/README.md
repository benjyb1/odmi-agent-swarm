# who_speech — WHO/Europe speech-writer PoC

A parallel application of the ODMI agent-swarm architecture to a new domain:
producing defensible, sourced speaking points for the WHO Regional Office for
Europe (EURO) from its published record in the IRIS repository. Built for a
proof-of-concept requested by a EURO contact.

The intellectual core (researcher / verifier / adjudicator with honest
abstention and a quote-level provenance gate) is reused from `agents/`. This
package is the new backend that feeds it. It has no dependency on the ODMI
code and is self-contained, so it can be lifted into its own repo later.

## Pipeline (coarse-to-fine funnel)

```
IRIS EURO subtree  ->  Docling extraction  ->  provenance chunking
   (iris.py)            (extract.py)            (index.py)
        ->  LanceDB hybrid retrieval  ->  [researcher/verifier/adjudicator]
            (search.py)                   (not built yet — forks agents/)
        ->  briefing pack of verbatim, cited, licence-cleared points
```

## Status

| Layer | File | State |
|---|---|---|
| IRIS client (Stage 0) | `iris.py` | Built, verified live (Kyrgyzstan 168/51 counts, licence read, PDF download) |
| Docling extraction + provenance | `extract.py` | Built, verified live (page/bbox/charspan, deterministic hash, OCR gate) |
| Chunking + LanceDB index | `index.py` | Built; end-to-end run via `demo.py` |
| Hybrid retrieval + rerank + abstain | `search.py` | Built; end-to-end run via `demo.py` |
| Agent swarm (researcher/verifier/adjudicator) | — | Not started; forks `agents/` |
| Coordinator + briefing-pack assembly | — | Not started |
| Faithfulness eval harness | — | Not started |

## Run

Dependencies beyond the ODMI project (`httpx` is already present) are pulled
ephemerally and are **not** added to the MSc `pyproject.toml`:

```bash
# Stage 0 only (no heavy deps):
uv run python -m who_speech.iris

# Extraction (Docling, CPU):
uv run --with docling python -m who_speech.extract [optional.pdf]

# Full backend end-to-end (downloads BGE-M3 + reranker, ~5 GB first run):
uv run --with docling --with lancedb --with sentence-transformers \
    python -m who_speech.demo
```

## Decisions baked in (see `config.py`)

- **Corpus = the EURO subtree of IRIS** (~23k items), pre-indexed (eager).
- **Country = MeSH heading**, the precise field. Some headings differ from the
  common name (`Republic of North Macedonia`, `Georgia (Republic)`).
- **Anchor document classes**: Country Cooperation Strategy (forward
  priorities) + WHO Country Office annual reports (delivered activity) + HiT
  health-system reviews (context). The BCA is not in IRIS.
- **Extraction**: Docling, `do_ocr=False` (born-digital corpus; also avoids a
  RapidOCR crash), per-page char gate for the scanned tail, deterministic
  serialisation hashed for the quote-gate.
- **Retrieval**: BGE-M3 (MIT) dense + BM25, RRF (k=60), BGE-reranker-v2-m3
  (Apache-2.0), top-5 to the LLM, abstain below the reranker floor.

## Licensing and politeness (load-bearing)

- Quote only from CC-licensed items (`IrisItem.quotable`); items with no
  `dc.rights` are indexable but never quoted. **Verbatim quotes only** (reworded
  points risk being adaptations -> ShareAlike + disclaimers).
- Attribute in WHO format (`IrisItem.citation()`).
- Polite, bounded, per-item fetch (`IRIS_REQUEST_DELAY_S`). Corpus-scale
  harvesting needs WHO sign-off; do not crawl the whole repository.
