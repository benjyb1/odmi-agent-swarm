"""Shared on-disk cache for search-adjudication verdicts.

Both expensive judge harnesses (``evaluation/diy_vs_tavily.py`` and
``evaluation/provider_ab.py``) run the Opus adjudicator twice per arm-pair and
again for every robustness re-judge. A full ``provider_ab`` run is on the order
of a thousand Opus calls. Before this cache the verdicts were only written to
the JSONL at the very end, so a machine restart mid-run lost the lot and the
re-run paid for every judgement again.

This module caches the adjudication VERDICT keyed on everything the verdict
depends on, mirroring the evidence cache (``.cache_diy_vs_tavily.json``) that
already protects the search side. A re-run replays already-judged orientations
for free and resumes nearly free.

The cache is written to disk after every miss, so a crash keeps every verdict
judged up to that point. The cache is transparent: a hit reconstructs an
identical ``AdjudicationResult``, so verdicts, the JSONL schema, and every
downstream statistic are unchanged.

Key: a deterministic SHA-256 over a canonical JSON of ``question_text``,
``ground_truth``, the ordered ``(url, snippet)`` of ``evidence_a`` and of
``evidence_b``, ``model``, and ``answer_blind``. These are exactly the inputs
the adjudicator renders into its prompt (the renderer reduces each URL to its
registrable domain and shows only the snippet; title and score are dropped), so
re-fetched evidence with jittered scores still hits. Each position-swapped
orientation and each ``answer_blind`` value is a distinct key, which is correct:
they are distinct judgements.

Value: the ``AdjudicationResult`` fields (winner, answer_supported_by_a,
answer_supported_by_b, reasoning, confidence), enough to reconstruct the verdict
without an LLM call.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from agents.models import LLMUsage
from agents.tools.search_adjudicator import AdjudicationResult, adjudicate

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "evaluation" / ".cache_adjudications.json"

# Process-level in-memory mirror of the disk cache. ``None`` means "not loaded
# yet"; the first access lazily loads it from CACHE_PATH. Kept module-level so
# every caller in a run shares one dict and the file is read once.
_CACHE: Optional[dict] = None


def _evidence_fingerprint(evidence: List[dict]) -> List[List[str]]:
    """Ordered ``[url, snippet]`` pairs, the only evidence the verdict sees.

    The adjudicator renders each passage as its registrable domain (derived from
    the URL) plus the snippet, and drops title and score. Keying on url+snippet
    alone therefore matches exactly what drives the verdict, so re-fetched
    evidence whose title or score jittered still hits the cache. Order is
    preserved because the renderer numbers passages in order.
    """
    out: List[List[str]] = []
    for p in evidence or []:
        out.append([str(p.get("url") or ""), str(p.get("snippet") or "")])
    return out


def _make_key(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
    model: str,
    answer_blind: bool,
) -> str:
    """Deterministic SHA-256 of the canonical judgement inputs.

    ``sort_keys`` and a fixed separator make the JSON canonical, so the same
    inputs always hash to the same hex digest regardless of dict insertion
    order. ``ensure_ascii`` keeps the bytes stable across platforms.
    """
    payload = {
        "question_text": question_text,
        "ground_truth": ground_truth,
        "evidence_a": _evidence_fingerprint(evidence_a),
        "evidence_b": _evidence_fingerprint(evidence_b),
        "model": model,
        "answer_blind": bool(answer_blind),
    }
    blob = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load() -> dict:
    """Return the in-memory cache, loading it from disk on first use.

    A malformed or absent file yields an empty cache rather than crashing the
    run: a corrupt cache must never block a fresh judgement.
    """
    global _CACHE
    if _CACHE is None:
        if CACHE_PATH.exists():
            try:
                _CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _CACHE = {}
        else:
            _CACHE = {}
    return _CACHE


def _save(cache: dict) -> None:
    """Persist the cache to disk (called after every miss)."""
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False), encoding="utf-8",
    )


def _to_result(stored: dict) -> AdjudicationResult:
    """Reconstruct an ``AdjudicationResult`` from a stored cache value."""
    return AdjudicationResult(**stored)


def _from_result(result: AdjudicationResult) -> dict:
    """Serialise an ``AdjudicationResult`` to the stored cache value."""
    return result.model_dump()


def _hit_usage(model: str) -> LLMUsage:
    """A zero-cost usage stamp for a cache hit (no LLM call was made).

    The harnesses discard the usage element (``verdict, _ = judge_fn(...)``), so
    this is only for call-shape parity. It is flagged as a cache hit and carries
    no cost, so it can never inflate a cost receipt.
    """
    return LLMUsage(
        input_tokens=0,
        output_tokens=0,
        wall_clock_ms=0,
        estimated_cost_usd=0.0,
        model_version=model,
        condition_label="search_adjudication_cache_hit",
    )


def cached_adjudicate(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
    model: str,
    answer_blind: bool = False,
    adjudicate_fn: Callable[..., Tuple[AdjudicationResult, LLMUsage]] = adjudicate,
    **kwargs,
) -> Tuple[AdjudicationResult, LLMUsage]:
    """Cache-transparent wrapper around an adjudicate call.

    On a cache HIT the stored verdict is reconstructed and returned with NO LLM
    call. On a MISS ``adjudicate_fn`` is invoked, the verdict is stored, the
    cache is written to disk, and the verdict is returned. The disk write on
    every miss is what makes a crashed run resumable: everything judged so far
    survives.

    Returns the same ``(AdjudicationResult, LLMUsage)`` tuple shape as
    ``adjudicate`` so existing call sites (which unpack ``verdict, _ = ...``) are
    unchanged. On a hit the usage is a zero-cost cache-hit stamp.

    ``adjudicate_fn`` defaults to the Opus ``adjudicate`` but lets the same
    wrapper serve the Gemini / Groq cross-family judges later; ``model`` is part
    of the key, so different judges never collide. ``answer_blind`` and the A/B
    position are each part of the key, so the harnesses' answer-blind and
    position-swap behaviour is preserved exactly.

    Extra keyword arguments (e.g. ``subtrio_id``) are forwarded to
    ``adjudicate_fn`` on a miss but are NOT part of the cache key: they do not
    change the verdict, only the receipt row the underlying call writes.
    """
    cache = _load()
    key = _make_key(
        question_text=question_text,
        ground_truth=ground_truth,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        model=model,
        answer_blind=answer_blind,
    )
    stored = cache.get(key)
    if stored is not None:
        return _to_result(stored), _hit_usage(model)

    result, usage = adjudicate_fn(
        question_text=question_text,
        ground_truth=ground_truth,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        model=model,
        answer_blind=answer_blind,
        **kwargs,
    )
    cache[key] = _from_result(result)
    _save(cache)
    return result, usage
