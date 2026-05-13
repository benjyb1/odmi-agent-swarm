"""Results — scan finalised pairs as cards, drill into raw rows by tab."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Results", page_icon="📋", layout="wide")
page_header(
    "Results",
    "Cards view first — scan question, answer, and proof at a glance. "
    "Raw Researcher / Verifier / Finals tables follow.",
)
render_session_widget()


# ============================================================
# Cards view
# ============================================================

def _status_chip(status: str) -> str:
    """Coloured Streamlit-friendly chip text for a terminal status."""
    if status.startswith("accepted_"):
        emoji = "🟢"
    elif status.startswith("rejected_"):
        emoji = "🔴"
    elif status.startswith("escalated_"):
        emoji = "🟡"
    else:
        emoji = "⚪"
    pretty = status.replace("_", " ").title()
    return f"{emoji} {pretty}"


def _path_summary(row: pd.Series) -> str:
    """One-line summary of the agent path the pair took."""
    retries = int(row["retry_count"] or 0)
    adjud = bool(row["adjudicator_involved"])
    if row["terminal_status"] == "accepted_by_verifier":
        return "Researcher → Verifier passed on first attempt."
    if row["terminal_status"] == "accepted_by_adjudicator":
        return (
            f"Researcher → Verifier failed {retries + 1}× → "
            "Adjudicator agreed with the Researcher."
        )
    if row["terminal_status"] == "escalated_adjudicator":
        return (
            f"Researcher → Verifier failed {retries + 1}× → "
            "Adjudicator unsure, escalated to human review."
        )
    if row["terminal_status"] == "escalated_captcha":
        return "Pipeline blocked by CAPTCHA / 403. Escalated to human review."
    if row["terminal_status"] == "agent_failure":
        return "Agent threw an unrecoverable error during the run."
    if adjud:
        return f"Researcher → Verifier failed {retries + 1}× → Adjudicator decided."
    return "Path unknown."


def _render_card(row: pd.Series) -> None:
    chip = _status_chip(row["terminal_status"])
    title = f"**{row['question_id']} · {row['country_code']}** — {chip}"

    with st.container(border=True):
        # Top row: title + answer.
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(title)
            if pd.notna(row.get("dimension")):
                st.caption(
                    f"{row['dimension']} · {row['indicator']}"
                )
        with c2:
            answer = (row.get("final_answer") or "—").strip() or "—"
            st.markdown(f"### Answer: `{answer}`")

        # Question text.
        if pd.notna(row.get("question_text")):
            st.markdown("**Question**")
            st.markdown(f"> {row['question_text']}")

        # Why the swarm picked this answer.
        if pd.notna(row.get("final_answer_explanation")):
            st.markdown("**Why**")
            st.write(row["final_answer_explanation"])

        # Evidence block — the proof.
        if pd.notna(row.get("final_evidence_quote")):
            st.markdown("**Evidence**")
            st.markdown(f"> _{row['final_evidence_quote']}_")
        if pd.notna(row.get("final_source_url")):
            url = row["final_source_url"]
            st.markdown(f"**Source:** [{url}]({url})")

        # Path + verifier line.
        st.caption(_path_summary(row))

        verifier_verdict = row.get("verifier_verdict")
        if pd.notna(verifier_verdict):
            v_conf = row.get("verifier_confidence")
            v_strat = row.get("verifier_strategy") or "verifier-disprove"
            v_line = (
                f"Verifier ({v_strat}) returned **{verifier_verdict}** "
                f"with confidence {v_conf:.2f}."
                if pd.notna(v_conf)
                else f"Verifier ({v_strat}) returned **{verifier_verdict}**."
            )
            if row.get("substring_check_result") == "fail":
                v_line += " ⚠️ Substring check failed (quote not present on the page)."
            st.caption(v_line)

        # If Verifier ever pushed back, show what it said.
        rejection = row.get("rejection_reason")
        if pd.notna(rejection) and str(rejection).strip():
            with st.expander("Verifier counter-position"):
                st.markdown(f"**Rejection reason:** {rejection}")
                quote = row.get("counter_evidence_quote")
                if pd.notna(quote) and str(quote).strip():
                    st.markdown(f"> _{quote}_")
                c_url = row.get("counter_source_url")
                if pd.notna(c_url) and str(c_url).strip():
                    st.markdown(f"**Counter source:** [{c_url}]({c_url})")

        # Tech details.
        with st.expander("Technical details"):
            ans_conf = row.get("final_answer_confidence")
            retr_conf = row.get("final_retrieval_confidence")
            cost = row.get("cumulative_cost_usd")
            ms = row.get("cumulative_wall_clock_ms")
            cols = st.columns(4)
            with cols[0]:
                st.metric(
                    "Answer conf.",
                    f"{ans_conf:.2f}" if pd.notna(ans_conf) else "—",
                )
            with cols[1]:
                st.metric(
                    "Retrieval conf.",
                    f"{retr_conf:.2f}" if pd.notna(retr_conf) else "—",
                )
            with cols[2]:
                st.metric(
                    "Cost",
                    f"${cost:.4f}" if pd.notna(cost) else "—",
                )
            with cols[3]:
                st.metric(
                    "Wall clock",
                    f"{ms / 1000:.1f}s" if pd.notna(ms) else "—",
                )
            st.caption(
                f"pair_run_id `{row['pair_run_id']}` · "
                f"created_at {row['created_at']}"
            )


def render_cards_tab() -> None:
    cards = db.result_cards()
    if len(cards) == 0:
        st.info(
            "No finalised pairs yet. Release a subtrio from the Run "
            "Console to see results here."
        )
        return

    # Filters — keep them light so the page stays scannable.
    fcol1, fcol2, fcol3 = st.columns([1, 1, 2])
    with fcol1:
        countries = sorted(cards["country_code"].dropna().unique().tolist())
        c_filter = st.multiselect(
            "Country", countries, default=countries, key="cards_country",
        )
    with fcol2:
        statuses = sorted(cards["terminal_status"].dropna().unique().tolist())
        s_filter = st.multiselect(
            "Outcome", statuses,
            default=statuses,
            format_func=lambda s: s.replace("_", " ").title(),
            key="cards_status",
        )
    with fcol3:
        text_filter = st.text_input(
            "Search question text or question_id",
            key="cards_text",
            placeholder="e.g. portal, P21, sparql",
        )

    filtered = cards[
        cards["country_code"].isin(c_filter)
        & cards["terminal_status"].isin(s_filter)
    ]
    if text_filter:
        needle = text_filter.lower()
        filtered = filtered[
            filtered["question_id"].str.lower().str.contains(needle, na=False)
            | filtered["question_text"]
                .fillna("").str.lower().str.contains(needle, na=False)
        ]

    st.caption(
        f"{len(filtered)} of {len(cards)} finalised pairs. "
        "Newest first."
    )

    for _, row in filtered.iterrows():
        _render_card(row)


# ============================================================
# Raw tables (unchanged — kept for the audit trail)
# ============================================================

def render_raw_researcher_tab() -> None:
    rdf = db.researcher_runs(limit=500)
    if len(rdf) == 0:
        st.info("No Researcher runs yet.")
        return
    col1, col2, col3 = st.columns(3)
    with col1:
        countries = sorted(rdf["country_code"].dropna().unique().tolist())
        country_filter = st.multiselect(
            "Country", countries, default=countries, key="r_country",
        )
    with col2:
        answers = sorted(rdf["answer"].dropna().unique().tolist())
        answer_filter = st.multiselect(
            "Answer", answers, default=answers, key="r_answer",
        )
    with col3:
        models = sorted(rdf["model_version"].dropna().unique().tolist())
        model_filter = st.multiselect(
            "Model", models, default=models, key="r_model",
        )
    filtered = rdf[
        rdf["country_code"].isin(country_filter)
        & rdf["answer"].isin(answer_filter)
        & rdf["model_version"].isin(model_filter)
    ]
    st.caption(f"{len(filtered)} of {len(rdf)} rows shown.")
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    if len(filtered) > 0:
        picked = st.selectbox(
            "Inspect row id", [None] + filtered["id"].tolist(),
            format_func=lambda v: "select…" if v is None else str(v),
            key="r_inspect",
        )
        if picked is not None:
            row = filtered[filtered["id"] == picked].iloc[0]
            with st.expander(
                f"Row {picked} — {row['question_id']}/{row['country_code']}",
                expanded=True,
            ):
                st.json(row.to_dict())


def render_raw_verifier_tab() -> None:
    vdf = db.verifier_runs(limit=500)
    if len(vdf) == 0:
        st.info("No Verifier runs yet.")
        return
    col1, col2, col3 = st.columns(3)
    with col1:
        strategies = sorted(vdf["strategy_label"].dropna().unique().tolist())
        strat_filter = st.multiselect(
            "Strategy", strategies, default=strategies, key="v_strat",
        )
    with col2:
        verdicts = sorted(vdf["verdict"].dropna().unique().tolist())
        v_filter = st.multiselect(
            "Verdict", verdicts, default=verdicts, key="v_verdict",
        )
    with col3:
        countries = sorted(vdf["country_code"].dropna().unique().tolist())
        c_filter = st.multiselect(
            "Country", countries, default=countries, key="v_country",
        )
    filtered = vdf[
        vdf["strategy_label"].isin(strat_filter)
        & vdf["verdict"].isin(v_filter)
        & vdf["country_code"].isin(c_filter)
    ]
    st.caption(f"{len(filtered)} of {len(vdf)} rows shown.")
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    if len(filtered) > 0:
        picked = st.selectbox(
            "Inspect row id", [None] + filtered["id"].tolist(),
            format_func=lambda v: "select…" if v is None else str(v),
            key="v_inspect",
        )
        if picked is not None:
            row = filtered[filtered["id"] == picked].iloc[0]
            with st.expander(
                f"Row {picked} — {row['question_id']}/{row['country_code']}",
                expanded=True,
            ):
                st.json(row.to_dict())


def render_raw_finals_tab() -> None:
    fdf = db.finals(limit=500)
    if len(fdf) == 0:
        st.info("No finalised pairs yet. Run a Coordinator pass.")
        return
    col1, col2 = st.columns(2)
    with col1:
        statuses = sorted(fdf["terminal_status"].dropna().unique().tolist())
        status_filter = st.multiselect(
            "Terminal status", statuses, default=statuses, key="f_status",
        )
    with col2:
        countries = sorted(fdf["country_code"].dropna().unique().tolist())
        c_filter = st.multiselect(
            "Country", countries, default=countries, key="f_country",
        )
    filtered = fdf[
        fdf["terminal_status"].isin(status_filter)
        & fdf["country_code"].isin(c_filter)
    ]
    st.caption(f"{len(filtered)} of {len(fdf)} rows shown.")
    st.dataframe(filtered, use_container_width=True, hide_index=True)


# ============================================================
# Layout
# ============================================================

tab_cards, tab_r, tab_v, tab_f = st.tabs(
    ["Cards", "Researcher runs", "Verifier runs", "Finals"]
)

with tab_cards:
    render_cards_tab()
with tab_r:
    render_raw_researcher_tab()
with tab_v:
    render_raw_verifier_tab()
with tab_f:
    render_raw_finals_tab()
