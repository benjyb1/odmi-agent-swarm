"""EXP-36 held-out ODMI score bands (dissertation section 4.6, Part B).

Two figures over the eight held-out countries of the frozen headline run:

  Figure 1  band chart. One row per country, a bar spanning the swarm's
            floor to its ceiling, with the country's published ODMI score
            marked separately. Sorted by coverage descending so the width
            gradient reads first.
  Figure 2  scatter of published ODMI score against coverage.

Three quantities, all computed under one aggregation rule so the comparison
is internally valid:

  published  the country's own ODMI score from its ground-truth answers.
  ceiling    the swarm's score on the pairs it committed, with each
             dimension's denominator restricted to committed pairs in that
             dimension. What the swarm asserts about what it answered.
  floor      the swarm's score on committed pairs, with each dimension's
             denominator over all pairs in that dimension. Abstentions
             earn nothing.

Aggregation follows the published ODMI methodology: a dimension percentage
is the pooled earned/max over that dimension's questions, and the overall
score is the unweighted mean of the four dimension percentages, each
dimension carrying an equal 25%. Pooling over all 143 questions instead
would over-weight the larger dimensions (max totals run 580 to 670) and is
wrong. The rule is validated against the 2025 Belgium factsheet, which
prints Policy 82.8, Portal 82.8, Quality 75.4, Impact 65.5, overall 76.6;
this script reproduces all five from the questionnaire data.

Scoring rubric. `questions.response_scoring` carries the official
answer-to-score map for all 143 questions. It is checked here against the
map derived empirically from the 36 countries' ground-truth rows: every
overlapping (question, answer) cell must agree, and each question's rubric
maximum must equal its `max_score`. The empirical derivation alone is not
sufficient, because 20 questions never observe at least one of their
allowed answers across the 36 countries.

Commit rule. A pair committed iff `final_answer` is non-null and not
`inconclusive`. Terminal status does not decide this: 95 rows in this run
carry `accepted_by_adjudicator` with an inconclusive answer, and those are
abstentions.

Reads the canonical database only. Writes vector PDF and 300 dpi PNG.

    uv run python evaluation/figures/exp36_score_bands.py
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# The canonical checkout, never a worktree copy.
DEFAULT_DB = Path.home() / "Desktop" / "MscProject" / "data" / "odmi.db"
OUT_DIR = Path(__file__).resolve().parent

EXPERIMENT_ID = "exp36_frozen_headline"

STRATUM_A = ("BA", "MK", "ME", "BG")   # negative-rich low/mid-resource
STRATUM_B = ("FI", "HR", "SE", "BE")   # higher-resource balanced

DIMENSIONS = (
    "policy_dimension",
    "portal_dimension",
    "quality_dimension",
    "impact_dimension",
)

# 2025 Belgium factsheet, data.europa.eu. Used as the methodology check.
BE_FACTSHEET = {
    "policy_dimension": 82.8,
    "portal_dimension": 82.8,
    "quality_dimension": 75.4,
    "impact_dimension": 65.5,
    "overall": 76.6,
}

ABSTENTION = "inconclusive"


# Normalisation

def norm(value):
    """Lower, collapse whitespace, underscores to spaces.

    The swarm emits `not_applicable` where ground truth writes `not
    applicable`. That is not cosmetic: on P11 the answer scores 40 of 40
    and on P16 20 of 20. `dashboard/lib/db.py:_MATCH_STATUS_SQL` folds
    underscores for the same reason.
    """
    if value is None:
        return None
    return " ".join(str(value).strip().lower().split()).replace("_", " ")


def is_committed(final_answer) -> bool:
    a = norm(final_answer)
    return a is not None and a != "" and a != ABSTENTION


def stratum_of(country_code: str) -> str:
    if country_code in STRATUM_A:
        return "A"
    if country_code in STRATUM_B:
        return "B"
    raise KeyError(f"{country_code} is in neither held-out stratum")


# Load

def load_rubric(conn) -> dict:
    """Official answer-to-score map per question."""
    rubric = {}
    for row in conn.execute(
        "SELECT question_id, response_scoring FROM questions"
    ):
        raw = row["response_scoring"]
        if not raw:
            raise ValueError(f"{row['question_id']} has no response_scoring")
        parsed = ast.literal_eval(raw)
        rubric[row["question_id"]] = {
            norm(k): float(v) for k, v in parsed.items()
        }
    return rubric


def load_ground_truth(conn) -> dict:
    gt = {}
    for row in conn.execute(
        """SELECT question_id, country_code, response, awarded_score,
                  max_score, dimension FROM ground_truth"""
    ):
        gt[(row["question_id"], row["country_code"])] = {
            "response": norm(row["response"]),
            "awarded": row["awarded_score"],
            "max": row["max_score"],
            "dimension": row["dimension"],
        }
    return gt


def load_shapes(conn) -> dict:
    return {
        r["question_id"]: (r["answer_shape"] or "").lower()
        for r in conn.execute(
            "SELECT question_id, answer_shape FROM questions"
        )
    }


def load_canonical_pairs(conn, experiment_id: str) -> list:
    """Canonical rows: highest id per (question_id, country_code).

    Deliberately not scoped by `condition_label`. This is a single-arm run,
    and five re-dispatched pairs lost their label, so keying on the label
    would keep both the superseded row and its re-run and return 1,149
    pairs instead of 1,144.
    """
    return [
        dict(r)
        for r in conn.execute(
            """SELECT f.question_id, f.country_code, f.terminal_status,
                      f.final_answer
               FROM phase2_final f
               WHERE f.experiment_id = ?
                 AND f.id = (SELECT MAX(g.id) FROM phase2_final g
                             WHERE g.experiment_id = f.experiment_id
                               AND g.question_id = f.question_id
                               AND g.country_code = f.country_code)""",
            (experiment_id,),
        )
    ]


# Rubric validation

def validate_rubric(rubric: dict, gt: dict) -> dict:
    """Check the official rubric against the empirically derived one.

    The empirical map comes from grouping the 36 countries' ground-truth
    rows by (question_id, response) and reading off awarded_score. Raises
    on any disagreement; the figures must not be drawn on a rubric that
    contradicts the data.
    """
    empirical = collections.defaultdict(dict)
    max_score = {}
    inconstant = []
    for (qid, _cc), g in gt.items():
        max_score.setdefault(qid, g["max"])
        if g["max"] != max_score[qid]:
            inconstant.append(("max_score", qid))
        held = empirical[qid].get(g["response"])
        if held is not None and abs(held - g["awarded"]) > 1e-9:
            inconstant.append(("awarded_score", qid, g["response"]))
        empirical[qid][g["response"]] = g["awarded"]

    disagreements, overlap = [], 0
    for qid, answers in empirical.items():
        for answer, score in answers.items():
            if answer is None or answer not in rubric.get(qid, {}):
                continue
            overlap += 1
            if abs(rubric[qid][answer] - score) > 1e-9:
                disagreements.append((qid, answer, score, rubric[qid][answer]))

    bad_max = [
        (qid, max_score[qid], max(rubric[qid].values()))
        for qid in rubric
        if abs(max(rubric[qid].values()) - max_score[qid]) > 1e-9
    ]

    if inconstant:
        raise ValueError(f"ground truth is not internally constant: {inconstant}")
    if disagreements:
        raise ValueError(f"rubric disagrees with ground truth: {disagreements}")
    if bad_max:
        raise ValueError(f"rubric maximum != max_score: {bad_max}")

    return {"overlapping_cells": overlap, "disagreements": 0}


# Scoring

def score_country(country_code, pairs, rubric, gt, shapes):
    """The three scores for one country, dimension-equal weighted."""
    buckets = {
        d: {"awarded": 0.0, "max": 0.0, "earned": 0.0, "max_committed": 0.0}
        for d in DIMENSIONS
    }
    committed = 0
    unscorable = []

    for pair in pairs:
        qid = pair["question_id"]
        g = gt[(qid, country_code)]
        bucket = buckets[g["dimension"]]
        bucket["awarded"] += g["awarded"]
        bucket["max"] += g["max"]

        if not is_committed(pair["final_answer"]):
            continue
        committed += 1
        answer = norm(pair["final_answer"])
        earned = rubric[qid].get(answer)
        if earned is None:
            # Only legal on the unscored free-text questions, whose rubric
            # is {None: 0.0} and whose max_score is 0. Anything else is a
            # scoring gap and must surface.
            if g["max"] != 0:
                unscorable.append((qid, answer))
            earned = 0.0
        bucket["earned"] += earned
        bucket["max_committed"] += g["max"]

    if unscorable:
        raise ValueError(
            f"{country_code}: committed answers with no rubric entry on "
            f"scored questions: {unscorable}"
        )

    published = statistics.mean(
        100.0 * buckets[d]["awarded"] / buckets[d]["max"] for d in DIMENSIONS
    )
    floor = statistics.mean(
        100.0 * buckets[d]["earned"] / buckets[d]["max"] for d in DIMENSIONS
    )
    ceiling_parts = [
        100.0 * buckets[d]["earned"] / buckets[d]["max_committed"]
        for d in DIMENSIONS
        if buckets[d]["max_committed"] > 0
    ]
    if len(ceiling_parts) < len(DIMENSIONS):
        missing = [d for d in DIMENSIONS if buckets[d]["max_committed"] == 0]
        print(
            f"  note: {country_code} committed nothing in {missing}; "
            f"ceiling is the mean of {len(ceiling_parts)} dimensions",
            file=sys.stderr,
        )
    ceiling = statistics.mean(ceiling_parts)

    negative_gold = sum(
        1
        for p in pairs
        if shapes[p["question_id"]] == "binary"
        and gt[(p["question_id"], country_code)]["response"] == "no"
    )

    return {
        "country": country_code,
        "stratum": stratum_of(country_code),
        "n_pairs": len(pairs),
        "committed": committed,
        "coverage": committed / len(pairs),
        "floor": floor,
        "ceiling": ceiling,
        "published": published,
        "negative_gold": negative_gold,
        "dimensions": {
            d: {
                "published": 100.0 * buckets[d]["awarded"] / buckets[d]["max"],
                "floor": 100.0 * buckets[d]["earned"] / buckets[d]["max"],
                "ceiling": (
                    100.0 * buckets[d]["earned"] / buckets[d]["max_committed"]
                    if buckets[d]["max_committed"]
                    else None
                ),
            }
            for d in DIMENSIONS
        },
    }


def check_belgium(result) -> list:
    """Compare the Belgium reconstruction with the 2025 factsheet."""
    lines = []
    for d in DIMENSIONS:
        got = result["dimensions"][d]["published"]
        want = BE_FACTSHEET[d]
        lines.append((d, got, want, got - want))
    lines.append(("overall", result["published"], BE_FACTSHEET["overall"],
                  result["published"] - BE_FACTSHEET["overall"]))
    return lines


# Correlation

def _pearson(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(
        sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)
    )
    return num / den if den else float("nan")


def _spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            shared = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = shared
            i = j + 1
        return out

    return _pearson(ranks(xs), ranks(ys))


# Style

# Greyscale-safe: the stratum reads from hatch and marker shape, never hue.
# Near-black rather than pure black; at print size 000 rings harsh against
# white and makes every edge shout for equal attention.
INK = "#1A1A1A"
MUTED = "#6E6E6E"
FILL_A = "#FFFFFF"
FILL_B = "#D2D2D2"
HATCH_A = "///"
HATCH_B = ""
MARKER_A = "D"
MARKER_B = "o"


def apply_style():
    """Plain matplotlib. No seaborn, no styles that carry meaning in hue."""
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial",
                            "DejaVu Sans"],
        "font.size": 8.5,
        "axes.linewidth": 0.7,
        "axes.edgecolor": INK,
        "axes.labelsize": 8.5,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.labelsize": 8,
        "ytick.labelsize": 9,
        "xtick.color": INK,
        "ytick.color": INK,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 3,
        "xtick.major.width": 0.7,
        # Fine hatching. The matplotlib default is heavy enough to read as
        # texture noise at print size and muddies the bar it fills.
        "hatch.linewidth": 0.55,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.03,
    })


def save(fig, stem: str, out_dir: Path) -> list:
    written = []
    for suffix, kwargs in (("pdf", {}), ("png", {"dpi": 300})):
        path = out_dir / f"{stem}.{suffix}"
        fig.savefig(path, **kwargs)
        written.append(path)
    plt.close(fig)
    return written


# Figure 1

def figure_band(results, out_dir: Path) -> list:
    rows = sorted(results, key=lambda r: r["coverage"], reverse=True)

    fig, ax = plt.subplots(figsize=(7.0, 3.9))
    ys = list(range(len(rows)))[::-1]

    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=INK, alpha=0.09, linewidth=0.6)
    ax.yaxis.grid(False)

    for y, r in zip(ys, rows):
        is_a = r["stratum"] == "A"

        # Leader rule across the full width, carrying the eye from the
        # country label through the bar to the coverage column.
        ax.plot(
            [0, 100], [y, y],
            color=INK, alpha=0.13, linewidth=0.5,
            linestyle=(0, (1, 2.5)), zorder=1,
        )

        ax.barh(
            y,
            width=r["ceiling"] - r["floor"],
            left=r["floor"],
            height=0.46,
            facecolor=FILL_A if is_a else FILL_B,
            edgecolor=INK,
            linewidth=0.7,
            hatch=HATCH_A if is_a else HATCH_B,
            zorder=3,
        )

        # Floor and ceiling values, set just outside the bar ends. The
        # reader should not have to measure the bar against the axis.
        # Where the published tick falls outside the band it occupies the
        # space the value label wants, so that label goes inside the bar
        # instead: Bosnia's published score sits below its floor, and
        # Croatia's above its ceiling.
        floor_inside = r["published"] < r["floor"]
        ceil_inside = r["published"] > r["ceiling"]
        ax.annotate(f"{r['floor']:.0f}", xy=(r["floor"], y),
                    xytext=(4 if floor_inside else -4, 0),
                    textcoords="offset points", va="center",
                    ha="left" if floor_inside else "right",
                    fontsize=7.2, color=MUTED, zorder=4,
                    path_effects=[pe.Stroke(linewidth=2.2,
                                            foreground="white"),
                                  pe.Normal()])
        ax.annotate(f"{r['ceiling']:.0f}", xy=(r["ceiling"], y),
                    xytext=(-4 if ceil_inside else 4, 0),
                    textcoords="offset points", va="center",
                    ha="right" if ceil_inside else "left",
                    fontsize=7.2, color=MUTED, zorder=4,
                    path_effects=[pe.Stroke(linewidth=2.2,
                                            foreground="white"),
                                  pe.Normal()])

        # Published score: a vertical tick, readable wherever it lands,
        # including outside the band. Taller than the bar so it stays
        # legible where it coincides with a bar edge, as Montenegro's does
        # with its ceiling, and haloed in white so it separates from the
        # bar fill instead of merging with the edge stroke.
        ax.plot(
            [r["published"], r["published"]],
            [y - 0.36, y + 0.36],
            color=INK,
            linewidth=1.7,
            solid_capstyle="butt",
            zorder=6,
            path_effects=[pe.Stroke(linewidth=3.6, foreground="white"),
                          pe.Normal()],
        )

        ax.annotate(
            f"{100 * r['coverage']:.0f}%",
            xy=(1.0, y),
            xycoords=("axes fraction", "data"),
            xytext=(14, 0),
            textcoords="offset points",
            va="center",
            ha="right",
            fontsize=8.5,
        )

    ax.annotate(
        "coverage",
        xy=(1.0, 1.0),
        xycoords="axes fraction",
        xytext=(14, 10),
        textcoords="offset points",
        va="bottom",
        ha="right",
        fontsize=7.5,
        color=MUTED,
    )

    ax.set_yticks(ys)
    ax.set_yticklabels([r["country"] for r in rows])
    ax.set_ylim(-0.65, len(rows) - 0.35)
    ax.set_xlim(0, 100)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("ODMI score (%)")

    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_position(("outward", 6))
    ax.tick_params(axis="y", length=0, pad=6)

    handles = [
        Patch(facecolor=FILL_A, edgecolor=INK, hatch=HATCH_A,
              linewidth=0.7, label="Stratum A (low/mid-resource)"),
        Patch(facecolor=FILL_B, edgecolor=INK, linewidth=0.7,
              label="Stratum B (higher-resource)"),
        Line2D([0], [0], color=INK, linewidth=1.7,
               label="Published ODMI score"),
    ]
    ax.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.34),
        ncol=3,
        handlelength=1.5,
        handletextpad=0.6,
        columnspacing=2.0,
    )
    return save(fig, "fig_exp36_score_bands", out_dir)


# Figure 2

# Croatia and Belgium sit 3 points apart on both axes, and Finland and
# Sweden differ by 0.1 on the x axis. Nudged by hand so no label overlaps a
# neighbour's marker; (dx, dy, horizontal alignment) in points.
LABEL_OFFSETS = {
    "HR": (-8, -2, "right"),
    "BE": (9, -1, "left"),
    "FI": (9, 2, "left"),
    "SE": (9, -2, "left"),
    "ME": (-8, 3, "right"),
    "MK": (-8, 2, "right"),
    "BG": (8, -4, "left"),
    "BA": (9, 1, "left"),
}


def figure_scatter(results, out_dir: Path, stats: dict) -> list:
    fig, ax = plt.subplots(figsize=(4.6, 4.2))

    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=INK, alpha=0.09, linewidth=0.6)
    ax.yaxis.grid(False)

    for r in results:
        is_a = r["stratum"] == "A"
        ax.scatter(
            r["published"],
            100 * r["coverage"],
            marker=MARKER_A if is_a else MARKER_B,
            s=58 if is_a else 52,
            facecolor=FILL_A if is_a else FILL_B,
            edgecolor=INK,
            linewidth=0.9,
            zorder=4,
        )
        dx, dy, ha = LABEL_OFFSETS.get(r["country"], (7, 3, "left"))
        ax.annotate(
            r["country"],
            xy=(r["published"], 100 * r["coverage"]),
            xytext=(dx, dy),
            textcoords="offset points",
            ha=ha,
            fontsize=8.5,
            zorder=5,
            # Croatia and Belgium sit close enough that a label can cross a
            # neighbour's marker at some figure sizes.
            path_effects=[pe.Stroke(linewidth=2.4, foreground="white"),
                          pe.Normal()],
        )

    # No trend line. n = 8, and the Pearson coefficient leans on Bosnia,
    # whose published score sits 28 points below the next country. The
    # coefficients are printed instead so the reader judges the fit.
    ax.annotate(
        f"Pearson $r$ = {stats['pearson']:.2f}\n"
        f"Spearman $\\rho$ = {stats['spearman']:.2f}\n"
        f"$n$ = {stats['n']}",
        xy=(0.035, 0.965),
        xycoords="axes fraction",
        va="top",
        ha="left",
        fontsize=7.8,
        color=MUTED,
        linespacing=1.5,
    )

    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xticks(range(0, 101, 20))
    ax.set_yticks(range(0, 101, 20))
    ax.set_xlabel("Published ODMI score (%)")
    ax.set_ylabel("Coverage (committed / 143, %)")
    ax.set_aspect("equal", adjustable="box")

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_position(("outward", 6))

    handles = [
        Line2D([0], [0], marker=MARKER_A, linestyle="none",
               markerfacecolor=FILL_A, markeredgecolor=INK,
               markersize=6.8, label="Stratum A"),
        Line2D([0], [0], marker=MARKER_B, linestyle="none",
               markerfacecolor=FILL_B, markeredgecolor=INK,
               markersize=6.6, label="Stratum B"),
    ]
    ax.legend(handles=handles, loc="lower right", handletextpad=0.5,
              borderpad=0.2)
    return save(fig, "fig_exp36_coverage_vs_published", out_dir)


# Main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--experiment-id", default=EXPERIMENT_ID)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"database not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rubric = load_rubric(conn)
    gt = load_ground_truth(conn)
    shapes = load_shapes(conn)
    pairs = load_canonical_pairs(conn, args.experiment_id)

    check = validate_rubric(rubric, gt)
    print(
        f"rubric validated: {check['overlapping_cells']} overlapping "
        f"(question, answer) cells, {check['disagreements']} disagreements"
    )

    by_country = collections.defaultdict(list)
    for p in pairs:
        by_country[p["country_code"]].append(p)

    expected = set(STRATUM_A) | set(STRATUM_B)
    if set(by_country) != expected:
        print(
            f"country set mismatch: got {sorted(by_country)}, "
            f"expected {sorted(expected)}",
            file=sys.stderr,
        )
        return 1
    for cc, rows in sorted(by_country.items()):
        if len(rows) != 143:
            print(f"{cc} has {len(rows)} pairs, expected 143", file=sys.stderr)
            return 1

    total_committed = sum(1 for p in pairs if is_committed(p["final_answer"]))
    print(
        f"pairs: {len(pairs)} canonical across {len(by_country)} countries, "
        f"{total_committed} committed"
    )

    results = [
        score_country(cc, rows, rubric, gt, shapes)
        for cc, rows in sorted(by_country.items())
    ]
    index = {r["country"]: r for r in results}

    print("\nBelgium against the 2025 factsheet (methodology check):")
    print(f"  {'':<20}{'computed':>10}{'factsheet':>11}{'delta':>8}")
    for name, got, want, delta in check_belgium(index["BE"]):
        print(f"  {name:<20}{got:>10.2f}{want:>11.1f}{delta:>+8.2f}")

    xs = [r["published"] for r in results]
    ys = [100 * r["coverage"] for r in results]
    stats = {
        "pearson": _pearson(xs, ys),
        "spearman": _spearman(xs, ys),
        "n": len(results),
    }

    print("\n| Country | Stratum | Coverage | Floor | Ceiling | Published | Negative golds |")
    print("|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda r: r["coverage"], reverse=True):
        print(
            f"| {r['country']} | {r['stratum']} | "
            f"{100 * r['coverage']:.1f}% | {r['floor']:.1f} | "
            f"{r['ceiling']:.1f} | {r['published']:.1f} | "
            f"{r['negative_gold']} |"
        )

    print(
        f"\ncoverage vs published: Pearson r = {stats['pearson']:.3f}, "
        f"Spearman rho = {stats['spearman']:.3f}, n = {stats['n']} "
        f"(no trend line drawn)"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    apply_style()
    written = figure_band(results, args.out_dir)
    written += figure_scatter(results, args.out_dir, stats)

    payload = {
        "experiment_id": args.experiment_id,
        "n_pairs": len(pairs),
        "n_committed": total_committed,
        "rubric_check": check,
        "belgium_factsheet_check": {
            name: {"computed": got, "factsheet": want, "delta": delta}
            for name, got, want, delta in check_belgium(index["BE"])
        },
        "correlation": stats,
        "countries": results,
    }
    table_path = args.out_dir / "exp36_score_bands.json"
    table_path.write_text(json.dumps(payload, indent=2) + "\n")
    written.append(table_path)

    print("\nwrote:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
