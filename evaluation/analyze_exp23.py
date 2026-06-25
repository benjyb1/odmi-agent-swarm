#!/usr/bin/env python3
"""EXP-23 trusted-domain narrow-then-widen retrieval analysis.

Reads the three exp23_narrow_then_widen_{nl,mt,al} experiments and reports
the endpoints declared at dispatch in evaluation/specs/exp23_narrow_then_widen.json:

    Primary    FP rate on negative golds (binary-commit subset), Wilson CI.
    Co-primary commit accuracy on binary-commit subset.
    Secondary  candidate recall, abstention, per-class recall, retries/pair,
               fetched-page novelty, cost/pair.
    Diagnostic among FPs, how many cite a trusted-domain source URL.

The declared inference rules then fire at the bottom (NL primary): promote
wide_only only if it cuts negative-gold FP by >= 5 absolute points AND commit
accuracy is non-inferior (delta accuracy >= -0.02); also check the AL recall
side-finding (wide_only raises candidate recall by >= 5pp -> narrow was
suppressing thin-web recall).

Run:
    uv run python evaluation/analyze_exp23.py
    uv run python evaluation/analyze_exp23.py --md       # also write report
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"
OUT_MD = REPO / "evaluation" / "results" / "exp23_analysis.md"

ARMS = ["baseline_narrow_then_wide", "wide_only", "narrow_only"]
COUNTRIES = ["NL", "MT", "AL"]
EXPERIMENT_IDS = {cc: f"exp23_narrow_then_widen_{cc.lower()}" for cc in COUNTRIES}
ABSTAIN_SHAPES = {"inconclusive", "other", "not_applicable", "not applicable",
                  "i don't know", "idk", ""}
USD_TO_GBP = 0.79


# ----------------------------------------------------------------------
# stats
# ----------------------------------------------------------------------

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def norm(s: str | None) -> str:
    return (s or "").strip().lower()


def fmt_pp(p: float) -> str:
    return f"{100*p:5.1f}%"


def fmt_ci(k: int, n: int) -> str:
    if n == 0:
        return "  n=0"
    lo, hi = wilson_ci(k, n)
    return f"{100*k/n:5.1f}% [{100*lo:4.1f}, {100*hi:4.1f}]"


# ----------------------------------------------------------------------
# data loading
# ----------------------------------------------------------------------

def load_trusted_domains() -> dict[str, set[str]]:
    """Each country's trusted_domains JSON list, ready for endswith checks."""
    out: dict[str, set[str]] = {}
    for cc in COUNTRIES:
        path = REPO / "data" / "trusted_domains" / f"{cc}.json"
        doc = json.loads(path.read_text())
        out[cc] = set(doc.get("trusted_domains", []))
    return out


def domain_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def is_trusted(url: str, trusted: set[str]) -> bool:
    d = domain_of(url)
    if not d:
        return False
    return any(d == t or d.endswith("." + t) for t in trusted)


def load_pairs(conn: sqlite3.Connection, experiment_ids: Iterable[str]) -> list[dict]:
    """One row per (pair_run_id) in the binary-commit subset across all arms.

    Joins phase2_final -> questions -> ground_truth, then a separate query
    pulls the per-attempt Researcher answers so we can compute candidate
    recall (gold in any attempt) without losing the final row.
    """
    rows = conn.execute(f"""
        SELECT
            f.pair_run_id, f.question_id, f.country_code,
            f.terminal_status, f.final_answer, f.final_source_url,
            f.cumulative_cost_usd, f.retry_count,
            q.dimension, lower(trim(g.response)) AS gold,
            (SELECT condition_label FROM phase2_researcher_runs
              WHERE pair_run_id = f.pair_run_id
              ORDER BY retry_count DESC LIMIT 1) AS arm,
            (SELECT experiment_id FROM phase2_researcher_runs
              WHERE pair_run_id = f.pair_run_id LIMIT 1) AS exp_id
        FROM phase2_final f
        JOIN questions q     ON q.question_id = f.question_id
        JOIN ground_truth g  ON g.question_id = f.question_id
                            AND g.country_code = f.country_code
        WHERE f.experiment_id IN ({','.join('?' for _ in experiment_ids)})
          AND q.answer_shape = 'binary'
          AND lower(trim(g.response)) IN ('yes', 'no')
    """, list(experiment_ids)).fetchall()

    pairs = []
    for r in rows:
        prid, qid, cc, status, final, src, cost, retries, dim, gold, arm, exp_id = r
        # candidate recall: gold appears in any attempt
        atts = [norm(a[0]) for a in conn.execute(
            "SELECT answer FROM phase2_researcher_runs WHERE pair_run_id = ?",
            (prid,)).fetchall()]
        pairs.append({
            "pair_run_id": prid, "qid": qid, "cc": cc, "dim": dim,
            "gold": gold, "final": norm(final), "src": src or "",
            "status": status, "cost": cost or 0.0, "retries": retries or 0,
            "arm": arm or "?", "exp_id": exp_id or "?",
            "recall_hit": any(a == gold for a in atts),
        })
    return pairs


def load_search_telemetry(conn: sqlite3.Connection,
                          experiment_ids: Iterable[str]) -> dict[str, list[dict]]:
    """Per-arm: every Researcher row's queries + fetched URLs. Used for
    secondary endpoints (novelty) and the manipulation diagnostic."""
    out: dict[str, list[dict]] = defaultdict(list)
    rows = conn.execute(f"""
        SELECT condition_label, country_code, question_id,
               search_queries_used, fetched_urls
          FROM phase2_researcher_runs
         WHERE experiment_id IN ({','.join('?' for _ in experiment_ids)})
    """, list(experiment_ids)).fetchall()
    for arm, cc, qid, queries_j, fetched_j in rows:
        out[arm].append({
            "cc": cc, "qid": qid,
            "queries": json.loads(queries_j) if queries_j else [],
            "fetched": json.loads(fetched_j) if fetched_j else [],
        })
    return out


# ----------------------------------------------------------------------
# endpoints
# ----------------------------------------------------------------------

def per_arm_endpoints(pairs: list[dict], trusted: dict[str, set[str]]) -> dict:
    """Compute every endpoint for one filtered slice (one arm, one country,
    one dimension, etc.). Returns a dict of counts so the caller can format."""
    n = len(pairs)
    committed = [p for p in pairs if p["final"] not in ABSTAIN_SHAPES]
    neg_committed = [p for p in committed if p["gold"] == "no"]
    fp = [p for p in neg_committed if p["final"] != "no"]  # committed 'yes' on a 'no' gold
    commit_ok = [p for p in committed if p["final"] == p["gold"]]

    yes_pairs = [p for p in pairs if p["gold"] == "yes"]
    no_pairs = [p for p in pairs if p["gold"] == "no"]
    yes_ok = [p for p in yes_pairs if p["final"] == "yes"]
    no_ok = [p for p in no_pairs if p["final"] == "no"]

    recall_hits = sum(1 for p in pairs if p["recall_hit"])
    abst = sum(1 for p in pairs if p["final"] in ABSTAIN_SHAPES)
    cost_total = sum(p["cost"] for p in pairs)
    retries_total = sum(p["retries"] for p in pairs)

    trusted_set_per_pair = {p["pair_run_id"]: trusted.get(p["cc"], set()) for p in pairs}
    fp_trusted = sum(1 for p in fp
                     if is_trusted(p["src"], trusted_set_per_pair[p["pair_run_id"]]))

    return {
        "n_pairs": n,
        "n_committed": len(committed),
        "n_neg_committed": len(neg_committed),
        "n_fp": len(fp),
        "n_commit_ok": len(commit_ok),
        "n_recall": recall_hits,
        "n_abst": abst,
        "n_yes": len(yes_pairs), "n_yes_ok": len(yes_ok),
        "n_no": len(no_pairs),   "n_no_ok": len(no_ok),
        "fp_trusted_src": fp_trusted,
        "cost_gbp": cost_total * USD_TO_GBP,
        "retries_mean": (retries_total / n) if n else 0.0,
    }


# ----------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------

def render_arm_table(label: str, slices: dict[str, dict]) -> list[str]:
    """slices: {arm_label: endpoints_dict}. Returns markdown lines."""
    lines = [f"### {label}", ""]
    lines.append("| Arm | n | FP rate (neg-commit) | Commit acc | Recall | Abstain | Yes-rec | No-rec | £/pair | Retries/pair | FP via trusted-src |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        s = slices.get(arm)
        if not s or s["n_pairs"] == 0:
            lines.append(f"| {arm} | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        fp_str = fmt_ci(s["n_fp"], s["n_neg_committed"])
        acc_str = fmt_ci(s["n_commit_ok"], s["n_committed"])
        rec_str = fmt_ci(s["n_recall"], s["n_pairs"])
        abst_str = fmt_pp(s["n_abst"] / s["n_pairs"])
        yes_str = fmt_ci(s["n_yes_ok"], s["n_yes"])
        no_str = fmt_ci(s["n_no_ok"], s["n_no"])
        cost_str = f"£{s['cost_gbp']/s['n_pairs']:.2f}"
        ret_str = f"{s['retries_mean']:.2f}"
        trust_str = f"{s['fp_trusted_src']}/{s['n_fp']}" if s["n_fp"] else "0/0"
        lines.append(f"| {arm} | {s['n_pairs']} | {fp_str} | {acc_str} | {rec_str} | "
                     f"{abst_str} | {yes_str} | {no_str} | {cost_str} | {ret_str} | {trust_str} |")
    lines.append("")
    return lines


def render_novelty(telemetry: dict[str, list[dict]]) -> list[str]:
    """Per-arm unique fetched URLs, and the pairwise overlap matrix.

    Confirms wide_only actually reaches different evidence pages; if the
    set overlap is very high, the experiment's design loses force."""
    sets = {arm: set() for arm in ARMS}
    for arm, rows in telemetry.items():
        for r in rows:
            sets[arm].update(r["fetched"])
    lines = ["### Fetched-page novelty", "",
             "| Arm | Unique URLs |", "|---|---|"]
    for arm in ARMS:
        lines.append(f"| {arm} | {len(sets[arm])} |")
    lines.append("")
    lines.append("Pairwise Jaccard overlap of fetched-URL sets:")
    lines.append("")
    lines.append("| | " + " | ".join(ARMS) + " |")
    lines.append("|---|" + "---|" * len(ARMS))
    for a in ARMS:
        row = [a]
        for b in ARMS:
            if a == b:
                row.append("—")
                continue
            inter = len(sets[a] & sets[b])
            union = len(sets[a] | sets[b])
            row.append(f"{inter/union:.2f}" if union else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def render_inference(slices_by_cc: dict[str, dict[str, dict]]) -> list[str]:
    """Run the adoption rule and the side-finding rule on NL/AL primary slices."""
    nl = slices_by_cc.get("NL", {})
    al = slices_by_cc.get("AL", {})
    lines = ["## Declared inference rules", ""]

    # Rule 1: NL primary -- FP cut + commit-acc non-inferior?
    base = nl.get("baseline_narrow_then_wide")
    wide = nl.get("wide_only")
    if base and wide and base["n_neg_committed"] and wide["n_neg_committed"]:
        base_fp = base["n_fp"] / base["n_neg_committed"]
        wide_fp = wide["n_fp"] / wide["n_neg_committed"]
        fp_delta = base_fp - wide_fp  # positive => wide reduces FP
        base_acc = (base["n_commit_ok"] / base["n_committed"]) if base["n_committed"] else 0
        wide_acc = (wide["n_commit_ok"] / wide["n_committed"]) if wide["n_committed"] else 0
        acc_delta = wide_acc - base_acc
        rule1_passes = fp_delta >= 0.05 and acc_delta >= -0.02
        lines.append(f"**NL rule (adoption).** baseline FP={fmt_pp(base_fp)}, "
                     f"wide_only FP={fmt_pp(wide_fp)} -> delta FP={fp_delta*100:+.1f}pp.")
        lines.append(f"baseline commit-acc={fmt_pp(base_acc)}, wide_only="
                     f"{fmt_pp(wide_acc)} -> delta={acc_delta*100:+.1f}pp.")
        lines.append(f"Adoption rule: FP cut >= 5pp AND commit-acc non-inferior "
                     f"(delta >= -2pp). **Result: "
                     f"{'PROMOTE wide_only' if rule1_passes else 'KEEP narrow_then_wide'}**.")
        lines.append("")

    # Rule 2: AL recall side-finding
    al_base = al.get("baseline_narrow_then_wide")
    al_wide = al.get("wide_only")
    if al_base and al_wide and al_base["n_pairs"] and al_wide["n_pairs"]:
        base_rec = al_base["n_recall"] / al_base["n_pairs"]
        wide_rec = al_wide["n_recall"] / al_wide["n_pairs"]
        rec_delta = wide_rec - base_rec
        rule2 = rec_delta >= 0.05
        lines.append(f"**AL rule (side-finding).** baseline recall={fmt_pp(base_rec)}, "
                     f"wide_only={fmt_pp(wide_rec)} -> delta={rec_delta*100:+.1f}pp.")
        lines.append(f"Side-finding rule: wide_only raises AL recall by >= 5pp. "
                     f"**Result: {'CONFIRMED: narrow suppresses thin-web recall' if rule2 else 'No side-finding'}**.")
        lines.append("")

    # Rule 3: over-trust mechanism - among baseline FPs, are most via trusted-domain sources?
    if base and base["n_fp"]:
        share = base["fp_trusted_src"] / base["n_fp"]
        lines.append(f"**Mechanism diagnostic (NL).** {base['fp_trusted_src']} / "
                     f"{base['n_fp']} ({fmt_pp(share)}) of baseline FPs cite a "
                     f"trusted-domain source URL. If this share is high AND "
                     f"wide_only's FPs are concentrated in non-trusted URLs, the "
                     f"over-trust mechanism is implicated specifically.")
        lines.append("")

    return lines


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true",
                    help=f"Also write a markdown report to {OUT_MD.relative_to(REPO)}")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    trusted = load_trusted_domains()
    experiment_ids = list(EXPERIMENT_IDS.values())
    pairs = load_pairs(conn, experiment_ids)
    telemetry = load_search_telemetry(conn, experiment_ids)
    conn.close()

    if not pairs:
        print("No EXP-23 rows in phase2_final yet -- dispatch incomplete?")
        return 1

    lines: list[str] = []
    lines.append("# EXP-23 trusted-domain narrow-then-widen results\n")
    lines.append(f"Pairs scored: {len(pairs)} across "
                 f"{len(set(p['cc'] for p in pairs))} countries and "
                 f"{len(set(p['arm'] for p in pairs))} arms.\n")

    # Pooled (all countries)
    by_arm_pooled = {arm: per_arm_endpoints([p for p in pairs if p["arm"] == arm], trusted)
                     for arm in ARMS}
    lines += render_arm_table("Pooled across NL/MT/AL", by_arm_pooled)

    # Per country
    slices_by_cc: dict[str, dict[str, dict]] = {}
    for cc in COUNTRIES:
        cc_pairs = [p for p in pairs if p["cc"] == cc]
        if not cc_pairs:
            continue
        sl = {arm: per_arm_endpoints([p for p in cc_pairs if p["arm"] == arm], trusted)
              for arm in ARMS}
        slices_by_cc[cc] = sl
        lines += render_arm_table(f"{cc}", sl)

    # Per dimension (pooled)
    dims = sorted(set(p["dim"] for p in pairs))
    for dim in dims:
        dim_pairs = [p for p in pairs if p["dim"] == dim]
        sl = {arm: per_arm_endpoints([p for p in dim_pairs if p["arm"] == arm], trusted)
              for arm in ARMS}
        lines += render_arm_table(f"Dimension: {dim}", sl)

    # Novelty
    lines += render_novelty(telemetry)

    # Inference rules
    lines += render_inference(slices_by_cc)

    report = "\n".join(lines)
    print(report)
    if args.md:
        OUT_MD.parent.mkdir(parents=True, exist_ok=True)
        OUT_MD.write_text(report)
        print(f"\nWrote {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
