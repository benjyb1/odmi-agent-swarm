"""Analytics — slice the main-results dataset on any axis.

A read-only "slice and dice" view for the dissertation's main runs.
Filter by country / dimension / model / strategy / search provider,
then pick the axis to group by. The page renders a metrics table
plus a couple of charts so you can see match-rate, completion-rate,
rejection-rate, escalation-rate, mean cost and mean wall-clock
broken down by whichever variable you care about.

Strictly read-only. The Experimentation page (D27 Phase 2, not yet
built) covers tagged ablation runs separately; this page only sees
rows where `experiment_id IS NULL`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.currency import format_gbp, to_gbp
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Analytics", page_icon="📊", layout="wide")
page_header(
    "Analytics",
    "Filter the main results, then pick a group-by axis to compare "
    "match rate, completion rate, rejection rate, escalation rate, "
    "cost, and wall-clock side by side.",
)
render_session_widget()


# Pull the fat frame once per render

df_all = db.analytics_frame()
if len(df_all) == 0:
    st.warning("No finalised main-run pairs in the DB yet.")
    st.stop()

# Make NaNs explicit so the multiselects expose them and the user can
# include or exclude them by hand. Without this, a NaN researcher_model
# would be silently dropped by the filter chain.
_NULLABLE_COLS = [
    "country_code", "dimension", "researcher_model", "verifier_model",
    "adjudicator_model", "verifier_strategy", "search_provider", "indicator",
]
for _c in _NULLABLE_COLS:
    df_all[_c] = df_all[_c].fillna("(unknown)")


# Filter sidebar

st.sidebar.markdown("### Filters")


def _multi(label: str, col: str, default_all: bool = True) -> list:
    """Multiselect with 'all values present in column' as the default."""
    opts = sorted([v for v in df_all[col].dropna().unique().tolist()])
    if not opts:
        return []
    return st.sidebar.multiselect(
        label, opts,
        default=opts if default_all else [],
        key=f"filter_{col}",
    )


sel_countries = _multi("Country", "country_code")
sel_dimensions = _multi("ODMI dimension", "dimension")
sel_r_models = _multi("Researcher model", "researcher_model")
sel_v_models = _multi("Verifier model", "verifier_model")
sel_strategies = _multi("Verifier strategy", "verifier_strategy")
sel_providers = _multi("Search provider", "search_provider")


df = df_all[
    df_all["country_code"].isin(sel_countries)
    & df_all["dimension"].isin(sel_dimensions)
    & df_all["researcher_model"].isin(sel_r_models)
    & df_all["verifier_model"].isin(sel_v_models)
    & df_all["verifier_strategy"].isin(sel_strategies)
    & df_all["search_provider"].isin(sel_providers)
]

st.sidebar.markdown("---")
st.sidebar.caption(
    f"**{len(df):,}** of {len(df_all):,} finalised main-run pairs match "
    f"the current filters."
)


# Group-by selector

GROUP_OPTIONS = {
    "ODMI dimension":     "dimension",
    "Country":            "country_code",
    "Researcher model":   "researcher_model",
    "Verifier model":     "verifier_model",
    "Verifier strategy":  "verifier_strategy",
    "Search provider":    "search_provider",
    "Indicator":          "indicator",
    "Terminal status":    "terminal_status",
    "Retry count":        "retry_count",
}

col1, col2 = st.columns([2, 1])
with col1:
    group_label = st.selectbox(
        "Group by",
        list(GROUP_OPTIONS.keys()),
        index=0,
    )
with col2:
    min_n = st.number_input(
        "Min sample size",
        min_value=1, max_value=200, value=5, step=1,
        help="Groups smaller than this are hidden. Stops a single pair "
             "from looking like a 100% match rate.",
    )

group_col = GROUP_OPTIONS[group_label]

if len(df) == 0:
    st.info("No rows match the current filter.")
    st.stop()


# Per-group metrics

def _metrics(g: pd.DataFrame) -> pd.Series:
    n = len(g)
    n_with_truth = (g["odmi_response"].notna() & (g["odmi_response"] != "")).sum()
    n_match = (g["match_status"] == "match").sum()
    n_near = (g["match_status"] == "near_match").sum()
    n_differ = (g["match_status"] == "differ").sum()
    n_abstained = (g["match_status"] == "abstained").sum()
    n_agent_failure = (g["terminal_status"] == "agent_failure").sum()
    n_adj = int(g["adjudicator_involved"].sum())
    n_rejected = int(g["had_rejection"].sum())

    # D28: informative now includes near_match. `match %` is exact;
    # `within-band %` counts near-misses as success. D35/D37: abstentions
    # stay in the denominator (a failure to answer), reported on their own
    # as `abstain %`.
    informative = n_match + n_near + n_differ + n_abstained

    return pd.Series({
        "n": n,
        "match %": (100.0 * n_match / informative) if informative else float("nan"),
        "within-band %": (
            100.0 * (n_match + n_near) / informative
            if informative else float("nan")
        ),
        "abstain %": (
            100.0 * n_abstained / informative if informative else float("nan")
        ),
        "complete %": 100.0 * (n - n_agent_failure) / n,
        "rejection %": 100.0 * n_rejected / n,
        "escalation %": 100.0 * n_adj / n,
        "mean £": float(to_gbp(g["cumulative_cost_usd"].mean() or 0)),
        "mean s": (g["cumulative_wall_clock_ms"].mean() or 0) / 1000.0,
    })


grouped = df.groupby(group_col, dropna=False).apply(_metrics).round(2)
grouped = grouped[grouped["n"] >= min_n]
grouped = grouped.sort_values("match %", ascending=False)

st.subheader(f"Breakdown by {group_label.lower()}")
st.dataframe(
    grouped.style.format({
        "n": "{:.0f}",
        "match %": "{:.1f}",
        "within-band %": "{:.1f}",
        "complete %": "{:.1f}",
        "rejection %": "{:.1f}",
        "escalation %": "{:.1f}",
        "mean £": "£{:.3f}",
        "mean s": "{:.1f}s",
    }).bar(subset=["match %"], color="#9EE493"),
    use_container_width=True,
    height=min(50 + 38 * len(grouped), 500),
)


# Charts

if len(grouped) >= 2:
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("##### Match rate")
        st.bar_chart(grouped["match %"], height=320, use_container_width=True)
    with chart_col2:
        st.markdown("##### Rejection rate")
        st.bar_chart(grouped["rejection %"], height=320, use_container_width=True)

    # Stacked-bar style: terminal status mix by group.
    status_mix = (
        df.groupby([group_col, "terminal_status"])
          .size()
          .unstack(fill_value=0)
    )
    status_mix = status_mix.loc[grouped.index]  # drop groups under min_n
    status_pct = status_mix.div(status_mix.sum(axis=1), axis=0) * 100.0
    st.markdown(f"##### Terminal status mix by {group_label.lower()} (% of pairs)")
    st.bar_chart(status_pct, height=360, use_container_width=True)


# Drill: pairs in the current filter

with st.expander(f"Show the {len(df)} pairs behind these numbers", expanded=False):
    drill_cols = [
        "created_at", "question_id", "country_code", "dimension",
        "verifier_strategy", "search_provider",
        "final_answer", "odmi_response", "match_status",
        "terminal_status", "retry_count", "had_rejection",
        "cumulative_cost_usd",
    ]
    drill = df[drill_cols].copy()
    drill["cumulative_£"] = drill["cumulative_cost_usd"].apply(
        lambda x: format_gbp(x) if pd.notna(x) else ""
    )
    drill = drill.drop(columns=["cumulative_cost_usd"])
    st.dataframe(drill, use_container_width=True, height=400)


# Self-report (ODMI decision) stratification
# Production-wide and independent of the filters above: the headline figures
# split by ODMI's confirm / complement / change validation field (D22;
# docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md section 1A). ODMI is a country
# self-report questionnaire, so a swarm-vs-`confirm` disagreement on the
# country's unverifiable word is often a measurement mismatch, not a swarm
# error, whereas `complement` golds carry assessor desk-research evidence.

st.divider()
st.subheader("Accuracy by ODMI validation decision (self-report split)")
st.caption(
    "Production runs, all countries and shapes, not filtered by the controls "
    "above. `confirm` = the country's answer accepted as submitted, `complement` "
    "= kept with assessor-added desk-research evidence, `change` = assessor "
    "overrode. False positives (a committed `yes` on a `no` gold) concentrate on "
    "`confirm` golds, where the gold encodes the country's word, not the web."
)
_by_decision = db.accuracy_by_decision()
if _by_decision:
    _dec_rows = [
        {
            "decision": d["decision"],
            "n (with gold)": d["n_finalised"],
            "accuracy": f"{d['accuracy']:.0%}" if d["accuracy"] is not None else "-",
            "abstention": (
                f"{d['abstention_rate']:.0%}"
                if d["abstention_rate"] is not None else "-"
            ),
            "false positives": d["n_fp"],
            "committed negatives": d["n_committed_neg"],
            "FP rate": f"{d['fp_rate']:.0%}" if d["fp_rate"] is not None else "-",
        }
        for d in _by_decision
    ]
    st.dataframe(
        pd.DataFrame(_dec_rows), use_container_width=True, hide_index=True
    )
else:
    st.info("No ground-truth-joined production rows to stratify yet.")
