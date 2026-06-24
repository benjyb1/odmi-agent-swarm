"""Tests for the query-language ablation knob (foreign-language experiment).

Behaviour contract:
- The query-gen step has two modes. "bilingual" (default, production) keeps the
  native-language query instruction unchanged. "en" ablates it: all queries in
  English only. Selecting the mode swaps the system prompt and its
  prompt_versions identity, so each arm logs against its own versioned prompt.
- The default everywhere is "bilingual", so a default dispatch is byte-identical
  to before this knob landed (no native behaviour changes unless asked).
- The retry-divergence guidance is identical in both modes; only the language
  instruction differs (one variable).
"""

import inspect

from agents.researcher import (
    _query_gen_spec,
    generate_queries,
    run_researcher,
)


def test_bilingual_is_the_production_prompt():
    name, version, system, _desc = _query_gen_spec("bilingual")
    assert name == "phase2_researcher_query_gen"
    assert version == 2
    assert "local language" in system
    assert "in English" in system


def test_en_only_drops_the_native_language_instruction():
    name, version, system, _desc = _query_gen_spec("en")
    # Distinct versioned identity so the arm is auditable in prompt_versions.
    assert name == "phase2_researcher_query_gen_en_only"
    assert "local language" not in system
    # It must still say English-only, positively.
    assert "English" in system


def test_default_mode_is_bilingual():
    assert _query_gen_spec() == _query_gen_spec("bilingual")


def test_retry_divergence_guidance_is_identical_across_modes():
    # The only difference between the two prompts is the language instruction.
    _, _, bilingual, _ = _query_gen_spec("bilingual")
    _, _, en_only, _ = _query_gen_spec("en")
    for marker in (
        "DIFFERENT from the ones already tried",
        "Return JSON matching the schema",
        "5-10 word queries",
    ):
        assert marker in bilingual
        assert marker in en_only


def test_invalid_mode_raises():
    import pytest
    with pytest.raises(ValueError):
        _query_gen_spec("french")


def test_callers_default_to_bilingual():
    # The knob must default to production behaviour at every entry point.
    assert (
        inspect.signature(generate_queries).parameters["query_language"].default
        == "bilingual"
    )
    assert (
        inspect.signature(run_researcher).parameters["query_language"].default
        == "bilingual"
    )
