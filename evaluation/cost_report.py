#!/usr/bin/env python3
"""Cost surface over live data (rebuilds the stale June Malta-only figures).

Computes four analyses and writes each as a hand-rolled SVG plus a single
markdown summary with the numbers behind them:

  a. cost_frontier        mean cost/pair (GBP) vs committed accuracy, one
                           marker per completed experiment arm and one per
                           main-run country with n >= 20.
  b. cost_role_share      total spend share by LLM-call role.
  c. cost_per_correct_country  main runs, cost per committed-correct answer,
                           per country with n >= 20 finals.
  d. cost_by_dimension    main runs, mean cost/pair by ODMI dimension.

Cost source split (D12/D20 schema):
  - `claude_usage_log` is the per-call receipt (role/context, tokens, cost),
    but only rows with a `subtrio_id` join back to a pair. The dominant
    `snippet_pick` and `search_adjudicate` contexts never carry a
    `subtrio_id`, so role-share (b) uses `claude_usage_log` directly (it does
    not need to join to a pair) while the per-arm/per-country/per-dimension
    figures (a, c, d) use `phase2_final.cumulative_cost_usd`, which already
    sums every role's spend for that pair regardless of subtrio_id linkage.
  - Match/accuracy logic replicates `dashboard/lib/db.py::_MATCH_STATUS_SQL`
    verbatim (not imported, to keep this script Streamlit-free per the task).

Usage:
    uv run python evaluation/cost_report.py
    uv run python evaluation/cost_report.py --db /path/to/odmi.db \\
        --figures-dir docs/figures --out docs/COST_SURFACE.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "odmi.db"
FIGURES_DIR = REPO / "docs" / "figures"
OUT_PATH = REPO / "docs" / "COST_SURFACE.md"

USD_TO_GBP = 0.79  # dashboard/lib/currency.py, last reviewed 2026-05-13

MIN_N_COUNTRY = 20
MIN_N_DIMENSION = 1  # dimensions are always well populated in main runs

# D57 / stalled / absent arms excluded per task brief. exp29 is absent from
# the DB entirely (0 phase2_final rows) so it drops out on its own; it is
# listed here anyway for documentation.
EXCLUDED_EXPERIMENTS = {
    "exp19_verifier_search_multicountry",  # still running
    "exp20_chaining_committing",           # still running
    "exp18_breadth_multicountry",          # still running
    "exp21_frozen_headline",               # voided per D57 (superseded by exp31)
    "exp28_arch_ablation",                 # absent / not requested
    "exp29_sonnet5_model",                 # absent (0 finals)
    "smoke_nl",                            # smoke test
    "smoketest-001",                       # smoke test
    "retry_chaining_mt_v1_aborted",        # aborted arm
    "model_variants_mt",                   # stalled, 21 finals
}

INCLUDED_EXPERIMENT_PREFIXES = (
    "exp14",
    "exp16",
    "exp17_breadth_nl",
    "exp17_picker_nl",
    "exp22_foreign_lang_al",
    "expA_calibration_anchors",
    "expB_verifier_fit_check",
    "expC_neg_evidence_licence",
    "retry_chaining_mt_v1",
)


def _included_experiment(experiment_id: str) -> bool:
    if experiment_id in EXCLUDED_EXPERIMENTS:
        return False
    return any(experiment_id.startswith(p) for p in INCLUDED_EXPERIMENT_PREFIXES)


# Replicates dashboard/lib/db.py::_MATCH_STATUS_SQL verbatim. Kept as a
# literal copy (not imported) so this script has no dependency on Streamlit
# or the dashboard package.
_MATCH_STATUS_SQL = """
    CASE
      WHEN gt.response IS NULL OR TRIM(gt.response) = ''
        THEN 'no_ground_truth'
      WHEN f.final_answer IS NULL OR TRIM(f.final_answer) = ''
        THEN 'no_swarm_answer'
      WHEN REPLACE(LOWER(TRIM(gt.response)), '_', ' ') IN
             ('not applicable', 'n/a', 'na')
        THEN CASE
          WHEN LOWER(TRIM(f.final_answer)) = 'inconclusive'
               OR REPLACE(LOWER(TRIM(f.final_answer)), '_', ' ') IN
                    ('not applicable', 'n/a', 'na')
            THEN 'match'
          ELSE 'flag_review'
        END
      WHEN LOWER(TRIM(f.final_answer)) = 'inconclusive'
        THEN 'abstained'
      WHEN REPLACE(LOWER(TRIM(f.final_answer)), '_', ' ')
           = REPLACE(LOWER(TRIM(gt.response)), '_', ' ')
        THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'yes'
           AND (LOWER(TRIM(gt.response)) LIKE 'yes%')
           AND EXISTS (
             SELECT 1 FROM questions q
             WHERE q.question_id = f.question_id
               AND q.answer_shape = 'binary'
           )
        THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'no'
           AND LOWER(TRIM(gt.response)) = 'no'
        THEN 'match'
      WHEN EXISTS (
        SELECT 1
        FROM questions q,
             json_each(q.allowed_answers) ja_swarm,
             json_each(q.allowed_answers) ja_gt
        WHERE q.question_id = f.question_id
          AND q.answer_shape IN ('percentage_band',
                                  'ordinal_magnitude',
                                  'count_band')
          AND ABS(ja_swarm.key - ja_gt.key) = 1
          AND LOWER(TRIM(ja_swarm.value)) = LOWER(TRIM(f.final_answer))
          AND LOWER(TRIM(ja_gt.value)) = LOWER(TRIM(gt.response))
          AND LOWER(TRIM(ja_swarm.value)) NOT IN
                ('not applicable', 'i don''t know', 'inconclusive', 'other')
          AND LOWER(TRIM(ja_gt.value)) NOT IN
                ('not applicable', 'i don''t know', 'inconclusive', 'other')
      )
        THEN 'near_match'
      ELSE 'differ'
    END
"""

# One phase2_final row per (question, country, experiment_id): the latest
# by id. Mirrors dashboard/lib/db.py::_LATEST_FINALS.
_LATEST_FINALS = """(
    SELECT * FROM phase2_final
    WHERE id IN (
        SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY question_id, country_code, experiment_id
                ORDER BY id DESC
            ) AS _rn
            FROM phase2_final
        ) WHERE _rn = 1
    )
)"""


def connect_ro(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only. Never write."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def gbp(usd: float | None) -> float:
    return (usd or 0.0) * USD_TO_GBP


# ============================================================
# Data pulls
# ============================================================

def fetch_experiment_arms(conn: sqlite3.Connection) -> list[dict]:
    """One row per (experiment_id, condition_label) completed arm.

    n = committed pairs, ground-truth pairs only, mean_cost_gbp = mean
    cumulative_cost_usd -> GBP over those pairs, accuracy = committed
    accuracy (match / (match+near+differ+abstained)). condition_label
    comes from phase2_researcher_runs at retry_count = 0, joined by
    pair_run_id (subtrio_status carries no condition_label column).

    Uses raw `phase2_final` (not the `_LATEST_FINALS` dedup view): that
    view collapses by (question_id, country_code, experiment_id), which is
    right for main runs but wrong here, since a two-arm experiment runs the
    *same* (question, country) pair once per arm under one experiment_id --
    deduping on that key would silently drop one arm's row for every pair
    the two arms share. `phase2_final.pair_run_id` is already UNIQUE per
    schema, so no re-dispatch duplication exists to dedup within an arm.
    """
    rows = conn.execute(
        f"""
        SELECT f.experiment_id,
               r.condition_label,
               COUNT(*) AS n,
               AVG(f.cumulative_cost_usd) AS mean_cost_usd,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'match' THEN 1 ELSE 0 END) AS n_match,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'near_match' THEN 1 ELSE 0 END) AS n_near,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'differ' THEN 1 ELSE 0 END) AS n_differ,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'abstained' THEN 1 ELSE 0 END) AS n_abstained
        FROM phase2_final f
        JOIN phase2_researcher_runs r
          ON r.pair_run_id = f.pair_run_id AND r.retry_count = 0
        LEFT JOIN ground_truth gt
          ON gt.question_id = f.question_id AND gt.country_code = f.country_code
        WHERE f.experiment_id IS NOT NULL
          AND gt.response IS NOT NULL AND TRIM(gt.response) != ''
        GROUP BY f.experiment_id, r.condition_label
        ORDER BY f.experiment_id, r.condition_label
        """
    ).fetchall()
    out = []
    for r in rows:
        if not _included_experiment(r["experiment_id"]):
            continue
        n_match = int(r["n_match"] or 0)
        n_near = int(r["n_near"] or 0)
        n_differ = int(r["n_differ"] or 0)
        n_abst = int(r["n_abstained"] or 0)
        denom = n_match + n_near + n_differ + n_abst
        out.append({
            "label": f"{r['experiment_id']}/{r['condition_label']}",
            "experiment_id": r["experiment_id"],
            "condition_label": r["condition_label"],
            "n": int(r["n"]),
            "n_scored": denom,
            "mean_cost_gbp": gbp(r["mean_cost_usd"]),
            "accuracy": (n_match / denom) if denom else None,
        })
    return out


def fetch_main_run_countries(conn: sqlite3.Connection, min_n: int = MIN_N_COUNTRY) -> list[dict]:
    """Main runs (experiment_id IS NULL), per country with n >= min_n finals."""
    rows = conn.execute(
        f"""
        SELECT f.country_code,
               COUNT(*) AS n,
               AVG(f.cumulative_cost_usd) AS mean_cost_usd,
               SUM(f.cumulative_cost_usd) AS total_cost_usd,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'match' THEN 1 ELSE 0 END) AS n_match,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'near_match' THEN 1 ELSE 0 END) AS n_near,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'differ' THEN 1 ELSE 0 END) AS n_differ,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'abstained' THEN 1 ELSE 0 END) AS n_abstained
        FROM {_LATEST_FINALS} f
        LEFT JOIN ground_truth gt
          ON gt.question_id = f.question_id AND gt.country_code = f.country_code
        WHERE f.experiment_id IS NULL
        GROUP BY f.country_code
        HAVING COUNT(*) >= ?
        ORDER BY f.country_code
        """,
        (min_n,),
    ).fetchall()
    out = []
    for r in rows:
        n_match = int(r["n_match"] or 0)
        n_near = int(r["n_near"] or 0)
        n_differ = int(r["n_differ"] or 0)
        n_abst = int(r["n_abstained"] or 0)
        denom = n_match + n_near + n_differ + n_abst
        out.append({
            "label": r["country_code"],
            "country_code": r["country_code"],
            "n": int(r["n"]),
            "n_scored": denom,
            "n_match": n_match,
            "mean_cost_gbp": gbp(r["mean_cost_usd"]),
            "total_cost_gbp": gbp(r["total_cost_usd"]),
            "accuracy": (n_match / denom) if denom else None,
        })
    return out


def fetch_role_share(conn: sqlite3.Connection) -> list[dict]:
    """Total spend share by role, from claude_usage_log directly.

    Role = context prefix before the first ':'. `verifier_<strategy>`
    contexts collapse to `verifier`; `exp6_*` legacy rows are dropped.
    """
    rows = conn.execute(
        """
        SELECT context, estimated_cost_usd
        FROM claude_usage_log
        WHERE context IS NOT NULL
        """
    ).fetchall()
    totals: dict[str, float] = {}
    for r in rows:
        ctx = r["context"] or ""
        prefix = ctx.split(":", 1)[0]
        if prefix.startswith("exp6_"):
            continue  # legacy rows, ignore per task brief
        if prefix.startswith("verifier_") and prefix not in ("verifier_query_gen",):
            role = "verifier"
        else:
            role = prefix
        totals[role] = totals.get(role, 0.0) + (r["estimated_cost_usd"] or 0.0)
    grand_total = sum(totals.values())
    out = [
        {
            "role": role,
            "total_cost_gbp": gbp(cost),
            "share": (cost / grand_total) if grand_total else 0.0,
        }
        for role, cost in totals.items()
    ]
    out.sort(key=lambda d: d["total_cost_gbp"], reverse=True)
    return out


def fetch_by_dimension(conn: sqlite3.Connection) -> list[dict]:
    """Main runs, mean cost/pair by ODMI dimension (questions.dimension)."""
    rows = conn.execute(
        f"""
        SELECT q.dimension AS dimension,
               COUNT(*) AS n,
               AVG(f.cumulative_cost_usd) AS mean_cost_usd,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'match' THEN 1 ELSE 0 END) AS n_match,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'near_match' THEN 1 ELSE 0 END) AS n_near,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'differ' THEN 1 ELSE 0 END) AS n_differ,
               SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'abstained' THEN 1 ELSE 0 END) AS n_abstained
        FROM {_LATEST_FINALS} f
        LEFT JOIN questions q ON q.question_id = f.question_id
        LEFT JOIN ground_truth gt
          ON gt.question_id = f.question_id AND gt.country_code = f.country_code
        WHERE f.experiment_id IS NULL AND q.dimension IS NOT NULL
        GROUP BY q.dimension
        ORDER BY q.dimension
        """
    ).fetchall()
    out = []
    for r in rows:
        n_match = int(r["n_match"] or 0)
        n_near = int(r["n_near"] or 0)
        n_differ = int(r["n_differ"] or 0)
        n_abst = int(r["n_abstained"] or 0)
        denom = n_match + n_near + n_differ + n_abst
        out.append({
            "dimension": r["dimension"],
            "n": int(r["n"]),
            "n_scored": denom,
            "mean_cost_gbp": gbp(r["mean_cost_usd"]),
            "accuracy": (n_match / denom) if denom else None,
        })
    return out


def fetch_overall_totals(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(estimated_cost_usd) AS cost, "
        "MIN(timestamp) AS mn, MAX(timestamp) AS mx FROM claude_usage_log"
    ).fetchone()
    return {
        "n_calls": int(row["n"] or 0),
        "total_cost_gbp": gbp(row["cost"]),
        "earliest": row["mn"],
        "latest": row["mx"],
    }


# ============================================================
# SVG rendering (dependency-free, style follows evaluation/risk_coverage.py)
# ============================================================

def _svg_header(w: int, h: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Helvetica, Arial, sans-serif">\n'
        f'  <rect width="{w}" height="{h}" fill="white"/>\n'
        f'  <text x="{w/2}" y="24" text-anchor="middle" font-size="14" '
        f'fill="#222">{title}</text>\n'
    )


def render_cost_frontier(arms: list[dict], countries: list[dict], path: Path) -> None:
    """Scatter: x = mean cost/pair (GBP), y = committed accuracy."""
    pts = [p for p in (arms + countries) if p["accuracy"] is not None]
    if not pts:
        return
    W, H, M = 760, 520, 70
    max_cost = max(p["mean_cost_gbp"] for p in pts) or 1.0
    max_cost *= 1.15

    def sx(c):
        return M + (c / max_cost) * (W - 2 * M)

    def sy(a):
        return H - M - a * (H - 2 * M)

    grid = []
    for gy in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        y = sy(gy)
        grid.append(
            f'<line x1="{M}" y1="{y:.1f}" x2="{W-M}" y2="{y:.1f}" '
            f'stroke="#ddd" stroke-width="1"/>'
            f'<text x="{M-8}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#555">{gy:.0%}</text>'
        )
    n_xticks = 6
    for i in range(n_xticks + 1):
        gx = max_cost * i / n_xticks
        x = sx(gx)
        grid.append(
            f'<line x1="{x:.1f}" y1="{M}" x2="{x:.1f}" y2="{H-M}" '
            f'stroke="#eee" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{H-M+18}" text-anchor="middle" '
            f'font-size="11" fill="#555">£{gx:.2f}</text>'
        )

    dots = []
    for p in pts:
        is_country = "country_code" in p
        colour = "#2471a3" if is_country else "#c0392b"
        x, y = sx(p["mean_cost_gbp"]), sy(p["accuracy"])
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{colour}" '
            f'fill-opacity="0.85"/>'
            f'<text x="{x+8:.1f}" y="{y-8:.1f}" font-size="9.5" '
            f'fill="#222">{p["label"]}</text>'
        )

    svg = _svg_header(W, H, "Cost-accuracy frontier: mean cost/pair vs committed accuracy")
    svg += "".join(grid)
    svg += "".join(dots)
    svg += (
        f'  <circle cx="{M+10}" cy="{H-20}" r="5" fill="#c0392b"/>'
        f'<text x="{M+22}" y="{H-16}" font-size="11" fill="#333">Experiment arm</text>'
        f'  <circle cx="{M+150}" cy="{H-20}" r="5" fill="#2471a3"/>'
        f'<text x="{M+162}" y="{H-16}" font-size="11" fill="#333">Main-run country (n&gt;=20)</text>'
    )
    svg += (
        f'  <text x="{W/2}" y="{H-42}" text-anchor="middle" font-size="12" '
        f'fill="#333">Mean cost per pair (GBP)</text>\n'
        f'  <text x="18" y="{H/2}" font-size="12" fill="#333" '
        f'transform="rotate(-90 18 {H/2})">Committed accuracy (match rate)</text>\n'
        f'</svg>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)


ROLE_COLOURS = {
    "snippet_pick": "#7f8c8d",
    "researcher": "#c0392b",
    "researcher_query_gen": "#e67e22",
    "verifier": "#2471a3",
    "verifier_query_gen": "#5dade2",
    "adjudicator": "#27ae60",
    "search_adjudicate": "#8e44ad",
}


def render_role_share(roles: list[dict], path: Path) -> None:
    """Horizontal stacked bar: total spend share by role."""
    W, H, M = 700, 220, 90
    total = sum(r["total_cost_gbp"] for r in roles) or 1.0
    bar_y, bar_h = 90, 60
    x = M
    segs = []
    legend = []
    for i, r in enumerate(roles):
        w = (r["total_cost_gbp"] / total) * (W - 2 * M)
        colour = ROLE_COLOURS.get(r["role"], "#34495e")
        segs.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w,0.5):.1f}" height="{bar_h}" '
            f'fill="{colour}" stroke="white" stroke-width="1"/>'
        )
        if w > 28:
            segs.append(
                f'<text x="{x+w/2:.1f}" y="{bar_y+bar_h/2+4}" text-anchor="middle" '
                f'font-size="10.5" fill="white">{r["share"]:.0%}</text>'
            )
        legend.append(
            f'<rect x="{M} " y="{170+16*i}" width="10" height="10" fill="{colour}"/>'
            f'<text x="{M+16}" y="{178+16*i}" font-size="10.5" fill="#333">'
            f'{r["role"]} (£{r["total_cost_gbp"]:.2f}, {r["share"]:.1%})</text>'
        )
        x += w
    H = 170 + 16 * len(roles) + 20
    svg = _svg_header(W, H, "Total spend share by LLM-call role")
    svg += "".join(segs)
    svg += "".join(legend)
    svg += "</svg>"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)


def render_cost_per_correct_country(countries: list[dict], path: Path) -> None:
    """Bar chart: total cost / n_match, per country, with n on each bar."""
    rows = [c for c in countries if c["n_match"] > 0]
    rows.sort(key=lambda c: c["country_code"])
    if not rows:
        return
    for c in rows:
        c["cost_per_correct_gbp"] = c["total_cost_gbp"] / c["n_match"]
    W = max(560, 110 * len(rows) + 120)
    H, M = 420, 70
    max_val = max(c["cost_per_correct_gbp"] for c in rows) * 1.2 or 1.0
    bar_w = (W - 2 * M) / len(rows) * 0.6
    slot_w = (W - 2 * M) / len(rows)

    def sy(v):
        return H - M - (v / max_val) * (H - 2 * M)

    grid = []
    for i in range(5):
        v = max_val * i / 4
        y = sy(v)
        grid.append(
            f'<line x1="{M}" y1="{y:.1f}" x2="{W-M}" y2="{y:.1f}" '
            f'stroke="#eee" stroke-width="1"/>'
            f'<text x="{M-8}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#555">£{v:.2f}</text>'
        )
    bars = []
    for i, c in enumerate(rows):
        cx = M + slot_w * i + slot_w / 2
        bh = H - M - sy(c["cost_per_correct_gbp"])
        y = sy(c["cost_per_correct_gbp"])
        bars.append(
            f'<rect x="{cx-bar_w/2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{bh:.1f}" fill="#16a085"/>'
            f'<text x="{cx:.1f}" y="{y-8:.1f}" text-anchor="middle" '
            f'font-size="11" fill="#222">£{c["cost_per_correct_gbp"]:.2f}</text>'
            f'<text x="{cx:.1f}" y="{H-M+18:.1f}" text-anchor="middle" '
            f'font-size="12" fill="#333">{c["country_code"]}</text>'
            f'<text x="{cx:.1f}" y="{H-M+32:.1f}" text-anchor="middle" '
            f'font-size="9.5" fill="#777">n={c["n_match"]}/{c["n_scored"]}</text>'
        )
    svg = _svg_header(W, H, "Cost per committed-correct answer, main runs (n>=20)")
    svg += "".join(grid)
    svg += "".join(bars)
    svg += (
        f'  <text x="{W/2}" y="{H-10}" text-anchor="middle" font-size="12" '
        f'fill="#333">Country (n = matches / scored pairs)</text>\n</svg>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)


def render_cost_by_dimension(dims: list[dict], path: Path) -> None:
    """Bar chart: mean cost/pair by ODMI dimension, main runs."""
    order = ["Policy", "Portal", "Quality", "Impact"]
    rows = sorted(dims, key=lambda d: order.index(d["dimension"]) if d["dimension"] in order else 9)
    if not rows:
        return
    W, H, M = 560, 400, 70
    max_val = max(r["mean_cost_gbp"] for r in rows) * 1.2 or 1.0
    slot_w = (W - 2 * M) / len(rows)
    bar_w = slot_w * 0.55

    def sy(v):
        return H - M - (v / max_val) * (H - 2 * M)

    grid = []
    for i in range(5):
        v = max_val * i / 4
        y = sy(v)
        grid.append(
            f'<line x1="{M}" y1="{y:.1f}" x2="{W-M}" y2="{y:.1f}" '
            f'stroke="#eee" stroke-width="1"/>'
            f'<text x="{M-8}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#555">£{v:.3f}</text>'
        )
    bars = []
    for i, r in enumerate(rows):
        cx = M + slot_w * i + slot_w / 2
        y = sy(r["mean_cost_gbp"])
        bh = H - M - y
        bars.append(
            f'<rect x="{cx-bar_w/2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{bh:.1f}" fill="#8e44ad"/>'
            f'<text x="{cx:.1f}" y="{y-8:.1f}" text-anchor="middle" '
            f'font-size="11" fill="#222">£{r["mean_cost_gbp"]:.3f}</text>'
            f'<text x="{cx:.1f}" y="{H-M+18:.1f}" text-anchor="middle" '
            f'font-size="12" fill="#333">{r["dimension"]}</text>'
            f'<text x="{cx:.1f}" y="{H-M+32:.1f}" text-anchor="middle" '
            f'font-size="9.5" fill="#777">n={r["n"]}</text>'
        )
    svg = _svg_header(W, H, "Mean cost per pair by ODMI dimension, main runs")
    svg += "".join(grid)
    svg += "".join(bars)
    svg += (
        f'  <text x="{W/2}" y="{H-10}" text-anchor="middle" font-size="12" '
        f'fill="#333">ODMI dimension (n = finalised pairs)</text>\n</svg>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)


# ============================================================
# Markdown summary
# ============================================================

def _fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "-"


def write_summary(
    out_path: Path,
    totals: dict,
    arms: list[dict],
    countries: list[dict],
    roles: list[dict],
    dims: list[dict],
) -> None:
    lines = []
    lines.append("# Cost surface")
    lines.append("")
    lines.append(
        "Rebuilt over the canonical DB (`data/odmi.db`), superseding the "
        "June Malta-only cost figures. Figures in `docs/figures/`."
    )
    lines.append("")
    lines.append(
        f"Total spend across all logged LLM calls: "
        f"£{totals['total_cost_gbp']:.2f} ({totals['n_calls']:,} calls, "
        f"{totals['earliest']} to {totals['latest']})."
    )
    lines.append("")

    lines.append("## a. Cost-accuracy frontier (`cost_frontier.svg`)")
    lines.append("")
    lines.append(
        "Method: committed pairs per experiment arm (`condition_label` from "
        "`phase2_researcher_runs`, retry_count 0) and per main-run country "
        "with n >= 20 finals, joined to ground truth. Accuracy is match / "
        "(match + near_match + differ + abstained). Excludes still-running "
        "arms (exp18/19/20), exp21 (voided, D57), exp28/29 (absent or "
        "not requested), and smoke/aborted/stalled runs (smoke_nl, "
        "smoketest-001, retry_chaining_mt_v1_aborted, model_variants_mt)."
    )
    lines.append("")
    lines.append("| Arm | n | n scored | mean cost/pair (GBP) | accuracy |")
    lines.append("|---|---|---|---|---|")
    for a in arms:
        lines.append(
            f"| {a['label']} | {a['n']} | {a['n_scored']} | "
            f"£{a['mean_cost_gbp']:.4f} | {_fmt_pct(a['accuracy'])} |"
        )
    lines.append("")
    lines.append("| Country (main run) | n | n scored | mean cost/pair (GBP) | accuracy |")
    lines.append("|---|---|---|---|---|")
    for c in countries:
        lines.append(
            f"| {c['country_code']} | {c['n']} | {c['n_scored']} | "
            f"£{c['mean_cost_gbp']:.4f} | {_fmt_pct(c['accuracy'])} |"
        )
    lines.append("")

    lines.append("## b. Spend share by role (`cost_role_share.svg`)")
    lines.append("")
    lines.append(
        "Method: every row in `claude_usage_log`, grouped by context prefix "
        "(role). `verifier_<strategy>` rows collapse to `verifier`. Legacy "
        "`exp6_*` rows excluded. Role totals do not require a `subtrio_id` "
        "join, so this table covers `snippet_pick` and `search_adjudicate` "
        "calls that the per-arm/per-country/per-dimension tables below "
        "cannot reach (those calls carry no subtrio_id)."
    )
    lines.append("")
    lines.append("| Role | total cost (GBP) | share |")
    lines.append("|---|---|---|")
    for r in roles:
        lines.append(f"| {r['role']} | £{r['total_cost_gbp']:.2f} | {r['share']:.1%} |")
    lines.append("")

    lines.append("## c. Cost per committed-correct answer, by country (`cost_per_correct_country.svg`)")
    lines.append("")
    lines.append(
        "Method: main runs only (`experiment_id IS NULL`), countries with "
        "n >= 20 finals. Cost per correct = total `cumulative_cost_usd` "
        "for the country divided by the number of committed matches."
    )
    lines.append("")
    lines.append("| Country | n finals | n scored | n match | total cost (GBP) | cost per correct (GBP) |")
    lines.append("|---|---|---|---|---|---|")
    for c in countries:
        cpc = (c["total_cost_gbp"] / c["n_match"]) if c["n_match"] else None
        cpc_s = f"£{cpc:.2f}" if cpc is not None else "-"
        lines.append(
            f"| {c['country_code']} | {c['n']} | {c['n_scored']} | "
            f"{c['n_match']} | £{c['total_cost_gbp']:.2f} | {cpc_s} |"
        )
    lines.append("")

    lines.append("## d. Mean cost per pair by ODMI dimension (`cost_by_dimension.svg`)")
    lines.append("")
    lines.append(
        "Method: main runs only, joined to `questions.dimension`. Mean of "
        "`cumulative_cost_usd` per finalised pair in that dimension."
    )
    lines.append("")
    lines.append("| Dimension | n | mean cost/pair (GBP) | accuracy |")
    lines.append("|---|---|---|---|")
    for d in dims:
        lines.append(
            f"| {d['dimension']} | {d['n']} | £{d['mean_cost_gbp']:.4f} | "
            f"{_fmt_pct(d['accuracy'])} |"
        )
    lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "Costs are notional subscription-equivalent pricing, not billed "
        "spend (D12/Q9); Opus pricing was backfilled 2026-06-25; rows "
        "before 2026-07-01 are Sonnet 4.6 era."
    )
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")


# ============================================================
# Main
# ============================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild the cost surface over live data")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--figures-dir", type=Path, default=FIGURES_DIR)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    conn = connect_ro(args.db)

    totals = fetch_overall_totals(conn)
    arms = fetch_experiment_arms(conn)
    countries = fetch_main_run_countries(conn)
    roles = fetch_role_share(conn)
    dims = fetch_by_dimension(conn)

    conn.close()

    render_cost_frontier(arms, countries, args.figures_dir / "cost_frontier.svg")
    render_role_share(roles, args.figures_dir / "cost_role_share.svg")
    render_cost_per_correct_country(countries, args.figures_dir / "cost_per_correct_country.svg")
    render_cost_by_dimension(dims, args.figures_dir / "cost_by_dimension.svg")
    write_summary(args.out, totals, arms, countries, roles, dims)

    print(f"total spend: £{totals['total_cost_gbp']:.2f} ({totals['n_calls']:,} calls)")
    print(f"experiment arms included: {len(arms)}")
    print(f"main-run countries (n>=20): {len(countries)}")
    print(f"roles: {len(roles)}")
    print(f"dimensions: {len(dims)}")
    print(f"wrote {args.figures_dir / 'cost_frontier.svg'}")
    print(f"wrote {args.figures_dir / 'cost_role_share.svg'}")
    print(f"wrote {args.figures_dir / 'cost_per_correct_country.svg'}")
    print(f"wrote {args.figures_dir / 'cost_by_dimension.svg'}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
