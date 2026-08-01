"""Tests for the shared on-disk adjudication cache.

The expensive harnesses (evaluation/diy_vs_tavily.py, evaluation/provider_ab.py)
make ~1080 Opus adjudication calls per run. A crash used to lose all of them
because verdicts were only written at the end. cached_adjudicate stores every
verdict to disk on the miss that produced it, so a re-run replays already-judged
pairs for free and resumes nearly free.

These tests mock the adjudicator: no live LLM calls. They check that a miss
calls the adjudicate function exactly once and stores the verdict, an identical
second call is a hit that does not call it again and returns an equal verdict,
and that answer_blind / evidence changes are distinct keys (miss).
"""
from __future__ import annotations

import json

import pytest

from agents.models import LLMUsage
from agents.tools.search_adjudicator import AdjudicationResult
from evaluation import adjudication_cache as ac


# helpers

def _result(winner: str = "A", reasoning: str = "A is on point") -> AdjudicationResult:
    return AdjudicationResult(
        winner=winner,
        answer_supported_by_a="yes",
        answer_supported_by_b="insufficient evidence",
        reasoning=reasoning,
        confidence=0.8,
    )


def _usage() -> LLMUsage:
    return LLMUsage(
        input_tokens=10, output_tokens=5, wall_clock_ms=1, model_version="x",
    )


class _CountingJudge:
    """A stand-in adjudicate_fn that records its calls and never hits a network."""

    def __init__(self, result: AdjudicationResult | None = None):
        self.calls: list[dict] = []
        self._result = result or _result()

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._result, _usage()


_EV_A = [{"url": "https://a.example/1", "snippet": "alpha", "title": "t", "score": 0.9}]
_EV_B = [{"url": "https://b.example/1", "snippet": "beta", "title": "u", "score": 0.1}]


@pytest.fixture()
def cache_path(tmp_path, monkeypatch):
    """Point the module-level cache at a temp file and reset the in-memory cache."""
    path = tmp_path / "cache_adjudications.json"
    monkeypatch.setattr(ac, "CACHE_PATH", path)
    monkeypatch.setattr(ac, "_CACHE", None)  # force a fresh load from the temp path
    return path


# miss then hit

def test_miss_calls_judge_once_and_stores(cache_path):
    judge = _CountingJudge()
    out, usage = ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 1                     # the miss called through
    assert isinstance(out, AdjudicationResult)
    assert out.winner == "A"
    assert isinstance(usage, LLMUsage)
    assert cache_path.exists()                        # persisted after the miss


def test_identical_second_call_is_a_hit_no_second_judge_call(cache_path):
    judge = _CountingJudge()
    first, _ = ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    second, _ = ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 1                      # NO second adjudicate call
    assert second == first                            # reconstructed verdict is equal
    assert isinstance(second, AdjudicationResult)


def test_hit_survives_a_fresh_in_memory_cache_reload(cache_path, monkeypatch):
    """A crash drops the in-memory cache; the disk copy must still serve the hit."""
    judge = _CountingJudge()
    first, _ = ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    # Simulate process restart: clear the in-memory cache, keep the file.
    monkeypatch.setattr(ac, "_CACHE", None)
    second, _ = ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 1                      # served from disk, no new call
    assert second == first


# distinct keys => miss

def test_answer_blind_is_a_distinct_key(cache_path):
    judge = _CountingJudge()
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=True,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 2                       # different answer_blind -> miss


def test_different_evidence_is_a_distinct_key(cache_path):
    judge = _CountingJudge()
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    other_b = [{"url": "https://c.example/9", "snippet": "gamma"}]
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=other_b, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 2                       # different evidence_b -> miss


def test_swapped_positions_are_a_distinct_key(cache_path):
    """Position swap is the harness's bias control; A/B order must change the key."""
    judge = _CountingJudge()
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_B, evidence_b=_EV_A, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 2                       # swapped orientation -> miss


def test_different_model_is_a_distinct_key(cache_path):
    """The cross-family judges reuse the wrapper; model must change the key."""
    judge = _CountingJudge()
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="opus", answer_blind=False,
        adjudicate_fn=judge,
    )
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="gemini", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 2                       # different model -> miss


# key construction

def test_key_ignores_non_url_snippet_evidence_fields(cache_path):
    """The verdict depends only on (url, snippet) per arm (plus the rendered
    domain, which is derived from url). Extra fields like title/score must not
    change the key, so re-fetched evidence with jittered scores still hits."""
    judge = _CountingJudge()
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    # Same url+snippet, different title/score, no title key at all on B.
    ev_a2 = [{"url": "https://a.example/1", "snippet": "alpha", "score": 0.01}]
    ev_b2 = [{"url": "https://b.example/1", "snippet": "beta"}]
    ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=ev_a2, evidence_b=ev_b2, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    assert len(judge.calls) == 1                        # still a hit


def test_make_key_is_deterministic_sha256(cache_path):
    k1 = ac._make_key(
        question_text="Q", ground_truth="g", evidence_a=_EV_A,
        evidence_b=_EV_B, model="m", answer_blind=False,
    )
    k2 = ac._make_key(
        question_text="Q", ground_truth="g", evidence_a=_EV_A,
        evidence_b=_EV_B, model="m", answer_blind=False,
    )
    assert k1 == k2
    assert isinstance(k1, str) and len(k1) == 64       # hex SHA-256


def test_stored_value_round_trips_through_json(cache_path):
    """A hit served from a freshly reloaded JSON file reconstructs every field."""
    judge = _CountingJudge(_result(winner="tie", reasoning="both adequate"))
    first, _ = ac.cached_adjudicate(
        question_text="Q", ground_truth="ANSWER: yes",
        evidence_a=_EV_A, evidence_b=_EV_B, model="m", answer_blind=False,
        adjudicate_fn=judge,
    )
    # Read the raw file: it must be JSON and hold the verdict fields.
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(raw) == 1
    (stored,) = raw.values()
    assert stored["winner"] == "tie"
    assert stored["reasoning"] == "both adequate"
    assert stored["confidence"] == 0.8
