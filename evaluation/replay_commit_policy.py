"""EXP-11 S0.2: replay the in-loop commit rule under absence-ceiling variants.

The decision: what minimum confidence should an ABSENCE-class answer
(binary 'no', or an ordered shape's bottom band) need to commit in-loop,
above the D37 floor of 0.65, so that unsupported 'no' answers stop
committing without throwing away correct ones?

Grain: (pair, attempt), holding stored verdicts, answers, and
confidences fixed. For each pair we find the first attempt at which the
incumbent in-loop rule (_should_accept_verifier_pass: verdict=pass, not
an abstention, confidence >= 0.65) fires. Then, per candidate ceiling C
in {0.70, 0.75, 0.80}, that commit survives iff the answer is not
absence-class OR its confidence >= C; otherwise it is 'deferred' (in
the live loop it would retry or fall to the Adjudicator).

Honest limitation, by construction: this replay sees single attempts.
It cannot model a retry recovering to a better answer, nor the
Adjudicator. A deferred commit is therefore the conservative worst case
(treated as lost), so the recall cost reported here is an upper bound.

Read-only. Writes evaluation/results/commit_policy_grid.jsonl.

  uv run python evaluation/replay_commit_policy.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from evaluation._replay_common import (
    is_absence_class,
    is_abstention,
    is_correct,
    ro_connect,
)

RESULTS = Path(__file__).resolve().parent / "results"
FLOOR = 0.65
CEILINGS = [0.70, 0.75, 0.80]
COUNTRIES = ["MT", "NO"]


def _incumbent_commits(answer, conf, verdict) -> bool:
    return (
        verdict == "pass"
        and not is_abstention(answer)
        and (conf or 0.0) >= FLOOR
    )


def _load_pairs(conn, country):
    """Return {pair_run_id: [ (retry_count, qid, answer, conf, verdict, gold) ]}
    ordered by retry, for attempts that carry a verifier verdict and gold."""
    sql = """
        SELECT r.pair_run_id, r.retry_count, r.question_id, r.answer,
               r.answer_confidence, v.verdict, gt.response AS gold
        FROM phase2_researcher_runs r
        JOIN phase2_verifier_runs v ON v.researcher_run_id = r.id
        JOIN ground_truth gt
          ON gt.question_id = r.question_id AND gt.country_code = r.country_code
        WHERE r.country_code = ?
          AND r.answer IS NOT NULL
          AND gt.response IS NOT NULL AND TRIM(gt.response) <> ''
        ORDER BY r.pair_run_id, r.retry_count
    """
    pairs = defaultdict(list)
    for row in conn.execute(sql, (country,)):
        pairs[row["pair_run_id"]].append((
            row["retry_count"], row["question_id"], row["answer"],
            row["answer_confidence"], row["verdict"], row["gold"],
        ))
    return pairs


def _analyse_country(conn, country):
    pairs = _load_pairs(conn, country)
    # incumbent in-loop commits
    commits = []  # (qid, answer, conf, correct, absence)
    for attempts in pairs.values():
        for (_rt, qid, answer, conf, verdict, gold) in attempts:
            if _incumbent_commits(answer, conf, verdict):
                commits.append((
                    qid, answer, conf,
                    is_correct(qid, answer, gold),
                    is_absence_class(qid, answer),
                ))
                break  # first committing attempt only

    n_pairs = len(pairs)
    n_commit = len(commits)
    inc_correct = sum(1 for c in commits if c[3])
    inc_wrong = n_commit - inc_correct
    absence_commits = [c for c in commits if c[4]]

    rows = []
    # Incumbent (ceiling == floor, no absence rule)
    rows.append(dict(
        country=country, ceiling=FLOOR, n_pairs=n_pairs,
        committed=n_commit, committed_correct=inc_correct,
        committed_wrong=inc_wrong, deferred=0,
        deferred_correct=0, deferred_wrong=0, deferred_rate=0.0,
    ))
    for C in CEILINGS:
        still_c = still_w = def_c = def_w = 0
        for (qid, answer, conf, correct, absence) in commits:
            survives = (not absence) or (conf or 0.0) >= C
            if survives:
                still_c += int(correct)
                still_w += int(not correct)
            else:
                def_c += int(correct)
                def_w += int(not correct)
        rows.append(dict(
            country=country, ceiling=C, n_pairs=n_pairs,
            committed=still_c + still_w,
            committed_correct=still_c, committed_wrong=still_w,
            deferred=def_c + def_w, deferred_correct=def_c,
            deferred_wrong=def_w,
            deferred_rate=round((def_c + def_w) / n_commit, 4) if n_commit else 0.0,
        ))
    return rows, n_commit, len(absence_commits)


def main():
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "commit_policy_grid.jsonl"
    all_rows = []
    with ro_connect() as conn:
        for country in COUNTRIES:
            rows, n_commit, n_absence = _analyse_country(conn, country)
            all_rows.extend(rows)
            print(f"\n=== {country}: {n_commit} in-loop commits "
                  f"({n_absence} absence-class) ===")
            print(f"  {'ceiling':>7} {'commit':>6} {'corr':>5} {'wrong':>5} "
                  f"{'defer':>5} {'def_c':>5} {'def_w':>5} {'defer_rate':>10}")
            for r in rows:
                tag = " (incumbent)" if r["ceiling"] == FLOOR else ""
                print(f"  {r['ceiling']:>7.2f} {r['committed']:>6} "
                      f"{r['committed_correct']:>5} {r['committed_wrong']:>5} "
                      f"{r['deferred']:>5} {r['deferred_correct']:>5} "
                      f"{r['deferred_wrong']:>5} {r['deferred_rate']:>10.3f}{tag}")

    with out.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")

    # Decision rule: lowest committed-wrong subject to deferred_rate <= 0.05
    # on BOTH countries; ties to 0.75.
    print("\n=== DECISION (lowest committed-wrong; deferred-rate rise <= 5pts both countries; ties->0.75) ===")
    by_ceiling = defaultdict(dict)
    for r in all_rows:
        by_ceiling[r["ceiling"]][r["country"]] = r
    feasible = []
    for C in CEILINGS:
        ok = all(by_ceiling[C][cc]["deferred_rate"] <= 0.05 for cc in COUNTRIES)
        tot_wrong = sum(by_ceiling[C][cc]["committed_wrong"] for cc in COUNTRIES)
        tot_def_c = sum(by_ceiling[C][cc]["deferred_correct"] for cc in COUNTRIES)
        tot_def_w = sum(by_ceiling[C][cc]["deferred_wrong"] for cc in COUNTRIES)
        print(f"  ceiling {C:.2f}: committed_wrong(MT+NO)={tot_wrong} "
              f"caught_wrong={tot_def_w} lost_correct={tot_def_c} "
              f"feasible(<=5pts both)={ok}")
        if ok:
            feasible.append((tot_wrong, abs(C - 0.75), C))
    inc_wrong = sum(by_ceiling[FLOOR][cc]["committed_wrong"] for cc in COUNTRIES)
    print(f"  incumbent (0.65): committed_wrong(MT+NO)={inc_wrong}")
    if feasible:
        feasible.sort()
        choice = feasible[0][2]
        print(f"  -> ABSENCE_CEILING = {choice:.2f}")
    else:
        print(f"  -> no ceiling clears the 5pt bar; ABSENCE_CEILING stays {FLOOR:.2f} (no change)")


if __name__ == "__main__":
    main()
