"""EXP-40 analysis: adversarial vs cooperative architecture contrast.

Four arms over the same 156-pair dev battery (MT+NL+AL):

  trio             exp34 wide_only, as run (full adversarial pipeline)
  no_adjudicator   trio replay: an adjudicated pair (accepted/abstained by the
                   Adjudicator) becomes an abstention; a verifier-accept stays
  researcher_only  exp34 attempt-1 (retry_count=0): commit iff a real answer at
                   or above the D37 0.65 floor, else abstain
  cooperative      exp40_cooperative_contrast, as run (corroborate verifier,
                   consensus commit, no adjudicator) -- the only live arm

The three adversarial arms are replays/reuse of the frozen exp34 run; only
cooperative was dispatched (docs/EXPERIMENTS_COOPERATIVE_CONTRAST.md). The
primary contrast is no_adjudicator vs cooperative: same researcher, same
retries, neither has an adjudicator, so the one variable is the verifier
stance (refute vs corroborate).

Every arm's per-pair outcome is normalised to the committed/abstained
vocabulary of evaluation/exp36_analysis so its validated balance-aware and
three-outcome readers apply unchanged. Match on binary golds is exact
equality (near_match is a band-shape concern and does not arise on the
yes/no subset that carries the headline).

Usage:
    uv run python evaluation/exp40_analysis.py \
        --db data/odmi.db \
        --out evaluation/results/exp40_analysis.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.exp36_analysis import (  # noqa: E402
    PairRow, binary_headline, three_outcome, norm, is_committed, is_match,
    is_binary_gold,
)
from evaluation.stats import mcnemar_exact  # noqa: E402

FLOOR = 0.65
EXP34 = "exp34_retrieval_strategy_s46"
EXP34_COND = "wide_only"
EXP40 = "exp40_cooperative_contrast"

# Normalised terminal statuses the exp36 readers understand.
_COMMIT = "accepted_by_verifier"     # any committed answer
_ABSTAIN = "abstained_adjudicator"   # any honest abstention
_FAILED = "agent_failure"            # a crash, never an abstention


def _gold(conn, q, cc):
    r = conn.execute(
        "SELECT response, decision, dimension FROM ground_truth "
        "WHERE question_id=? AND country_code=?", (q, cc)
    ).fetchone()
    return r if r else (None, None, None)


def _shape(conn, q):
    r = conn.execute(
        "SELECT answer_shape FROM questions WHERE question_id=?", (q,)
    ).fetchone()
    return r[0] if r else None


def _match_status(committed: bool, answer, gold, shape) -> str:
    if not committed:
        return "abstained"
    if gold is None or norm(gold) in ("", "n/a", "not applicable"):
        return "flag_review" if gold is not None else "no_ground_truth"
    return "match" if norm(answer) == norm(gold) else "differ"


def _pair_row(conn, q, cc, committed, answer, idx, failed: bool = False) -> PairRow:
    """One pair in the exp36 reader vocabulary.

    `failed` must survive the mapping. The reader already separates crashes from
    abstentions (`three_outcome.n_failed`); recoding a crash to an abstention
    here defeated that and reported eight `agent_failure` pairs as decisions to
    decline, which is exactly the Selectivity property the ablation measures.
    """
    gold, decision, dim = _gold(conn, q, cc)
    shape = _shape(conn, q)
    if failed:
        status = _FAILED
    elif committed:
        status = _COMMIT
    else:
        status = _ABSTAIN
    return PairRow(
        row_id=idx,
        question_id=q, country_code=cc, condition_label="x",
        terminal_status=status,
        final_answer=answer if committed else "inconclusive",
        final_confidence=None,
        gold_answer=gold, gold_decision=decision, dimension=dim,
        answer_shape=shape,
        match_status=_match_status(committed, answer, gold, shape),
    )


def attempt1_gap_pairs(conn) -> list[tuple[str, str]]:
    """Pairs in the exp34 arm with no readable attempt-1 researcher row.

    The coordinator used to skip the write when an attempt produced no output,
    so the retry became the first logged attempt. 17 pairs lost their
    `retry_count=0` row this way. The researcher-only arm cannot read an answer
    for them and therefore abstains, but that is a logging gap rather than a
    researcher decision, so report which pairs it affects instead of letting
    them sink silently into the abstention count.
    """
    rows = conn.execute(
        """SELECT question_id, country_code FROM phase2_researcher_runs
           WHERE experiment_id=? AND condition_label=?
           GROUP BY question_id, country_code
           HAVING MIN(retry_count) > 0
           ORDER BY question_id, country_code""",
        (EXP34, EXP34_COND),
    ).fetchall()
    return [(q, cc) for q, cc in rows]


def completed_only(arms: dict[str, list[PairRow]]) -> dict[str, list[PairRow]]:
    """The same arms restricted to pairs that completed in every arm.

    Coverage divides by all pairs, so a crash silently depresses it. Dropping
    the crashed pairs gives the coverage the pipeline actually achieved where it
    ran. The same pairs go from every arm, so the arms stay paired and the
    McNemar contrast remains valid.
    """
    crashed = {
        (r.question_id, r.country_code)
        for rows in arms.values() for r in rows
        if r.terminal_status == _FAILED
    }
    return {
        name: [
            r for r in rows if (r.question_id, r.country_code) not in crashed
        ]
        for name, rows in arms.items()
    }


def _trio_canonical(conn):
    rows = conn.execute(
        """SELECT f.question_id,f.country_code,f.terminal_status,
                  f.final_answer,f.id
           FROM phase2_final f JOIN phase2_researcher_runs r
             ON r.pair_run_id=f.pair_run_id
           WHERE f.experiment_id=? AND r.condition_label=?""",
        (EXP34, EXP34_COND),
    ).fetchall()
    canon = {}
    for q, cc, st, ans, rid in rows:
        k = (q, cc)
        if k not in canon or rid > canon[k][-1]:
            canon[k] = (q, cc, st, ans, rid)
    return list(canon.values())


def build_arms(conn) -> dict[str, list[PairRow]]:
    trio_raw = _trio_canonical(conn)
    committed_trio = {"accepted_by_verifier", "accepted_by_adjudicator"}

    trio, no_adj, res_only = [], [], []
    for i, (q, cc, st, ans, _rid) in enumerate(trio_raw):
        # A crash is a crash in all three replay arms: they share the run, so a
        # pair the pipeline never resolved has no outcome to reinterpret.
        failed = st == _FAILED
        committed = st in committed_trio and norm(ans) != "inconclusive"
        trio.append(_pair_row(conn, q, cc, committed, ans, i, failed))
        # no_adjudicator: only a verifier-accept commits; adjudicated -> abstain
        na_commit = st == "accepted_by_verifier" and norm(ans) != "inconclusive"
        no_adj.append(_pair_row(conn, q, cc, na_commit, ans, i, failed))
        # researcher_only: exp34 attempt-1 answer at/above the floor
        r = conn.execute(
            """SELECT answer, answer_confidence FROM phase2_researcher_runs
               WHERE experiment_id=? AND condition_label=?
               AND question_id=? AND country_code=? AND retry_count=0
               ORDER BY id DESC LIMIT 1""",
            (EXP34, EXP34_COND, q, cc),
        ).fetchone()
        if r and r[0] and norm(r[0]) != "inconclusive" and (r[1] or 0) >= FLOOR:
            res_only.append(_pair_row(conn, q, cc, True, r[0], i, failed))
        else:
            res_only.append(_pair_row(conn, q, cc, False, None, i, failed))

    # cooperative: exp40 finals (canonical latest per pair)
    coop_raw = conn.execute(
        """SELECT question_id,country_code,terminal_status,final_answer,id
           FROM phase2_final WHERE experiment_id=?""", (EXP40,),
    ).fetchall()
    coop_canon = {}
    for q, cc, st, ans, rid in coop_raw:
        k = (q, cc)
        if k not in coop_canon or rid > coop_canon[k][-1]:
            coop_canon[k] = (q, cc, st, ans, rid)
    coop = []
    for i, (q, cc, st, ans, _rid) in enumerate(coop_canon.values()):
        committed = st == "accepted_cooperative" and norm(ans) != "inconclusive"
        coop.append(_pair_row(conn, q, cc, committed, ans, i, st == _FAILED))

    return {"trio": trio, "no_adjudicator": no_adj,
            "researcher_only": res_only, "cooperative": coop}


def paired_mcnemar(a: list[PairRow], b: list[PairRow]) -> dict:
    """Paired McNemar on per-pair committed-correctness (binary golds only),
    a=no_adjudicator vs b=cooperative on the shared pair set."""
    idx_a = {(r.question_id, r.country_code): r for r in a if is_binary_gold(r)}
    idx_b = {(r.question_id, r.country_code): r for r in b if is_binary_gold(r)}
    shared = sorted(set(idx_a) & set(idx_b))

    def correct(r) -> bool:
        return is_committed(r) and is_match(r)

    b_only = c_only = 0  # b_only: a-correct not b; c_only: b-correct not a
    for k in shared:
        ca, cb = correct(idx_a[k]), correct(idx_b[k])
        if ca and not cb:
            b_only += 1
        elif cb and not ca:
            c_only += 1
    p = mcnemar_exact(b_only, c_only)
    return {
        "n_shared_binary": len(shared),
        "a_correct_not_b": b_only, "b_correct_not_a": c_only,
        "mcnemar_p": p,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/odmi.db")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    arms = build_arms(conn)

    result = {"arms": {}, "primary_contrast": {}}
    for name, rows in arms.items():
        result["arms"][name] = {
            "n_pairs": len(rows),
            "three_outcome": three_outcome(rows),
            "balance_aware": binary_headline(rows),
        }

    # Coverage on the pairs that actually completed. The crashed pairs sit in
    # the full-universe denominator above and depress every arm's coverage; the
    # same pairs leave every arm here, so the arms stay paired.
    trimmed = completed_only(arms)
    result["arms_completed_only"] = {
        "description": "coverage denominators excluding pairs that crashed in "
                       "any arm; commit-accuracy is unaffected because a crash "
                       "contributes no commits",
        "excluded_pairs": sorted(
            {(r.question_id, r.country_code) for rows in arms.values()
             for r in rows if r.terminal_status == "agent_failure"}
        ),
        "arms": {
            name: {"n_pairs": len(rows), "three_outcome": three_outcome(rows)}
            for name, rows in trimmed.items()
        },
    }

    gaps = attempt1_gap_pairs(conn)
    result["researcher_only_attempt1_gap"] = {
        "description": "exp34 pairs with no readable retry_count=0 researcher "
                       "row, so the researcher-only arm abstains on them by "
                       "default; a logging gap, not a researcher decision",
        "n_pairs": len(gaps),
        "pairs": sorted(gaps),
    }

    result["primary_contrast"] = {
        "description": "no_adjudicator vs cooperative: one variable (verifier "
                       "stance), neither has an adjudicator",
        "mcnemar_committed_correctness":
            paired_mcnemar(arms["no_adjudicator"], arms["cooperative"]),
    }

    # compact console summary
    print(f"{'arm':16} {'n':>4} {'cov':>5} {'commit-acc':>11} "
          f"{'neg-FPR':>8} {'bal-acc':>8} {'J':>6} {'fail':>5}")
    for name, rows in arms.items():
        t = result["arms"][name]["three_outcome"]
        h = result["arms"][name]["balance_aware"]
        cov = t["coverage"]["rate"]
        acc = t["commit_accuracy"]["rate"]
        fpr = t["negative_golds"]["fp_rate"]["rate"]
        ba = h["balanced_accuracy"]
        j = h["youden_j"]
        print(f"{name:16} {t['n']:>4} "
              f"{(cov or 0):>5.2f} {(acc or 0):>11.2f} {(fpr or 0):>8.2f} "
              f"{(ba if ba is not None else 0):>8.2f} "
              f"{(j if j is not None else 0):>6.2f} {t['n_failed']:>5}")

    ex = result["arms_completed_only"]["excluded_pairs"]
    print(f"\ncoverage excluding {len(ex)} crashed pair(s):")
    for name, block in result["arms_completed_only"]["arms"].items():
        t = block["three_outcome"]
        print(f"  {name:16} n={t['n']:>4} cov={t['coverage']['rate'] or 0:.3f} "
              f"commit-acc={t['commit_accuracy']['rate'] or 0:.3f}")
    print(f"\nresearcher_only attempt-1 logging gap: {len(gaps)} pair(s) "
          f"abstained for want of a readable attempt")

    pc = result["primary_contrast"]["mcnemar_committed_correctness"]
    print(f"\nprimary no_adj vs cooperative: n={pc['n_shared_binary']} "
          f"no_adj-only-correct={pc['a_correct_not_b']} "
          f"coop-only-correct={pc['b_correct_not_a']} "
          f"McNemar p={pc['mcnemar_p']:.3f}")

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
