"""Hybrid retrieval over the LanceDB index: dense + BM25, RRF-fused, then a
cross-encoder rerank, with an abstention floor.

This is the local replacement for the ODMI swarm's web-search wrapper. It
returns provenance-bearing passages (text, parent context for the LLM, page,
citation, IRIS URL) so the downstream researcher quotes and the verifier can
gate the quote back to source. The query profile (exact entity + year + fuzzy
topic) is why retrieval is hybrid rather than dense-only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from who_speech import config


@dataclass
class Passage:
    text: str
    parent_text: str
    citation: str
    iris_url: str
    page_start: int
    page_end: int
    rights: str
    score: float


def _rrf_fuse(rankings: list[list[dict]], key: str = "id", k: int = config.RRF_K) -> list[dict]:
    """Reciprocal-rank fusion across independent result lists."""
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking):
            rid = row[key]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (rank + 1 + k)
            rows.setdefault(rid, row)
    ordered = sorted(scores, key=lambda r: scores[r], reverse=True)
    return [rows[r] for r in ordered]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class Retriever:
    """Loads the index, the embedder and the reranker; serves passages."""

    def __init__(self, db_path: str, table_name: str = "passages", model=None, reranker=None):
        import lancedb
        from sentence_transformers import CrossEncoder, SentenceTransformer

        self.model = model or SentenceTransformer(config.EMBED_MODEL)
        try:
            self.model.max_seq_length = min(
                getattr(self.model, "max_seq_length", 512) or 512, 512
            )
        except Exception:
            pass
        self.reranker = reranker or CrossEncoder(config.RERANK_MODEL, max_length=512)
        self.table = lancedb.connect(db_path).open_table(table_name)

    def retrieve(self, query: str, k: int = config.PASS_TO_LLM) -> list[Passage]:
        qv = self.model.encode(query, normalize_embeddings=True).tolist()

        vec_hits = self.table.search(qv).limit(config.RETRIEVE_CANDIDATES).to_list()
        try:
            fts_hits = (
                self.table.search(query, query_type="fts")
                .limit(config.RETRIEVE_CANDIDATES)
                .to_list()
            )
        except Exception:
            fts_hits = []  # FTS index missing or query unparseable; dense-only fallback

        fused = _rrf_fuse([vec_hits, fts_hits])[: config.RERANK_KEEP]
        if not fused:
            return []

        pair_scores = self.reranker.predict([(query, c["text"]) for c in fused])
        for cand, raw in zip(fused, pair_scores):
            cand["_score"] = _sigmoid(float(raw))
        fused.sort(key=lambda c: c["_score"], reverse=True)

        kept = [c for c in fused if c["_score"] >= config.ABSTAIN_SCORE_FLOOR][:k]
        return [_to_passage(c) for c in kept]


def _to_passage(row: dict) -> Passage:
    from who_speech.models import IrisItem

    cite = IrisItem(
        uuid=row["doc_uuid"],
        title=row["title"],
        year=row["year"] or None,
        rights=row["rights"],
    ).citation()
    return Passage(
        text=row["text"],
        parent_text=row.get("parent_text", ""),
        citation=cite,
        iris_url=row.get("iris_url", ""),
        page_start=row.get("page_start", 0),
        page_end=row.get("page_end", 0),
        rights=row.get("rights", ""),
        score=row["_score"],
    )
