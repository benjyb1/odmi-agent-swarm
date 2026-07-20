"""Reliability diagram for EXP-36, split by gold class, with bin counts.

Aggregate calibration can look healthy while the rare class is badly
miscalibrated, so an aggregate expected calibration error is not evidence that
a system's confidence means anything on the class that matters. This figure
splits the held-out committed answers by the ODMI gold they were graded
against and plots each class on its own axes.

The split is the point. On yes-golds the swarm is mildly *under*-confident:
every bin sits on or above the diagonal, so a stated 0.80 buys at least 0.80.
On no-golds the relationship inverts. Observed accuracy falls as stated
confidence rises, and in the top bin the swarm is wrong every time it is most
sure. A single aggregate number averages the two and reports neither.

Binning is the pre-registered scheme from `docs/EXPERIMENTS_EXP36_PREREG.md`:
ten equal-width bins over [0, 1]. Keeping it means the per-class ECEs here are
directly comparable to the aggregate the analysis pack reports, rather than an
artefact of a binning choice made for this plot. Every committed confidence
sits above the D37 floor of 0.65, so the six bins below 0.6 are empty and the
axes start at 0.6.

Panels cover the 523 committed, scoreable pairs whose gold is binary yes or no.
The aggregate ECE quoted in the subtitle is over all 623 committed scoreable
pairs, including the 100 with non-binary golds, which is the pack's figure.

Outputs (under evaluation/figures/):
  - reliability_by_class.svg   the chart, self-contained for the manuscript
  - reliability_by_class.csv   per-bin counts, accuracy and confidence

Usage:
    uv run python evaluation/reliability_by_class.py
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
    N_CALIBRATION_BINS,
    dedup_canonical,
    is_binary_gold,
    is_committed,
    is_match,
    is_scoreable,
    load_rows,
    norm,
)

EXPERIMENT_ID = "exp36_frozen_headline"
X_MIN = 0.6                      # every committed confidence clears the floor

INK_TITLE = "#161616"
INK_BODY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
DIAGONAL = "#a9a79e"
# Emphasis, not decoration: the yes class behaves, the no class is the problem.
CLASS_COLOUR = {"yes": "#2a78d6", "no": "#d03b3b"}


def bin_edges() -> list[float]:
    return [i / N_CALIBRATION_BINS for i in range(N_CALIBRATION_BINS + 1)]


def reliability(items) -> tuple[list[dict], float]:
    """Per-bin accuracy and mean confidence, plus the ECE over those bins."""
    edges = bin_edges()
    total = len(items)
    bins: list[dict] = []
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        top = hi == edges[-1]
        members = [
            r for r in items
            if r.final_confidence >= lo
            and (r.final_confidence <= hi if top else r.final_confidence < hi)
        ]
        if not members:
            bins.append({"lo": lo, "hi": hi, "n": 0,
                         "accuracy": None, "confidence": None})
            continue
        acc = sum(1 for r in members if is_match(r)) / len(members)
        conf = sum(r.final_confidence for r in members) / len(members)
        ece += (len(members) / total) * abs(acc - conf)
        bins.append({"lo": lo, "hi": hi, "n": len(members),
                     "accuracy": acc, "confidence": conf})
    return bins, ece


def build_data(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        rows, _ = dedup_canonical(load_rows(conn, EXPERIMENT_ID),
                                  scope_by_label=False)
    finally:
        conn.close()
    scoreable = [r for r in rows if is_committed(r) and is_scoreable(r)]
    binary = [r for r in scoreable if is_binary_gold(r)]
    per_class = {
        cls: reliability([r for r in binary if norm(r.gold_answer) == cls])
        for cls in ("yes", "no")
    }
    _, aggregate_ece = reliability(scoreable)
    return per_class, aggregate_ece, len(scoreable)


def _panel(out: list[str], cls: str, bins: list[dict], ece: float,
           px0: float, py0: float, pw: float, ph: float, hist_h: float) -> None:
    """One class panel: reliability plot with a count histogram beneath."""
    colour = CLASS_COLOUR[cls]
    populated = [b for b in bins if b["n"]]
    n_total = sum(b["n"] for b in populated)

    def sx(v: float) -> float:
        return px0 + (v - X_MIN) / (1 - X_MIN) * pw

    def sy(v: float) -> float:
        return py0 + (1 - v) * ph

    label = "Yes-golds" if cls == "yes" else "No-golds"
    out.append(f'<text x="{px0}" y="{py0 - 34}" font-size="15" '
               f'font-weight="700" fill="{INK_TITLE}">'
               f'{label} (n = {n_total})</text>')
    verdict = ("under-confident: bins sit on or above the line"
               if cls == "yes"
               else "inverted: accuracy falls as confidence rises")
    out.append(f'<text x="{px0}" y="{py0 - 16}" font-size="12" '
               f'fill="{INK_BODY}">ECE '
               f'<tspan font-weight="700" fill="{colour}">{ece:.3f}</tspan> '
               f'&#8212; {verdict}</text>')

    # Grid and axes.
    for i in range(6):
        v = i / 5
        y = sy(v)
        out.append(f'<line x1="{px0}" y1="{y:.1f}" x2="{px0 + pw}" '
                   f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{px0 - 10}" y="{y + 4:.1f}" font-size="11" '
                   f'text-anchor="end" fill="{INK_MUTED}">{v:.1f}</text>')
    out.append(f'<line x1="{px0}" y1="{py0}" x2="{px0}" y2="{py0 + ph}" '
               f'stroke="{AXIS}" stroke-width="1"/>')
    out.append(f'<line x1="{px0}" y1="{py0 + ph}" x2="{px0 + pw}" '
               f'y2="{py0 + ph}" stroke="{AXIS}" stroke-width="1"/>')

    # Perfect-calibration diagonal.
    out.append(f'<line x1="{sx(X_MIN):.1f}" y1="{sy(X_MIN):.1f}" '
               f'x2="{sx(1.0):.1f}" y2="{sy(1.0):.1f}" stroke="{DIAGONAL}" '
               f'stroke-width="1.5" stroke-dasharray="6 4"/>')
    # Sits below the diagonal at its left end, where both panels are empty.
    out.append(f'<text x="{sx(0.618):.1f}" y="{sy(0.618) + 15:.1f}" '
               f'font-size="10.5" fill="{INK_MUTED}">perfect calibration</text>')

    # Gap sticks from the diagonal to each observed point, then the points.
    for b in populated:
        x, y = sx(b["confidence"]), sy(b["accuracy"])
        out.append(f'<line x1="{x:.1f}" y1="{sy(b["confidence"]):.1f}" '
                   f'x2="{x:.1f}" y2="{y:.1f}" stroke="{colour}" '
                   f'stroke-width="1.5" opacity="0.45"/>')
    pts = " ".join(f'{sx(b["confidence"]):.1f},{sy(b["accuracy"]):.1f}'
                   for b in populated)
    out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" '
               f'stroke-width="2" stroke-linejoin="round"/>')
    for b in populated:
        x, y = sx(b["confidence"]), sy(b["accuracy"])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{colour}" '
                   f'stroke="#ffffff" stroke-width="2"/>')
        # Near the top of the panel the label would run into the panel
        # subtitle, so it flips below the marker.
        dy = 18 if b["accuracy"] > 0.93 else -13
        out.append(f'<text x="{x:.1f}" y="{y + dy:.1f}" font-size="10.5" '
                   f'text-anchor="middle" fill="{INK_BODY}">'
                   f'{b["accuracy"]:.2f}</text>')

    out.append(f'<text x="{px0 - 44}" y="{py0 + ph / 2:.0f}" font-size="12" '
               f'text-anchor="middle" fill="{INK_BODY}" '
               f'transform="rotate(-90 {px0 - 44} {py0 + ph / 2:.0f})">'
               f'Observed accuracy</text>')

    # Count histogram beneath, sharing the x scale.
    hy = py0 + ph + 46
    max_n = max(b["n"] for b in populated)
    out.append(f'<text x="{px0 - 44}" y="{hy + hist_h / 2:.0f}" font-size="11" '
               f'text-anchor="middle" fill="{INK_MUTED}" '
               f'transform="rotate(-90 {px0 - 44} {hy + hist_h / 2:.0f})">'
               f'pairs</text>')
    bar_w = pw / N_CALIBRATION_BINS
    for b in bins:
        if not b["n"]:
            continue
        bh = (b["n"] / max_n) * hist_h
        bx = sx(b["lo"]) if b["lo"] >= X_MIN else px0
        out.append(f'<rect x="{bx + 2:.1f}" y="{hy + hist_h - bh:.1f}" '
                   f'width="{bar_w - 4:.1f}" height="{bh:.1f}" '
                   f'fill="{colour}" opacity="0.30"/>')
        out.append(f'<text x="{bx + bar_w / 2:.1f}" '
                   f'y="{hy + hist_h - bh - 5:.1f}" font-size="10.5" '
                   f'text-anchor="middle" fill="{INK_BODY}">{b["n"]}</text>')
    out.append(f'<line x1="{px0}" y1="{hy + hist_h}" x2="{px0 + pw}" '
               f'y2="{hy + hist_h}" stroke="{AXIS}" stroke-width="1"/>')

    # Shared x ticks under the histogram.
    for i in range(5):
        v = X_MIN + (1 - X_MIN) * i / 4
        out.append(f'<text x="{sx(v):.1f}" y="{hy + hist_h + 18:.1f}" '
                   f'font-size="11" text-anchor="middle" fill="{INK_MUTED}">'
                   f'{v:.2f}</text>')
    out.append(f'<text x="{px0 + pw / 2:.0f}" y="{hy + hist_h + 40:.0f}" '
               f'font-size="12" text-anchor="middle" fill="{INK_BODY}">'
               f'Stated confidence</text>')


def build_svg(per_class, aggregate_ece, n_scoreable) -> str:
    width, height = 1040, 660
    pw, ph, hist_h = 350, 250, 70
    left_x, right_x = 96, 606
    top_y = 148

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, \'Segoe UI\', sans-serif">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(
        f'<text x="26" y="38" font-size="21" font-weight="700" '
        f'fill="{INK_TITLE}">Reliability by gold class, held-out eight '
        f'(EXP-36)</text>'
    )
    out.append(
        f'<text x="26" y="60" font-size="13" fill="{INK_BODY}">'
        f'Aggregate ECE is '
        f'<tspan font-weight="700">{aggregate_ece:.3f}</tspan> over all '
        f'{n_scoreable} committed scoreable pairs, which reads as well '
        f'calibrated. Splitting by gold class shows it is not.</text>'
    )
    out.append(
        f'<text x="26" y="80" font-size="13" fill="{INK_BODY}">'
        f'The rare negative class carries an ECE of '
        f'<tspan font-weight="700" fill="{CLASS_COLOUR["no"]}">'
        f'{per_class["no"][1]:.3f}</tspan>, and its confidence is inverted: '
        f'in the top bin the swarm is always wrong.</text>'
    )

    _panel(out, "yes", per_class["yes"][0], per_class["yes"][1],
           left_x, top_y, pw, ph, hist_h)
    _panel(out, "no", per_class["no"][0], per_class["no"][1],
           right_x, top_y, pw, ph, hist_h)

    fy = top_y + ph + 46 + hist_h + 76
    out.append(
        f'<text x="26" y="{fy}" font-size="11.5" fill="{INK_BODY}">'
        f'Points show observed accuracy against mean stated confidence per '
        f'bin; the stick is the gap from perfect calibration. Bins below 0.6 '
        f'are empty (D37 floor 0.65).</text>'
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    out.append(
        f'<text x="26" y="{fy + 18}" font-size="11" fill="{INK_MUTED}">'
        f'Source: {EXPERIMENT_ID}, latest row per (question, country). '
        f'Panels: 523 binary-gold committed pairs; pre-registered '
        f'{N_CALIBRATION_BINS} bins over [0,1]. Generated {stamp}.</text>'
    )
    out.append('</svg>')
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "odmi.db"))
    ap.add_argument("--out-dir",
                    default=str(REPO_ROOT / "evaluation" / "figures"))
    args = ap.parse_args()

    per_class, aggregate_ece, n_scoreable = build_data(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reliability_by_class.svg").write_text(
        build_svg(per_class, aggregate_ece, n_scoreable)
    )
    with (out_dir / "reliability_by_class.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["gold_class", "bin_lo", "bin_hi", "n",
                    "observed_accuracy", "mean_confidence", "gap"])
        for cls, (bins, _) in per_class.items():
            for b in bins:
                if not b["n"]:
                    continue
                w.writerow([cls, b["lo"], b["hi"], b["n"],
                            round(b["accuracy"], 4), round(b["confidence"], 4),
                            round(b["accuracy"] - b["confidence"], 4)])
        w.writerow([])
        for cls, (_, ece) in per_class.items():
            w.writerow([f"ece_{cls}_gold", round(ece, 4)])
        w.writerow(["ece_aggregate_all_scoreable", round(aggregate_ece, 4)])

    for cls, (_, ece) in per_class.items():
        print(f"ECE {cls}-gold {ece:.4f}")
    print(f"ECE aggregate {aggregate_ece:.4f} over {n_scoreable} pairs")
    print(f"wrote {out_dir / 'reliability_by_class.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
