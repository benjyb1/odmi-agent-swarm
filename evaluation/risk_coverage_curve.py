"""Risk-coverage curve for the EXP-36 held-out headline, with a random-abstention null.

The canonical selective-prediction plot. Every committed, scoreable pair is
ranked by the confidence the swarm attached to its answer. Sweeping a threshold
down that ranking traces coverage (share of all 1,144 pairs answered) against
selective risk (error rate among the answers given).

Two reference marks make the plot readable as a claim rather than a shape:

  - **The random-abstention null.** If declining carried no information, the
    pairs dropped at any threshold would be a random sample of the committed
    set, so the error rate among survivors would not move. That null is a flat
    line at the full-coverage risk. A curve below it means the confidence
    signal ranks errors, which is the property selective prediction needs.
  - **AURC**, the area under the risk-coverage curve, normalised over the
    achievable coverage range so it is directly comparable to the null's area
    (the flat line's height). Lower is better.

Coverage is measured against all 1,144 pairs, so the curve ends at 0.545, not
1.0: the swarm abstains on 508 pairs and 13 more commit against an ODMI
`not applicable` gold and cannot be scored. The headline coverage of 0.556
counts those 13; this curve cannot, because risk is undefined for them.

The left tail is small-n and therefore noisy (at coverage 0.01 the risk is an
average over a dozen pairs), so the drawn curve starts at MIN_ACCEPTED
accepted pairs. AURC is computed over the full sweep regardless, so the
reported number does not depend on that drawing choice.

Outputs (under evaluation/figures/):
  - risk_coverage_curve.svg   the chart, self-contained for the manuscript
  - risk_coverage_curve.csv   the swept points (receipts)

Usage:
    uv run python evaluation/risk_coverage_curve.py
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.exp36_analysis import (  # noqa: E402
    dedup_canonical,
    is_committed,
    is_match,
    is_scoreable,
    load_rows,
)

EXPERIMENT_ID = "exp36_frozen_headline"
MIN_ACCEPTED = 10          # smallest accepted set that gets drawn
PRODUCTION_FLOOR = 0.65    # D37: the floor the run committed under

# Ink and palette (light surface), per the project's figure convention.
INK_TITLE = "#161616"
INK_BODY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CURVE = "#2a78d6"          # sequential blue: the swarm's own ranking
NULL = "#898781"           # neutral: the no-information reference
MARK = "#d03b3b"           # the operating point


def sweep(db_path: str) -> tuple[list[tuple[float, float, float]], int, int]:
    """Return (points, n_total, n_accepted).

    Each point is (coverage, selective_risk, threshold_confidence) after
    accepting the i highest-confidence committed scoreable pairs.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows, _ = dedup_canonical(load_rows(conn, EXPERIMENT_ID),
                                  scope_by_label=False)
    finally:
        conn.close()

    n_total = len(rows)
    accepted = [r for r in rows if is_committed(r) and is_scoreable(r)]
    # Rank by the confidence the swarm attached to its own answer, best first.
    accepted.sort(key=lambda r: -(r.final_confidence or 0.0))

    points: list[tuple[float, float, float]] = []
    errors = 0
    for i, row in enumerate(accepted, start=1):
        if not is_match(row):
            errors += 1
        points.append((i / n_total, errors / i, row.final_confidence or 0.0))
    return points, n_total, len(accepted)


def aurc(points: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Normalised area under the risk-coverage curve, and the null's area.

    Trapezoidal in coverage over the achievable range, divided by that range so
    the number is a coverage-weighted mean risk and sits on the same scale as
    the flat null.
    """
    area = 0.0
    prev_cov, prev_risk = 0.0, points[0][1]
    for cov, risk, _ in points:
        area += (cov - prev_cov) * (risk + prev_risk) / 2
        prev_cov, prev_risk = cov, risk
    max_cov = points[-1][0]
    return area / max_cov, points[-1][1]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(points, n_total, n_accepted, area, null_risk) -> str:
    width, height = 1040, 620
    x0, y0 = 96, 104               # plot area top-left
    pw, ph = 852, 372              # plot width / height
    x_max, y_max = 0.60, 0.35      # axis maxima

    def px(cov: float) -> float:
        return x0 + (cov / x_max) * pw

    def py(risk: float) -> float:
        return y0 + (1 - risk / y_max) * ph

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, \'Segoe UI\', sans-serif">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(
        f'<text x="26" y="38" font-size="21" font-weight="700" fill="{INK_TITLE}">'
        'Risk-coverage curve, held-out eight (EXP-36)</text>'
    )
    out.append(
        f'<text x="26" y="60" font-size="13" fill="{INK_BODY}">'
        'Selective risk against coverage, sweeping a threshold down the '
        'swarm&#8217;s own answer confidence. Lower is better.</text>'
    )
    out.append(
        f'<text x="26" y="80" font-size="13" fill="{INK_BODY}">'
        f'The curve sits below the random-abstention null, so confidence '
        f'ranks errors: <tspan font-weight="700">AURC {area:.3f}</tspan> '
        f'against a null of {null_risk:.3f}.</text>'
    )

    # Gridlines and axis ticks.
    for i in range(8):
        risk = y_max * i / 7
        y = py(risk)
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + pw}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x0 - 12}" y="{y + 4:.1f}" font-size="11.5" '
                   f'text-anchor="end" fill="{INK_MUTED}">{risk:.2f}</text>')
    for i in range(7):
        cov = x_max * i / 6
        x = px(cov)
        out.append(f'<text x="{x:.1f}" y="{y0 + ph + 22}" font-size="11.5" '
                   f'text-anchor="middle" fill="{INK_MUTED}">{cov:.2f}</text>')
    out.append(f'<line x1="{x0}" y1="{y0 + ph}" x2="{x0 + pw}" y2="{y0 + ph}" '
               f'stroke="{AXIS}" stroke-width="1"/>')
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0 + ph}" '
               f'stroke="{AXIS}" stroke-width="1"/>')

    # Axis titles.
    out.append(f'<text x="{x0 + pw / 2:.0f}" y="{y0 + ph + 48}" font-size="13" '
               f'text-anchor="middle" fill="{INK_BODY}">'
               f'Coverage (share of all {n_total:,} pairs answered)</text>')
    out.append(f'<text x="28" y="{y0 + ph / 2:.0f}" font-size="13" '
               f'text-anchor="middle" fill="{INK_BODY}" '
               f'transform="rotate(-90 28 {y0 + ph / 2:.0f})">'
               f'Selective risk (error rate among answers given)</text>')

    drawn = [p for p in points if p[0] * n_total >= MIN_ACCEPTED]

    # Area under the curve: the AURC made visible.
    area_pts = " ".join(f"{px(c):.1f},{py(r):.1f}" for c, r, _ in drawn)
    out.append(
        f'<polygon points="{px(drawn[0][0]):.1f},{py(0):.1f} {area_pts} '
        f'{px(drawn[-1][0]):.1f},{py(0):.1f}" fill="{CURVE}" opacity="0.10"/>'
    )

    # The random-abstention null.
    out.append(
        f'<line x1="{x0}" y1="{py(null_risk):.1f}" x2="{px(drawn[-1][0]):.1f}" '
        f'y2="{py(null_risk):.1f}" stroke="{NULL}" stroke-width="2" '
        f'stroke-dasharray="7 5"/>'
    )
    out.append(
        f'<text x="{px(0.055):.1f}" y="{py(null_risk) - 9:.1f}" font-size="12" '
        f'fill="{INK_BODY}">Random-abstention null '
        f'({null_risk:.3f}) &#8212; declining carries no information</text>'
    )

    # The curve.
    out.append(f'<polyline points="{area_pts}" fill="none" stroke="{CURVE}" '
               f'stroke-width="2" stroke-linejoin="round" '
               f'stroke-linecap="round"/>')

    # The production operating point: the full committed set.
    ox, oy = px(drawn[-1][0]), py(drawn[-1][1])
    out.append(f'<circle cx="{ox:.1f}" cy="{oy:.1f}" r="6" fill="{MARK}" '
               f'stroke="#ffffff" stroke-width="2"/>')
    # Label sits in the empty band above the null line, clear of both the
    # dashed rule and the curve, with a hairline leader down to the marker.
    out.append(f'<line x1="{ox:.1f}" y1="{y0 + 36}" x2="{ox:.1f}" '
               f'y2="{oy - 8:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    out.append(
        f'<text x="{ox + 6:.1f}" y="{y0 + 14}" font-size="12" '
        f'font-weight="700" text-anchor="end" fill="{INK_TITLE}">'
        f'Operating point (D37 floor {PRODUCTION_FLOOR})</text>'
    )
    out.append(
        f'<text x="{ox + 6:.1f}" y="{y0 + 30}" font-size="11.5" '
        f'text-anchor="end" fill="{INK_BODY}">'
        f'coverage {drawn[-1][0]:.3f}, risk {drawn[-1][1]:.3f}</text>'
    )

    # A few threshold callouts so the x-axis can be read as a confidence dial.
    for target in (0.10, 0.20, 0.30, 0.40):
        candidates = [p for p in drawn if p[0] <= target]
        if not candidates:
            continue
        cov, risk, conf = candidates[-1]
        out.append(f'<circle cx="{px(cov):.1f}" cy="{py(risk):.1f}" r="3.5" '
                   f'fill="{CURVE}" stroke="#ffffff" stroke-width="1.5"/>')
        out.append(
            f'<text x="{px(cov):.1f}" y="{py(risk) + 20:.1f}" font-size="10.5" '
            f'text-anchor="middle" fill="{INK_MUTED}">&#8805;{conf:.2f}</text>'
        )

    # Footer.
    fy = y0 + ph + 78
    out.append(
        f'<text x="26" y="{fy}" font-size="11.5" fill="{INK_BODY}">'
        f'Curve drawn from {MIN_ACCEPTED} accepted pairs (small-n left tail); '
        f'AURC integrates the full sweep. Coverage ends at '
        f'{drawn[-1][0]:.3f}: the other {n_total - n_accepted} pairs abstain '
        f'or are unscoreable.</text>'
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    out.append(
        f'<text x="26" y="{fy + 18}" font-size="11" fill="{INK_MUTED}">'
        f'Source: {EXPERIMENT_ID} finalised pairs, latest row per '
        f'(question, country), classified by _MATCH_STATUS_SQL. '
        f'n = {n_accepted} scoreable committed of {n_total}. '
        f'Generated {stamp}.</text>'
    )
    out.append('</svg>')
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "odmi.db"))
    ap.add_argument("--out-dir",
                    default=str(REPO_ROOT / "evaluation" / "figures"))
    args = ap.parse_args()

    points, n_total, n_accepted = sweep(args.db)
    area, null_risk = aurc(points)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "risk_coverage_curve.svg").write_text(
        build_svg(points, n_total, n_accepted, area, null_risk)
    )
    with (out_dir / "risk_coverage_curve.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["n_accepted", "coverage", "selective_risk",
                    "threshold_confidence"])
        for i, (cov, risk, conf) in enumerate(points, start=1):
            w.writerow([i, round(cov, 6), round(risk, 6), conf])
        w.writerow([])
        w.writerow(["aurc_normalised", round(area, 6)])
        w.writerow(["null_flat_risk", round(null_risk, 6)])
        w.writerow(["improvement_over_null", round(null_risk - area, 6)])

    print(f"n_total {n_total}, scoreable committed {n_accepted}, "
          f"max coverage {points[-1][0]:.4f}")
    print(f"AURC {area:.4f} vs null {null_risk:.4f} "
          f"(improvement {null_risk - area:+.4f})")
    print(f"wrote {out_dir / 'risk_coverage_curve.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
