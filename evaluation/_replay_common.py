"""Shared read-only helpers for the EXP-11 stage 0 replays.

All three replay scripts (substring v2, commit policy, absence
receipts) open the DB read-only and classify answers against ODMI
ground truth with the same logic. That logic lives here so the three
scripts cannot drift apart.

Read-only by construction: connect through `ro_connect`, which opens
the file with mode=ro so a replay can never write the headline DB.
"""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "odmi.db"

# Sentinel labels that are not real bands and not absence answers.
_SENTINELS = {
    "not applicable", "not_applicable", "i don't know", "i don’t know",
    "inconclusive", "other", "1",
}


def ro_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower().replace("_", " ")


@lru_cache(maxsize=4096)
def _question_meta(question_id: str) -> tuple[str, tuple[str, ...]]:
    """(answer_shape, allowed_answers) for a question, cached."""
    with ro_connect() as conn:
        row = conn.execute(
            "SELECT answer_shape, allowed_answers FROM questions "
            "WHERE question_id = ?",
            (question_id,),
        ).fetchone()
    if row is None:
        return ("binary", ("yes", "no"))
    shape = row["answer_shape"] or "binary"
    try:
        allowed = tuple(json.loads(row["allowed_answers"] or "[]"))
    except (json.JSONDecodeError, TypeError):
        allowed = ()
    return (shape, allowed)


def is_correct(question_id: str, answer: str, gold: str) -> bool:
    """True iff `answer` is an exact match to the ODMI gold.

    Mirrors the exact / yes-prefix / equal-no cases of
    dashboard/lib/db.py::_MATCH_STATUS_SQL. Adjacent bands are NOT
    counted correct: EXP-6 labels a one-band miss as should_fail, and
    the replays need the same 'is the committed answer actually right'
    question, so only an exact band hit counts.
    """
    a = _norm(answer)
    g = _norm(gold)
    if not g:
        return False
    if a == g:
        return True
    shape, _ = _question_meta(question_id)
    if shape == "binary":
        if a == "yes" and g.startswith("yes"):
            return True
        if a == "no" and g == "no":
            return True
    return False


def is_absence_class(question_id: str, answer: str) -> bool:
    """True iff `answer` is an absence answer for its question shape:
    binary 'no', or the bottom real band of an ordered shape.

    The bottom band is the last element of allowed_answers after the
    sentinels are removed (the percentage_band lists carry a stray '1'
    header token, handled by the sentinel set).
    """
    a = _norm(answer)
    if a == "no":
        return True
    shape, allowed = _question_meta(question_id)
    if shape in ("percentage_band", "ordinal_magnitude", "count_band"):
        reals = [x for x in allowed if _norm(x) not in _SENTINELS]
        if reals and a == _norm(reals[-1]):
            return True
    return False


def parse_search_snippets(raw: Optional[str]) -> list[str]:
    """Researcher.search_snippets is a JSON list of {url, snippet}."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for it in items:
        if isinstance(it, dict):
            s = it.get("snippet")
            if s:
                out.append(s)
        elif isinstance(it, str) and it:
            out.append(it)
    return out


def parse_independent_evidence(raw: Optional[str]) -> list[str]:
    """Verifier.independent_evidence is a JSON list of snippet strings
    (URLs were dropped by the production formatter)."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [it for it in items if isinstance(it, str) and it]


def is_abstention(answer: Optional[str]) -> bool:
    return _norm(answer) in ("inconclusive", "not applicable")
