"""Locked configuration for the WHO/Europe speech-writer PoC.

Every value here is a decision backed by the pre-registered research pass
(live IRIS probing + the extraction/retrieval literature). Grouped by build
layer so each module reads its own constants.

Constants are fixed methodological choices. The functions at the foot of the
file read environment variables instead, so the deployable package can be
repointed (model backend, index location, corpus breadth) in WHO's
environment without a code change.
"""
from __future__ import annotations

import os
from pathlib import Path

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


# --- Deployment knobs (environment-driven, not methodological constants) -----
# These let one container image run unchanged in WHO's environment. The model
# backend in particular is the seam that decouples the swarm from any single
# provider: "claude" routes through the local proxy used in development;
# "azure_openai" routes to a deployment in WHO's tenant.

def llm_backend() -> str:
    """The model backend the swarm calls: "claude" (default) or "azure_openai"."""
    return os.environ.get("WHO_LLM_BACKEND", "claude").strip().lower()


def azure_openai_settings() -> dict[str, str]:
    """Azure OpenAI connection settings, read from the environment.

    Validated only when the azure_openai backend is actually used; in
    development the keys are simply absent and the claude backend is used.
    """
    return {
        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        "api_key": os.environ.get("AZURE_OPENAI_API_KEY", ""),
        "deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }


# Durable index location. The PoC cached indexes under /tmp (ephemeral); a
# deployed service needs a path that survives a restart and can be mounted to
# a volume. Override with WHO_INDEX_ROOT (e.g. a mounted Azure file share).
_DEFAULT_INDEX_ROOT = Path.home() / ".who_speech" / "index"


def index_root() -> str:
    return os.environ.get("WHO_INDEX_ROOT", str(_DEFAULT_INDEX_ROOT))


def max_docs() -> int:
    """Documents indexed per country. The demo used 8; raise for real use."""
    return int(os.environ.get("WHO_MAX_DOCS", "25"))


def index_languages() -> list[str]:
    """ISO language codes to index. Default English; widen for native-language
    coverage once cross-lingual retrieval is validated."""
    raw = os.environ.get("WHO_INDEX_LANGUAGES", "en")
    return [x.strip() for x in raw.split(",") if x.strip()]


def numeric_guard() -> bool:
    """When on, drop a point that asserts a number/percentage/year absent from
    its quote (FM-06). Deterministic. Off by default until the ablation shows
    it helps."""
    return os.environ.get("WHO_NUMERIC_GUARD", "0").strip().lower() in ("1", "true", "yes", "on")


def context_check() -> bool:
    """When on, drop a point judged misleading given the surrounding passage
    (FM-02). Off by default until the ablation shows it helps."""
    return os.environ.get("WHO_CONTEXT_CHECK", "0").strip().lower() in ("1", "true", "yes", "on")


def verify_source() -> bool:
    """When on, re-verify every finalised quote against an independent
    extraction of the cited PDF and drop any that does not reproduce. On by
    default; set WHO_VERIFY_SOURCE=0 to disable (it adds a per-point PDF
    re-download). The defensibility guarantee is worth the latency."""
    return os.environ.get("WHO_VERIFY_SOURCE", "1").strip().lower() in ("1", "true", "yes", "on")
