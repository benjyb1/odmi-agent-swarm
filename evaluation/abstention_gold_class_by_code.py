"""Gold-class composition of the two dominant EXP-36 abstention codes (§4.4).

Codes E (verifier relevance rejection) and G (below the 0.65 confidence floor)
account for 407 of the 508 EXP-36 abstentions. This figure asks whether the two
codes withhold the same kind of question. They do not: E's binary golds sit on
the held-out base rate, G's are enriched in negative golds.

Everything is recomputed from `data/odmi.db`. The abstention codes are
re-derived here from the stored trails rather than read from
`evaluation/abstention_records.csv`, so this script is self-contained and is the
source of truth for the numbers it prints. The predicates and their priority
order mirror `evaluation/abstention_taxonomy.py` exactly; the replication was
checked against the filed CSV and agrees on 508/508 pairs. Nothing here writes
to the pipeline or feeds ground truth back into any agent.

Read-only. Strictly EXP-36:
    phase2_final.experiment_id = 'exp36_frozen_headline'

Outputs (under evaluation/figures/):
  - abstention_gold_class_by_code.png    300 dpi, for the manuscript
  - abstention_gold_class_by_code.json   the computed numbers (receipts)

Usage:
    uv run --extra dev python evaluation/abstention_gold_class_by_code.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.exp36_analysis import (  # noqa: E402
    dedup_canonical,
    load_rows,
    norm,
)

EXPERIMENT_ID = "exp36_frozen_headline"
EXPECTED_CANONICAL_PAIRS = 1144

# predicate constants, mirroring evaluation/abstention_taxonomy.py
DENY_HOSTS = ("data.europa.eu",)
MQA_MARKERS = ("data.europa.eu/mqa", "/mqa/", "metadata-quality")
FETCH_ERROR_MARKERS = (
    "status 0", "head/get returned status", "timed out", "timeout",
    "connection", "ssl", "403", "404", "429", "500", "502", "503",
    "unreachable", "could not fetch", "failed to fetch",
)
SELFREPORT_MARKERS = (
    "self-report", "self report", "self-assess", "self-asses",
    "would require explicit", "no formal policy", "no explicit policy",
    "not publicly documented", "no public documentation", "internal process",
    "administrative", "not published", "would need internal",
)
CONFIDENCE_FLOOR = 0.65
PRIORITY = ("F", "A", "B", "C", "D", "E", "G", "H", "I")

# Golds that carry no committed expert answer, excluded from the binary split.
NON_ANSWERS = (
    "", "inconclusive", "n/a", "not applicable", "no data", "unknown",
    "i don't know", "i dont know",
)

ROW_LABELS = {
    "E": "E, verifier relevance rejection",
    "G": "G, below confidence floor",
}

# Okabe-Ito, safe under deuteranopia, protanopia and tritanopia.
COLOUR_YES = "#0072B2"   # blue
COLOUR_NO = "#E69F00"    # orange
INK = "#1a1a1a"


def _jload(raw):
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else [value]
    except Exception:
        return []


def classify_abstentions(conn: sqlite3.Connection) -> dict[str, dict]:
    """Re-derive the abstention code for every non-committed EXP-36 pair.

    Returns {"QID:CC": {"code": str, "satisfies_G": bool}}. The code is the
    first predicate in PRIORITY the trail satisfies, which is what makes the
    taxonomy a first-match marker rather than a causal claim.
    """
    finals = conn.execute(
        """
        SELECT * FROM phase2_final
        WHERE experiment_id = ?
          AND (final_answer = 'inconclusive' OR terminal_status = 'agent_failure')
        """,
        (EXPERIMENT_ID,),
    ).fetchall()
    if not finals:
        raise SystemExit(f"no non-committed rows for experiment_id={EXPERIMENT_ID!r}")

    pair_ids = [f["pair_run_id"] for f in finals]
    placeholders = ",".join("?" * len(pair_ids))

    def trail(table: str) -> dict[str, list]:
        out = defaultdict(list)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE pair_run_id IN ({placeholders})",
            tuple(pair_ids),
        ):
            out[row["pair_run_id"]].append(row)
        return out

    researcher = trail("phase2_researcher_runs")
    verifier = trail("phase2_verifier_runs")

    out: dict[str, dict] = {}
    for final in finals:
        pid = final["pair_run_id"]
        res = sorted(researcher.get(pid, []), key=lambda r: (r["retry_count"], r["id"]))
        ver = sorted(verifier.get(pid, []), key=lambda r: (r["retry_count"], r["id"]))

        notes = " ".join((r["notes"] or "") for r in res).lower()
        explanations = " ".join((r["answer_explanation"] or "") for r in res).lower()
        failure_modes = [r["failure_mode"] for r in res if r["failure_mode"]]

        answers = [norm(r["answer"]) for r in res]
        ever_committed = any(
            a and a not in ("inconclusive", "other", "i don't know") for a in answers
        )

        blobs = [r["fetched_urls"] for r in res] + [r["source_url"] for r in res]
        blobs = [
            b if (b and b.strip().startswith("[")) else json.dumps([b]) if b else "[]"
            for b in blobs
        ]
        urls = [u.lower() for b in blobs for u in _jload(b) if isinstance(u, str)]

        has_snippets = any(
            (r["search_snippets"] and r["search_snippets"] not in ("[]", "")) for r in res
        )
        reason = final["final_failure_reason"] or ""
        search_empty = ("search_empty" in reason) or (not has_snippets and len(res) > 0)

        last_verifier = ver[-1] if ver else None
        confidences = [
            r["answer_confidence"] for r in res if r["answer_confidence"] is not None
        ]
        max_confidence = max(confidences) if confidences else None

        predicate = {
            "F": final["terminal_status"] == "agent_failure"
            and not final["final_answer"],
            "A": search_empty,
            "B": ("url_unreachable" in failure_modes)
            or any(m in notes for m in FETCH_ERROR_MARKERS),
            "C": any(m in u for u in urls for m in MQA_MARKERS)
            or any(h in u for u in urls for h in DENY_HOSTS),
            "D": ever_committed
            and any(v["substring_check_result"] == "fail" for v in ver),
            "E": ever_committed
            and last_verifier is not None
            and last_verifier["verdict"] == "fail",
            "G": ever_committed
            and max_confidence is not None
            and max_confidence < CONFIDENCE_FLOOR,
            "H": any(m in (explanations + notes) for m in SELFREPORT_MARKERS),
            "I": not ever_committed,
        }
        code = next((c for c in PRIORITY if predicate[c]), "Z")
        key = f"{final['question_id']}:{final['country_code']}"
        out[key] = {"code": code, "satisfies_G": predicate["G"]}
    return out


def compute(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        canonical, superseded = dedup_canonical(
            load_rows(conn, EXPERIMENT_ID), scope_by_label=False
        )
        coded = classify_abstentions(conn)
    finally:
        conn.close()

    if len(canonical) != EXPECTED_CANONICAL_PAIRS:
        raise SystemExit(
            f"canonical pair count is {len(canonical)}, expected "
            f"{EXPECTED_CANONICAL_PAIRS}. The held-out population changed; do "
            f"not publish this figure until that is understood."
        )

    gold_of = {f"{r.question_id}:{r.country_code}": norm(r.gold_answer) for r in canonical}

    # 1. binary gold split per code
    per_code: dict[str, dict] = {}
    for code in ("E", "G"):
        members = [k for k, v in coded.items() if v["code"] == code]
        golds = [gold_of.get(k, "") for k in members]
        scored = [g for g in golds if g not in NON_ANSWERS]
        yes = sum(1 for g in scored if g == "yes")
        no = sum(1 for g in scored if g == "no")
        per_code[code] = {
            "pairs": len(members),
            "yes_gold": yes,
            "no_gold": no,
            "binary_gold": yes + no,
            "excluded_non_binary_gold": len(members) - (yes + no),
            "yes_share": (yes / (yes + no)) if (yes + no) else None,
        }

    # 2. held-out binary base rate over the full canonical set
    base_yes = sum(1 for g in gold_of.values() if g == "yes")
    base_no = sum(1 for g in gold_of.values() if g == "no")
    base_rate = base_yes / (base_yes + base_no)

    # 3. E pairs that also satisfy G's predicate
    e_also_g = sum(
        1 for v in coded.values() if v["code"] == "E" and v["satisfies_G"]
    )

    try:
        db_label = str(db_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        db_label = str(db_path)

    return {
        "experiment_id": EXPERIMENT_ID,
        "db": db_label,
        "canonical_pairs": len(canonical),
        "superseded_duplicates": superseded,
        "non_committed_pairs": len(coded),
        "codes": per_code,
        "base_rate": {
            "yes_gold": base_yes,
            "no_gold": base_no,
            "binary_gold": base_yes + base_no,
            "yes_share": base_rate,
        },
        "e_pairs_also_satisfying_G_predicate": e_also_g,
    }


def report(result: dict) -> None:
    print(f"db              : {result['db']}")
    print(f"experiment_id   : {result['experiment_id']}")
    print(f"canonical pairs : {result['canonical_pairs']} "
          f"(superseded duplicates dropped: {result['superseded_duplicates']})")
    print(f"non-committed   : {result['non_committed_pairs']}")

    print("\n1. binary gold split by abstention code")
    print(f"   {'code':6s}{'pairs':>7s}{'yes':>6s}{'no':>6s}{'binary':>8s}"
          f"{'excl.':>7s}{'yes share':>11s}")
    for code, block in result["codes"].items():
        share = "n/a" if block["yes_share"] is None else f"{block['yes_share']:.4f}"
        print(f"   {code:6s}{block['pairs']:7d}{block['yes_gold']:6d}"
              f"{block['no_gold']:6d}{block['binary_gold']:8d}"
              f"{block['excluded_non_binary_gold']:7d}{share:>11s}")

    base = result["base_rate"]
    print("\n2. held-out binary base rate")
    print(f"   yes {base['yes_gold']} / (yes {base['yes_gold']} + no "
          f"{base['no_gold']}) = {base['yes_gold']}/{base['binary_gold']} "
          f"= {base['yes_share']:.4f}")

    print("\n3. E pairs that also satisfy G's predicate")
    e = result["codes"]["E"]
    print(f"   {result['e_pairs_also_satisfying_G_predicate']} of {e['pairs']}")


def build_figure(result: dict, out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcdefaults()          # no inherited style; seaborn is never involved
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "text.color": INK,
        "axes.edgecolor": INK,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    })

    codes = ["E", "G"]
    y = [1, 0]                # E on top
    bar_height = 0.42

    fig, ax = plt.subplots(figsize=(6.5, 2.15))

    for code, ypos in zip(codes, y):
        block = result["codes"][code]
        share = block["yes_share"]
        ax.barh(ypos, share, height=bar_height, color=COLOUR_YES,
                edgecolor="none", zorder=2)
        ax.barh(ypos, 1 - share, left=share, height=bar_height,
                color=COLOUR_NO, edgecolor="none", zorder=2)
        # The yes share, once, at the boundary between the two segments.
        ax.text(share - 0.012, ypos, f"{share * 100:.1f}%", ha="right",
                va="center", color="white", fontsize=9, zorder=4)

    base_rate = result["base_rate"]["yes_share"]
    ax.axvline(base_rate, color=INK, linestyle=(0, (4, 3)), linewidth=1.0,
               zorder=3, clip_on=False, ymin=0.02, ymax=0.90)
    ax.text(base_rate, 1.53, f"base rate {base_rate * 100:.1f}%", ha="center",
            va="bottom", fontsize=9, color=INK)

    ax.set_yticks(y)
    ax.set_yticklabels([ROW_LABELS[c] for c in codes], fontsize=9, color=INK)
    ax.set_xticks([])
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.55, 1.62)
    ax.tick_params(axis="y", length=0, pad=6)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(False)

    ax.legend(
        handles=[
            Patch(facecolor=COLOUR_YES, label="yes gold"),
            Patch(facecolor=COLOUR_NO, label="no gold"),
        ],
        loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2,
        frameon=False, handlelength=1.1, handleheight=1.1,
        columnspacing=1.6, borderpad=0, fontsize=9,
    )

    fig.tight_layout()
    fig.savefig(out_png, dpi=300)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "odmi.db"))
    parser.add_argument("--outdir", default=str(REPO_ROOT / "evaluation" / "figures"))
    args = parser.parse_args()

    result = compute(Path(args.db))
    report(result)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    png = outdir / "abstention_gold_class_by_code.png"
    js = outdir / "abstention_gold_class_by_code.json"

    build_figure(result, png)
    js.write_text(json.dumps(result, indent=2) + "\n")

    print(f"\nwrote {png}")
    print(f"wrote {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
