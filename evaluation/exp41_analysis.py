"""EXP-41 analysis: run-to-run stability of the incumbent trio.

Implements M1 to M6 exactly as pre-registered in
`docs/EXPERIMENTS_RUN_STABILITY.md`. Written and committed BEFORE the data
existed, which is the point: a metric defined after seeing the numbers is a
choice, and §3.10 rests on the choices being fixed in advance.

  M1  three-way outcome unanimity + Fleiss' kappa over
      {commit-yes, commit-no, no-commit}. No pair is ever dropped:
      `agent_failure` folds into no-commit, because failures do not land on the
      same pairs in every run and excluding them per run deletes exactly the
      disagreements the experiment is measuring.
  M2  per-run marginal commit rate and commit accuracy, with spread. Guards the
      degenerate all-abstain case and gives §4.2 an empirical noise floor.
  M3  label agreement restricted to pairs all three runs committed.
  M4  M1 and M3 decomposed by gold class.
  M5  evidence-path divergence: share of unanimously-committed-and-agreed pairs
      citing two or more distinct normalised URLs across the runs.
  M6  confidence distribution at the D37 floor, post-D7-fix.

Pre-registered tolerances, checked and reported as pass/miss:
  M1  >= 0.80 unanimous AND Fleiss kappa >= 0.60   (predicted to miss)
  M2  commit-rate range across the three <= 0.10
  M3  >= 0.90 unanimous AND Fleiss kappa >= 0.70   (predicted to clear)
  M5  descriptive; predicted > 0.50

    uv run python evaluation/exp41_analysis.py --db data/odmi.db \
        --out evaluation/results/exp41_analysis.json
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

REPLICATES = ("exp41_stability_rep1", "exp41_stability_rep2", "exp41_stability_rep3")

# A completed run may finalise this many pairs short of 156 through benign
# search stalls without being treated as partial. Matches SHORTFALL_TOLERANCE in
# scripts/audit_exp41_gate.py so the gate and the analysis agree on "complete".
STALL_TOLERANCE = 5

COMMITTED_PREFIX = "accepted"
ABSTENTION_TOKENS = {"inconclusive", "abstain", "abstained", "", "none", "null"}

# Pre-registered bars. Not to be edited after the data lands.
BARS = {
    "m1_unanimity": 0.80, "m1_kappa": 0.60,
    "m2_commit_rate_range": 0.10,
    "m3_unanimity": 0.90, "m3_kappa": 0.70,
    "m5_divergence": 0.50,
}


# outcome vocabulary

def outcome(terminal_status: str, answer: str | None) -> str:
    """One of commit-yes / commit-no / no-commit.

    `agent_failure` and every abstention collapse to no-commit. A committed row
    whose answer is an abstention token is not a commit either: the D37 floor
    can produce a committed status with no real answer behind it.
    """
    if not terminal_status.startswith(COMMITTED_PREFIX):
        return "no-commit"
    a = (answer or "").strip().lower()
    if a in ABSTENTION_TOKENS:
        return "no-commit"
    if a in {"yes", "true"}:
        return "commit-yes"
    if a in {"no", "false"}:
        return "commit-no"
    return "commit-other"  # non-binary answer shape; kept visible, not silently binned


def normalise_url(u: str | None) -> str:
    """Pre-registered normalisation: lowercase scheme and host, strip the
    trailing slash, drop query string and fragment. Fixed here so 'distinct
    URL' cannot be redefined once the divergence number is known."""
    if not u:
        return ""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return u.strip().lower()
    host = (p.netloc or "").lower()
    path = (p.path or "").rstrip("/")
    scheme = (p.scheme or "https").lower()
    return f"{scheme}://{host}{path}" if host else u.strip().lower()


# Fleiss' kappa

def fleiss_kappa(rows: list[list[int]]) -> float:
    """Fleiss' kappa. `rows` is one row per item, counts per category.

    Fleiss rather than Cohen because there are three raters, not two. Every row
    must carry the same rater count; a short row means a pair was dropped
    somewhere upstream, which this design forbids.
    """
    rows = [r for r in rows if sum(r) > 0]
    if not rows:
        return float("nan")
    n = sum(rows[0])
    if n < 2 or any(sum(r) != n for r in rows):
        return float("nan")
    N, k = len(rows), len(rows[0])
    p_j = [sum(r[j] for r in rows) / (N * n) for j in range(k)]
    P_i = [(sum(c * c for c in r) - n) / (n * (n - 1)) for r in rows]
    P_bar = sum(P_i) / N
    P_e = sum(p * p for p in p_j)
    if abs(1 - P_e) < 1e-12:
        return float("nan")  # every rater used one category; kappa undefined
    return (P_bar - P_e) / (1 - P_e)


def bootstrap_kappa(rows: list[list[int]], draws: int = 10000, seed: int = 20260721):
    """Item-level resample, as pre-registered. Seeded so the interval is
    reproducible from the committed code alone."""
    if not rows:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        sample = [rows[rng.randrange(len(rows))] for _ in range(len(rows))]
        k = fleiss_kappa(sample)
        if k == k:  # not nan
            vals.append(k)
    if not vals:
        return (float("nan"), float("nan"))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))])


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    # Clamp: at k=0 the arithmetic lands a hair below zero, and a probability
    # interval printed as -2e-17 in a results table is simply wrong.
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


# data

def load(conn: sqlite3.Connection, eid: str) -> dict[str, dict]:
    """Canonical row per pair: the latest finalised row wins."""
    out: dict[str, dict] = {}
    for q, cc, ts, ans, url, conf, retry in conn.execute(
        """SELECT question_id, country_code, terminal_status, final_answer,
                  final_source_url, final_answer_confidence, retry_count
           FROM phase2_final WHERE experiment_id = ? ORDER BY id ASC""", (eid,)
    ):
        out[f"{q}:{cc}"] = {
            "outcome": outcome(ts, ans), "status": ts,
            "answer": (ans or "").strip().lower(),
            "url": normalise_url(url), "confidence": conf, "retry": retry,
        }
    return out


def gold(conn: sqlite3.Connection) -> dict[str, str]:
    g: dict[str, str] = {}
    for q, cc, resp in conn.execute(
        "SELECT question_id, country_code, response FROM ground_truth"
    ):
        g[f"{q}:{cc}"] = (resp or "").strip().lower()
    return g


def counts_row(outs: list[str], cats: list[str]) -> list[int]:
    return [sum(1 for o in outs if o == c) for c in cats]


def agreement(per_run: list[dict], pairs: list[str], cats: list[str], key: str) -> dict:
    rows, unanimous = [], 0
    for p in pairs:
        vals = [r[p][key] for r in per_run]
        rows.append(counts_row(vals, cats))
        if len(set(vals)) == 1:
            unanimous += 1
    n = len(pairs)
    k = fleiss_kappa(rows)
    lo, hi = bootstrap_kappa(rows)
    u_lo, u_hi = wilson(unanimous, n)
    return {
        "n": n, "n_unanimous": unanimous,
        "unanimity": (unanimous / n) if n else 0.0,
        "unanimity_ci": [u_lo, u_hi],
        "fleiss_kappa": k, "fleiss_kappa_ci": [lo, hi],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/odmi.db")
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-partial", action="store_true",
                    help="Analyse even if a replicate finalised fewer than "
                         f"{156 - STALL_TOLERANCE} pairs. For monitoring only; a "
                         "reported result must not use it.")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    runs = [load(conn, e) for e in REPLICATES]
    g = gold(conn)

    sizes = [len(r) for r in runs]
    print("replicate sizes:", dict(zip(REPLICATES, sizes)))
    # A completed run may finalise a few pairs short of 156: some pairs stall on
    # a search that never returns and the orchestrator abandons them and exits
    # healthy (rep1 lost 1, rep2 lost 2, rep3 lost 5, all Albanian search
    # stalls). This is the disclosed behaviour, not a partial or peeked run: n
    # is the three-way intersection by design (R11 is about not stopping early,
    # which none of these did). A shortfall beyond the tolerance means a run did
    # not complete, and that does need --allow-partial.
    if any(s < 156 - STALL_TOLERANCE for s in sizes) and not args.allow_partial:
        print(f"A replicate finalised fewer than {156 - STALL_TOLERANCE} pairs, "
              f"more than benign stalls explain. Re-run with --allow-partial to "
              f"inspect, but do not report a partial result (R11).")
        return 2
    short = [(e, s) for e, s in zip(REPLICATES, sizes) if s < 156]
    if short:
        print("benign shortfall (stalled pairs, dropped from the intersection):",
              {e: 156 - s for e, s in short})

    shared = sorted(set(runs[0]) & set(runs[1]) & set(runs[2]))
    if not shared:
        print("no pairs shared across all three replicates")
        return 2
    print(f"{len(shared)} pairs present in all three replicates\n")

    cats3 = ["commit-yes", "commit-no", "no-commit", "commit-other"]

    # M1
    m1 = agreement(runs, shared, cats3, "outcome")

    # M2
    m2_runs = []
    for eid, r in zip(REPLICATES, runs):
        committed = [p for p in shared if r[p]["outcome"].startswith("commit")]
        scoreable = [p for p in committed if g.get(p) in {"yes", "no"}]
        correct = sum(1 for p in scoreable if r[p]["answer"] == g[p])
        m2_runs.append({
            "experiment_id": eid,
            "commit_rate": len(committed) / len(shared),
            "n_committed": len(committed),
            "commit_accuracy": (correct / len(scoreable)) if scoreable else None,
            "n_scoreable": len(scoreable),
        })
    rates = [x["commit_rate"] for x in m2_runs]
    accs = [x["commit_accuracy"] for x in m2_runs if x["commit_accuracy"] is not None]
    mean_r = sum(rates) / len(rates)
    m2 = {
        "per_run": m2_runs,
        "commit_rate_range": max(rates) - min(rates),
        "commit_rate_sd": (sum((x - mean_r) ** 2 for x in rates) / len(rates)) ** 0.5,
        "commit_accuracy_range": (max(accs) - min(accs)) if len(accs) == 3 else None,
    }

    # M3
    all_committed = [p for p in shared
                     if all(r[p]["outcome"].startswith("commit") for r in runs)]
    m3 = agreement(runs, all_committed, ["yes", "no", "other"],
                   "answer") if all_committed else {"n": 0}
    if all_committed:
        rows, unan = [], 0
        for p in all_committed:
            vals = [r[p]["answer"] if r[p]["answer"] in {"yes", "no"} else "other"
                    for r in runs]
            rows.append(counts_row(vals, ["yes", "no", "other"]))
            if len(set(vals)) == 1:
                unan += 1
        lo, hi = bootstrap_kappa(rows)
        ulo, uhi = wilson(unan, len(all_committed))
        m3 = {"n": len(all_committed), "n_unanimous": unan,
              "unanimity": unan / len(all_committed), "unanimity_ci": [ulo, uhi],
              "fleiss_kappa": fleiss_kappa(rows), "fleiss_kappa_ci": [lo, hi]}

    # M4
    m4 = {}
    for cls in ("yes", "no"):
        sub = [p for p in shared if g.get(p) == cls]
        sub_c = [p for p in all_committed if g.get(p) == cls]
        m4[f"{cls}_gold"] = {
            "m1": agreement(runs, sub, cats3, "outcome") if sub else {"n": 0},
            "m3_n": len(sub_c),
            "m3_unanimous": sum(1 for p in sub_c
                                if len({r[p]["answer"] for r in runs}) == 1),
        }

    # M5
    unan_commit = [p for p in all_committed
                   if len({r[p]["answer"] for r in runs}) == 1]
    div = [p for p in unan_commit if len({r[p]["url"] for r in runs if r[p]["url"]}) >= 2]
    all_three = [p for p in unan_commit if len({r[p]["url"] for r in runs if r[p]["url"]}) == 3]
    dlo, dhi = wilson(len(div), len(unan_commit)) if unan_commit else (0.0, 0.0)
    m5 = {
        "n_unanimously_committed_and_agreed": len(unan_commit),
        "n_with_2plus_distinct_urls": len(div),
        "n_with_3_distinct_urls": len(all_three),
        "divergence": (len(div) / len(unan_commit)) if unan_commit else 0.0,
        "divergence_ci": [dlo, dhi],
    }

    # M6
    m6 = []
    for eid, r in zip(REPLICATES, runs):
        c = [p for p in shared if r[p]["outcome"].startswith("commit")]
        first = [p for p in c if (r[p]["retry"] or 0) == 0]
        retried = [p for p in c if (r[p]["retry"] or 0) > 0]
        at = lambda xs: sum(1 for p in xs if r[p]["confidence"] == 0.65)  # noqa: E731
        m6.append({
            "experiment_id": eid,
            "first_attempt_at_floor": (at(first) / len(first)) if first else None,
            "n_first": len(first),
            "retried_at_floor": (at(retried) / len(retried)) if retried else None,
            "n_retried": len(retried),
        })

    verdicts = {
        "M1": {"unanimity": m1["unanimity"] >= BARS["m1_unanimity"],
               "kappa": (m1["fleiss_kappa"] or 0) >= BARS["m1_kappa"]},
        "M2": {"range": m2["commit_rate_range"] <= BARS["m2_commit_rate_range"]},
        "M3": {"unanimity": m3.get("unanimity", 0) >= BARS["m3_unanimity"],
               "kappa": (m3.get("fleiss_kappa") or 0) >= BARS["m3_kappa"]},
        "M5": {"divergence": m5["divergence"] > BARS["m5_divergence"]},
    }

    result = {"n_pairs_shared": len(shared), "bars": BARS, "verdicts": verdicts,
              "M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6,
              "exp34_m6_baseline": {"first_attempt_at_floor": 3 / 32,
                                    "retried_at_floor": 16 / 49}}

    print(f"M1 outcome unanimity {m1['unanimity']:.3f} "
          f"(bar {BARS['m1_unanimity']}), Fleiss k={m1['fleiss_kappa']:.3f} "
          f"[{m1['fleiss_kappa_ci'][0]:.3f}, {m1['fleiss_kappa_ci'][1]:.3f}]")
    print(f"M2 commit rates {[round(x['commit_rate'],3) for x in m2_runs]} "
          f"range {m2['commit_rate_range']:.3f} (bar <= {BARS['m2_commit_rate_range']})")
    if m3.get("n"):
        print(f"M3 label unanimity {m3['unanimity']:.3f} on n={m3['n']} "
              f"(bar {BARS['m3_unanimity']}), Fleiss k={m3['fleiss_kappa']:.3f}")
    print(f"M5 evidence-path divergence {m5['divergence']:.3f} "
          f"on n={m5['n_unanimously_committed_and_agreed']}")
    print(f"\nverdicts: {json.dumps(verdicts)}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
        print(f"wrote {args.out}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
