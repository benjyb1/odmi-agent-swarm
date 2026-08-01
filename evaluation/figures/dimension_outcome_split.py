"""Outcome composition by ODMI dimension, for the Discussion.

Answers the sentence the figure is cited from: oversight does not have to fall
evenly. Each dimension's pairs are split into what the swarm got right, what it
got wrong, and what it declined, with the wrong answers separated into false
positives and everything else. The false-positive band is the one that decides
where a human still has to read, because a wrong yes on a negative gold is the
error the assessment cannot absorb.

Bars are proportions, not counts, because the dimensions differ in size (232 to
360 pairs) and the question is where the mix is worse, not where the workload
is. Counts are on the axis labels so nothing is hidden.

Ordered by false-positive share ascending, so the dimensions the system can be
trusted with sit at the top.

House Okabe-Ito palette, split into two families that carry the argument: blue
for the outcomes the design intends, either a correct answer or a deliberate
decline, and the vermillion family for error. The width of the red block is
therefore the figure's message, and it is readable at a glance without the
legend. Okabe-Ito is colour-vision-safe by construction; the false-positive
band also carries a hatch so the load-bearing distinction survives greyscale
printing.

    uv run python evaluation/figures/dimension_outcome_split.py
"""

from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

LEDGER = "evaluation/results/exp36_headline.json"
OUT = "evaluation/figures/fig_dimension_outcome_split"

INK = "#1A1A1A"
MUTED = "#6E6E6E"

# House Okabe-Ito: #0072B2 blue, #56B4E9 sky, #E69F00 orange, #009E73 green,
# #D55E00 vermillion, #9E9E9E grey.
BLUE = "#0072B2"
SKY = "#56B4E9"
VERMILLION = "#D55E00"
VERMILLION_LIGHT = "#EC9A6D"   # a tint of the same hue, not a second colour
GREY = "#9E9E9E"

# Two families, and the split is the argument: blue for what the design
# intends (a correct answer, or a deliberate decline), vermillion for error.
# (label, fill, hatch, light_text)
BANDS = [
    ("Correct",           BLUE,             "",    True),
    ("Wrong: false yes",  VERMILLION,       "///", True),
    ("Wrong: other",      VERMILLION_LIGHT, "",    False),
    ("Unscoreable",       GREY,             "...", False),
    ("Declined",          SKY,              "",    False),
]


def apply_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
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
        "hatch.linewidth": 0.55,
        "legend.frameon": False,
        "figure.dpi": 300,
    })


def load():
    with open(LEDGER) as f:
        dims = json.load(f)["strata"]["by_dimension"]

    rows = []
    for name, d in dims.items():
        n = d["n"]
        correct = d["commit_accuracy"]["successes"]
        scoreable = d["commit_accuracy"]["n"]
        fp = d["negative_golds"]["false_positives"]
        unscoreable = d["n_committed_unscoreable"]["flag_review"]
        other_wrong = scoreable - correct - fp
        declined = d["n_abstained"]

        parts = [correct, fp, other_wrong, unscoreable, declined]
        if sum(parts) != n:
            raise SystemExit(
                f"{name}: parts {parts} sum to {sum(parts)}, expected n={n}. "
                "Refusing to draw a figure whose segments do not reconcile.")
        rows.append({"dim": name, "n": n, "parts": parts,
                     "fp_share": fp / n})

    rows.sort(key=lambda r: r["fp_share"])
    return rows


def draw(rows):
    fig, ax = plt.subplots(figsize=(6.6, 3.1))

    ypos = range(len(rows))
    for yi, row in zip(ypos, rows):
        left = 0.0
        for (label, fill, hatch, light_text), value in zip(BANDS, row["parts"]):
            share = value / row["n"] * 100
            ax.barh(yi, share, left=left, height=0.62,
                    facecolor=fill, edgecolor=INK, linewidth=0.6,
                    hatch=hatch, zorder=2)
            # Only label a band with room for the number, so nothing collides.
            if share >= 7:
                ax.text(left + share / 2, yi, f"{share:.0f}",
                        ha="center", va="center", fontsize=7.6,
                        color="#FFFFFF" if light_text else INK,
                        zorder=3)
            left += share

    ax.set_yticks(list(ypos))
    ax.set_yticklabels([f"{r['dim']}\n{r['n']} pairs" for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25", "50", "75", "100%"])
    ax.set_xlabel("Share of the dimension's held-out pairs")

    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)

    ax.set_title("Where the swarm can be trusted, by ODMI dimension",
                 fontsize=10.5, loc="left", pad=10)

    # Legend below the axis label. Above the plot it competes with the title
    # for the same band of space and the two collide at this figure width.
    handles = [Patch(facecolor=f, edgecolor=INK, linewidth=0.6, hatch=h, label=l)
               for l, f, h, _ in BANDS]
    ax.legend(handles=handles, ncol=5, fontsize=7.4,
              loc="upper center", bbox_to_anchor=(0.5, -0.28),
              handlelength=1.5, columnspacing=1.1, handletextpad=0.5)

    fig.tight_layout()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT + ".png", bbox_inches="tight")
    fig.savefig(OUT + ".pdf", bbox_inches="tight")
    print(f"wrote {OUT}.png and {OUT}.pdf")

    for r in rows:
        c, fp, ow, un, dec = r["parts"]
        print(f"  {r['dim']:8} n={r['n']:4}  correct={c:4} fp={fp:3} "
              f"other_wrong={ow:3} unscoreable={un:2} declined={dec:4}  "
              f"fp_share={r['fp_share']*100:.1f}%")


if __name__ == "__main__":
    apply_style()
    draw(load())
