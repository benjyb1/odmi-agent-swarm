"""Unit tests for the EXP-17 DIY snippet-funnel knobs.

Three lossy points in the DIY retrieval funnel are exposed as additive,
flag-gated knobs:

  --snippet-picker on|off  (bypass the LLM picker, default on)
  --max-snippet-chars N    (per-snippet prompt truncation, default 600)
  --picker-max-chunks N    (chunks kept per non-confident page, default 3)
  --page-text-cap N        (page text the picker sees, default 16000)

These tests prove the defaults are byte-identical to current production and
that each knob does what it claims. All network/LLM calls are mocked at the
layer seam; no real HTTP, Serper, Playwright, or Claude calls are made.
"""
import pytest
from unittest.mock import patch

from agents.tools.search import SearchResult, format_for_prompt
from agents.tools.snippet_picker import PickedChunk
from agents.models import LLMUsage


# Shared fixture: isolate the cache and stub every layer of the DIY pipeline.

@pytest.fixture
def mock_layers(monkeypatch, tmp_path):
    """Mock all four DIY layers so diy_search runs without network."""
    import agents.tools.search_cache as cache_mod
    monkeypatch.setattr(cache_mod, "_DB_PATH", tmp_path / "test_funnel.db")
    monkeypatch.setattr(cache_mod, "_TABLES_ENSURED", False)
    monkeypatch.setattr(cache_mod, "_READ_DISABLED", False)

    def fake_serper(query, **kw):
        return [
            SearchResult(title="A", url="https://a.example", snippet="raw A",
                         score=1.0, provider="serper"),
            SearchResult(title="B", url="https://b.example", snippet="raw B",
                         score=0.5, provider="serper"),
        ]

    monkeypatch.setattr("agents.tools.search_diy.serper_search", fake_serper)

    from agents.tools.fetch import FetchResult

    def fake_fetch_html(url, **kw):
        # A long body so page_text_cap / truncation is observable.
        body = f"CLEAN-{url}-" + ("z" * 20000)
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=body, truncated=False, failure_mode=None,
        )

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", fake_fetch_html)
    monkeypatch.setattr(
        "agents.tools.search_diy.extract_text",
        lambda content, url, is_html=True: content,
    )
    return {}


_USAGE = LLMUsage(
    input_tokens=1, output_tokens=1, wall_clock_ms=1,
    estimated_cost_usd=0.0, model_version="test",
    prompt_version_id=None, condition_label="t", raw_response="{}",
)


# 1. Defaults byte-identical: the picker IS called and an empty pick drops
#    the URL, exactly as before EXP-17.

def test_default_calls_picker_and_drops_empty(mock_layers, monkeypatch):
    """Default funnel: picker runs; a URL with no chunks is dropped."""
    seen_kwargs = []

    def picker(*, query, url, page_text, subtrio_id=None):
        seen_kwargs.append({"url": url})
        if "a.example" in url:
            return ([], _USAGE)  # picker bins this page
        return ([PickedChunk(text="kept passage", score=0.8)], _USAGE)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", picker)

    from agents.tools.search_diy import diy_search
    out = diy_search("q")

    # Picker was called for both URLs; the binned one is dropped.
    assert len(seen_kwargs) == 2
    assert len(out) == 1
    assert "b.example" in out[0].url
    assert out[0].snippet == "kept passage"


def test_default_does_not_pass_funnel_kwargs_to_picker(mock_layers, monkeypatch):
    """The default call must NOT pass max_chunks/page_text_cap to the picker,
    so a mock with the historical signature keeps working byte-identically."""
    # This picker signature is exactly the pre-EXP-17 one (no new kwargs).
    def historical_picker(*, query, url, page_text, subtrio_id=None):
        return ([PickedChunk(text="ok", score=0.9)], _USAGE)

    monkeypatch.setattr(
        "agents.tools.search_diy.pick_snippet", historical_picker,
    )
    from agents.tools.search_diy import diy_search
    out = diy_search("q")  # must not raise TypeError
    assert len(out) == 2


# 2. --snippet-picker off : BYPASS the LLM picker entirely.

def test_picker_off_bypasses_llm_and_keeps_all_urls(mock_layers, monkeypatch):
    """With use_snippet_picker=False the picker function is NEVER called and
    no URL is dropped: the cleaned page text becomes the snippet."""
    called = {"n": 0}

    def picker_must_not_run(*, query, url, page_text, subtrio_id=None, **kw):
        called["n"] += 1
        return ([], _USAGE)

    monkeypatch.setattr(
        "agents.tools.search_diy.pick_snippet", picker_must_not_run,
    )

    from agents.tools.search_diy import diy_search
    out = diy_search("q", use_snippet_picker=False)

    assert called["n"] == 0                      # picker never invoked
    assert len(out) == 2                         # no URL dropped
    assert all(r.provider == "diy" for r in out)
    # Snippet is the cleaned page text (truncated), not a picked chunk.
    assert out[0].snippet.startswith("CLEAN-https://a.example")
    assert all(r.score is None for r in out)     # no picker confidence


def test_picker_off_truncates_to_page_text_cap(mock_layers, monkeypatch):
    """In bypass mode the snippet is truncated to page_text_cap chars."""
    monkeypatch.setattr(
        "agents.tools.search_diy.pick_snippet",
        lambda **kw: ([], _USAGE),
    )
    from agents.tools.search_diy import diy_search
    out = diy_search("q", use_snippet_picker=False, page_text_cap=50)
    assert all(len(r.snippet) == 50 for r in out)


# 3. --max-snippet-chars : per-snippet prompt truncation in format_for_prompt.

def test_format_for_prompt_default_truncation_is_600():
    """Default max_chars_per_snippet stays at 600 (byte-identical)."""
    long = "x" * 1000
    res = [SearchResult(title="T", url="https://u", snippet=long, provider="diy")]
    block = format_for_prompt(res)
    # 600 chars kept + the " ..." overflow marker.
    assert "x" * 600 + " ..." in block
    assert "x" * 601 not in block


def test_format_for_prompt_respects_max_snippet_chars():
    """A smaller max_chars_per_snippet truncates harder; a larger one keeps more."""
    long = "y" * 1000
    res = [SearchResult(title="T", url="https://u", snippet=long, provider="diy")]

    tight = format_for_prompt(res, max_chars_per_snippet=100)
    assert "y" * 100 + " ..." in tight
    assert "y" * 101 not in tight

    wide = format_for_prompt(res, max_chars_per_snippet=1000)
    assert "y" * 1000 in wide
    assert "..." not in wide  # nothing truncated when cap >= snippet length


def test_researcher_build_user_message_threads_max_snippet_chars():
    """build_user_message forwards max_chars_per_snippet to format_for_prompt."""
    from agents.prompts.researcher import build_user_message
    from agents.models import ResearcherInput

    inp = ResearcherInput(
        question_id="P1", country_code="FR", country_name="France",
        country_language="French", dimension="Policy", indicator="ind",
        response_scoring="binary", question_text="text?",
        answer_shape="binary", allowed_answers=["yes", "no"],
    )
    long = "w" * 1000
    res = [SearchResult(title="T", url="https://u", snippet=long, provider="diy")]

    msg = build_user_message(
        inp, search_results=res, queries_used=["q"], max_chars_per_snippet=80,
    )
    assert "w" * 80 + " ..." in msg
    assert "w" * 81 not in msg


# 4. --picker-max-chunks and --page-text-cap thread into the picker.

def test_picker_max_chunks_forwarded(mock_layers, monkeypatch):
    """A non-default picker_max_chunks is forwarded to pick_snippet."""
    captured = {}

    def picker(*, query, url, page_text, subtrio_id=None, **kw):
        captured.update(kw)
        return ([PickedChunk(text="c", score=0.9)], _USAGE)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", picker)
    from agents.tools.search_diy import diy_search
    diy_search("q", picker_max_chunks=2)
    assert captured.get("max_chunks") == 2


def test_page_text_cap_forwarded(mock_layers, monkeypatch):
    """A non-default page_text_cap is forwarded to pick_snippet."""
    captured = {}

    def picker(*, query, url, page_text, subtrio_id=None, **kw):
        captured.update(kw)
        return ([PickedChunk(text="c", score=0.9)], _USAGE)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", picker)
    from agents.tools.search_diy import diy_search
    diy_search("q", page_text_cap=8000)
    assert captured.get("page_text_cap") == 8000


def test_pick_snippet_max_chunks_caps_returned_list():
    """pick_snippet returns at most max_chunks when no chunk crosses the
    confident-top-hit threshold (0.7)."""
    from agents.tools import snippet_picker as sp

    out_schema = sp._ChunksOut(chunks=[
        PickedChunk(text="a", score=0.4),
        PickedChunk(text="b", score=0.3),
        PickedChunk(text="c", score=0.2),
    ])

    def fake_structured(**kw):
        return out_schema, _USAGE

    with patch.object(sp, "call_for_structured", fake_structured), \
            patch.object(sp, "ensure_prompt_version", lambda *a, **k: None):
        chunks, _ = sp.pick_snippet(
            query="q", url="https://u", page_text="p", max_chunks=2,
        )
    assert len(chunks) == 2


def test_pick_snippet_default_max_chunks_is_three():
    """Default pick_snippet keeps up to three chunks (byte-identical)."""
    from agents.tools import snippet_picker as sp

    out_schema = sp._ChunksOut(chunks=[
        PickedChunk(text="a", score=0.4),
        PickedChunk(text="b", score=0.3),
        PickedChunk(text="c", score=0.2),
    ])

    with patch.object(sp, "call_for_structured",
                      lambda **kw: (out_schema, _USAGE)), \
            patch.object(sp, "ensure_prompt_version", lambda *a, **k: None):
        chunks, _ = sp.pick_snippet(query="q", url="https://u", page_text="p")
    assert len(chunks) == 3


def test_build_user_message_default_page_text_cap_is_16000():
    """The snippet-picker prompt still truncates page text at 16000 by default."""
    from agents.prompts.snippet_picker import build_user_message, PAGE_TEXT_CAP

    assert PAGE_TEXT_CAP == 16000
    page = "p" * 20000
    msg = build_user_message("q", "https://u", page)
    assert "p" * 16000 in msg
    assert "p" * 16001 not in msg

    narrow = build_user_message("q", "https://u", page, page_text_cap=500)
    assert "p" * 500 in narrow
    assert "p" * 501 not in narrow
