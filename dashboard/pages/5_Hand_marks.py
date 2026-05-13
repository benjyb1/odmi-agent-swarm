"""Hand-marks — view existing rubric scores and add new ones in-app.

The CSV files in data/hand_marks/ remain canonical. This page provides
a form that appends a new row to the right CSV, then git-commits and
runs scripts/sync_hand_marks.py so the D9 lock is satisfied without
the marker ever opening a text editor.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db, mode
from dashboard.lib.sidebar import page_header, render_session_widget


HAND_MARKS_DIR = REPO_ROOT / "data" / "hand_marks"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_hand_marks.py"

CSV_FIELDS = [
    "question_id", "country",
    "evidence_score", "evidence_justification",
    "determinism_score", "determinism_justification",
    "complexity_score", "complexity_justification",
    "composite_score", "tier",
    "search_queries", "sources_found", "answer_obtained",
    "marker", "marked_at", "notes",
]

COUNTRIES = {
    "FR": "France", "DE": "Germany", "NL": "Netherlands",
    "RO": "Romania", "HU": "Hungary", "EE": "Estonia",
}


# ============================================================
# Tier mapping (per METHODOLOGY.md §3)
# ============================================================

def tier_for(composite: int) -> str:
    if composite >= 7:
        return "Highly Likely"
    if composite >= 5:
        return "Likely"
    if composite >= 3:
        return "Unlikely"
    return "Very Unlikely"


# ============================================================
# CSV write
# ============================================================

def csv_path_for(country_code: str) -> Path:
    return HAND_MARKS_DIR / f"{country_code.lower()}_handmarks.csv"


def _pipe_join(blob: str) -> str:
    """Normalise multi-line or pipe-separated input to pipes."""
    if not blob:
        return ""
    parts = [p.strip() for line in blob.splitlines() for p in line.split("|")]
    return " | ".join(p for p in parts if p)


def append_row(row: dict) -> Path:
    path = csv_path_for(row["country"])
    HAND_MARKS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return path


# ============================================================
# Git + sync
# ============================================================

def run_git(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def commit_and_sync(
    csv_path: Path, question_id: str, country: str, marker: str
) -> tuple[bool, str]:
    rel = csv_path.resolve().relative_to(REPO_ROOT)

    rc, _, err = run_git("add", "--", str(rel))
    if rc != 0:
        return False, f"git add failed: {err or 'unknown error'}"

    msg = f"hand-marks: add {question_id}/{country} ({marker})"
    rc, _, err = run_git("commit", "-m", msg, "--", str(rel))
    if rc != 0:
        if "nothing to commit" in err or "nothing added" in err:
            return False, (
                "Nothing changed in the CSV. The row may already exist "
                "verbatim, or another commit already locked it."
            )
        return False, f"git commit failed: {err or 'unknown error'}"

    rc, _, err = run_git("log", "-1", "--pretty=format:%H")
    sha = err if rc != 0 else _last_commit_sha()
    if rc != 0:
        return False, f"git log failed: {err}"

    sync = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), str(csv_path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if sync.returncode != 0:
        return False, (
            "Commit landed but sync_hand_marks.py failed: "
            + (sync.stderr.strip() or sync.stdout.strip() or "unknown")
        )

    return True, sync.stdout.strip()


def _last_commit_sha() -> str:
    rc, sha, err = run_git("rev-parse", "HEAD")
    return sha if rc == 0 else "?"


# ============================================================
# UI
# ============================================================

st.set_page_config(page_title="Hand-marks", page_icon="✍", layout="wide")
page_header(
    "Hand-marks",
    "Audit-trail rubric scores. CSV is canonical; saving here writes "
    "the row, commits the change, and syncs the DB so the D9 lock is "
    "automatic.",
)
render_session_widget()


hm = db.hand_marks()
questions_df = db.all_questions()
qid_to_text = (
    dict(zip(questions_df["question_id"], questions_df["question_text"]))
    if "question_id" in questions_df.columns else {}
)

existing_pairs = set(
    zip(hm["question_id"], hm["country_code"])
    if "question_id" in hm.columns else []
)


# ----- Add form -----
existing_count = len(hm)
with st.expander(
    "➕ Add a new hand-mark",
    expanded=(existing_count < 3),
):
    if len(questions_df) == 0:
        st.error(
            "No questions loaded. Run "
            "`uv run python scripts/load_questions.py` first."
        )
    else:
        all_qids = questions_df["question_id"].tolist()

        with st.form("add_handmark", clear_on_submit=False):
            colq, colc = st.columns([3, 1])
            with colq:
                qid = st.selectbox(
                    "Question",
                    options=all_qids,
                    format_func=lambda q: (
                        f"{q} — {qid_to_text.get(q, '')[:90]}"
                        + ("…" if len(qid_to_text.get(q, '')) > 90 else "")
                    ),
                )
            with colc:
                country = st.selectbox(
                    "Country",
                    options=list(COUNTRIES.keys()),
                    format_func=lambda c: f"{c} — {COUNTRIES[c]}",
                )

            # Full question text for context.
            if qid and qid_to_text.get(qid):
                st.markdown(f"> {qid_to_text[qid]}")

            # Existing-pair warning.
            if (qid, country) in existing_pairs:
                st.warning(
                    f"A hand-mark for {qid}/{country} already exists. "
                    "Saving will add a new row per PROTOCOL.md's "
                    "re-marking rule (the old row stays in the audit "
                    "trail; mark it as superseded in the notes field)."
                )

            st.markdown("### Rubric scores")
            cols = st.columns(3)
            with cols[0]:
                ea = st.slider(
                    "Evidence Accessibility (0–3)",
                    min_value=0, max_value=3, value=2,
                    help="How findable is the evidence on the open web "
                         "for this country?",
                )
                ea_just = st.text_area(
                    "EA justification",
                    placeholder="One sentence. Include the URL if applicable.",
                    height=80,
                )
            with cols[1]:
                ad = st.slider(
                    "Answer Determinism (0–3)",
                    min_value=0, max_value=3, value=2,
                    help="How objective is the answer? Could two "
                         "evaluators agree from the same evidence?",
                )
                ad_just = st.text_area(
                    "AD justification",
                    placeholder="One sentence.",
                    height=80,
                )
            with cols[2]:
                sc = st.slider(
                    "Source Complexity (0–3)",
                    min_value=0, max_value=3, value=2,
                    help="How many sources need to be cross-referenced?",
                )
                sc_just = st.text_area(
                    "SC justification",
                    placeholder="One sentence.",
                    height=80,
                )

            composite = ea + ad + sc
            tier = tier_for(composite)
            st.markdown(
                f"**Composite:** {composite}/9  **Tier:** _{tier}_"
            )

            st.markdown("### Search trail (optional but recommended)")
            colt1, colt2 = st.columns(2)
            with colt1:
                queries = st.text_area(
                    "Search queries used",
                    placeholder="One per line, or pipe-separated.",
                    height=80,
                )
            with colt2:
                sources = st.text_area(
                    "Sources found",
                    placeholder="One URL per line, or pipe-separated.",
                    height=80,
                )

            answer = st.text_input(
                "Answer you actually reached",
                placeholder='e.g. "Yes", "No", "not reached"',
            )

            colm1, colm2 = st.columns([1, 3])
            with colm1:
                marker = st.text_input("Marker initials", value="BB")
            with colm2:
                notes = st.text_input(
                    "Notes (optional)",
                    placeholder="Anything an examiner should know.",
                )

            submitted = st.form_submit_button(
                "💾 Save, commit, and lock", type="primary",
                use_container_width=True,
            )

        if submitted and mode.block_if_read_only():
            submitted = False

        if submitted:
            errors = []
            if not ea_just.strip():
                errors.append("Evidence justification is required.")
            if not ad_just.strip():
                errors.append("Determinism justification is required.")
            if not sc_just.strip():
                errors.append("Complexity justification is required.")
            if not marker.strip():
                errors.append("Marker initials are required.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                row = {
                    "question_id": qid,
                    "country": country,
                    "evidence_score": ea,
                    "evidence_justification": ea_just.strip(),
                    "determinism_score": ad,
                    "determinism_justification": ad_just.strip(),
                    "complexity_score": sc,
                    "complexity_justification": sc_just.strip(),
                    "composite_score": composite,
                    "tier": tier,
                    "search_queries": _pipe_join(queries),
                    "sources_found": _pipe_join(sources),
                    "answer_obtained": answer.strip(),
                    "marker": marker.strip(),
                    "marked_at": (
                        datetime.utcnow()
                        .isoformat(timespec="seconds") + "Z"
                    ),
                    "notes": notes.strip(),
                }
                csv_path = append_row(row)
                ok, message = commit_and_sync(
                    csv_path, qid, country, marker.strip()
                )
                if ok:
                    st.success(
                        f"Locked. {message}"
                        if message else "Locked and synced."
                    )
                    st.balloons()
                    st.rerun()
                else:
                    st.error(message)


# ----- Existing marks -----
st.divider()

if len(hm) == 0:
    st.info(
        "No hand-marks in the DB yet. Add one above, or run "
        "`uv run python scripts/sync_hand_marks.py "
        "data/hand_marks/<country>_handmarks.csv` if you have an "
        "existing CSV that needs mirroring."
    )
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total hand-marks", len(hm))
with col2:
    locked = hm[hm["locked_by_commit"].notna()]
    st.metric("Locked", f"{len(locked)} / {len(hm)}")
with col3:
    st.metric("Countries", hm["country_code"].nunique())

st.divider()

col_c, col_t = st.columns(2)
with col_c:
    chosen_countries = st.multiselect(
        "Country",
        sorted(hm["country_code"].unique().tolist()),
        default=sorted(hm["country_code"].unique().tolist()),
    )
with col_t:
    tiers = ["Highly Likely", "Likely", "Unlikely", "Very Unlikely"]
    tier_filter = st.multiselect("Tier", tiers, default=tiers)

filtered = hm[hm["country_code"].isin(chosen_countries)]
if "tier" in filtered.columns:
    filtered = filtered[filtered["tier"].isin(tier_filter)]

show_cols = [
    "question_id", "country_code",
    "evidence_score", "determinism_score", "complexity_score",
    "composite_score", "tier",
    "locked_by_commit", "marker", "marked_at",
]
show_cols = [c for c in show_cols if c in filtered.columns]
st.dataframe(filtered[show_cols], use_container_width=True, hide_index=True)
