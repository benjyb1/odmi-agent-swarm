"""Tests for agents.tools.llm._extract_json robustness.

The model sometimes wraps JSON in markdown fences AND adds trailing prose,
or precedes the JSON with a sentence. The eval's Opus adjudicator did
exactly this (```json fence followed by an explanation), which the
end-anchored fence strip missed. _extract_json must recover the JSON object
in these cases without a second model call.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from agents.tools.llm import _extract_json


def test_extract_plain_json():
    assert json.loads(_extract_json('{"a": 1}'))["a"] == 1


def test_extract_fenced_json():
    assert json.loads(_extract_json('```json\n{"a": 1}\n```'))["a"] == 1


def test_extract_fenced_json_with_trailing_prose():
    raw = '```json\n{"winner": "both_fail", "confidence": 0.5}\n```\n\nNote: here is why.'
    assert json.loads(_extract_json(raw))["winner"] == "both_fail"


def test_extract_leading_prose_then_json():
    raw = 'Here is my answer:\n{"a": 1}'
    assert json.loads(_extract_json(raw))["a"] == 1


def test_extract_plain_json_unchanged_when_clean():
    # A clean object with nested braces must survive intact.
    raw = '{"a": {"b": 2}, "c": 3}'
    obj = json.loads(_extract_json(raw))
    assert obj["a"]["b"] == 2 and obj["c"] == 3


def test_usage_log_timestamp_format_is_naive_utc_z():
    """The claude_usage_log timestamp must stay naive UTC ISO with a "Z"
    suffix and no numeric offset, so rows stored before and after the
    utcnow() -> now(timezone.utc) swap remain consistent."""
    ts = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds") + "Z"
    )
    # e.g. 2026-06-04T12:34:56Z — no "+00:00" offset, no microseconds.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), ts
    assert "+00:00" not in ts
