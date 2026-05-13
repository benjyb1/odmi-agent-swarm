"""Database — every (question, country) pair from ODMI, with the
latest swarm answer joined in. 5,148 rows. Filter by country,
dimension, indicator, or coverage status. Delete a pair's swarm rows
in-page when one needs a clean re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db, mode
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Database", page_icon="🗄", layout="wide")
page_header(
    "Database",
    "Every ODMI (question, country) pair from the 2025 cycle's "
    "merged_responses sheet, joined to the swarm's latest answer for "
    "the pair. Filter, scan coverage, delete bad results.",
)
render_session_widget()


# ============================================================
# Data
# ============================================================

grid = db.coverage_grid()

if len(grid) == 0:
    st.error(
        "No ODMI ground truth loaded. Run "
        "`uv run python scripts/load_ground_truth.py` first."
    )
    st.stop()


# ============================================================
# Coverage KPI strip
# ============================================================

n_total = len(grid)
n_covered = int((grid["swarm_runs"] > 0).sum())
n_match = int((grid["match_status"] == "match").sum())
n_differ = int((grid["match_status"] == "differ").sum())
denom = n_match + n_differ
accuracy = (n_match / denom) if denom > 0 else None

k1, k2, k3, k4 = st.columns(4)
k1.metric("Pairs in ODMI", f"{n_total:,}")
k2.metric(
    "Covered by swarm",
    f"{n_covered:,}",
    delta=f"{n_covered / n_total:.1%} of total",
    delta_color="off",
)
k3.metric("Match / Differ", f"{n_match} / {n_differ}")
k4.metric(
    "Accuracy vs ODMI",
    f"{accuracy:.0%}" if accuracy is not None else "—",
)


# ============================================================
# Filters
# ============================================================

st.divider()

f1, f2, f3, f4 = st.columns([1.3, 1, 1, 1])
with f1:
    all_countries = sorted(grid["country_code"].dropna().unique().tolist())
    selected_countries = st.multiselect(
        "Country",
        options=all_countries,
        default=all_countries,
        format_func=lambda c: (
            f"{c} — {grid[grid['country_code']==c]['country_name'].iloc[0]}"
            if c in all_countries else c
        ),
        key="db_country",
    )
with f2:
    all_dims = sorted(grid["dimension"].dropna().unique().tolist())
    selected_dims = st.multiselect(
        "Dimension", options=all_dims, default=all_dims, key="db_dim",
    )
with f3:
    coverage_filter = st.selectbox(
        "Coverage",
        options=["All", "Covered (has swarm run)",
                 "Not yet covered", "Matches ODMI", "Differs from ODMI"],
        key="db_coverage",
    )
with f4:
    text_filter = st.text_input(
        "Search Q / response",
        placeholder="e.g. P21, sparql, yes",
        key="db_search",
    )

filtered = grid[
    grid["country_code"].isin(selected_countries)
    & grid["dimension"].isin(selected_dims)
].copy()

if coverage_filter == "Covered (has swarm run)":
    filtered = filtered[filtered["swarm_runs"] > 0]
elif coverage_filter == "Not yet covered":
    filtered = filtered[filtered["swarm_runs"] == 0]
elif coverage_filter == "Matches ODMI":
    filtered = filtered[filtered["match_status"] == "match"]
elif coverage_filter == "Differs from ODMI":
    filtered = filtered[filtered["match_status"] == "differ"]

if text_filter:
    needle = text_filter.lower()
    filtered = filtered[
        filtered["question_id"].str.lower().str.contains(needle, na=False)
        | filtered["odmi_response"]
            .fillna("").astype(str).str.lower().str.contains(needle, na=False)
        | filtered["swarm_answer"]
            .fillna("").astype(str).str.lower().str.contains(needle, na=False)
    ]


# ============================================================
# Coverage by country (small bar)
# ============================================================

cov_per_country = (
    filtered.assign(covered=(filtered["swarm_runs"] > 0).astype(int))
    .groupby("country_code")["covered"].sum()
    .sort_values(ascending=False)
)
if len(cov_per_country) > 0 and cov_per_country.sum() > 0:
    with st.expander("Coverage per country (filtered)"):
        st.bar_chart(cov_per_country, horizontal=False)


# ============================================================
# The grid
# ============================================================

st.caption(
    f"{len(filtered):,} of {n_total:,} rows match the filters. "
    "Newest run first within each country."
)

display = filtered[[
    "question_id", "country_code", "dimension", "indicator",
    "odmi_response", "swarm_answer", "match_status",
    "swarm_runs", "last_run",
]].rename(columns={
    "question_id": "Q",
    "country_code": "Country",
    "dimension": "Dimension",
    "indicator": "Indicator",
    "odmi_response": "ODMI answer",
    "swarm_answer": "Swarm answer",
    "match_status": "vs ODMI",
    "swarm_runs": "Runs",
    "last_run": "Last run",
})
st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    height=min(640, 35 + 35 * len(display)),
    column_config={
        "vs ODMI": st.column_config.TextColumn(
            "vs ODMI", width="small",
            help="match / differ / no_ground_truth / no_swarm_answer.",
        ),
        "Runs": st.column_config.NumberColumn(
            "Runs", width="small",
            help="How many phase2_final rows exist for this pair.",
        ),
        "ODMI answer": st.column_config.TextColumn(width="medium"),
        "Swarm answer": st.column_config.TextColumn(width="small"),
    },
)


# ============================================================
# Delete a pair
# ============================================================

st.divider()
st.subheader("Delete a pair's swarm rows")
st.caption(
    "Removes every row from `phase2_final`, `phase2_adjudications`, "
    "`phase2_verifier_runs`, `phase2_researcher_runs`, and "
    "`subtrio_status` for the chosen pair. `claude_usage_log` is kept "
    "so cost audit stays intact. After deletion the pair counts as "
    "fresh on the Run Console."
)

covered_only = grid[grid["swarm_runs"] > 0].copy()
covered_only["pair_label"] = covered_only.apply(
    lambda r: f"{r['question_id']} / {r['country_code']} "
              f"(runs: {int(r['swarm_runs'])}, vs ODMI: {r['match_status']})",
    axis=1,
)

if len(covered_only) == 0:
    st.info("No covered pairs to delete.")
else:
    pair_label = st.selectbox(
        "Pair",
        options=[None] + covered_only["pair_label"].tolist(),
        format_func=lambda v: "pick a pair…" if v is None else v,
        key="db_delete_pick",
    )
    if pair_label:
        row = covered_only[covered_only["pair_label"] == pair_label].iloc[0]
        qid = row["question_id"]
        cc = row["country_code"]
        counts = db.pair_row_counts(qid, cc)
        total = sum(counts.values())
        st.write(
            f"**{qid} / {cc}** — about to delete **{total}** row(s) "
            "across the five swarm tables:"
        )
        st.write(
            {k: v for k, v in counts.items() if v > 0} or "(nothing to delete)"
        )
        confirm = st.checkbox(
            f"I want to delete every swarm row for {qid} / {cc}",
            key="db_delete_confirm",
        )
        if st.button(
            f"Delete {qid} / {cc} now",
            type="primary", disabled=not confirm,
            key="db_delete_go",
        ):
            if mode.block_if_read_only():
                st.stop()
            deleted = db.delete_pair(qid, cc)
            st.success(
                f"Deleted {sum(deleted.values())} row(s) for "
                f"{qid} / {cc}: {deleted}."
            )
            st.toast(f"Wiped {qid}/{cc}", icon="🗑")
            st.rerun()
