"""Per-class accuracy against commit threshold, held-out eight (EXP-36).

No setting of the confidence threshold makes this system safe to publish
unreviewed. Tightening the threshold improves the positive class and destroys
the negative one, and the two move in opposite directions the whole way up.
Any apparent aggregate improvement is the positive class outnumbering the
negative one, not the system getting better.

The sweep is continuous over the swarm's stated confidence, from the D37 floor
of 0.65 (where every committed answer is retained) to the maximum observed, in
steps of SWEEP_STEP. Confidence is never binned: at each threshold the retained
set is recomputed from scratch and scored separately per gold class, each with
a Wilson 95% interval. The interval is load-bearing rather than decorative,
because the no-gold class thins to three pairs at the top of the range and an
unbanded line there would read as certainty.

Population is the 523 committed, scoreable pairs whose ODMI gold is binary yes
or no (339 yes, 184 no). Non-binary answer shapes are excluded: a percentage
band has no positive or negative class to separate.

Validation, asserted at run time against the filed figures for the frozen
held-out run: at threshold 0.65 the yes-gold line must read 0.870 on n = 339
and the no-gold line 0.489 on n = 184. If those endpoints do not reproduce the
sweep is wrong and nothing else in the figure can be trusted, so the script
raises rather than writing a plausible-looking chart.

Outputs (under evaluation/figures/):
  - per_class_accuracy_vs_threshold.svg  the chart, self-contained
  - per_class_accuracy_vs_threshold.csv  the swept points (receipts)

Usage:
    uv run python evaluation/per_class_accuracy_vs_threshold.py
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
    is_binary_gold,
    is_committed,
    is_match,
    is_scoreable,
    load_rows,
    norm,
)
from evaluation.stats import wilson_interval  # noqa: E402

EXPERIMENT_ID = "exp36_frozen_headline"
PRODUCTION_FLOOR = 0.65
SWEEP_STEP = 0.005

# Filed true-positive and true-negative rates for the frozen held-out run.
# The sweep must reproduce these at the floor or the figure is not written.
ANCHORS = {"yes": (339, 0.870), "no": (184, 0.489)}

CLASS_COLOUR = {"yes": "#2a78d6", "no": "#d03b3b"}
CLASS_LABEL = {"yes": "Yes-golds", "no": "No-golds"}

INK_TITLE = "#161616"
INK_BODY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
RULE = "#52514e"

X_LO, X_HI = PRODUCTION_FLOOR, 1.00


def load_population(db_path: str) -> dict[str, list]:
    conn = sqlite3.connect(db_path)
    try:
        rows, _ = dedup_canonical(load_rows(conn, EXPERIMENT_ID),
                                  scope_by_label=False)
    finally:
        conn.close()
    pop = [r for r in rows
           if is_committed(r) and is_scoreable(r) and is_binary_gold(r)]
    return {cls: [r for r in pop if norm(r.gold_answer) == cls]
            for cls in ("yes", "no")}


def sweep(population: dict[str, list]) -> list[dict]:
    """Accuracy, retained n and Wilson interval per class at each threshold."""
    top = max(r.final_confidence for cls in population
              for r in population[cls])
    points: list[dict] = []
    steps = int(round((top - PRODUCTION_FLOOR) / SWEEP_STEP))
    for i in range(steps + 1):
        t = PRODUCTION_FLOOR + i * SWEEP_STEP
        row: dict = {"threshold": round(t, 4)}
        for cls, items in population.items():
            kept = [r for r in items if r.final_confidence >= t - 1e-9]
            if kept:
                hits = sum(1 for r in kept if is_match(r))
                lo, hi = wilson_interval(hits, len(kept))
                row[cls] = {"n": len(kept), "accuracy": hits / len(kept),
                            "lo": lo, "hi": hi}
            else:
                row[cls] = {"n": 0, "accuracy": None, "lo": None, "hi": None}
        points.append(row)
    return points


def validate(points: list[dict]) -> None:
    """Refuse to emit a figure whose endpoints do not match the filed run."""
    floor = points[0]
    assert abs(floor["threshold"] - PRODUCTION_FLOOR) < 1e-9, (
        f"sweep starts at {floor['threshold']}, not {PRODUCTION_FLOOR}"
    )
    for cls, (want_n, want_acc) in ANCHORS.items():
        got_n = floor[cls]["n"]
        got_acc = floor[cls]["accuracy"]
        if got_n != want_n or got_acc is None or abs(got_acc - want_acc) > 5e-4:
            raise SystemExit(
                f"VALIDATION FAILED for {cls}-gold at {PRODUCTION_FLOOR}: "
                f"got n={got_n} accuracy={got_acc}, expected n={want_n} "
                f"accuracy={want_acc}. The sweep is wrong; no figure written."
            )
    print(f"validation OK at {PRODUCTION_FLOOR}: "
          + ", ".join(f"{c}-gold {floor[c]['accuracy']:.3f} on n={floor[c]['n']}"
                      for c in ("yes", "no")))


def build_svg(points: list[dict]) -> str:
    width, height = 1060, 736
    x0, y0, pw, ph = 100, 140, 782, 356
    strip_y, strip_h = 540, 74

    def sx(t: float) -> float:
        return x0 + (t - X_LO) / (X_HI - X_LO) * pw

    def sy(a: float) -> float:
        return y0 + (1 - a) * ph

    max_n = max(p[c]["n"] for p in points for c in ("yes", "no"))

    def sny(n: int) -> float:
        return strip_y + strip_h - (n / max_n) * strip_h

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, \'Segoe UI\', sans-serif">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(
        f'<text x="26" y="38" font-size="21" font-weight="700" '
        f'fill="{INK_TITLE}">Per-class accuracy against commit threshold, '
        f'held-out eight (EXP-36)</text>'
    )
    out.append(
        f'<text x="26" y="60" font-size="13" fill="{INK_BODY}">'
        'Raising the threshold keeps only the answers the swarm was more sure '
        'of, and rescores each class on whatever survives.</text>'
    )
    out.append(
        f'<text x="26" y="84" font-size="14" font-weight="700" '
        f'fill="{INK_TITLE}">As the bar rises the swarm gets nearly everything '
        f'right when the answer is yes, and everything wrong when it is '
        f'no.</text>'
    )

    # Legend, backing up the direct labels rather than replacing them.
    lx = x0
    for cls in ("yes", "no"):
        out.append(f'<rect x="{lx}" y="{104}" width="13" height="13" rx="2.5" '
                   f'fill="{CLASS_COLOUR[cls]}"/>')
        out.append(f'<text x="{lx + 18}" y="{115}" font-size="12.5" '
                   f'fill="{INK_TITLE}">{CLASS_LABEL[cls]}</text>')
        lx += 18 + len(CLASS_LABEL[cls]) * 7.2 + 26
    out.append(f'<text x="{lx}" y="{115}" font-size="12" fill="{INK_MUTED}">'
               f'shaded band = Wilson 95% interval</text>')

    # Horizontal grid and accuracy ticks.
    for i in range(6):
        a = i / 5
        y = sy(a)
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + pw}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x0 - 12}" y="{y + 4:.1f}" font-size="11.5" '
                   f'text-anchor="end" fill="{INK_MUTED}">{a:.1f}</text>')

    # Coin-flip reference.
    out.append(f'<line x1="{x0}" y1="{sy(0.5):.1f}" x2="{x0 + pw}" '
               f'y2="{sy(0.5):.1f}" stroke="{INK_MUTED}" stroke-width="1" '
               f'stroke-dasharray="4 4" opacity="0.75"/>')
    out.append(f'<text x="{x0 + pw - 4:.1f}" y="{sy(0.5) - 7:.1f}" '
               f'font-size="11" text-anchor="end" fill="{INK_MUTED}">'
               f'coin flip (0.5)</text>')

    # Wilson ribbons, then lines, per class.
    for cls in ("yes", "no"):
        valid = [p for p in points if p[cls]["n"] > 0]
        upper = " ".join(f'{sx(p["threshold"]):.1f},{sy(p[cls]["hi"]):.1f}'
                         for p in valid)
        lower = " ".join(f'{sx(p["threshold"]):.1f},{sy(p[cls]["lo"]):.1f}'
                         for p in reversed(valid))
        out.append(f'<polygon points="{upper} {lower}" '
                   f'fill="{CLASS_COLOUR[cls]}" opacity="0.16"/>')
    for cls in ("yes", "no"):
        valid = [p for p in points if p[cls]["n"] > 0]
        line = " ".join(f'{sx(p["threshold"]):.1f},{sy(p[cls]["accuracy"]):.1f}'
                        for p in valid)
        out.append(f'<polyline points="{line}" fill="none" '
                   f'stroke="{CLASS_COLOUR[cls]}" stroke-width="2.5" '
                   f'stroke-linejoin="round"/>')
        # Direct label at the right-hand end of the line.
        last = valid[-1]
        lx_end = sx(last["threshold"])
        ly_end = sy(last[cls]["accuracy"])
        dy = -12 if cls == "yes" else -46
        out.append(f'<circle cx="{lx_end:.1f}" cy="{ly_end:.1f}" r="4" '
                   f'fill="{CLASS_COLOUR[cls]}" stroke="#ffffff" '
                   f'stroke-width="1.5"/>')
        out.append(
            f'<text x="{lx_end + 8:.1f}" y="{ly_end + dy:.1f}" font-size="13" '
            f'font-weight="700" fill="{CLASS_COLOUR[cls]}">'
            f'{CLASS_LABEL[cls]}</text>'
        )
        out.append(
            f'<text x="{lx_end + 8:.1f}" y="{ly_end + dy + 15:.1f}" '
            f'font-size="11" fill="{INK_BODY}">ends {last[cls]["accuracy"]:.2f} '
            f'at n = {last[cls]["n"]}</text>'
        )

    # Retained-n callouts on the no-gold line, so the thinning is visible.
    for target in (0.70, 0.75, 0.82):
        hit = min(points, key=lambda p: abs(p["threshold"] - target))
        block = hit["no"]
        if not block["n"]:
            continue
        cx, cy = sx(hit["threshold"]), sy(block["accuracy"])
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" '
                   f'fill="{CLASS_COLOUR["no"]}" stroke="#ffffff" '
                   f'stroke-width="1.5"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 18:.1f}" '
                   f'font-size="10.5" text-anchor="middle" '
                   f'fill="{CLASS_COLOUR["no"]}">n = {block["n"]}</text>')

    # Operating-point rule at the D37 floor, with both accuracies annotated.
    floor = points[0]
    fx = sx(PRODUCTION_FLOOR)
    out.append(f'<line x1="{fx:.1f}" y1="{y0 - 6}" x2="{fx:.1f}" '
               f'y2="{strip_y + strip_h:.1f}" stroke="{RULE}" '
               f'stroke-width="1.5" stroke-dasharray="5 4"/>')
    out.append(f'<text x="{fx + 8:.1f}" y="{sy(0.70):.1f}" font-size="11.5" '
               f'font-weight="700" fill="{RULE}">Operating point '
               f'(D37 floor 0.65)</text>')
    for cls in ("yes", "no"):
        a = floor[cls]["accuracy"]
        out.append(f'<circle cx="{fx:.1f}" cy="{sy(a):.1f}" r="5" '
                   f'fill="{CLASS_COLOUR[cls]}" stroke="#ffffff" '
                   f'stroke-width="2"/>')
        out.append(
            f'<text x="{fx + 10:.1f}" y="{sy(a) - 9:.1f}" font-size="12" '
            f'font-weight="700" fill="{CLASS_COLOUR[cls]}">{a:.3f}</text>'
        )
        out.append(
            f'<text x="{fx + 10:.1f}" y="{sy(a) + 6:.1f}" font-size="10.5" '
            f'fill="{INK_BODY}">n = {floor[cls]["n"]}</text>'
        )

    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0 + ph}" '
               f'stroke="{AXIS}" stroke-width="1"/>')
    out.append(f'<line x1="{x0}" y1="{y0 + ph}" x2="{x0 + pw}" '
               f'y2="{y0 + ph}" stroke="{AXIS}" stroke-width="1"/>')
    out.append(f'<text x="{x0 - 52}" y="{y0 + ph / 2:.0f}" font-size="13" '
               f'text-anchor="middle" fill="{INK_BODY}" '
               f'transform="rotate(-90 {x0 - 52} {y0 + ph / 2:.0f})">'
               f'Accuracy on retained answers</text>')

    # Companion strip: how many pairs each line is standing on.
    out.append(f'<text x="{x0}" y="{strip_y - 12}" font-size="12" '
               f'fill="{INK_BODY}">Pairs retained at each threshold</text>')
    for cls in ("yes", "no"):
        pts = " ".join(f'{sx(p["threshold"]):.1f},{sny(p[cls]["n"]):.1f}'
                       for p in points)
        out.append(f'<polyline points="{pts}" fill="none" '
                   f'stroke="{CLASS_COLOUR[cls]}" stroke-width="2"/>')
    for value in (0, max_n):
        out.append(f'<line x1="{x0}" y1="{sny(value):.1f}" x2="{x0 + pw}" '
                   f'y2="{sny(value):.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x0 - 12}" y="{sny(value) + 4:.1f}" '
                   f'font-size="10.5" text-anchor="end" fill="{INK_MUTED}">'
                   f'{value}</text>')

    # Shared x axis beneath the strip.
    axis_y = strip_y + strip_h
    out.append(f'<line x1="{x0}" y1="{axis_y:.1f}" x2="{x0 + pw}" '
               f'y2="{axis_y:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    for i in range(8):
        t = X_LO + (X_HI - X_LO) * i / 7
        out.append(f'<text x="{sx(t):.1f}" y="{axis_y + 20:.1f}" '
                   f'font-size="11.5" text-anchor="middle" '
                   f'fill="{INK_MUTED}">{t:.2f}</text>')
    out.append(f'<text x="{x0 + pw / 2:.0f}" y="{axis_y + 44:.0f}" '
               f'font-size="13" text-anchor="middle" fill="{INK_BODY}">'
               f'Commit threshold (minimum stated confidence retained)</text>')

    no_last = [p for p in points if p["no"]["n"] > 0][-1]
    fy = axis_y + 74
    out.append(
        f'<text x="26" y="{fy:.0f}" font-size="11.5" fill="{INK_BODY}">'
        f'Sweep is continuous in steps of {SWEEP_STEP}, not binned. The '
        f'no-gold line ends at threshold {no_last["threshold"]:.2f}, its '
        f'highest observed confidence, on n = {no_last["no"]["n"]}; beyond '
        f'that the class is empty.</text>'
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    out.append(
        f'<text x="26" y="{fy + 18:.0f}" font-size="11" fill="{INK_MUTED}">'
        f'Source: {EXPERIMENT_ID}, latest row per (question, country). '
        f'n = 523 binary-gold committed pairs (339 yes, 184 no); non-binary '
        f'shapes excluded. Generated {stamp}.</text>'
    )
    out.append('</svg>')
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "odmi.db"))
    ap.add_argument("--out-dir",
                    default=str(REPO_ROOT / "evaluation" / "figures"))
    args = ap.parse_args()

    population = load_population(args.db)
    print(f"population {sum(len(v) for v in population.values())} "
          f"(yes {len(population['yes'])}, no {len(population['no'])})")
    points = sweep(population)
    validate(points)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "per_class_accuracy_vs_threshold.svg").write_text(
        build_svg(points))
    with (out_dir / "per_class_accuracy_vs_threshold.csv").open(
            "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["threshold",
                    "yes_n", "yes_accuracy", "yes_wilson_lo", "yes_wilson_hi",
                    "no_n", "no_accuracy", "no_wilson_lo", "no_wilson_hi"])
        for p in points:
            row = [p["threshold"]]
            for cls in ("yes", "no"):
                b = p[cls]
                row += [b["n"],
                        None if b["accuracy"] is None else round(b["accuracy"], 6),
                        None if b["lo"] is None else round(b["lo"], 6),
                        None if b["hi"] is None else round(b["hi"], 6)]
            w.writerow(row)

    no_last = [p for p in points if p["no"]["n"] > 0][-1]
    print(f"no-gold terminal: threshold {no_last['threshold']:.2f}, "
          f"accuracy {no_last['no']['accuracy']:.3f}, n = {no_last['no']['n']}")
    print(f"wrote {out_dir / 'per_class_accuracy_vs_threshold.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
