"""Abstention rate per held-out country, decomposed by cause (EXP-36).

The filed reading of EXP-36 is that low resource drives abstention rather than
fabricated error. That claim is about a mechanism, and the stratum contrast
alone cannot test it: a higher abstention rate in the low-resource stratum is
equally consistent with two very different stories.

  - **Retrieval.** Stratum A abstains more because the web is thin there and
    pages fail to fetch, so the swarm never gets evidence to reason over.
  - **Verification.** Stratum A abstains more because the verifier rejects
    more of what the researcher finds, which would mean the verification layer
    is stricter on countries it understands less well.

Decomposing each country's abstention rate by cause separates them. The answer
is neither: verifier rejection is flat across strata (slightly higher in B),
retrieval failure is near zero everywhere except Bulgaria, and essentially the
whole stratum gap is the researcher's own answer confidence falling under the
D37 floor of 0.65. The system declines because it is unsure, not because it
cannot retrieve and not because the verifier is harsher.

Causes are the taxonomy in `evaluation/abstention_taxonomy.py`, grouped to five
so the mechanism is legible:

  Below confidence floor       G   researcher had an answer, under 0.65
  Verifier rejection           D+E substring gate failed, or verifier rejected
  Researcher never committed   I   every attempt inconclusive
  Retrieval failure            A+B+F3  thin web, fetch error, empty search
  Other / deny-list            C+Z deny-listed source contacted, uncategorised

Bars are the abstention rate over each country's 143 pairs, so bar length is
the rate and segment length is that cause's share of it. The two summary bars
pool each stratum's four countries (572 pairs each).

Outputs (under evaluation/figures/):
  - abstention_causes_by_country.svg  the chart, self-contained for the manuscript
  - abstention_causes_by_country.csv  the counts (receipts)

Prerequisite: `uv run python evaluation/abstention_taxonomy.py` writes
`evaluation/abstention_records.csv`, which this script reads.

Usage:
    uv run python evaluation/abstention_causes_by_country.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

EXPERIMENT_ID = "exp36_frozen_headline"
PAIRS_PER_COUNTRY = 143

STRATUM_A = ["BA", "BG", "MK", "ME"]     # low/mid-resource, negative-rich
STRATUM_B = ["HR", "BE", "SE", "FI"]     # higher-resource

COUNTRY_NAMES = {
    "BA": "Bosnia & Herz.", "BE": "Belgium", "BG": "Bulgaria",
    "FI": "Finland", "HR": "Croatia", "ME": "Montenegro",
    "MK": "North Macedonia", "SE": "Sweden",
}

# Taxonomy category -> reported cause group.
GROUP_OF = {
    "G_below_confidence_floor": "Below confidence floor",
    "D_evidence_ungrounded": "Verifier rejection",
    "E_verifier_relevance_reject": "Verifier rejection",
    "I_researcher_never_committed": "Researcher never committed",
    "A_thin_web_no_results": "Retrieval failure",
    "B_fetch_error": "Retrieval failure",
    "F3_search_empty_failure": "Retrieval failure",
    "C_denylist_mqa": "Other / deny-list",
    "C_denylist_europa": "Other / deny-list",
    "Z_other": "Other / deny-list",
}

# Fixed left-to-right order; never reordered.
GROUPS = [
    "Below confidence floor",
    "Verifier rejection",
    "Researcher never committed",
    "Retrieval failure",
    "Other / deny-list",
]

COLOUR = {
    "Below confidence floor": "#2a78d6",
    "Verifier rejection": "#1baf7a",
    "Researcher never committed": "#4a3aa7",
    "Retrieval failure": "#eb6834",
    "Other / deny-list": "#a9a79e",
}
# Dark ink where the fill is light enough that white would not hold up.
INK_ON = {
    "Below confidence floor": "#ffffff",
    "Verifier rejection": "#0b2b20",
    "Researcher never committed": "#ffffff",
    "Retrieval failure": "#ffffff",
    "Other / deny-list": "#1f1e1c",
}

INK_TITLE = "#161616"
INK_BODY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

X_MAX = 0.70      # headroom above the highest rate, and round tick steps
N_TICKS = 8       # 0.00 to 0.70 in steps of 0.10


def load_counts(records_csv: Path) -> dict[str, Counter]:
    """Per-country cause counts for the experiment's non-committed pairs."""
    counts: dict[str, Counter] = {}
    unknown: set[str] = set()
    with records_csv.open() as fh:
        for row in csv.DictReader(fh):
            if row["exp"] != EXPERIMENT_ID:
                continue
            cc = row["pair"].split(":")[1]
            group = GROUP_OF.get(row["cat"])
            if group is None:
                unknown.add(row["cat"])
                continue
            counts.setdefault(cc, Counter())[group] += 1
    if unknown:
        raise SystemExit(
            f"unmapped abstention categories: {sorted(unknown)}. Add them to "
            "GROUP_OF so no pair is silently dropped."
        )
    return counts


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(counts: dict[str, Counter]) -> str:
    width = 1040
    bar_x0, bar_w = 232, 650
    y0, row_pitch, bar_h = 132, 34, 22
    gap_before_summary = 22

    def sx(rate: float) -> float:
        return bar_x0 + (rate / X_MAX) * bar_w

    # Rows: each stratum's countries by abstention rate, then pooled summaries.
    def rate_of(cc: str) -> float:
        return sum(counts[cc].values()) / PAIRS_PER_COUNTRY

    rows: list[tuple[str, Counter, int, bool]] = []
    for stratum in (STRATUM_A, STRATUM_B):
        for cc in sorted(stratum, key=rate_of, reverse=True):
            rows.append((COUNTRY_NAMES[cc], counts[cc], PAIRS_PER_COUNTRY, False))
    summaries: list[tuple[str, Counter, int, bool]] = []
    for name, stratum in (("Stratum A (low-resource)", STRATUM_A),
                          ("Stratum B (higher-resource)", STRATUM_B)):
        pooled = Counter()
        for cc in stratum:
            pooled.update(counts[cc])
        summaries.append((name, pooled, PAIRS_PER_COUNTRY * len(stratum), True))

    n_rows = len(rows) + len(summaries)
    plot_bottom = y0 + n_rows * row_pitch + gap_before_summary
    height = int(plot_bottom + 118)

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, \'Segoe UI\', sans-serif">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(
        f'<text x="26" y="38" font-size="21" font-weight="700" '
        f'fill="{INK_TITLE}">Why the swarm abstains, by country (EXP-36)</text>'
    )
    out.append(
        f'<text x="26" y="60" font-size="13" fill="{INK_BODY}">'
        'Abstention rate over each country&#8217;s 143 pairs, split by cause. '
        'Countries grouped by D47 resource stratum, then by rate.</text>'
    )
    out.append(
        f'<text x="26" y="80" font-size="13" fill="{INK_BODY}">'
        'The stratum gap is almost entirely the confidence floor. Verifier '
        'rejection is flat across strata, and retrieval failure is near zero '
        'outside Bulgaria.</text>'
    )

    # Legend.
    lx, ly = 26, 108
    for group in GROUPS:
        out.append(f'<rect x="{lx}" y="{ly - 11}" width="13" height="13" '
                   f'rx="2.5" fill="{COLOUR[group]}"/>')
        out.append(f'<text x="{lx + 18}" y="{ly}" font-size="12" '
                   f'fill="{INK_TITLE}">{_esc(group)}</text>')
        lx += 18 + len(group) * 6.85 + 18

    # Vertical gridlines behind the bars.
    for i in range(N_TICKS):
        rate = X_MAX * i / (N_TICKS - 1)
        x = sx(rate)
        out.append(f'<line x1="{x:.1f}" y1="{y0 - 8}" x2="{x:.1f}" '
                   f'y2="{plot_bottom - gap_before_summary + 4:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')

    def draw_row(label, counter, denom, is_summary, y):
        total = sum(counter.values())
        rate = total / denom
        weight = "700" if is_summary else "400"
        out.append(
            f'<text x="{bar_x0 - 14}" y="{y + bar_h / 2 + 4:.1f}" '
            f'font-size="{12.5 if is_summary else 13}" font-weight="{weight}" '
            f'text-anchor="end" fill="{INK_TITLE}">{_esc(label)}</text>'
        )
        clip = f"clip{abs(hash((label, y))) % 100000}"
        out.append(f'<clipPath id="{clip}"><rect x="{bar_x0}" y="{y}" '
                   f'width="{max(sx(rate) - bar_x0, 1):.1f}" height="{bar_h}" '
                   f'rx="4" ry="4"/></clipPath>')
        out.append(f'<g clip-path="url(#{clip})">')
        cum = 0.0
        drawn = [g for g in GROUPS if counter.get(g, 0)]
        for group in drawn:
            seg_rate = counter[group] / denom
            x = sx(cum)
            seg_w = sx(cum + seg_rate) - x
            last = group == drawn[-1]
            w = seg_w if last else max(seg_w - 2, 0.5)
            out.append(f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" '
                       f'height="{bar_h}" fill="{COLOUR[group]}"/>')
            if seg_w >= 22:
                out.append(
                    f'<text x="{x + seg_w / 2:.2f}" '
                    f'y="{y + bar_h / 2 + 4:.1f}" font-size="11" '
                    f'text-anchor="middle" fill="{INK_ON[group]}">'
                    f'{counter[group]}</text>'
                )
            cum += seg_rate
        out.append('</g>')
        out.append(
            f'<text x="{sx(rate) + 9:.1f}" y="{y + bar_h / 2 + 4:.1f}" '
            f'font-size="11.5" font-weight="{weight}" fill="{INK_BODY}">'
            f'{rate:.3f}</text>'
        )

    y = y0
    for i, (label, counter, denom, is_summary) in enumerate(rows):
        draw_row(label, counter, denom, is_summary, y)
        y += row_pitch
        # Hairline between the two strata.
        if i == len(STRATUM_A) - 1:
            out.append(f'<line x1="{bar_x0 - 186}" y1="{y - 6:.1f}" '
                       f'x2="{bar_x0 + bar_w}" y2="{y - 6:.1f}" '
                       f'stroke="{GRID}" stroke-width="1"/>')

    y += gap_before_summary
    out.append(f'<line x1="{bar_x0 - 186}" y1="{y - 12:.1f}" '
               f'x2="{bar_x0 + bar_w}" y2="{y - 12:.1f}" '
               f'stroke="{AXIS}" stroke-width="1"/>')
    for label, counter, denom, is_summary in summaries:
        draw_row(label, counter, denom, is_summary, y)
        y += row_pitch

    # x axis.
    axis_y = y + 4
    out.append(f'<line x1="{bar_x0}" y1="{axis_y:.1f}" '
               f'x2="{bar_x0 + bar_w}" y2="{axis_y:.1f}" '
               f'stroke="{AXIS}" stroke-width="1"/>')
    for i in range(N_TICKS):
        rate = X_MAX * i / (N_TICKS - 1)
        out.append(f'<text x="{sx(rate):.1f}" y="{axis_y + 18:.1f}" '
                   f'font-size="11.5" text-anchor="middle" '
                   f'fill="{INK_MUTED}">{rate:.2f}</text>')
    out.append(f'<text x="{bar_x0 + bar_w / 2:.0f}" y="{axis_y + 40:.0f}" '
               f'font-size="12.5" text-anchor="middle" fill="{INK_BODY}">'
               f'Abstention rate</text>')

    fy = axis_y + 66
    out.append(
        f'<text x="26" y="{fy:.0f}" font-size="11.5" fill="{INK_BODY}">'
        'Segment labels are pair counts (country n = 143, stratum n = 572); '
        'bar length is the rate. Causes from the '
        '`abstention_taxonomy.py` register.</text>'
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    out.append(
        f'<text x="26" y="{fy + 18:.0f}" font-size="11" fill="{INK_MUTED}">'
        f'Source: {EXPERIMENT_ID}, 508 non-committed pairs of 1,144. '
        f'Generated {stamp}.</text>'
    )
    out.append('</svg>')
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records",
                    default=str(REPO_ROOT / "evaluation"
                                / "abstention_records.csv"))
    ap.add_argument("--out-dir",
                    default=str(REPO_ROOT / "evaluation" / "figures"))
    args = ap.parse_args()

    records = Path(args.records)
    if not records.exists():
        raise SystemExit(
            f"{records} not found. Run "
            "`uv run python evaluation/abstention_taxonomy.py` first."
        )
    counts = load_counts(records)
    missing = [cc for cc in STRATUM_A + STRATUM_B if cc not in counts]
    if missing:
        raise SystemExit(f"no {EXPERIMENT_ID} abstention rows for: {missing}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "abstention_causes_by_country.svg").write_text(build_svg(counts))

    with (out_dir / "abstention_causes_by_country.csv").open(
            "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["country", "stratum", "n_pairs", *GROUPS,
                    "total_abstained", "abstention_rate"])
        for stratum, name in ((STRATUM_A, "A"), (STRATUM_B, "B")):
            for cc in stratum:
                c = counts[cc]
                total = sum(c.values())
                w.writerow([cc, name, PAIRS_PER_COUNTRY,
                            *[c.get(g, 0) for g in GROUPS], total,
                            round(total / PAIRS_PER_COUNTRY, 4)])
        for stratum, name in ((STRATUM_A, "A"), (STRATUM_B, "B")):
            pooled = Counter()
            for cc in stratum:
                pooled.update(counts[cc])
            denom = PAIRS_PER_COUNTRY * len(stratum)
            total = sum(pooled.values())
            w.writerow([f"POOLED_{name}", name, denom,
                        *[pooled.get(g, 0) for g in GROUPS], total,
                        round(total / denom, 4)])

    total = sum(sum(c.values()) for c in counts.values())
    print(f"{total} non-committed pairs decomposed across "
          f"{len(counts)} countries")
    for stratum, name in ((STRATUM_A, "A"), (STRATUM_B, "B")):
        pooled = Counter()
        for cc in stratum:
            pooled.update(counts[cc])
        denom = PAIRS_PER_COUNTRY * len(stratum)
        parts = ", ".join(f"{g}={pooled.get(g, 0) / denom:.3f}" for g in GROUPS)
        print(f"  stratum {name}: rate {sum(pooled.values()) / denom:.3f} | {parts}")
    print(f"wrote {out_dir / 'abstention_causes_by_country.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
