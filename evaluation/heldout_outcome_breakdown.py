"""Per-country outcome makeup for the held-out eight (EXP-36), as a 100%
horizontal stacked bar.

Each finalised pair for a held-out country lands in exactly one of five
outcomes, read off the same classification the dashboard headline uses
(`dashboard.lib.db._MATCH_STATUS_SQL`), so "correct" here means what it means
everywhere else in the project:

  - Correct       match or near_match against the ODMI gold.
  - Yes when No    binary false positive: swarm committed `yes`, ODMI says `no`.
                   The over-claim direction (spurious maturity).
  - No when Yes    binary false negative: swarm committed `no`, ODMI says `yes`.
  - Abstain        swarm returned `inconclusive` (D35/D37): an honest
                   non-answer, not an error label.
  - Other          everything else: a band or category miss on a non-binary
                   question, a commit against an unclear gold (`i don't know`
                   / `other`), or a `flag_review` (committed answer against an
                   ODMI `not applicable`). Small, mixed, never a clean yes/no
                   flip.

Bars are one canonical row per (question, country, condition_label) within the
experiment (docs/EXPERIMENT_RUNBOOK.md), so the loader and dedup are imported
from `exp36_analysis` rather than re-implemented. Countries are ordered by
correct share, high to low. n varies 143 to 146 because a few pairs carry a
second condition_label; the bars are proportions so the varying n does not
distort the comparison, and the raw counts travel in the CSV.

Colour is a status-semantic scale, not arbitrary categorical: good (green) for
correct, critical (red) for the over-claim false positive, serious (orange) for
the false negative, a cool neutral slate for the honest abstention, a recessive
grey for the mixed remainder. The two error hues clear the CVD target against
each other and against correct (green-red worst adjacent Machado deltaE 12.4);
the neutrals carry their meaning by legend, fixed position and direct labels,
not by hue.

Outputs (under evaluation/figures/):
  - heldout_outcome_breakdown.svg   the chart, self-contained for the manuscript
  - heldout_outcome_breakdown.csv   the underlying counts (receipts)

Usage:
    uv run python evaluation/heldout_outcome_breakdown.py
    uv run python evaluation/heldout_outcome_breakdown.py --db data/odmi.db
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.exp36_analysis import (  # noqa: E402
    dedup_canonical,
    load_rows,
    norm,
)

EXPERIMENT_ID = "exp36_frozen_headline"

# Full names so the figure does not rely on ISO codes alone.
COUNTRY_NAMES = {
    "BA": "Bosnia & Herz.", "BE": "Belgium", "BG": "Bulgaria",
    "FI": "Finland", "HR": "Croatia", "ME": "Montenegro",
    "MK": "North Macedonia", "SE": "Sweden",
}

# Fixed left-to-right segment order. Never reordered: a reader learns it once
# from the legend and then reads position, which is the CVD fallback.
CATS = ["Correct", "Yes when No", "No when Yes", "Abstain", "Other"]

# Status-semantic fills (light surface). See module docstring for the CVD read.
COLOUR = {
    "Correct":     "#0ca30c",   # good
    "Yes when No": "#d03b3b",   # critical  (false positive, over-claim)
    "No when Yes": "#ec835a",   # serious   (false negative)
    "Abstain":     "#6f7683",   # neutral slate (honest non-answer)
    "Other":       "#a9a79e",   # recessive grey (mixed remainder)
}
# Ink on each fill: white on the four darker fills, near-black on the light grey.
INK = {c: "#ffffff" for c in CATS}
INK["Other"] = "#1f1e1c"


def _yes_like(a) -> bool:
    return norm(a).startswith("yes")


def _no_like(a) -> bool:
    return norm(a) == "no"


def outcome(row) -> str:
    """Fold the dashboard match_status into the five report outcomes."""
    ms = row.match_status
    if ms in ("match", "near_match"):
        return "Correct"
    if ms == "abstained":
        return "Abstain"
    if ms == "differ":
        if _yes_like(row.final_answer) and _no_like(row.gold_answer):
            return "Yes when No"
        if _no_like(row.final_answer) and _yes_like(row.gold_answer):
            return "No when Yes"
        return "Other"
    # flag_review / no_ground_truth / no_swarm_answer all fold to Other.
    return "Other"


def build_counts(db_path: str) -> tuple[list[str], dict[str, Counter]]:
    """Return (country order high-to-low correct share, per-country counts)."""
    conn = sqlite3.connect(db_path)
    try:
        rows, _ = dedup_canonical(load_rows(conn, EXPERIMENT_ID))
    finally:
        conn.close()
    counts: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        counts[r.country_code][outcome(r)] += 1
    order = sorted(
        counts,
        key=lambda cc: counts[cc]["Correct"] / sum(counts[cc].values()),
        reverse=True,
    )
    return order, counts


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_svg(order: list[str], counts: dict[str, Counter]) -> str:
    # Geometry.
    width = 1040
    bar_x0 = 212
    bar_w = 726
    y0 = 128           # first bar top
    row_pitch = 42
    bar_h = 28
    height = y0 + len(order) * row_pitch + 78

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, \'Segoe UI\', sans-serif">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

    # Title and subtitle.
    out.append(
        '<text x="26" y="38" font-size="21" font-weight="700" fill="#161616">'
        'Outcome makeup per held-out country (EXP-36)</text>'
    )
    out.append(
        '<text x="26" y="60" font-size="13" fill="#52514e">'
        'Every finalised pair placed in one outcome, as a share of the '
        'country&#8217;s pairs. Ordered by correct share.</text>'
    )

    # Legend, aligned to the bars, one swatch + short label per outcome.
    lx = bar_x0
    ly = 90
    for cat in CATS:
        out.append(
            f'<rect x="{lx}" y="{ly - 11}" width="13" height="13" rx="2.5" '
            f'fill="{COLOUR[cat]}"/>'
        )
        out.append(
            f'<text x="{lx + 18}" y="{ly}" font-size="12.5" fill="#161616">'
            f'{_esc(cat)}</text>'
        )
        lx += 18 + len(cat) * 7.4 + 26

    # Bars.
    for i, cc in enumerate(order):
        c = counts[cc]
        n = sum(c.values())
        y = y0 + i * row_pitch

        # Country label, right-anchored into the left gutter.
        out.append(
            f'<text x="{bar_x0 - 14}" y="{y + bar_h / 2 + 4:.1f}" '
            f'font-size="13.5" text-anchor="end" fill="#161616">'
            f'{_esc(COUNTRY_NAMES[cc])}</text>'
        )

        # Rounded clip so the bar has soft outer ends but square inner gaps.
        clip = f"barclip{i}"
        out.append(
            f'<clipPath id="{clip}"><rect x="{bar_x0}" y="{y}" '
            f'width="{bar_w}" height="{bar_h}" rx="6" ry="6"/></clipPath>'
        )
        out.append(f'<g clip-path="url(#{clip})">')

        cum = 0.0
        for j, cat in enumerate(CATS):
            v = c.get(cat, 0)
            if v == 0:
                continue
            prop = v / n
            seg_w = prop * bar_w
            x = bar_x0 + cum * bar_w
            last = (j == len(CATS) - 1) or all(
                c.get(k, 0) == 0 for k in CATS[j + 1:]
            )
            # 2px surface gap between segments; the final segment runs to the
            # rounded end so no white sliver sits inside the corner.
            w = seg_w if last else max(seg_w - 2, 0.5)
            out.append(
                f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{bar_h}" '
                f'fill="{COLOUR[cat]}"/>'
            )
            # Direct label only where the segment is wide enough to hold it.
            if seg_w >= 24:
                pct = round(prop * 100)
                out.append(
                    f'<text x="{x + seg_w / 2:.2f}" '
                    f'y="{y + bar_h / 2 + 4:.1f}" font-size="11.5" '
                    f'text-anchor="middle" fill="{INK[cat]}">{pct}%</text>'
                )
            cum += prop
        out.append('</g>')

        # n at the right end.
        out.append(
            f'<text x="{bar_x0 + bar_w + 9}" y="{y + bar_h / 2 + 4:.1f}" '
            f'font-size="11.5" fill="#898781">n={n}</text>'
        )

    # Definitions and provenance footer. Kept within the canvas width.
    fy = y0 + len(order) * row_pitch + 26
    out.append(
        f'<text x="26" y="{fy}" font-size="11.5" fill="#52514e">'
        'Yes when No = false positive (swarm yes, gold no); No when Yes = '
        'false negative; Abstain = inconclusive; Other = band or category '
        'miss, or unclear gold.</text>'
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    out.append(
        f'<text x="26" y="{fy + 18}" font-size="11" fill="#898781">'
        f'Source: {EXPERIMENT_ID} finalised pairs, canonical row per '
        f'(question, country, condition), classified by _MATCH_STATUS_SQL. '
        f'Generated {stamp}.</text>'
    )

    out.append('</svg>')
    return "\n".join(out)


def write_csv(path: Path, order: list[str], counts: dict[str, Counter]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["country_code", "country", "n", *CATS,
                    *[f"{c}_pct" for c in CATS]])
        for cc in order:
            c = counts[cc]
            n = sum(c.values())
            raw = [c.get(k, 0) for k in CATS]
            pct = [round(100 * v / n, 1) for v in raw]
            w.writerow([cc, COUNTRY_NAMES[cc], n, *raw, *pct])
        # Pooled row.
        pooled = Counter()
        for c in counts.values():
            pooled.update(c)
        n = sum(pooled.values())
        raw = [pooled.get(k, 0) for k in CATS]
        pct = [round(100 * v / n, 1) for v in raw]
        w.writerow(["ALL", "held-out eight", n, *raw, *pct])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "odmi.db"))
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "evaluation" / "figures"))
    args = ap.parse_args()

    order, counts = build_counts(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    svg_path = out_dir / "heldout_outcome_breakdown.svg"
    csv_path = out_dir / "heldout_outcome_breakdown.csv"
    svg_path.write_text(build_svg(order, counts))
    write_csv(csv_path, order, counts)

    print(f"wrote {svg_path}")
    print(f"wrote {csv_path}")
    print(f"countries (correct-share order): {', '.join(order)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
