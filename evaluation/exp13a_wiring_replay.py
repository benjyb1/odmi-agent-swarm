"""EXP-13a: verdict-wiring replay (H3). Free, read-only.

Replays the stored MT and NO trails (every researcher attempt with its
verifier verdict) under five wirings of the Verifier's verdict, and
classifies each pair's terminal outcome. Every wiring commits earlier
than or equal to production, so the stored attempts cover every
simulated path (no missing-data extrapolation). Method per the D44
receipt; pre-registration docs/EXPERIMENTS_VERIFIER_EVIDENCE.md
section 4.

Wirings (commit rule at each attempt, walked in retry order):
  W-gate      pass AND conf >= 0.65                      (production)
  W-veto-hard (pass OR substring != fail) AND conf >= 0.65
  W-adv2      conf >= 0.75 if fail else 0.65
  W-adv1      conf >= 0.65 (verdict advisory only)
  W-none      conf >= 0.65, no verifier, no adjudication (REFERENCE ONLY)

Abstention answers (`inconclusive`) never commit under any wiring.
Pairs that commit under no wiring fall back to their ACTUAL stored
final outcome (the adjudication path), except W-none, which falls back
to abstained (a verifier-less pipeline has no adjudicator material).

Fidelity gate: the simulated W-gate in-loop commits must reproduce the
actual `accepted_by_verifier` finals (pair set and answers) on at least
95% of pairs before any variant number is read.

  uv run python evaluation/exp13a_wiring_replay.py

Writes evaluation/results/exp13a_wiring_replay.jsonl.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from evaluation import stats
from evaluation._replay_common import is_correct, ro_connect

RESULTS = Path(__file__).resolve().parent / "results"
FLOOR = 0.65
SHADE = 0.10
COUNTRIES = ("MT", "NO")
WIRINGS = ("W-gate", "W-veto-hard", "W-adv2", "W-adv1", "W-none")


def _is_abstention(answer) -> bool:
    return bool(answer) and answer.strip().lower() == "inconclusive"


def _commits(wiring, answer, conf, v) -> bool:
    """Does this attempt commit under the wiring? `v` is the verifier row
    dict or None (verifier did not run / failed on this attempt)."""
    if not answer or _is_abstention(answer):
        return False
    conf = conf or 0.0
    if wiring == "W-gate":
        return v is not None and v["verdict"] == "pass" and conf >= FLOOR
    if wiring == "W-veto-hard":
        if v is None:
            return False
        blocked = v["verdict"] == "fail" and v["substring_check_result"] == "fail"
        return (not blocked) and conf >= FLOOR
    if wiring == "W-adv2":
        if v is None:
            return False
        bar = FLOOR + SHADE if v["verdict"] == "fail" else FLOOR
        return conf >= bar
    if wiring in ("W-adv1", "W-none"):
        return conf >= FLOOR
    raise ValueError(wiring)


def _outcome(answer, gold, qid) -> str:
    if not answer or not answer.strip() or _is_abstention(answer):
        return "abstain"
    return "match" if is_correct(qid, answer, gold) else "wrong"


def _load_trails():
    """pair_run_id -> dict(final=..., gold=..., qid=..., attempts=[(answer,
    conf, verifier_row_or_None), ...] in retry order)."""
    pairs = {}
    with ro_connect() as conn:
        finals = conn.execute(
            "SELECT f.*, gt.response AS gold FROM phase2_final f "
            "JOIN ground_truth gt ON gt.question_id=f.question_id "
            " AND gt.country_code=f.country_code "
            "WHERE f.country_code IN (?,?) AND gt.response IS NOT NULL "
            " AND TRIM(gt.response)<>''", COUNTRIES).fetchall()
        for f in finals:
            pairs[f["pair_run_id"]] = dict(
                final=dict(f), gold=f["gold"], qid=f["question_id"],
                country=f["country_code"], attempts=[])
        # researcher attempts: latest row per (pair, retry_count)
        rrows = conn.execute(
            "SELECT * FROM phase2_researcher_runs WHERE country_code IN (?,?) "
            "ORDER BY pair_run_id, retry_count, id", COUNTRIES).fetchall()
        latest = {}
        for r in rrows:
            if r["pair_run_id"] in pairs:
                latest[(r["pair_run_id"], r["retry_count"])] = dict(r)
        # verifier rows: latest per researcher_run_id
        vrows = conn.execute(
            "SELECT * FROM phase2_verifier_runs WHERE country_code IN (?,?) "
            "ORDER BY id", COUNTRIES).fetchall()
        vmap = {}
        for v in vrows:
            vmap[v["researcher_run_id"]] = dict(v)
    for (pid, rc), r in sorted(latest.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        pairs[pid]["attempts"].append(
            (r["answer"], r["answer_confidence"], vmap.get(r["id"])))
    return pairs


def simulate(pair, wiring):
    """Return (outcome, committed_in_loop, answer)."""
    for answer, conf, v in pair["attempts"]:
        if _commits(wiring, answer, conf, v):
            return _outcome(answer, pair["gold"], pair["qid"]), True, answer
    if wiring == "W-none":
        return "abstain", False, None
    actual = pair["final"]["final_answer"]
    return _outcome(actual, pair["gold"], pair["qid"]), False, actual


def main():
    pairs = _load_trails()
    print(f"Loaded {len(pairs)} golded pairs "
          f"({sum(1 for p in pairs.values() if p['country']=='MT')} MT, "
          f"{sum(1 for p in pairs.values() if p['country']=='NO')} NO)")

    # fidelity gate: simulated W-gate vs actual finals
    agree, mismatches = 0, []
    for pid, p in pairs.items():
        sim_out, sim_committed, sim_ans = simulate(p, "W-gate")
        actual_committed = p["final"]["terminal_status"] == "accepted_by_verifier"
        ans_match = (not sim_committed and not actual_committed) or (
            sim_committed and actual_committed
            and (sim_ans or "").strip().lower()
            == (p["final"]["final_answer"] or "").strip().lower())
        if sim_committed == actual_committed and ans_match:
            agree += 1
        else:
            mismatches.append((pid, p, sim_committed, sim_ans, actual_committed))
    fid = agree / len(pairs)
    print(f"\nFidelity: simulated W-gate reproduces actual on {agree}/{len(pairs)} "
          f"= {fid:.3f} (gate: >= 0.95)")
    for pid, p, sc, sa, ac in mismatches[:8]:
        print(f"  mismatch {p['country']}:{p['qid']} sim_commit={sc} ({sa!r}) "
              f"actual={p['final']['terminal_status']} "
              f"({p['final']['final_answer']!r})")
    if fid < 0.95:
        print("\nFIDELITY GATE FAILED: variant numbers below are NOT to be "
              "trusted; audit the mismatches first (pre-registered rule).")

    # the wirings
    results = {w: {} for w in WIRINGS}
    for pid, p in pairs.items():
        for w in WIRINGS:
            results[w][pid] = simulate(p, w)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "exp13a_wiring_replay.jsonl"
    with out.open("w") as fh:
        for pid, p in pairs.items():
            fh.write(json.dumps(dict(
                pair=pid, country=p["country"], qid=p["qid"], gold=p["gold"],
                actual_status=p["final"]["terminal_status"],
                actual_answer=p["final"]["final_answer"],
                **{w: dict(zip(("outcome", "in_loop", "answer"),
                               results[w][pid])) for w in WIRINGS},
            )) + "\n")

    print(f"\n{'wiring':12} {'match':>6} {'abstain':>8} {'wrong':>6} "
          f"{'in-loop commits':>16}")
    for w in WIRINGS:
        outs = [results[w][pid][0] for pid in pairs]
        commits = sum(1 for pid in pairs if results[w][pid][1])
        note = "  (reference, not a candidate)" if w == "W-none" else ""
        print(f"{w:12} {outs.count('match'):>6} {outs.count('abstain'):>8} "
              f"{outs.count('wrong'):>6} {commits:>16}{note}")

    # paired tests vs production
    print("\nPaired vs W-gate (exact McNemar):")
    base = results["W-gate"]
    for w in WIRINGS[1:]:
        for event, label in (("match", "match-vs-not"), ("wrong", "wrong-vs-not")):
            b = sum(1 for pid in pairs
                    if base[pid][0] == event and results[w][pid][0] != event)
            c = sum(1 for pid in pairs
                    if results[w][pid][0] == event and base[pid][0] != event)
            p_ = stats.mcnemar_exact(b, c)
            print(f"  {w:12} {label:13} b={b:<3} c={c:<3} p={p_:.4f}")

    # lexicographic decision (pre-registered)
    print("\nDecision rule: committed-wrong <= production, then max match, "
          "then min abstention (W-none excluded):")
    gw = [results["W-gate"][pid][0] for pid in pairs].count("wrong")
    cands = []
    for w in ("W-veto-hard", "W-adv2", "W-adv1"):
        outs = [results[w][pid][0] for pid in pairs]
        if outs.count("wrong") <= gw:
            cands.append((outs.count("wrong"), -outs.count("match"),
                          outs.count("abstain"), w))
    if cands:
        cands.sort()
        print(f"  provisional winner: {cands[0][3]}")
    else:
        print("  no variant holds committed-wrong at production's level; "
              "W-gate stands (null)")


if __name__ == "__main__":
    main()
