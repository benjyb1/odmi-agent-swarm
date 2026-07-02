#!/usr/bin/env python3
"""Risk-coverage analysis of the commit-confidence floor (selective prediction).

The D37 floor is a selective-prediction mechanism: raising it trades coverage
(share of pairs answered) for precision (share of answers matching gold).
This script sweeps the threshold over the finalised rows' confidences and
reports the risk-coverage table, plus an SVG figure for the report.

Rows counted: finalised pairs with a gold answer. At threshold t, a pair
counts as answered if its final answer is a real label AND its confidence is
at or above t; otherwise it counts as abstained. Precision is strict
(match / (match + differ)); a lenient variant folds near_match into match.

Usage:
    uv run python evaluation/risk_coverage.py
    uv run python evaluation/risk_coverage.py --experiment-id exp28_arch_ablation --condition-label trio_s5
    uv run python evaluation/risk_coverage.py --svg docs/figures/risk_coverage.svg
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "odmi.db"
sys.path.insert(0, str(REPO))

from dashboard.lib.db import _MATCH_STATUS_SQL  # noqa: E402

THRESHOLDS = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]


def fetch_rows(db: Path, experiment_id: str | None, condition_label: str | None):
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    where = ["gt.response IS NOT NULL", "TRIM(gt.response) != ''"]
    params: list = []
    if experiment_id:
        where.append("f.experiment_id = ?")
        params.append(experiment_id)
    else:
        where.append("f.experiment_id IS NULL")
    join_cond = ""
    if condition_label:
        join_cond = (
            " JOIN phase2_researcher_runs r ON r.pair_run_id = f.pair_run_id "
            "AND r.retry_count = 0 AND r.condition_label = ?"
        )
        params.insert(0, condition_label)
    rows = conn.execute(
        f"""
        SELECT f.final_answer, f.final_answer_confidence,
               ({_MATCH_STATUS_SQL}) AS match_status
        FROM phase2_final f
        {join_cond}
        JOIN ground_truth gt
          ON gt.question_id = f.question_id
         AND gt.country_code = f.country_code
        LEFT JOIN questions q ON q.question_id = f.question_id
        WHERE {' AND '.join(where)}
        """,
        params,
    ).fetchall()
    return rows


def sweep(rows):
    out = []
    n = len(rows)
    for t in THRESHOLDS:
        answered = [
            r for r in rows
            if r["match_status"] in ("match", "near_match", "differ")
            and (r["final_answer_confidence"] or 0.0) >= t
        ]
        match = sum(1 for r in answered if r["match_status"] == "match")
        near = sum(1 for r in answered if r["match_status"] == "near_match")
        differ = sum(1 for r in answered if r["match_status"] == "differ")
        denom = match + near + differ
        out.append({
            "threshold": t,
            "coverage": denom / n if n else 0.0,
            "precision_strict": match / denom if denom else None,
            "precision_lenient": (match + near) / denom if denom else None,
            "answered": denom,
            "n": n,
        })
    return out


def render_svg(table, path: Path, title: str):
    """Dependency-free risk-coverage SVG: precision (y) vs coverage (x)."""
    W, H, M = 640, 420, 60
    pts = [(r["coverage"], r["precision_strict"], r["threshold"])
           for r in table if r["precision_strict"] is not None]
    if not pts:
        return

    def sx(c):
        return M + c * (W - 2 * M)

    def sy(p):
        return H - M - (p - 0.4) / 0.6 * (H - 2 * M)  # y axis 0.4..1.0

    grid = []
    for gy in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        y = sy(gy)
        grid.append(
            f'<line x1="{M}" y1="{y:.1f}" x2="{W-M}" y2="{y:.1f}" '
            f'stroke="#ddd" stroke-width="1"/>'
            f'<text x="{M-8}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#555">{gy:.1f}</text>'
        )
    for gx in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        x = sx(gx)
        grid.append(
            f'<line x1="{x:.1f}" y1="{M}" x2="{x:.1f}" y2="{H-M}" '
            f'stroke="#eee" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{H-M+18}" text-anchor="middle" '
            f'font-size="11" fill="#555">{gx:.0%}</text>'
        )
    poly = " ".join(f"{sx(c):.1f},{sy(p):.1f}" for c, p, _ in sorted(pts))
    dots = "".join(
        f'<circle cx="{sx(c):.1f}" cy="{sy(p):.1f}" r="4" fill="#c0392b"/>'
        f'<text x="{sx(c)+7:.1f}" y="{sy(p)-7:.1f}" font-size="10" '
        f'fill="#333">{t:.2f}</text>'
        for c, p, t in pts
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"
     viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">
  <rect width="{W}" height="{H}" fill="white"/>
  <text x="{W/2}" y="24" text-anchor="middle" font-size="14"
        fill="#222">{title}</text>
  {''.join(grid)}
  <polyline points="{poly}" fill="none" stroke="#c0392b" stroke-width="2"/>
  {dots}
  <text x="{W/2}" y="{H-14}" text-anchor="middle" font-size="12"
        fill="#333">Coverage (share of gold pairs answered)</text>
  <text x="18" y="{H/2}" font-size="12" fill="#333"
        transform="rotate(-90 18 {H/2})">Precision (strict match)</text>
</svg>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Risk-coverage sweep (D37 floor)")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--experiment-id", default=None)
    ap.add_argument("--condition-label", default=None,
                    help="Restrict to one arm (needs --experiment-id).")
    ap.add_argument("--svg", type=Path, default=None)
    args = ap.parse_args()

    rows = fetch_rows(args.db, args.experiment_id, args.condition_label)
    table = sweep(rows)
    scope = args.condition_label or args.experiment_id or "main results"
    print(f"{scope}: {len(rows)} finalised gold pairs")
    print(f"{'floor':>6} {'coverage':>9} {'answered':>9} "
          f"{'prec(strict)':>13} {'prec(lenient)':>14}")
    for r in table:
        ps = f"{r['precision_strict']:.3f}" if r["precision_strict"] is not None else "-"
        pl = f"{r['precision_lenient']:.3f}" if r["precision_lenient"] is not None else "-"
        print(f"{r['threshold']:>6.2f} {r['coverage']:>9.3f} "
              f"{r['answered']:>9} {ps:>13} {pl:>14}")
    if args.svg:
        render_svg(table, args.svg, f"Risk-coverage: {scope}")
        print(f"wrote {args.svg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
