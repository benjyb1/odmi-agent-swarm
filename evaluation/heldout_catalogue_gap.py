"""Held-out catalogue gap heatmap (docs/figures/heldout_catalogue_gap.svg).

For each of the four catalogue-computable held-out countries (FI, HR, SE, ME)
and the nine catalogue questions, the cell is the percentage-point gap between
the swarm's deterministically computed value and the nearest printed edge of
ODMI's published band. Zero means the swarm's value falls inside ODMI's band
(the strongest possible agreement, since ODMI publishes a band, not a point).
Blue = swarm below ODMI's band, red = above. Grey n/a = a field the portal's
metadata does not expose, so the metric is unmeasurable on that route.

Data provenance (this session, 2026-07-23):
- FI, SE swarm values: canonical `catalogue_metrics` (snapshots FI 2026-06-24,
  SE 2026-07-17).
- HR: post-fix. data.gov.hr's DCAT carries no dct:license and no
  dcat:downloadURL on any record (verified by direct SPARQL query; predicates
  absent, no CKAN second route), so Q12/Q13/Q21/Q25 are unmeasurable. Q16/Q17/
  Q18/Q22/Q27 measurable.
- ME: fresh CKAN harvest (data.gov.me, 899 datasets); not yet persisted to
  canonical.
- ODMI bands: `ground_truth.response`.

Q13 is a distinct-licence count (bands 1-4 / 5-10 / >10), not a percentage; its
gap is a count and is marked with an asterisk.

Regenerate: `uv run python -m evaluation.heldout_catalogue_gap`.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path("docs/figures/heldout_catalogue_gap.svg")

QUESTIONS = ["Q12", "Q13", "Q16", "Q17", "Q18", "Q21", "Q22", "Q25", "Q27"]
COUNTRIES = [("FI", "Finland"), ("HR", "Croatia"),
             ("SE", "Sweden"), ("ME", "Montenegro")]

# Swarm-computed raw value per (country, question). Percentages except Q13
# (a distinct-licence count). None = unmeasurable (field absent from the route).
SWARM: dict[str, dict[str, float | None]] = {
    "FI": {"Q12": 96.06, "Q13": 9, "Q16": 99.3, "Q17": 100.0, "Q18": 98.69,
           "Q21": 100.0, "Q22": 100.0, "Q25": 86.06, "Q27": 48.75},
    "HR": {"Q12": None, "Q13": None, "Q16": 40.6, "Q17": 100.0, "Q18": 100.0,
           "Q21": None, "Q22": 97.67, "Q25": None, "Q27": 44.63},
    "SE": {"Q12": 63.65, "Q13": 34, "Q16": 98.9, "Q17": 100.0, "Q18": 94.82,
           "Q21": 5.46, "Q22": 100.0, "Q25": 63.34, "Q27": 63.92},
    "ME": {"Q12": 75.52, "Q13": 6, "Q16": 95.88, "Q17": 100.0, "Q18": 98.33,
           "Q21": 98.44, "Q22": 98.44, "Q25": 69.97, "Q27": 80.31},
}

# ODMI published band per (country, question).
ODMI: dict[str, dict[str, str]] = {
    "FI": {"Q12": ">90%", "Q13": "5-10", "Q16": ">90%", "Q17": ">90%",
           "Q18": ">90%", "Q21": ">90%", "Q22": ">90%", "Q25": ">90%",
           "Q27": "71-90%"},
    "HR": {"Q12": ">90%", "Q13": "1-4", "Q16": ">90%", "Q17": ">90%",
           "Q18": ">90%", "Q21": "10-30%", "Q22": "10-30%", "Q25": ">90%",
           "Q27": ">90%"},
    "SE": {"Q12": "71-90%", "Q13": ">10", "Q16": ">90%", "Q17": ">90%",
           "Q18": "51-70%", "Q21": "10-30%", "Q22": ">90%", "Q25": "71-90%",
           "Q27": ">90%"},
    "ME": {"Q12": ">90%", "Q13": "1-4", "Q16": ">90%", "Q17": ">90%",
           "Q18": ">90%", "Q21": ">90%", "Q22": ">90%", "Q25": ">90%",
           "Q27": ">90%"},
}

# Band edges by the printed numerals in the label.
PCT_EDGES = {">90%": (90.0, 100.0), "71-90%": (71.0, 90.0),
             "51-70%": (51.0, 70.0), "31-50%": (31.0, 50.0),
             "10-30%": (10.0, 30.0), "<10%": (0.0, 10.0)}
COUNT_EDGES = {"1-4": (1, 4), "5-10": (5, 10), ">10": (11, 10**9)}


def gap(value: float | None, band: str, is_count: bool) -> float | None:
    """Signed gap from `value` to the nearest edge of `band`; 0 if inside."""
    if value is None:
        return None
    lo, hi = (COUNT_EDGES if is_count else PCT_EDGES)[band]
    if lo <= value <= hi:
        return 0.0
    return value - lo if value < lo else value - hi


def cell_colour(v: float | None) -> tuple[str, str]:
    """(fill, text) for a gap value on the diverging blue<->red scale."""
    if v is None:
        return "#e3e2dd", "#7a7972"
    if round(v) == 0:
        return "#eceae4", "#52514e"
    a = abs(v)
    if v < 0:
        fill = "#cfe0f2" if a <= 10 else "#7fabdb" if a <= 25 else "#2f6fb4"
        text = "#0c447c" if a <= 10 else "#ffffff"
    else:
        fill = "#f6d0bc" if a <= 10 else "#eb9a72" if a <= 25 else "#c0392a"
        text = "#4a1b0c" if a <= 25 else "#ffffff"
    return fill, text


def cell_label(v: float | None, is_count: bool) -> str:
    if v is None:
        return "n/a"
    r = round(v)
    if r == 0:
        return "0"
    return ("+" if r > 0 else "−") + str(abs(r)) + ("*" if is_count else "")


def build_svg() -> str:
    L = 138          # left margin (country label column)
    CW, CH = 74, 46  # cell width / height
    GAP = 5
    top = 108        # y of the Q-header row baseline
    row0 = 120       # y of the first cell row (top edge)
    W = L + 9 * (CW + GAP) + 24
    H = row0 + 4 * (CH + GAP) + 92

    def cx(i: int) -> float:
        return L + i * (CW + GAP)

    s: list[str] = []
    s.append(
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, \'Segoe UI\', sans-serif">'
    )
    s.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
    s.append('<text x="26" y="40" font-size="21" font-weight="700" '
             'fill="#161616">Deterministic catalogue vs ODMI, '
             'percentage-point gap</text>')
    s.append('<text x="26" y="62" font-size="13" fill="#52514e">Gap from the '
             'swarm&#8217;s value to the nearest edge of ODMI&#8217;s band. '
             '0 = inside the band; blue = swarm below, red = above.</text>')
    s.append('<text x="26" y="80" font-size="13" fill="#52514e">Grey n/a = '
             'field not exposed by the portal. Q13* is a licence count, not '
             'a percentage.</text>')

    # Q-column headers.
    for i, q in enumerate(QUESTIONS):
        s.append(f'<text x="{cx(i) + CW / 2:.1f}" y="{top}" font-size="12.5" '
                 f'text-anchor="middle" fill="#52514e">{q}</text>')

    # Rows.
    for r, (cc, name) in enumerate(COUNTRIES):
        y = row0 + r * (CH + GAP)
        s.append(f'<text x="{L - 12}" y="{y + CH / 2 + 4:.1f}" font-size="13.5" '
                 f'text-anchor="end" fill="#161616">{name}</text>')
        for i, q in enumerate(QUESTIONS):
            is_count = q == "Q13"
            g = gap(SWARM[cc][q], ODMI[cc][q], is_count)
            fill, text = cell_colour(g)
            s.append(f'<rect x="{cx(i):.1f}" y="{y}" width="{CW}" height="{CH}" '
                     f'rx="6" fill="{fill}"/>')
            s.append(f'<text x="{cx(i) + CW / 2:.1f}" y="{y + CH / 2 + 5:.1f}" '
                     f'font-size="14" text-anchor="middle" font-weight="600" '
                     f'fill="{text}">{cell_label(g, is_count)}</text>')

    # Legend.
    ly = row0 + 4 * (CH + GAP) + 30
    s.append(f'<text x="26" y="{ly + 15}" font-size="12.5" fill="#52514e">'
             'swarm below</text>')
    swatches = [("−26", "#2f6fb4", "#ffffff"),
                ("−15", "#7fabdb", "#ffffff"),
                ("−4", "#cfe0f2", "#0c447c"),
                ("0", "#eceae4", "#52514e"),
                ("+25", "#eb9a72", "#4a1b0c"),
                ("+68", "#c0392a", "#ffffff"),
                ("n/a", "#e3e2dd", "#7a7972")]
    x = 108
    for lab, fill, text in swatches:
        s.append(f'<rect x="{x}" y="{ly}" width="34" height="22" rx="5" '
                 f'fill="{fill}"/>')
        s.append(f'<text x="{x + 17}" y="{ly + 15}" font-size="11.5" '
                 f'text-anchor="middle" font-weight="600" fill="{text}">{lab}'
                 f'</text>')
        x += 40
    s.append(f'<text x="{x + 4}" y="{ly + 15}" font-size="12.5" '
             f'fill="#52514e">swarm above</text>')

    s.append('</svg>')
    return "\n".join(s)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_svg(), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
