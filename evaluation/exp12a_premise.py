"""EXP-12a: premise diagnostic (H1). Free, read-only.

Did the Verifier's evidence cause the production-vs-frozen discrimination
gap? Matched pairs: for each stage 1 dev candidate, the stored PRODUCTION
disprove verdict on the SAME researcher run (same answer, quote,
confidences, snippets, prompt version, model family) is compared against
the stage 1 FROZEN-evidence arm A verdict. Item selection cancels out by
construction; the residual differences are the independent-search evidence
and the run context.

One known asymmetry, controlled by restriction: production applies the
deterministic substring hard-gate override (a failed grounding check forces
verdict=fail, agents/verifier.py); the stage 1 harness showed the substring
result in the prompt but did not apply the override. All headline numbers
are therefore ALSO reported restricted to substring-pass items, where no
override can fire on either side.

  uv run python evaluation/exp12a_premise.py

Writes evaluation/results/exp12a_premise.jsonl.
Pre-registration: docs/EXPERIMENTS_VERIFIER_EVIDENCE.md section 2.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import stats
from evaluation._replay_common import parse_independent_evidence, ro_connect
from evaluation.verifier_redesign import build_candidates

RESULTS = Path(__file__).resolve().parent / "results"
STAGE1 = RESULTS / "verifier_redesign_verifier_tristate_v1.jsonl"


def _load_stage1():
    """cand_id -> (gold_label, researcher_answer, substring_v1, frozen arm-A
    verdict, n adversarial snippets)."""
    freezes, verdicts = {}, {}
    for line in STAGE1.open():
        rec = json.loads(line)
        if rec["kind"] == "freeze":
            freezes[rec["cand_id"]] = rec
        elif rec["kind"] == "verdict" and rec["arm"] == "A" and "output" in rec:
            verdicts[rec["cand_id"]] = rec["output"]
    out = {}
    for cid, fr in freezes.items():
        if cid not in verdicts:
            continue
        out[cid] = dict(
            gold_label=fr["gold_label"],
            researcher_answer=fr["researcher_answer"],
            answer_shape=fr["answer_shape"],
            substring_v1=fr["freeze"]["substring_v1"],
            frozen_verdict=verdicts[cid]["verdict"],
            frozen_n_adv=len(fr["freeze"]["adversarial_snippets"]),
        )
    return out


def _production_rows(run_ids):
    """researcher_run_id -> latest production disprove verifier row."""
    rows = {}
    with ro_connect() as conn:
        q = ("SELECT * FROM phase2_verifier_runs WHERE strategy_label="
             "'verifier-disprove' AND researcher_run_id IN (%s) ORDER BY id"
             % ",".join("?" * len(run_ids)))
        for r in conn.execute(q, list(run_ids)):
            rows[r["researcher_run_id"]] = dict(r)  # later id wins
    return rows


def _correct(verdict: str, gold_label: str) -> bool:
    want = "fail" if gold_label == "should_fail" else "pass"
    return verdict == want


def _block(records, label):
    n = len(records)
    if n == 0:
        print(f"\n--- {label}: n=0 ---")
        return
    prod_ok = sum(r["prod_correct"] for r in records)
    froz_ok = sum(r["froz_correct"] for r in records)
    b = sum(1 for r in records if r["prod_correct"] and not r["froz_correct"])
    c = sum(1 for r in records if r["froz_correct"] and not r["prod_correct"])
    p = stats.mcnemar_exact(b, c)

    def _rates(key):
        corr = [r for r in records if r["gold_label"] == "should_pass"]
        wrong = [r for r in records if r["gold_label"] == "should_fail"]
        pc = sum(1 for r in corr if r[key] == "pass") / len(corr) if corr else float("nan")
        pw = sum(1 for r in wrong if r[key] == "pass") / len(wrong) if wrong else float("nan")
        # J with fail-as-positive: sens = P(fail|wrong), spec = P(pass|correct)
        sens = 1 - pw if wrong else float("nan")
        spec = pc if corr else float("nan")
        return pc, pw, sens + spec - 1

    ppc, ppw, pj = _rates("prod_verdict")
    fpc, fpw, fj = _rates("froz_verdict")

    def _direction(key):
        yes = [r for r in records if r["researcher_answer"].strip().lower() == "yes"]
        no = [r for r in records if r["researcher_answer"].strip().lower() == "no"]
        py = sum(1 for r in yes if r[key] == "pass") / len(yes) if yes else float("nan")
        pn = sum(1 for r in no if r[key] == "pass") / len(no) if no else float("nan")
        return py, pn

    pdy, pdn = _direction("prod_verdict")
    fdy, fdn = _direction("froz_verdict")

    print(f"\n--- {label}: n={n} "
          f"({sum(1 for r in records if r['gold_label']=='should_fail')} should_fail) ---")
    print(f"  verdict-correct: production {prod_ok}/{n} ({prod_ok/n:.2f})  "
          f"frozen {froz_ok}/{n} ({froz_ok/n:.2f})")
    print(f"  McNemar discordants b(prod-only-right)={b} c(frozen-only-right)={c}  "
          f"exact p={p:.4f}")
    print(f"  production: P(pass|correct)={ppc:.2f} P(pass|wrong)={ppw:.2f}  J={pj:.2f}")
    print(f"  frozen:     P(pass|correct)={fpc:.2f} P(pass|wrong)={fpw:.2f}  J={fj:.2f}")
    print(f"  direction gap (binary yes/no answers): production pass|yes={pdy:.2f} "
          f"pass|no={pdn:.2f}  frozen pass|yes={fdy:.2f} pass|no={fdn:.2f}")


def main():
    stage1 = _load_stage1()
    cands = {c.cand_id: c for c in build_candidates()}

    run_ids = {c.row["id"] for c in cands.values()}
    prod = _production_rows(run_ids)

    records = []
    for cid, s1 in stage1.items():
        cand = cands.get(cid)
        if cand is None:
            continue
        prow = prod.get(cand.row["id"])
        if prow is None:
            continue
        prod_n_ev = len(parse_independent_evidence(prow["independent_evidence"]))
        rec = dict(
            cand_id=cid,
            country=cand.country_code,
            gold_label=s1["gold_label"],
            researcher_answer=s1["researcher_answer"],
            substring_v1=s1["substring_v1"],
            prod_substring=prow["substring_check_result"],
            prod_verdict=prow["verdict"],
            froz_verdict=s1["frozen_verdict"],
            prod_correct=_correct(prow["verdict"], s1["gold_label"]),
            froz_correct=_correct(s1["frozen_verdict"], s1["gold_label"]),
            prod_n_evidence=prod_n_ev,
            frozen_n_adv=s1["frozen_n_adv"],
            prod_rejection=(prow["rejection_reason"] or "")[:200],
        )
        records.append(rec)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "exp12a_premise.jsonl"
    with out.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Matched {len(records)} of {len(stage1)} stage 1 candidates -> {out}")

    _block(records, "ALL matched")
    for cc in ("MT", "NO"):
        _block([r for r in records if r["country"] == cc], f"country {cc}")
    # Control for the hard-gate asymmetry: both substring checks passed.
    clean = [r for r in records
             if r["substring_v1"] == "pass" and r["prod_substring"] == "pass"]
    _block(clean, "RESTRICTED: substring pass on both sides (no override possible)")

    # Mechanism audit: discordant pairs, deterministic evidence diff.
    disc = [r for r in records if r["prod_correct"] != r["froz_correct"]]
    print(f"\n--- mechanism audit: {len(disc)} discordant pairs ---")
    froz_right = [r for r in disc if r["froz_correct"]]
    prod_right = [r for r in disc if r["prod_correct"]]
    for label, group in (("frozen-right (production wrong)", froz_right),
                         ("production-right (frozen wrong)", prod_right)):
        if not group:
            continue
        empty_prod = sum(1 for r in group if r["prod_n_evidence"] == 0)
        sub_fail = sum(1 for r in group if r["prod_substring"] == "fail")
        print(f"  {label}: n={len(group)}, production search EMPTY on {empty_prod}, "
              f"production substring-fail on {sub_fail}")
        for r in group[:6]:
            print(f"    {r['cand_id']:9} gold={r['gold_label']:11} "
                  f"prod={r['prod_verdict']}/ev{r['prod_n_evidence']}/sub:{r['prod_substring']} "
                  f"froz={r['froz_verdict']}/ev{r['frozen_n_adv']} "
                  f"| {r['prod_rejection'][:70]}")


if __name__ == "__main__":
    main()
