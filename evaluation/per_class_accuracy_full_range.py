"""Per-class accuracy across the full confidence range, above and below the
D37 commit floor (EXP-36 held-out).

The companion to `per_class_accuracy_vs_threshold.py`, which sweeps only the
range the system actually committed in. This one extends the sweep below the
floor, and the extension is the point: the floor at 0.65 is not a neutral
quality gate, it is the line at which the swarm stops being able to say no.

Above the floor the swarm is yes-biased. It gets yes-gold questions almost
always right and no-gold questions mostly wrong, and tightening the threshold
makes both worse in opposite directions. Below the floor that profile reverses.
The answers the pipeline discarded for being under-confident are mostly `no`,
and they are mostly right about `no` and wrong about `yes`. So the floor is
systematically throwing away correct negative answers, which is the class the
system is already worst at.

Two populations, kept visually and statistically distinct:

  Observed (>= 0.65). The 523 committed, scoreable, binary-gold pairs, scored
  on the pipeline's final answer at its final confidence. Identical to the
  as-run figure, and the floor endpoints are asserted against the filed rates.

  Counterfactual (< 0.65). The pairs the taxonomy attributes to
  `G_below_confidence_floor`: the researcher reached an answer but its
  confidence fell under 0.65, so the pipeline abstained. Of the 199 such pairs,
  161 carry a binary yes/no gold and a yes/no researcher answer and can be
  scored (73 yes-gold, 88 no-gold). They are scored on the researcher's answer
  at the researcher's confidence.

The counterfactual is a floor-relaxation, not a rerun. It answers "what were
these answers worth" and not "what would the system have produced", because a
lower floor would also change what the Verifier and Adjudicator saw downstream.
Every one of the 161 sits strictly below 0.65 by construction, so it
contributes nothing at or above the floor: the observed curve is untouched and
the two segments join continuously at 0.65. The sub-floor segment is drawn
dashed, and the legend labels it counterfactual, so it is not mistaken for
observed behaviour.

Outputs (under evaluation/figures/):
  - per_class_accuracy_full_range.svg   the chart, self-contained
  - per_class_accuracy_full_range.csv   the swept points (receipts)

Usage:
    uv run python evaluation/per_class_accuracy_full_range.py
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
SUBFLOOR_CATEGORY = "G_below_confidence_floor"

# Filed true-positive and true-negative rates at the floor. Asserted.
ANCHORS = {"yes": (339, 0.870), "no": (184, 0.489)}

CLASS_COLOUR = {"yes": "#2a78d6", "no": "#d03b3b"}
CLASS_LABEL = {"yes": "Yes-golds", "no": "No-golds"}

INK_TITLE = "#161616"
INK_BODY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
RULE = "#52514e"


def load_observed(db_path: str) -> dict[str, list[tuple[float, bool]]]:
    """(confidence, correct) per class for the committed binary-gold pairs."""
    conn = sqlite3.connect(db_path)
    try:
        rows, _ = dedup_canonical(load_rows(conn, EXPERIMENT_ID),
                                  scope_by_label=False)
    finally:
        conn.close()
    out: dict[str, list[tuple[float, bool]]] = {"yes": [], "no": []}
    for r in rows:
        if is_committed(r) and is_scoreable(r) and is_binary_gold(r):
            out[norm(r.gold_answer)].append((r.final_confidence, is_match(r)))
    return out


def load_subfloor(db_path: str, records_csv: Path
                  ) -> dict[str, list[tuple[float, bool]]]:
    """(confidence, correct) per class for pairs abstained under the floor.

    Scored on the researcher's best answer at the researcher's confidence.
    """
    wanted = {
        tuple(row["pair"].split(":"))
        for row in csv.DictReader(records_csv.open())
        if row["exp"] == EXPERIMENT_ID and row["cat"] == SUBFLOOR_CATEGORY
    }
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows, _ = dedup_canonical(load_rows(conn, EXPERIMENT_ID),
                                  scope_by_label=False)
        by_key = {(r.question_id, r.country_code): r for r in rows}
        query = """
            SELECT r.answer, r.answer_confidence
            FROM phase2_researcher_runs r
            JOIN phase2_final f ON f.pair_run_id = r.pair_run_id
            WHERE f.id = ?
              AND r.answer IS NOT NULL AND r.answer_confidence IS NOT NULL
            ORDER BY r.answer_confidence DESC, r.retry_count ASC, r.id ASC
            LIMIT 1
        """
        out: dict[str, list[tuple[float, bool]]] = {"yes": [], "no": []}
        for key in wanted:
            row = by_key.get(key)
            if row is None or not is_binary_gold(row):
                continue
            best = conn.execute(query, (row.row_id,)).fetchone()
            if best is None:
                continue
            answer = norm(best["answer"])
            if answer not in ("yes", "no"):
                continue
            conf = best["answer_confidence"]
            if conf >= PRODUCTION_FLOOR:
                raise SystemExit(
                    f"{SUBFLOOR_CATEGORY} pair {key} has confidence {conf} at "
                    f"or above the floor; the sub-floor population must sit "
                    f"strictly below {PRODUCTION_FLOOR}."
                )
            gold = norm(row.gold_answer)
            out[gold].append((conf, answer == gold))
    finally:
        conn.close()
    return out


def sweep(observed, subfloor) -> list[dict]:
    lowest = min(c for cls in subfloor for c, _ in subfloor[cls])
    highest = max(c for cls in observed for c, _ in observed[cls])
    start = round(lowest - 0.005, 3)
    steps = int(round((highest - start) / SWEEP_STEP))
    points: list[dict] = []
    for i in range(steps + 1):
        t = start + i * SWEEP_STEP
        row: dict = {"threshold": round(t, 4)}
        for cls in ("yes", "no"):
            pool = [p for p in observed[cls] if p[0] >= t - 1e-9]
            extra = [p for p in subfloor[cls] if p[0] >= t - 1e-9]
            kept = pool + extra
            if kept:
                hits = sum(1 for _, ok in kept if ok)
                lo, hi = wilson_interval(hits, len(kept))
                row[cls] = {"n": len(kept), "n_subfloor": len(extra),
                            "accuracy": hits / len(kept), "lo": lo, "hi": hi}
            else:
                row[cls] = {"n": 0, "n_subfloor": 0,
                            "accuracy": None, "lo": None, "hi": None}
        points.append(row)
    return points


def validate(points: list[dict]) -> None:
    """The floor must still reproduce the filed run, extension notwithstanding."""
    at_floor = min(points, key=lambda p: abs(p["threshold"] - PRODUCTION_FLOOR))
    if abs(at_floor["threshold"] - PRODUCTION_FLOOR) > 1e-6:
        raise SystemExit("sweep grid does not land on the floor exactly")
    for cls, (want_n, want_acc) in ANCHORS.items():
        block = at_floor[cls]
        if block["n_subfloor"]:
            raise SystemExit(
                f"{block['n_subfloor']} sub-floor pairs leaked into the "
                f"{cls} class at the floor; the observed curve is polluted."
            )
        if block["n"] != want_n or abs(block["accuracy"] - want_acc) > 5e-4:
            raise SystemExit(
                f"VALIDATION FAILED for {cls}-gold at {PRODUCTION_FLOOR}: got "
                f"n={block['n']} accuracy={block['accuracy']}, expected "
                f"n={want_n} accuracy={want_acc}. No figure written."
            )
    print(f"validation OK at {PRODUCTION_FLOOR}: "
          + ", ".join(f"{c}-gold {at_floor[c]['accuracy']:.3f} "
                      f"on n={at_floor[c]['n']}" for c in ("yes", "no")))


def build_svg(points: list[dict]) -> str:
    width, height = 1080, 700
    x0, y0, pw, ph = 104, 100, 800, 348
    strip_y, strip_h = 496, 72
    x_lo = points[0]["threshold"]
    x_hi = 1.00

    def sx(t: float) -> float:
        return x0 + (t - x_lo) / (x_hi - x_lo) * pw

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
        f'fill="{INK_TITLE}">Per-class accuracy across the confidence '
        f'range</text>'
    )

    # Legend.
    lx = x0
    for cls in ("yes", "no"):
        out.append(f'<rect x="{lx}" y="62" width="13" height="13" rx="2.5" '
                   f'fill="{CLASS_COLOUR[cls]}"/>')
        out.append(f'<text x="{lx + 18}" y="73" font-size="12.5" '
                   f'fill="{INK_TITLE}">{CLASS_LABEL[cls]}</text>')
        lx += 18 + len(CLASS_LABEL[cls]) * 7.2 + 26
    out.append(f'<text x="{lx}" y="73" font-size="12" fill="{INK_MUTED}">'
               f'band = Wilson 95%; dashed = counterfactual</text>')

    for i in range(6):
        a = i / 5
        y = sy(a)
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + pw}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x0 - 12}" y="{y + 4:.1f}" font-size="11.5" '
                   f'text-anchor="end" fill="{INK_MUTED}">{a:.1f}</text>')

    out.append(f'<line x1="{x0}" y1="{sy(0.5):.1f}" x2="{x0 + pw}" '
               f'y2="{sy(0.5):.1f}" stroke="{INK_MUTED}" stroke-width="1" '
               f'stroke-dasharray="4 4" opacity="0.75"/>')
    out.append(f'<text x="{x0 + pw - 4:.1f}" y="{sy(0.5) - 7:.1f}" '
               f'font-size="11" text-anchor="end" fill="{INK_MUTED}">'
               f'coin flip (0.5)</text>')

    # Ribbons across the whole range, then split lines by side of the floor.
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
        below = [p for p in valid
                 if p["threshold"] <= PRODUCTION_FLOOR + 1e-9]
        above = [p for p in valid
                 if p["threshold"] >= PRODUCTION_FLOOR - 1e-9]
        for segment, dash in ((below, ' stroke-dasharray="7 4"'), (above, "")):
            if len(segment) < 2:
                continue
            pts = " ".join(f'{sx(p["threshold"]):.1f},'
                           f'{sy(p[cls]["accuracy"]):.1f}' for p in segment)
            out.append(f'<polyline points="{pts}" fill="none" '
                       f'stroke="{CLASS_COLOUR[cls]}" stroke-width="2.5" '
                       f'stroke-linejoin="round"{dash}/>')
        last = valid[-1]
        ex, ey = sx(last["threshold"]), sy(last[cls]["accuracy"])
        dy = -12 if cls == "yes" else -46
        out.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" '
                   f'fill="{CLASS_COLOUR[cls]}" stroke="#ffffff" '
                   f'stroke-width="1.5"/>')
        out.append(f'<text x="{ex + 8:.1f}" y="{ey + dy:.1f}" font-size="13" '
                   f'font-weight="700" fill="{CLASS_COLOUR[cls]}">'
                   f'{CLASS_LABEL[cls]}</text>')
        out.append(f'<text x="{ex + 8:.1f}" y="{ey + dy + 15:.1f}" '
                   f'font-size="11" fill="{INK_BODY}">'
                   f'ends {last[cls]["accuracy"]:.2f} at n = '
                   f'{last[cls]["n"]}</text>')
        # Left-hand end, where the counterfactual is fullest.
        first = valid[0]
        fx_, fy_ = sx(first["threshold"]), sy(first[cls]["accuracy"])
        out.append(f'<circle cx="{fx_:.1f}" cy="{fy_:.1f}" r="4" '
                   f'fill="{CLASS_COLOUR[cls]}" stroke="#ffffff" '
                   f'stroke-width="1.5"/>')
        out.append(f'<text x="{fx_ + 8:.1f}" '
                   f'y="{fy_ + (-10 if cls == "no" else 18):.1f}" '
                   f'font-size="11" fill="{CLASS_COLOUR[cls]}">'
                   f'{first[cls]["accuracy"]:.2f} at n = '
                   f'{first[cls]["n"]}</text>')

    # The floor itself.
    at_floor = min(points,
                   key=lambda p: abs(p["threshold"] - PRODUCTION_FLOOR))
    fx = sx(PRODUCTION_FLOOR)
    out.append(f'<line x1="{fx:.1f}" y1="{y0 - 6}" x2="{fx:.1f}" '
               f'y2="{strip_y + strip_h:.1f}" stroke="{RULE}" '
               f'stroke-width="1.5" stroke-dasharray="5 4"/>')
    out.append(f'<text x="{fx:.1f}" y="{y0 - 12}" font-size="11.5" '
               f'font-weight="700" text-anchor="middle" fill="{RULE}">'
               f'D37 commit floor 0.65</text>')
    for cls in ("yes", "no"):
        a = at_floor[cls]["accuracy"]
        out.append(f'<circle cx="{fx:.1f}" cy="{sy(a):.1f}" r="5" '
                   f'fill="{CLASS_COLOUR[cls]}" stroke="#ffffff" '
                   f'stroke-width="2"/>')
        out.append(f'<text x="{fx + 10:.1f}" y="{sy(a) - 9:.1f}" '
                   f'font-size="12" font-weight="700" '
                   f'fill="{CLASS_COLOUR[cls]}">{a:.3f}</text>')
        out.append(f'<text x="{fx + 10:.1f}" y="{sy(a) + 6:.1f}" '
                   f'font-size="10.5" fill="{INK_BODY}">'
                   f'n = {at_floor[cls]["n"]}</text>')

    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0 + ph}" '
               f'stroke="{AXIS}" stroke-width="1"/>')
    out.append(f'<line x1="{x0}" y1="{y0 + ph}" x2="{x0 + pw}" '
               f'y2="{y0 + ph}" stroke="{AXIS}" stroke-width="1"/>')
    out.append(f'<text x="{x0 - 54}" y="{y0 + ph / 2:.0f}" font-size="13" '
               f'text-anchor="middle" fill="{INK_BODY}" '
               f'transform="rotate(-90 {x0 - 54} {y0 + ph / 2:.0f})">'
               f'Accuracy on retained answers</text>')

    # Companion strip.
    out.append(f'<text x="{x0}" y="{strip_y - 10}" font-size="12" '
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

    axis_y = strip_y + strip_h
    out.append(f'<line x1="{x0}" y1="{axis_y:.1f}" x2="{x0 + pw}" '
               f'y2="{axis_y:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    ticks = 8
    for i in range(ticks):
        t = x_lo + (x_hi - x_lo) * i / (ticks - 1)
        out.append(f'<text x="{sx(t):.1f}" y="{axis_y + 20:.1f}" '
                   f'font-size="11.5" text-anchor="middle" '
                   f'fill="{INK_MUTED}">{t:.2f}</text>')
    out.append(f'<text x="{x0 + pw / 2:.0f}" y="{axis_y + 44:.0f}" '
               f'font-size="13" text-anchor="middle" fill="{INK_BODY}">'
               f'Confidence threshold</text>')

    n_sub = sum(points[0][c]["n_subfloor"] for c in ("yes", "no"))
    fy = axis_y + 72
    out.append(
        f'<text x="26" y="{fy:.0f}" font-size="11.5" fill="{INK_BODY}">'
        f'The horizontal axis is the threshold itself. The vertical axis is '
        f'accuracy among the answers retained at that threshold.</text>'
    )
    out.append(
        f'<text x="26" y="{fy + 17:.0f}" font-size="11.5" fill="{INK_BODY}">'
        f'The strip beneath counts how many answers each point rests on, and '
        f'the shaded bands are Wilson 95% intervals.</text>'
    )
    stamp = datetime.now().strftime("%Y-%m-%d")
    out.append(
        f'<text x="26" y="{fy + 35:.0f}" font-size="11" fill="{INK_MUTED}">'
        f'Source: {EXPERIMENT_ID}, latest row per (question, country). '
        f'Observed n = 523 (339 yes, 184 no); dashed segment is the {n_sub} '
        f'discarded sub-floor answers. Generated {stamp}.</text>'
    )
    out.append('</svg>')
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "odmi.db"))
    ap.add_argument("--records", default=str(REPO_ROOT / "evaluation"
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
    observed = load_observed(args.db)
    subfloor = load_subfloor(args.db, records)
    print("observed  " + ", ".join(f"{c}={len(observed[c])}"
                                   for c in ("yes", "no")))
    print("sub-floor " + ", ".join(f"{c}={len(subfloor[c])}"
                                   for c in ("yes", "no")))
    for cls in ("yes", "no"):
        hits = sum(1 for _, ok in subfloor[cls] if ok)
        print(f"  sub-floor {cls}-gold accuracy "
              f"{hits / len(subfloor[cls]):.3f} ({hits}/{len(subfloor[cls])})")

    points = sweep(observed, subfloor)
    validate(points)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "per_class_accuracy_full_range.svg").write_text(
        build_svg(points))
    with (out_dir / "per_class_accuracy_full_range.csv").open(
            "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["threshold", "region",
                    "yes_n", "yes_n_subfloor", "yes_accuracy",
                    "yes_wilson_lo", "yes_wilson_hi",
                    "no_n", "no_n_subfloor", "no_accuracy",
                    "no_wilson_lo", "no_wilson_hi"])
        for p in points:
            region = ("observed" if p["threshold"] >= PRODUCTION_FLOOR
                      else "counterfactual")
            row = [p["threshold"], region]
            for cls in ("yes", "no"):
                b = p[cls]
                row += [b["n"], b["n_subfloor"],
                        None if b["accuracy"] is None else round(b["accuracy"], 6),
                        None if b["lo"] is None else round(b["lo"], 6),
                        None if b["hi"] is None else round(b["hi"], 6)]
            w.writerow(row)

    first = points[0]
    print(f"left end (t={first['threshold']:.3f}): "
          + ", ".join(f"{c}-gold {first[c]['accuracy']:.3f} on n={first[c]['n']}"
                      for c in ("yes", "no")))
    print(f"wrote {out_dir / 'per_class_accuracy_full_range.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
