#!/usr/bin/env python3
"""Balance-aware, three-outcome analysis for a phase-1 two-arm experiment.

Reads the canonical row per pair (the latest phase2_final for a given
question/country/condition, so duplicates from interrupted runs are superseded,
never summed) and reports, per arm:

  - candidate recall: gold answer present in ANY Researcher attempt (the
    retrieval signal, decoupled from selection)
  - coverage: share of pairs committed (1 - abstention)
  - commit accuracy: matches over committed answers, with a Wilson 95% CI
  - per-class recall: yes-gold and no-gold commit recall
  - false positives: committed-wrong on a no-gold pair (the visible-error class
    Malta/NL base-rate balance exists to expose), as a count and a rate
  - cost per pair in pounds (retries already folded into cumulative cost)

and the paired comparison between two arms (McNemar exact on per-pair
correctness, pairing on question/country where both arms committed).

Usage:
    uv run python evaluation/analyze_phase1.py <experiment_id> [arm_a arm_b]

The arms default to a known pair per experiment_id; pass them explicitly to
override. Binary pairs with a yes/no gold only.
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.stats import mcnemar_exact, wilson_interval  # noqa: E402

DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"
ABST = {"inconclusive", "other", "not_applicable", "not applicable",
        "i don't know", "idk", ""}
# Default arm pair per experiment. arm_a is the incumbent/baseline.
DEFAULT_ARMS = {
    "exp14_verifier_search_nl": ("always", "never"),
    "exp17_picker_nl": ("picker_on", "picker_off"),
    "exp16_adjudicator_selection_nl": ("standard", "free"),
}
GBP = 0.79  # USD->GBP, matches dashboard/lib/currency.py


def norm(s: str | None) -> str:
    return (s or "").strip().lower()


def canonical_rows(c: sqlite3.Cursor, experiment_id: str):
    """One row per (question, country, condition): the latest phase2_final.

    Pairs phase2_final to its arm via the Researcher condition_label, and keeps
    only the most recent finalisation per (question, country, arm) so duplicate
    rows from earlier interrupted runs do not double-count.
    """
    rows = c.execute(
        """
        SELECT f.id, f.pair_run_id, f.question_id, f.country_code,
               f.final_answer, g.response AS gold, f.cumulative_cost_usd,
               f.created_at,
               (SELECT condition_label FROM phase2_researcher_runs r
                WHERE r.pair_run_id = f.pair_run_id LIMIT 1) AS arm
        FROM phase2_final f
        JOIN questions q ON q.question_id = f.question_id
        JOIN ground_truth g
          ON g.question_id = f.question_id AND g.country_code = f.country_code
        WHERE f.experiment_id = ? AND q.answer_shape = 'binary'
          AND lower(trim(g.response)) IN ('yes', 'no')
        ORDER BY f.created_at ASC, f.id ASC
        """,
        (experiment_id,),
    ).fetchall()
    canon = {}  # (qid, cc, arm) -> row ; later rows overwrite earlier
    for r in rows:
        canon[(r[2], r[3], r[8])] = r
    return list(canon.values())


def attempts(c: sqlite3.Cursor, pair_run_id: str) -> list[str]:
    return [norm(a[0]) for a in c.execute(
        "SELECT answer FROM phase2_researcher_runs WHERE pair_run_id = ?",
        (pair_run_id,),
    ).fetchall()]


def analyse(experiment_id: str, arm_a: str, arm_b: str) -> None:
    c = sqlite3.connect(str(DB)).cursor()
    rows = canonical_rows(c, experiment_id)

    S = defaultdict(lambda: {
        "n": 0, "recall": 0, "commit": 0, "commit_ok": 0, "abst": 0,
        "fp": 0, "yes_n": 0, "yes_ok": 0, "no_n": 0, "no_ok": 0, "cost": 0.0})
    # per (qid,cc): arm -> correct(True/False) or None if abstained
    paired: dict[tuple, dict] = defaultdict(dict)

    for _id, prid, qid, cc, final, gold, cost, _ts, arm in rows:
        g, fin = norm(gold), norm(final)
        s = S[arm]
        s["n"] += 1
        s["cost"] += cost or 0.0
        if any(a == g for a in attempts(c, prid)):
            s["recall"] += 1
        committed = fin not in ABST
        if committed:
            s["commit"] += 1
            ok = fin == g
            s["commit_ok"] += int(ok)
            if not ok and g == "no":
                s["fp"] += 1
            paired[(qid, cc)][arm] = ok
        else:
            s["abst"] += 1
            paired[(qid, cc)][arm] = None
        if g == "yes":
            s["yes_n"] += 1
            s["yes_ok"] += int(committed and fin == g)
        else:
            s["no_n"] += 1
            s["no_ok"] += int(committed and fin == g)

    print(f"\n=== {experiment_id}: {arm_a} (incumbent) vs {arm_b} ===")
    hdr = (f"{'arm':<12}{'n':>4}{'cand_rec':>9}{'coverage':>9}"
           f"{'commit_acc[95% CI]':>22}{'yes_rec':>8}{'no_rec':>7}"
           f"{'FP':>4}{'£/pair':>8}")
    print(hdr)
    for arm in (arm_a, arm_b):
        s = S[arm]
        n = s["n"] or 1
        comm = s["commit"] or 1
        lo, hi = wilson_interval(s["commit_ok"], s["commit"])
        ci = f"{s['commit_ok']/comm:.2f}[{lo:.2f},{hi:.2f}]"
        yr = s["yes_ok"] / s["yes_n"] if s["yes_n"] else 0.0
        nr = s["no_ok"] / s["no_n"] if s["no_n"] else 0.0
        print(f"{arm:<12}{s['n']:>4}{s['recall']/n:>9.2f}{s['commit']/n:>9.2f}"
              f"{ci:>22}{yr:>8.2f}{nr:>7.2f}{s['fp']:>4}"
              f"{GBP*s['cost']/n:>8.3f}")

    # Paired McNemar on per-pair correctness where BOTH arms committed.
    b = sum(1 for v in paired.values()
            if v.get(arm_a) is True and v.get(arm_b) is False)
    cc_ = sum(1 for v in paired.values()
              if v.get(arm_a) is False and v.get(arm_b) is True)
    both = sum(1 for v in paired.values()
               if v.get(arm_a) is not None and v.get(arm_b) is not None)
    p = mcnemar_exact(b, cc_)
    print(f"\nPaired McNemar (both committed, n={both}): "
          f"{arm_a}-only-right={b}, {arm_b}-only-right={cc_}, exact p={p:.3f}")

    # Adoption rule: adopt arm_b only if commit accuracy does not drop and FP
    # rate does not rise versus arm_a, at strictly lower cost per pair.
    sa, sb = S[arm_a], S[arm_b]
    acc_a = sa["commit_ok"] / (sa["commit"] or 1)
    acc_b = sb["commit_ok"] / (sb["commit"] or 1)
    fpr_a = sa["fp"] / (sa["no_n"] or 1)
    fpr_b = sb["fp"] / (sb["no_n"] or 1)
    cost_a = GBP * sa["cost"] / (sa["n"] or 1)
    cost_b = GBP * sb["cost"] / (sb["n"] or 1)
    adopt = (acc_b >= acc_a) and (fpr_b <= fpr_a) and (cost_b < cost_a)
    print(f"\nAdoption check for {arm_b}: "
          f"commit_acc {acc_b:.2f} vs {acc_a:.2f} "
          f"({'ok' if acc_b >= acc_a else 'DROP'}); "
          f"FP rate {fpr_b:.2f} vs {fpr_a:.2f} "
          f"({'ok' if fpr_b <= fpr_a else 'RISE'}); "
          f"£/pair {cost_b:.3f} vs {cost_a:.3f} "
          f"({'lower' if cost_b < cost_a else 'NOT lower'})")
    print(f"VERDICT: {'adopt ' + arm_b if adopt else 'keep ' + arm_a + ' (rule not met)'}")
    print("\ncand_rec = gold in any Researcher attempt; coverage = share committed;")
    print("commit_acc = matches over committed; FP = committed-wrong on a no-gold.")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    eid = sys.argv[1]
    if len(sys.argv) >= 4:
        arm_a, arm_b = sys.argv[2], sys.argv[3]
    elif eid in DEFAULT_ARMS:
        arm_a, arm_b = DEFAULT_ARMS[eid]
    else:
        print(f"no default arms for {eid!r}; pass arm_a arm_b explicitly")
        return 1
    analyse(eid, arm_a, arm_b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
