"""Figure: published 2025 ODMI score vs the swarm's reconstructed score (EXP-36).

One row per held-out country. Each row carries two things:

- a **band**, spanning the swarm's floor to its ceiling, and
- a **marker**, the country's published 2025 ODMI score.

Both numbers come out of the same formula (the mean of the four dimension
percentages), so they sit on one scale. `evaluation/exp36_maturity_reconstruction.py`
computes them and documents why the substitution is exact; this module only
draws the result.

What the figure is for
----------------------
**Does the marker sit inside the band?** If it does, the swarm's assessment is
consistent with the published score given the evidence it could reach. That is
the weakest available claim and the honest one. Two countries fail it, and the
figure marks them in the status red rather than burying them: for Croatia and
Montenegro the published score sits *above* the swarm's ceiling, so the swarm
under-scores them even when only its committed answers are counted.

**How wide is the band?** Width is the share of the country's assessment that
public evidence could not reach, weighted by the marks at stake. It is not a
simple function of coverage: Bosnia has the lowest coverage of the eight (0.385)
and the *narrowest* band (12.3 points), because most of its golds are `no` and
therefore carry no marks to lose. Bulgaria, at a similar coverage, has the widest
(41.5). Width has two candidate causes this figure cannot separate: evidence is
scarcer for that country, or its true answers are mostly `no` and the swarm
cannot commit negatives. §4.3 establishes the second mechanism is real, so the
caption must state both readings.

Colour
------
Two categorical fills only, validated together against the white manuscript
surface (worst-pair CVD deltaE 23.8 protan, normal-vision 31.6, both above the
gates): the band blue and the out-of-band status red. The in-band marker is
achromatic ink, a reference mark rather than a series, so identity never rests
on colour alone: the marker's position relative to the band carries the same
information, and both band ends are directly labelled.

Outputs:
  - evaluation/figures/maturity_reconstruction.svg   beside the other EXP-36 figures
  - evaluation/figures/maturity_reconstruction.csv   the numbers behind it
  - docs/figures/maturity_reconstruction.svg         the manuscript figure set

The SVG is written to both places by the same run rather than copied by hand,
so the manuscript copy cannot drift from the analysis output.

Usage:
    uv run python evaluation/maturity_reconstruction_figure.py
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.exp36_analysis import (  # noqa: E402
    dedup_canonical,
    is_committed,
    load_rows,
)
from evaluation.exp36_maturity_reconstruction import (  # noqa: E402
    HELD_OUT,
    build_rubric,
    load_gold,
    load_gold_by_country,
    score_country,
)

# Full names so the figure does not rely on ISO codes alone.
NAMES = {
    "BA": "Bosnia and Herzegovina",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "FI": "Finland",
    "HR": "Croatia",
    "ME": "Montenegro",
    "MK": "North Macedonia",
    "SE": "Sweden",
}

# Validated categorical pair (light surface #ffffff). See module docstring.
BAND = "#2a78d6"        # swarm floor-to-ceiling
OUT_OF_BAND = "#d03b3b" # published score falls outside the band
INK = "#161616"
MUTED = "#52514e"
FAINT = "#898781"
GRID = "#e3e2dd"

# Geometry.
W = 1040
X_LABEL = 198           # country names, right-aligned
X0, X1 = 214, 856       # plot band, 0 to 100
X_SCORE = 916           # published score column, right-aligned
X_COV = 1014            # coverage column, right-aligned
Y0 = 178                # first row centre
PITCH = 40
BAND_H = 15
MARKER_R = 7.5          # half-diagonal of the published-score diamond


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(scored: list) -> str:
    height = Y0 + PITCH * (len(scored) - 1) + 128
    x = lambda v: X0 + (X1 - X0) * (v / 100.0)  # noqa: E731

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {W} {height}" xmlns="http://www.w3.org/2000/svg" '
        f"font-family=\"system-ui, -apple-system, 'Segoe UI', sans-serif\">"
    )
    out.append(f'<rect width="{W}" height="{height}" fill="#ffffff"/>')

    out.append(
        f'<text x="26" y="38" font-size="21" font-weight="700" fill="{INK}">'
        "Published 2025 ODMI score against the swarm&#8217;s reconstruction "
        "(EXP-36)</text>"
    )
    out.append(
        f'<text x="26" y="60" font-size="13" fill="{MUTED}">'
        "Both scored by ODMI&#8217;s own formula: the mean of the four "
        "dimension percentages.</text>"
    )
    out.append(
        f'<text x="26" y="78" font-size="13" fill="{MUTED}">'
        "The band spans abstentions scored as zero (floor) to scoring only "
        "what the swarm committed (ceiling).</text>"
    )

    # Legend.
    ly = 100
    out.append(f'<rect x="26" y="{ly}" width="34" height="13" rx="4" fill="{BAND}"/>')
    out.append(
        f'<text x="66" y="{ly + 11}" font-size="12.5" fill="{INK}">'
        "Swarm reconstruction, floor to ceiling</text>"
    )
    out.append(
        f'<path d="M 340 {ly + 6.5} l 7 -7 l 7 7 l -7 7 Z" fill="{INK}" '
        f'stroke="#ffffff" stroke-width="2"/>'
    )
    out.append(
        f'<text x="360" y="{ly + 11}" font-size="12.5" fill="{INK}">'
        "Published 2025 ODMI score</text>"
    )
    out.append(
        f'<path d="M 546 {ly + 6.5} l 7 -7 l 7 7 l -7 7 Z" fill="{OUT_OF_BAND}" '
        f'stroke="#ffffff" stroke-width="2"/>'
    )
    out.append(
        f'<text x="566" y="{ly + 11}" font-size="12.5" fill="{INK}">'
        "&#8230; falls outside the band</text>"
    )

    # Axis: ticks every 10, gridlines behind the rows.
    top = Y0 - PITCH / 2 - 2
    bottom = Y0 + PITCH * (len(scored) - 1) + PITCH / 2 - 2
    for tick in range(0, 101, 10):
        tx = x(tick)
        out.append(
            f'<line x1="{tx:.1f}" y1="{top:.1f}" x2="{tx:.1f}" y2="{bottom:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{tx:.1f}" y="{top - 8:.1f}" font-size="11.5" '
            f'text-anchor="middle" fill="{FAINT}">{tick}</text>'
        )

    out.append(
        f'<text x="{X_SCORE}" y="{top - 8:.1f}" font-size="11.5" '
        f'text-anchor="end" fill="{FAINT}">ODMI</text>'
    )
    out.append(
        f'<text x="{X_COV}" y="{top - 8:.1f}" font-size="11.5" '
        f'text-anchor="end" fill="{FAINT}">Reached</text>'
    )

    for i, s in enumerate(scored):
        cy = Y0 + PITCH * i
        inside = s.floor <= s.published <= s.ceiling
        marker_fill = INK if inside else OUT_OF_BAND

        out.append(
            f'<text x="{X_LABEL}" y="{cy + 4.5}" font-size="13.5" '
            f'text-anchor="end" fill="{INK}">{esc(NAMES[s.country_code])}</text>'
        )

        # The band. Rounded data-ends, anchored to the two policy bounds.
        bx0, bx1 = x(s.floor), x(s.ceiling)
        out.append(
            f'<rect x="{bx0:.1f}" y="{cy - BAND_H / 2:.1f}" '
            f'width="{max(bx1 - bx0, 2):.1f}" height="{BAND_H}" rx="4" '
            f'fill="{BAND}"/>'
        )

        # Both ends directly labelled: the band fill is never the only cue.
        # The ceiling label sits inside the band so the space just past the
        # band end stays clear for a marker that falls outside it.
        out.append(
            f'<text x="{bx0 - 7:.1f}" y="{cy + 4:.1f}" font-size="11.5" '
            f'text-anchor="end" fill="{FAINT}">{s.floor:.1f}</text>'
        )
        # Published score: diamond with a surface ring so it reads on the band.
        px = x(s.published)

        # ... unless the marker sits under where that label would go, in which
        # case the label moves out past the band end. Width is estimated from
        # the glyph count; the digits are all one advance at this size.
        # An out-of-band marker keeps its own connector clear, so its ceiling
        # label always stays inside regardless of the collision test.
        ceiling_text = f"{s.ceiling:.1f}"
        label_w = len(ceiling_text) * 6.6
        if inside and px + MARKER_R + 8 > bx1 - 7 - label_w:
            out.append(
                f'<text x="{bx1 + 7:.1f}" y="{cy + 4:.1f}" font-size="11.5" '
                f'fill="{FAINT}">{ceiling_text}</text>'
            )
        else:
            out.append(
                f'<text x="{bx1 - 7:.1f}" y="{cy + 4:.1f}" font-size="11.5" '
                f'text-anchor="end" fill="#ffffff">{ceiling_text}</text>'
            )

        # Where the published score falls outside the band, a connector spans
        # the miss, so the gap is legible without relying on the marker colour.
        if not inside:
            near = bx1 if s.published > s.ceiling else bx0
            out.append(
                f'<line x1="{near:.1f}" y1="{cy}" x2="{px:.1f}" y2="{cy}" '
                f'stroke="{OUT_OF_BAND}" stroke-width="2"/>'
            )
        out.append(
            f'<path d="M {px:.1f} {cy} l 7.5 -7.5 l 7.5 7.5 l -7.5 7.5 Z" '
            f'transform="translate(-7.5,0)" fill="{marker_fill}" '
            f'stroke="#ffffff" stroke-width="2"/>'
        )

        out.append(
            f'<text x="{X_SCORE}" y="{cy + 4.5}" font-size="13" '
            f'font-weight="600" text-anchor="end" fill="{marker_fill}">'
            f"{s.published:.1f}</text>"
        )
        out.append(
            f'<text x="{X_COV}" y="{cy + 4.5}" font-size="12.5" '
            f'text-anchor="end" fill="{MUTED}">{s.coverage * 100:.0f}%</text>'
        )

    foot = bottom + 32
    notes = (
        "1,144 finalised pairs over the eight held-out countries. 130 of each "
        "country&#8217;s 143 questions carry marks.",
        "&#8220;Reached&#8221; is the share of those 130 the swarm committed "
        "an answer to; it abstained on the rest.",
        "Band width is the share of the assessment public evidence could not "
        "reach, weighted by the marks at stake. It does not track coverage:",
        "Bosnia is reached least of the eight yet has the narrowest band, "
        "because most of its golds are &#8220;no&#8221; and carry no marks "
        "to lose.",
    )
    for i, note in enumerate(notes):
        out.append(
            f'<text x="26" y="{foot + 17 * i:.1f}" font-size="11.5" '
            f'fill="{FAINT}">{note}</text>'
        )

    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/odmi.db")
    parser.add_argument("--experiment-id", default="exp36_frozen_headline")
    parser.add_argument("--outdir", default="evaluation/figures")
    parser.add_argument(
        "--manuscript-dir",
        default="docs/figures",
        help="second destination for the SVG, the manuscript figure set. "
             "Pass an empty string to skip it.",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    rubric = build_rubric(load_gold(conn))
    gold_by_country = load_gold_by_country(conn)

    rows, _ = dedup_canonical(load_rows(conn, args.experiment_id),
                              scope_by_label=False)
    answers: dict[str, dict[str, str]] = {cc: {} for cc in HELD_OUT}
    for row in rows:
        if is_committed(row) and row.country_code in answers:
            answers[row.country_code][row.question_id] = row.final_answer

    scored = [
        score_country(cc, gold_by_country[cc], answers[cc], rubric)
        for cc in HELD_OUT
    ]
    scored.sort(key=lambda s: s.published, reverse=True)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    svg = build_svg(scored)
    svg_path = outdir / "maturity_reconstruction.svg"
    svg_path.write_text(svg)

    if args.manuscript_dir:
        manuscript_dir = Path(args.manuscript_dir)
        manuscript_dir.mkdir(parents=True, exist_ok=True)
        manuscript_path = manuscript_dir / "maturity_reconstruction.svg"
        manuscript_path.write_text(svg)
        print(f"wrote {manuscript_path}")

    csv_path = outdir / "maturity_reconstruction.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "country_code", "country", "published_odmi_2025",
            "swarm_floor", "swarm_ceiling", "band_width",
            "published_inside_band", "n_scored_questions",
            "n_committed", "n_abstained", "coverage",
        ])
        for s in scored:
            writer.writerow([
                s.country_code, NAMES[s.country_code], f"{s.published:.1f}",
                f"{s.floor:.1f}", f"{s.ceiling:.1f}", f"{s.width:.1f}",
                "yes" if s.floor <= s.published <= s.ceiling else "no",
                s.n_questions, s.n_committed, s.n_abstained,
                f"{s.coverage:.3f}",
            ])

    print(f"wrote {svg_path}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
