"""Run Console — release subtrios and watch them live."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db, mode
from dashboard.lib.currency import format_gbp
from dashboard.lib.sidebar import page_header, render_session_widget
from scripts.dispatch_subtrios import (
    MAX_PAIRS_PER_DISPATCH,
    dispatch,
    estimate_pair_cost,
)


st.set_page_config(page_title="Run Console", page_icon="▶", layout="wide")
page_header("Run Console", "Release subtrios and watch them progress live.")
render_session_widget()


# ============================================================
# State helpers
# ============================================================

VERIFIER_STRATEGIES = [
    "verifier-disprove",
    "verifier-negation",
    "verifier-steelman",
    "verifier-blind",
]

MODEL_OPTIONS = [
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-6",
]

COUNTRIES = {
    "FR": "France",
    "RO": "Romania",
    "DE": "Germany",
    "NL": "Netherlands",
    "HU": "Hungary",
    "EE": "Estonia",
}


def _model_default(role: str) -> str:
    defaults = db.model_defaults()
    if len(defaults) == 0:
        return MODEL_OPTIONS[0]
    matched = defaults[defaults["agent_role"] == role]
    if len(matched) == 0:
        return MODEL_OPTIONS[0]
    return matched.iloc[0]["model"]


def _all_questions() -> pd.DataFrame:
    return db.all_questions()


# ============================================================
# Launcher
# ============================================================

def render_launcher() -> None:
    st.subheader("Release subtrios")

    # Pull pre-staged questions from session_state if Questions page set them.
    queued = st.session_state.get("queued_questions", [])

    qs_df = _all_questions()
    all_q_ids = qs_df["question_id"].tolist() if "question_id" in qs_df else []

    col_c, col_q = st.columns([1, 2])
    with col_c:
        countries = st.multiselect(
            "Countries",
            options=list(COUNTRIES.keys()),
            default=["FR"],
            format_func=lambda c: f"{c} — {COUNTRIES[c]}",
            help="Multi-select. N questions × M countries = N×M subtrios.",
        )

    # Look up which question_ids are already covered against the
    # selected countries so the picker can sort the "still to do"
    # questions to the top and label the rest as already covered.
    n_covered_per_qid: dict[str, int] = {}
    if countries and all_q_ids:
        with sqlite3.connect(REPO_ROOT / "data" / "odmi.db") as _conn:
            placeholders = ",".join("?" for _ in countries)
            rows = _conn.execute(
                f"""SELECT question_id, COUNT(DISTINCT country_code) AS n
                    FROM phase2_final
                    WHERE country_code IN ({placeholders})
                      AND experiment_id IS NULL
                    GROUP BY question_id""",
                tuple(countries),
            ).fetchall()
        n_covered_per_qid = {qid: int(n) for qid, n in rows}

    sorted_q_ids = sorted(
        all_q_ids,
        key=lambda q: (n_covered_per_qid.get(q, 0), q),
    )

    def _q_label(qid: str) -> str:
        n_done = n_covered_per_qid.get(qid, 0)
        if n_done == 0 or not countries:
            return qid
        return f"{qid}  ✓ already run in {n_done}/{len(countries)}"

    with col_q:
        default_qids = (
            queued
            if queued
            else ([sorted_q_ids[0]] if sorted_q_ids else [])
        )
        questions = st.multiselect(
            "Questions",
            options=sorted_q_ids,
            default=default_qids,
            format_func=_q_label,
            help=(
                "Questions you have not yet run against the selected "
                "countries appear first. Already-covered ones sit at "
                "the bottom with a tick."
            ),
        )
        if queued:
            st.caption(
                f"Pre-staged from Questions page: {', '.join(queued)}. "
                f"Clear: Questions page → deselect all → Send."
            )

    col_a, col_b, col_d, col_e = st.columns(4)
    with col_a:
        researcher_model = st.selectbox(
            "Researcher model", MODEL_OPTIONS,
            index=MODEL_OPTIONS.index(_model_default("researcher"))
                  if _model_default("researcher") in MODEL_OPTIONS else 0,
        )
    with col_b:
        verifier_model = st.selectbox(
            "Verifier model", MODEL_OPTIONS,
            index=MODEL_OPTIONS.index(_model_default("verifier"))
                  if _model_default("verifier") in MODEL_OPTIONS else 0,
        )
    with col_d:
        adjudicator_model = st.selectbox(
            "Adjudicator model", MODEL_OPTIONS,
            index=MODEL_OPTIONS.index(_model_default("adjudicator"))
                  if _model_default("adjudicator") in MODEL_OPTIONS else 0,
        )
    with col_e:
        strategy = st.selectbox("Verifier strategy", VERIFIER_STRATEGIES)

    col_p, col_r, col_m = st.columns(3)
    with col_p:
        parallel = st.number_input(
            "Parallel limit", min_value=1, max_value=16, value=4, step=1,
        )
    with col_r:
        max_retries = st.number_input(
            "Max retries", min_value=0, max_value=5, value=3, step=1,
        )
    with col_m:
        _window_cost = float(db.rolling_window_summary().get("cost") or 0.0)
        st.metric("Window spend (5h)", format_gbp(_window_cost))

    with st.expander("Experiment settings (optional)", expanded=False):
        st.caption(
            "Leave the experiment ID blank for a normal main-results run. Set it "
            "to tag every row (D27) and vary the search knobs as a condition, for "
            "example the DIY cost/quality experiment: provider=diy, results=3, "
            "query cap=2 against provider=diy, results=5, no cap."
        )
        ce_a, ce_b, ce_c = st.columns(3)
        with ce_a:
            provider = st.selectbox(
                "Search provider", ["auto", "tavily", "brave", "diy", "serper_raw"],
                index=0,
                help="auto = Tavily then Brave (default). diy = self-hosted pipeline.",
            )
        with ce_b:
            max_results_per_query = int(st.number_input(
                "Results per query", min_value=1, max_value=10, value=5, step=1,
            ))
        with ce_c:
            num_queries = int(st.number_input(
                "Query cap (0 = no cap)", min_value=0, max_value=3, value=0, step=1,
            ))
        ce_d, ce_e = st.columns(2)
        with ce_d:
            experiment_id = st.text_input(
                "Experiment ID (blank = main run)", value="",
            ).strip()
        with ce_e:
            condition_label = st.text_input("Condition label", value="baseline").strip()

    n_pairs = len(questions) * len(countries)

    if n_pairs == 0:
        st.warning("Pick at least one question and one country.")
        return

    # Pre-flight estimate (informational only; nothing here blocks a run).
    try:
        est = estimate_pair_cost(
            researcher_model=researcher_model,
            verifier_model=verifier_model,
            adjudicator_model=adjudicator_model,
            strategy=strategy,
            n_pairs=n_pairs,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Pre-flight estimate failed: {exc}")
        return

    st.info(
        f"Pre-flight estimate: ~{format_gbp(est.per_subtrio_usd, places=3)}"
        f"/pair × {n_pairs} (uplift 1.2x, fallback={est.fallback_level}, "
        f"n={est.sample_size}) → projected "
        f"{format_gbp(est.projected_total_usd)}. "
        f"Window spend so far {format_gbp(est.rolling_window_cost_usd)} (5h)."
    )

    # Ground-truth coverage check (per D22, superseded the hand-mark lock check).
    requested_keys = {(q, c) for q in questions for c in countries}
    with sqlite3.connect(REPO_ROOT / "data" / "odmi.db") as _gt_conn:
        gt_rows = _gt_conn.execute(
            "SELECT question_id, country_code FROM ground_truth"
        ).fetchall()
    gt_keys = {(qid, cc) for qid, cc in gt_rows}
    missing = requested_keys - gt_keys
    if missing:
        st.caption(
            f"⚠ Ground-truth coverage: {len(missing)} of "
            f"{len(requested_keys)} pairs have no ODMI ground-truth row. "
            "Release proceeds; those pairs will not contribute to "
            "accuracy aggregates."
        )

    # Duplicate-run check: which of the requested pairs already have a
    # phase2_final row? Default behaviour is to skip them; opt-in
    # checkbox to re-run anyway (appends new rows, doesn't overwrite).
    dupes = db.already_finalised(questions, countries)
    rerun_dupes = False
    if len(dupes) > 0:
        st.warning(
            f"⚠ {len(dupes)} of {len(requested_keys)} pair(s) already "
            "have a finalised run in the database."
        )
        with st.expander("Already-done pairs", expanded=True):
            display = dupes[[
                "question_id", "country_code", "n_runs",
                "last_terminal_status", "last_match_status",
                "last_created_at",
            ]].rename(columns={
                "question_id": "Q", "country_code": "Country",
                "n_runs": "Runs", "last_terminal_status": "Last status",
                "last_match_status": "vs ODMI",
                "last_created_at": "Last run",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.caption(
                "Default: skip these and only dispatch the rest. To wipe "
                "a pair and start fresh, delete its rows from "
                "`phase2_final`, `phase2_adjudications`, "
                "`phase2_verifier_runs`, `phase2_researcher_runs`, and "
                "`subtrio_status` (keep `claude_usage_log` for cost "
                "audit), then re-release."
            )
            rerun_dupes = st.checkbox(
                "Run them anyway and append new rows",
                value=False, key="rerun_dupes",
                help="Off (default): skip the duplicates and only "
                     "dispatch the rest. On: dispatch every requested "
                     "pair, including the duplicates, creating new "
                     "phase2_final rows alongside the old ones.",
            )

    dupe_keys = {
        (r["question_id"], r["country_code"]) for _, r in dupes.iterrows()
    }
    if rerun_dupes:
        effective_pairs = requested_keys
    else:
        effective_pairs = requested_keys - dupe_keys

    if len(dupe_keys) > 0 and not rerun_dupes:
        skipped = len(dupe_keys)
        st.caption(
            f"✂ Skipping {skipped} duplicate pair(s); "
            f"dispatching {len(effective_pairs)}."
        )

    n_effective = len(effective_pairs)

    # Runaway guard (D41): a dispatch above the pair threshold is refused by
    # the dispatcher unless explicitly allowed. Surface that here so the run
    # doesn't silently no-op.
    allow_large = False
    if n_effective > MAX_PAIRS_PER_DISPATCH:
        st.error(
            f"⚠ {n_effective} pairs exceeds the {MAX_PAIRS_PER_DISPATCH}-pair "
            f"runaway guard. This is usually a misspecified selection. The "
            f"dispatcher will refuse unless you confirm."
        )
        allow_large = st.checkbox(
            "Allow this large run (override the runaway guard)", value=False,
        )

    clicked = st.button(
        f"▶ Release {n_effective} subtrio(s)",
        type="primary", use_container_width=True,
        disabled=(n_effective == 0
                  or (n_effective > MAX_PAIRS_PER_DISPATCH and not allow_large)),
    )

    if clicked:
        if mode.block_if_read_only():
            return
        eff_questions = sorted({q for q, _ in effective_pairs})
        eff_countries = sorted({c for _, c in effective_pairs})
        _trigger_release(
            questions=eff_questions, countries=eff_countries,
            pair_filter=effective_pairs, strategy=strategy,
            researcher_model=researcher_model, verifier_model=verifier_model,
            adjudicator_model=adjudicator_model,
            parallel=parallel, max_retries=max_retries,
            provider=provider, max_results_per_query=max_results_per_query,
            num_queries=num_queries, experiment_id=experiment_id,
            condition_label=condition_label, allow_large=allow_large,
        )


def _trigger_release(
    *, questions, countries, pair_filter, strategy,
    researcher_model, verifier_model, adjudicator_model,
    parallel, max_retries,
    provider="auto", max_results_per_query=5, num_queries=0,
    experiment_id="", condition_label="baseline", allow_large=False,
) -> None:
    """Spawn dispatch_subtrios.py as a fire-and-forget subprocess.

    `pair_filter` is the exact set of (qid, cc) pairs to dispatch.
    We pass it as `--pairs QID:CC ...` so the dispatcher honours the
    sparse selection (i.e. the duplicate-skip from the launcher).
    """
    batch_id = str(uuid.uuid4())
    pair_args = [f"{q}:{c}" for q, c in sorted(pair_filter)]
    cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "dispatch_subtrios.py"),
        "--pairs", *pair_args,
        "--strategy", strategy,
        "--researcher-model", researcher_model,
        "--verifier-model", verifier_model,
        "--adjudicator-model", adjudicator_model,
        "--parallel", str(parallel),
        "--max-retries", str(max_retries),
        "--batch-id", batch_id,
    ]
    if provider and provider != "auto":
        cmd += ["--provider", provider]
    cmd += ["--max-results-per-query", str(max_results_per_query)]
    if num_queries and num_queries > 0:
        cmd += ["--num-queries", str(num_queries)]
    if experiment_id:
        cmd += ["--experiment-id", experiment_id,
                "--condition-label", condition_label or "baseline"]
    if allow_large:
        cmd.append("--allow-large")

    # Fire-and-forget; capture stdout to a log file.
    logs_dir = REPO_ROOT / "dashboard" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"batch_{batch_id}.log"
    log_handle = open(log_path, "w")
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_ROOT),
        stdout=log_handle, stderr=subprocess.STDOUT,
    )
    st.session_state["last_batch_id"] = batch_id
    st.session_state["last_batch_pid"] = proc.pid
    st.session_state["last_batch_log"] = str(log_path)

    st.success(
        f"Released batch `{batch_id[:8]}` ({len(pair_filter)} subtrios). "
        f"PID {proc.pid}. Log: `{log_path.name}`."
    )
    st.toast("Dispatched. Watch the cards below.", icon="▶")


# ============================================================
# Active subtrio cards
# ============================================================

@st.fragment(run_every=1.5)
def render_active_cards() -> None:
    st.subheader("Active and recent subtrios")
    recent = db.recent_subtrios(limit=20)
    if len(recent) == 0:
        st.info("No subtrios yet. Release one above.")
        return

    # Group: active first, then done/failed.
    active_mask = recent["stage"].isin([
        "queued", "researching", "verifying", "adjudicating",
    ])
    active = recent[active_mask]
    finished = recent[~active_mask]

    if len(active) > 0:
        cols = st.columns(min(2, len(active)) or 1)
        for i, (_, row) in enumerate(active.iterrows()):
            with cols[i % len(cols)]:
                _render_card(row, is_active=True)

    if len(finished) > 0:
        st.caption("Recently finished:")
        cols = st.columns(min(2, len(finished)) or 1)
        for i, (_, row) in enumerate(finished.head(6).iterrows()):
            with cols[i % len(cols)]:
                _render_card(row, is_active=False)


def _render_card(row: pd.Series, *, is_active: bool) -> None:
    """One subtrio card. Mimics the wireframe."""
    stage = row.get("stage") or "?"
    border_colour = {
        "researching": "#2563eb",
        "verifying": "#f59e0b",
        "adjudicating": "#7c3aed",
        "done": "#10b981",
        "failed": "#dc2626",
        "interrupted_rate_limit": "#dc2626",
        "orphaned": "#6b7280",
    }.get(stage, "#9ca3af")

    with st.container(border=True):
        if is_active:
            col_h1, col_h2, col_x = st.columns([3, 2, 0.5])
        else:
            col_h1, col_h2 = st.columns([3, 2])
            col_x = None
        with col_h1:
            st.markdown(
                f"**{row['question_id']}** · {row['country_code']}  "
                f"&nbsp;<span style='color:{border_colour};font-weight:600'>"
                f"{stage.upper()}</span>",
                unsafe_allow_html=True,
            )
        with col_h2:
            cost = row.get("cumulative_cost_usd")
            cost_str = format_gbp(cost, places=3) if pd.notna(cost) else "—"
            retry = int(row.get("retry_count") or 0)
            st.caption(f"retry {retry}  ·  {cost_str}")
        if col_x is not None:
            with col_x:
                subtrio_id = row.get("subtrio_id")
                if subtrio_id and st.button(
                    "✕",
                    key=f"cancel_{subtrio_id}",
                    help="Cancel this subtrio: kill the running process and "
                         "delete every row it has written so far.",
                ):
                    if mode.block_if_read_only():
                        return
                    result = db.cancel_subtrio(str(subtrio_id))
                    n_deleted = sum(result["deleted"].values())
                    kill_note = (
                        "process stopped" if result["killed"]
                        else "no live process found"
                    )
                    st.toast(
                        f"Cancelled {row['question_id']}/{row['country_code']} "
                        f"({kill_note}, {n_deleted} row(s) deleted).",
                        icon="🗑",
                    )
                    st.rerun(scope="fragment")

        # Three-stage pipeline strip.
        r_state, v_state, f_state = _stage_states(stage, row.get("final_verdict"))
        p1, p2, p3 = st.columns(3)
        with p1:
            st.markdown(_pipeline_block("Researcher", r_state),
                        unsafe_allow_html=True)
        with p2:
            st.markdown(_pipeline_block("Verifier", v_state),
                        unsafe_allow_html=True)
        with p3:
            st.markdown(_pipeline_block("Final", f_state, row.get("final_verdict")),
                        unsafe_allow_html=True)

        msg = row.get("last_message")
        if msg:
            st.caption(f"`{msg}`")


def _stage_states(stage: str, final_verdict: str | None) -> tuple[str, str, str]:
    """Return (researcher_state, verifier_state, final_state) icons."""
    if stage == "queued":
        return ("waiting", "waiting", "waiting")
    if stage == "researching":
        return ("active", "waiting", "waiting")
    if stage == "verifying":
        return ("done", "active", "waiting")
    if stage == "adjudicating":
        return ("done", "done", "active")
    if stage == "done":
        if final_verdict in ("accepted_by_verifier",):
            return ("done", "done", "passed")
        if final_verdict in ("accepted_by_adjudicator",):
            return ("done", "done", "adjud_passed")
        if final_verdict and final_verdict.startswith(("abstained", "escalated")):
            return ("done", "done", "abstained")
        return ("done", "done", "passed")
    if stage in ("failed", "interrupted_rate_limit", "orphaned"):
        return ("done", "failed", "failed")
    return ("waiting", "waiting", "waiting")


def _pipeline_block(label: str, state: str, verdict: str | None = None) -> str:
    """One block in the three-stage pipeline."""
    styles = {
        "waiting": ("#f3f4f6", "#9ca3af", "—"),
        "active":  ("#dbeafe", "#2563eb", "active"),
        "done":    ("#d1fae5", "#10b981", "✓"),
        "passed":  ("#d1fae5", "#10b981", "✓ pass"),
        "adjud_passed": ("#ede9fe", "#7c3aed", "✓ adj"),
        "failed":  ("#fee2e2", "#dc2626", "✗"),
        "abstained": ("#fef3c7", "#d97706", "abstain"),
    }
    bg, border, icon = styles.get(state, styles["waiting"])
    text = label if state in ("waiting", "active") else f"{label} {icon}"
    return (
        f"<div style='background:{bg};border:1.5px solid {border};"
        f"border-radius:6px;padding:6px 10px;text-align:center;"
        f"font-size:12px;font-weight:600;color:#111827'>"
        f"{text}</div>"
    )


# ============================================================
# Live progress strip
# ============================================================

_ACTIVE_STAGES = {"queued", "researching", "verifying", "adjudicating"}


@st.fragment(run_every=1.5)
def render_progress_strip() -> None:
    """Top-of-page status: how many subtrios are in flight right now,
    plus a progress bar for the most recently dispatched batch (if any).
    """
    active = db.active_subtrios()
    n_active = len(active)
    stage_counts = (
        active["stage"].value_counts().to_dict() if n_active > 0 else {}
    )

    last_batch_id = st.session_state.get("last_batch_id")
    batch_df = (
        db.subtrios_by_batch(last_batch_id)
        if last_batch_id else None
    )

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
    c1.metric("In flight", n_active)
    c2.metric("Researching", int(stage_counts.get("researching", 0)))
    c3.metric("Verifying", int(stage_counts.get("verifying", 0)))
    c4.metric("Adjudicating", int(stage_counts.get("adjudicating", 0)))
    c5.metric("Queued", int(stage_counts.get("queued", 0)))

    if batch_df is not None and len(batch_df) > 0:
        n_total = len(batch_df)
        n_done = int((batch_df["stage"] == "done").sum())
        n_active_batch = int(
            batch_df["stage"].isin(list(_ACTIVE_STAGES)).sum()
        )
        n_other = n_total - n_done - n_active_batch
        progress = n_done / n_total if n_total > 0 else 0
        st.progress(
            progress,
            text=(
                f"Latest batch `{last_batch_id[:8]}` — "
                f"{n_done}/{n_total} done · {n_active_batch} in flight"
                + (f" · {n_other} other" if n_other else "")
            ),
        )

    if n_active > 0:
        previews = ", ".join(
            f"{r['question_id']}/{r['country_code']} ({r['stage']})"
            for _, r in active.head(6).iterrows()
        )
        st.caption(f"Active: {previews}")


# ============================================================
# Layout
# ============================================================

render_progress_strip()
st.divider()
render_launcher()
st.divider()
render_active_cards()

st.caption(
    "Progress strip refreshes every 1.5 seconds. "
    "A released batch keeps running even if you close this tab; "
    "watch the Home page or come back here to see progress."
)
