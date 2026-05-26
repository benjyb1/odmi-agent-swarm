"""Tests for agents/prompts/snippet_picker.py (prompt module)."""

from __future__ import annotations

import agents.prompts.snippet_picker as sp


def test_metadata_name():
    assert sp.NAME == "snippet_picker"


def test_metadata_version():
    assert sp.VERSION == 1


def test_system_contains_quote_literally_rule():
    assert "Quote literally" in sp.SYSTEM


def test_system_contains_contiguous_rule():
    assert "contiguous" in sp.SYSTEM


def test_system_contains_boilerplate_rule():
    assert "boilerplate" in sp.SYSTEM


def test_system_contains_score_bands():
    assert "0.8-1.0" in sp.SYSTEM


def test_system_contains_empty_list_rule():
    # Rule 4 spans a line break in the locked prompt: "return an empty\n   list"
    assert "return an empty" in sp.SYSTEM and "list" in sp.SYSTEM


def test_system_contains_language_rule():
    assert "any language" in sp.SYSTEM


def test_page_text_cap_value():
    assert sp.PAGE_TEXT_CAP == 8000


def test_build_user_message_includes_query():
    msg = sp.build_user_message("open data policy", "https://example.com", "some page text")
    assert "open data policy" in msg


def test_build_user_message_includes_url():
    msg = sp.build_user_message("query", "https://example.com/page", "text")
    assert "https://example.com/page" in msg


def test_build_user_message_includes_page_text():
    msg = sp.build_user_message("query", "https://example.com", "my page content")
    assert "my page content" in msg


def test_build_user_message_truncates_to_cap():
    long_text = "x" * 10_000
    msg = sp.build_user_message("query", "https://example.com", long_text)
    # The truncated page text in the message should be at most PAGE_TEXT_CAP chars long.
    # The message itself will be longer (it includes the query and URL), so we
    # check that the page text portion is truncated.
    assert "x" * (sp.PAGE_TEXT_CAP + 1) not in msg


def test_build_user_message_does_not_truncate_short_text():
    short_text = "short page content"
    msg = sp.build_user_message("query", "https://example.com", short_text)
    assert short_text in msg
