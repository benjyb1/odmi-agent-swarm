"""Locked configuration for the WHO/Europe speech-writer PoC.

Every value here is a decision backed by the pre-registered research pass
(live IRIS probing + the extraction/retrieval literature). Grouped by build
layer so each module reads its own constants.
"""
from __future__ import annotations

# --- IRIS (WHO Institutional Repository, DSpace 7.6) -------------------------
IRIS_API = "https://iris.who.int/server/api"
IRIS_SEARCH = f"{IRIS_API}/discover/search/objects"
IRIS_FACETS = f"{IRIS_API}/discover/facets"
IRIS_ITEM = f"{IRIS_API}/core/items"
IRIS_BUNDLES = f"{IRIS_API}/core/bundles"
IRIS_BITSTREAM_CONTENT = f"{IRIS_API}/core/bitstreams/{{uuid}}/content"
IRIS_HANDLE_URL = "https://iris.who.int/handle/{handle}"

# WHO Regional Office for Europe community (handle 10665/107131). Scope every
# query to this subtree: ~23k items, the only corpus the EURO tool needs.
EURO_SCOPE = "fb66a624-a5dc-4576-8b6b-929639e552d8"

# DSpace silently truncates page sizes above 100 (it echoes the requested size
# but returns only 100 objects). Never request more; page with offset instead.
IRIS_PAGE_SIZE = 100

# Politeness. IRIS robots.txt sets Crawl-delay: 10 on the discovery/search
# endpoints and allows /core/bitstreams. This delay covers a one-off, bounded
# PoC slice (one country, a few hundred items). Anything corpus-scale needs
# WHO's written sign-off and ideally a data dump, not crawling (licensing
# finding). Keep this conservative.
IRIS_REQUEST_DELAY_S = 1.5
IRIS_USER_AGENT = (
    "kcl-msc-who-euro-speechwriter-poc/0.1 (research; benjaminbream@gmail.com)"
)

# --- Licence gate ------------------------------------------------------------
# Only quote from items carrying a permissive Creative Commons IGO licence.
# Items with no dc.rights are treated as all-rights-reserved: indexable for
# internal retrieval, but never quoted or redisplayed. Verbatim quotation
# only (reworded points could count as adaptations -> ShareAlike + disclaimer).
QUOTABLE_LICENCE_MARKERS = ("CC BY",)  # case-insensitive substring test

# --- Extraction (Docling) ----------------------------------------------------
# do_ocr=False is both correct for a born-digital corpus AND sidesteps the
# RapidOCR PP-OCRv6 init crash in docling 2.105. Pin docling + model weights
# at build time; output is byte-deterministic under a fixed toolchain, which
# is what the quote-provenance hash gate relies on.
DOCLING_DO_OCR = False
DOCLING_DO_TABLE_STRUCTURE = True
# Below this many extractable characters on a page, treat it as image-only and
# route it to OCR (Docling has no reliable per-page auto-toggle).
OCR_CHAR_PER_PAGE_THRESHOLD = 100

# --- Chunking (provenance-preserving, retrieve-coarse / cite-fine) -----------
CHILD_CHUNK_TOKENS = 256        # the embedded + quoted unit
CHILD_CHUNK_MAX_TOKENS = 512
CHILD_CHUNK_OVERLAP = 32
PARENT_CHUNK_TOKENS = 1024      # context handed to the LLM on a hit

# --- Retrieval ---------------------------------------------------------------
EMBED_MODEL = "BAAI/bge-m3"               # MIT, multilingual, dense+sparse+colbert
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"  # Apache-2.0, cross-encoder
RRF_K = 60
RETRIEVE_CANDIDATES = 100   # dense top-100 + BM25 top-100 -> RRF
RERANK_KEEP = 100           # rerank the fused pool
PASS_TO_LLM = 5             # final passages to the researcher (max 8)
# Below this reranker probability, abstain rather than quote a weak passage.
ABSTAIN_SCORE_FLOOR = 0.5
