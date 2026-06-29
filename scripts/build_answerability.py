"""Classify every ODMI question by how its answer can be sourced.

Writes `data/questions/answerability.json`, a committed, reproducible tag per
question used to report accuracy separately by answerability class rather than
to exclude any question. Three classes:

- `catalogue`  — computable from the national portal's structured metadata by
  the deterministic catalogue tool (D30). The authoritative set is the one the
  tool actually handles, imported from `agents.tools.catalogue.compute`.
- `self_report` — an internal practice the country self-declares in the
  questionnaire (monitoring, feedback sessions, knowledge exchange, body-level
  plans). No external public source exists, so the open web cannot confirm it.
  Matched by a transparent keyword rule below; this is a first pass meant for
  review, not a final taxonomy.
- `web`        — everything else: answerable from public web evidence.

Rationale: the swarm's headline accuracy mixes questions no external system
could answer (self_report) with ones it can. Tagging lets the dissertation
report each class on its own terms. The catalogue split additionally marks the
questions where the swarm can independently recompute the metric and contradict
a country's self-report (the D29/D30 finding).

Run: uv run python scripts/build_answerability.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"
OUT_PATH = REPO_ROOT / "data" / "questions" / "answerability.json"

# Authoritative catalogue set: exactly what the D30 tool computes.
from agents.tools.catalogue.compute import COMPUTABLE_QUESTIONS  # noqa: E402

# Self-report rule. Each pattern flags an internal practice the country
# declares about itself, with no public artefact to verify. Kept deliberately
# narrow; broaden only with a recorded reason.
SELF_REPORT_PATTERNS = [
    r"processes? (are )?in place to (monitor|assess|measure|evaluate)",
    r"\bfeedback (sessions?|loops?)\b",
    r"\binterviews?\b",
    r"\bworkshops?\b",
    r"\bfocus group",
    r"exchange of (knowledge|experience|expertise)",
    r"\bregular(ly)? .*(session|meeting|exchange|dialogue)",
    r"publication plans? exist",
    r"plans? exist at (public body|organisation|institutional) level",
    r"do you (monitor|measure|track|assess) (the|your|whether)",
    r"is there a (regular|formal) (exchange|process|mechanism)",
    r"surveys?\b",
]
_SELF_RE = re.compile("|".join(SELF_REPORT_PATTERNS), re.IGNORECASE)


def classify(question_id: str, text: str) -> str:
    if question_id in COMPUTABLE_QUESTIONS:
        return "catalogue"
    if _SELF_RE.search(text or ""):
        return "self_report"
    return "web"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT question_id, dimension, question_text FROM questions "
        "ORDER BY question_id"
    ).fetchall()
    conn.close()

    items = []
    counts: dict[str, int] = {"web": 0, "catalogue": 0, "self_report": 0}
    by_dim: dict[str, dict[str, int]] = {}
    for qid, dim, text in rows:
        cls = classify(qid, text)
        counts[cls] += 1
        by_dim.setdefault(dim, {"web": 0, "catalogue": 0, "self_report": 0})
        by_dim[dim][cls] += 1
        items.append({"question_id": qid, "dimension": dim, "answerability": cls})

    payload = {
        "description": (
            "Per-question answerability class for separate reporting (not "
            "exclusion). catalogue = D30-computable; self_report = "
            "questionnaire-only internal practice; web = public-web answerable. "
            "self_report is a reviewable first-pass keyword rule; catalogue is "
            "authoritative from agents.tools.catalogue.compute."
        ),
        "generator": "scripts/build_answerability.py",
        "total": len(items),
        "counts": counts,
        "by_dimension": by_dim,
        "catalogue_question_ids": sorted(COMPUTABLE_QUESTIONS),
        "self_report_question_ids": sorted(
            i["question_id"] for i in items if i["answerability"] == "self_report"
        ),
        "questions": items,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    print("counts:", counts)
    print("by dimension:", json.dumps(by_dim))


if __name__ == "__main__":
    main()
