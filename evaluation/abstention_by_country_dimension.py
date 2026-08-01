"""Abstention rate per country per ODMI dimension, as a heatmap.

Abstention is the swarm returning `inconclusive` as its final answer (D35/D37):
an honest "I could not establish this", not a label. This script counts, for
each (country, dimension) cell, how many answerable finalised pairs abstained,
and renders the rate as a self-contained SVG that drops straight into the
manuscript.

Definitions, kept identical to the dashboard headline so the figure is
consistent with `accuracy_summary`:
  - One row per finalised main-run pair, latest row only, experiment rows
    excluded (D27). All of this comes from `dashboard.lib.db.analytics_frame`,
    so the match-status logic is not duplicated here.
  - Denominator is the answerable set: match + near_match + differ + abstained.
    Pairs with no ground truth, no swarm answer, or flagged for review are
    excluded, exactly as the headline abstention rate is.
  - abstention_rate = n_abstained / n_answerable, per cell.

Outputs (under evaluation/figures/):
  - abstention_by_country_dimension.svg  the heatmap
  - abstention_by_country_dimension.csv  the underlying numbers (receipts)

Usage:
    uv run python evaluation/abstention_by_country_dimension.py
    uv run python evaluation/abstention_by_country_dimension.py --db data/odmi.db
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from dashboard.lib import db

# ODMI's four dimensions, in the order CLAUDE.md records them.
DIMENSIONS = ["Policy", "Portal", "Quality", "Impact"]

# Full names so the manuscript figure does not rely on ISO codes alone.
COUNTRY_NAMES = {
    "AL": "Albania", "BA": "Bosnia & Herz.", "BE": "Belgium", "BG": "Bulgaria",
    "DE": "Germany", "EE": "Estonia", "FI": "Finland", "FR": "France",
    "HR": "Croatia", "ME": "Montenegro", "MK": "North Macedonia", "MT": "Malta",
    "NL": "Netherlands", "NO": "Norway", "RO": "Romania", "SE": "Sweden",
}

ANSWERABLE = {"match", "near_match", "differ", "abstained"}

# YlOrRd 5-class stops, interpolated across 0..100 %.
_STOPS = [
    (0.00, (255, 255, 204)),
    (0.25, (254, 217, 118)),
    (0.50, (253, 141, 60)),
    (0.75, (240, 59, 32)),
    (1.00, (189, 0, 38)),
]


def _colour(rate_pct: float) -> str:
    """Map a 0..100 rate to a YlOrRd hex colour by linear interpolation."""
    t = max(0.0, min(1.0, rate_pct / 100.0))
    for (lo, c_lo), (hi, c_hi) in zip(_STOPS, _STOPS[1:]):
        if t <= hi:
            f = 0.0 if hi == lo else (t - lo) / (hi - lo)
            r = round(c_lo[0] + f * (c_hi[0] - c_lo[0]))
            g = round(c_lo[1] + f * (c_hi[1] - c_lo[1]))
            b = round(c_lo[2] + f * (c_hi[2] - c_lo[2]))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#bd0026"


def build_matrix(args_db: str | None) -> tuple[list[str], dict, dict]:
    """Return (countries, n_answerable, n_abstained) keyed by (country, dim)."""
    if args_db:
        db.DB_PATH = Path(args_db).resolve()
    df = db.analytics_frame()
    df = df[df["match_status"].isin(ANSWERABLE)].copy()

    n_ans: dict[tuple[str, str], int] = {}
    n_abs: dict[tuple[str, str], int] = {}
    for _, row in df.iterrows():
        key = (row["country_code"], row["dimension"])
        n_ans[key] = n_ans.get(key, 0) + 1
        if row["match_status"] == "abstained":
            n_abs[key] = n_abs.get(key, 0) + 1
    countries = sorted({c for c, _ in n_ans})
    return countries, n_ans, n_abs


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(countries: list[str], n_ans: dict, n_abs: dict) -> str:
    cell_w, cell_h = 116, 50
    x0, y0 = 168, 96
    grid_w = cell_w * len(DIMENSIONS)
    grid_h = cell_h * len(countries)
    bar_x = x0 + grid_w + 26
    width = bar_x + 96
    height = y0 + grid_h + 78
    stamp = datetime.now().strftime("%Y-%m-%d")

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="Helvetica, Arial, sans-serif">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

    # Title and subtitle.
    out.append(
        '<text x="24" y="34" font-size="20" font-weight="700" fill="#1a1a1a">'
        'Swarm abstention rate by country and ODMI dimension</text>'
    )
    out.append(
        '<text x="24" y="56" font-size="12.5" fill="#555">'
        'Abstention = swarm returns &#8220;inconclusive&#8221;. '
        'Cells show rate and n (answerable pairs). Main runs only.</text>'
    )

    # Column headers.
    for j, dim in enumerate(DIMENSIONS):
        cx = x0 + j * cell_w + cell_w / 2
        out.append(
            f'<text x="{cx:.1f}" y="{y0 - 14}" font-size="14" font-weight="600" '
            f'text-anchor="middle" fill="#1a1a1a">{dim}</text>'
        )

    # Rows.
    for i, cc in enumerate(countries):
        cy = y0 + i * cell_h
        label = f"{COUNTRY_NAMES.get(cc, cc)} ({cc})"
        out.append(
            f'<text x="{x0 - 12}" y="{cy + cell_h / 2 + 4:.1f}" font-size="13" '
            f'text-anchor="end" fill="#1a1a1a">{_esc(label)}</text>'
        )
        for j, dim in enumerate(DIMENSIONS):
            cx = x0 + j * cell_w
            key = (cc, dim)
            n = n_ans.get(key, 0)
            a = n_abs.get(key, 0)
            if n == 0:
                fill, tcol, main, sub = "#ececec", "#999", "&#8212;", ""
            else:
                rate = 100.0 * a / n
                fill = _colour(rate)
                tcol = "#ffffff" if rate >= 55 else "#222222"
                main = f"{rate:.0f}%"
                sub = f"n={n}"
            out.append(
                f'<rect x="{cx}" y="{cy}" width="{cell_w}" height="{cell_h}" '
                f'fill="{fill}" stroke="#ffffff" stroke-width="2"/>'
            )
            out.append(
                f'<text x="{cx + cell_w / 2:.1f}" y="{cy + cell_h / 2 - 2:.1f}" '
                f'font-size="15" font-weight="700" text-anchor="middle" '
                f'fill="{tcol}">{main}</text>'
            )
            if sub:
                out.append(
                    f'<text x="{cx + cell_w / 2:.1f}" y="{cy + cell_h / 2 + 14:.1f}" '
                    f'font-size="10.5" text-anchor="middle" fill="{tcol}" '
                    f'opacity="0.85">{sub}</text>'
                )

    # Colourbar (vertical gradient) with ticks at 0/25/50/75/100.
    out.append(
        '<defs><linearGradient id="cb" x1="0" y1="1" x2="0" y2="0">'
        '<stop offset="0%" stop-color="#ffffcc"/>'
        '<stop offset="25%" stop-color="#fed976"/>'
        '<stop offset="50%" stop-color="#fd8d3c"/>'
        '<stop offset="75%" stop-color="#f03b20"/>'
        '<stop offset="100%" stop-color="#bd0026"/>'
        '</linearGradient></defs>'
    )
    out.append(
        f'<rect x="{bar_x}" y="{y0}" width="18" height="{grid_h}" '
        f'fill="url(#cb)" stroke="#bbb" stroke-width="0.5"/>'
    )
    for frac, lab in [(0, "0%"), (0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1, "100%")]:
        ty = y0 + grid_h - frac * grid_h
        out.append(
            f'<text x="{bar_x + 24}" y="{ty + 4:.1f}" font-size="11" '
            f'fill="#444">{lab}</text>'
        )
    out.append(
        f'<text x="{bar_x + 9}" y="{y0 - 12}" font-size="11" font-weight="600" '
        f'text-anchor="middle" fill="#444">rate</text>'
    )

    # Footnote.
    out.append(
        f'<text x="24" y="{height - 30}" font-size="10.5" fill="#777">'
        f'Denominator = answerable pairs (match + near_match + differ + abstained); '
        f'grey = no finalised pairs. Latest row per pair, experiment rows excluded (D27).</text>'
    )
    out.append(
        f'<text x="24" y="{height - 14}" font-size="10.5" fill="#777">'
        f'Source: data/odmi.db, generated {stamp}.</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None, help="path to odmi.db (default: repo data/odmi.db)")
    ap.add_argument(
        "--outdir", default="evaluation/figures",
        help="directory for the SVG and CSV outputs",
    )
    ap.add_argument(
        "--complete-dims", action="store_true",
        help="keep only countries with at least one answerable pair in every "
             "dimension (drops countries with a blank dimension cell)",
    )
    args = ap.parse_args()

    countries, n_ans, n_abs = build_matrix(args.db)
    if args.complete_dims:
        countries = [
            c for c in countries
            if all(n_ans.get((c, d), 0) > 0 for d in DIMENSIONS)
        ]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    stem = "abstention_by_country_dimension"
    if args.complete_dims:
        stem += "_complete_dims"

    svg_path = outdir / f"{stem}.svg"
    svg_path.write_text(build_svg(countries, n_ans, n_abs), encoding="utf-8")

    csv_path = outdir / f"{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["country_code", "dimension", "n_answerable",
                    "n_abstained", "abstention_rate_pct"])
        for cc in countries:
            for dim in DIMENSIONS:
                n = n_ans.get((cc, dim), 0)
                a = n_abs.get((cc, dim), 0)
                rate = f"{100.0 * a / n:.1f}" if n else ""
                w.writerow([cc, dim, n, a, rate])

    # Console summary (over the countries actually plotted).
    kept = set(countries)
    tot_n = sum(v for (c, _), v in n_ans.items() if c in kept)
    tot_a = sum(v for (c, _), v in n_abs.items() if c in kept)
    print(f"countries: {len(countries)}  answerable: {tot_n}  "
          f"abstained: {tot_a}  overall: {100.0 * tot_a / tot_n:.1f}%")
    print(f"wrote {svg_path}")
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
