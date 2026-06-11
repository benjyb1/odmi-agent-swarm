"""EXP-12b: the evidence ladder (H2). Phase 1, no new searches.

Holds the prompt fixed at verifier-disprove v3 and substring v2, and
varies ONLY the evidence block fed to the verifier, over the same 150
stage 1 dev candidates. Phase 1 arms reuse the stage 1 frozen searches
verbatim (zero new searches; ~150 disprove calls per arm):

  E5  researcher snippets only, no independent search block (floor)
  E0  E5 + frozen adversarial search results (the stage 1 J=0.41 anchor)
  E1  E0 + frozen confirmation-probe results

Endpoint: Youden's J (fail = positive), false-rejection rate (FRR) as the
guard, Holm McNemar on the ladder (E5 vs E0, E0 vs E1).

Reads the freezes from the stage 1 JSONL; writes verdicts to
evaluation/results/exp12b_evidence_ladder.jsonl. Resumable.
Pre-registration: docs/EXPERIMENTS_VERIFIER_EVIDENCE.md section 3.

  uv run python evaluation/exp12b_evidence_ladder.py --workers 6
  uv run python evaluation/exp12b_evidence_ladder.py --analyse-only PATH
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import ValidationError

from agents.models import VerifierOutput
from agents.prompts import verifier as vp
from agents.tools import db as db_helpers
from agents.tools.llm import StructuredOutputError, call_for_structured

from evaluation import stats
from evaluation.verifier_redesign import (
    _researcher_output,
    build_candidates,
)

RESULTS = Path(__file__).resolve().parent / "results"
STAGE1 = RESULTS / "verifier_redesign_verifier_tristate_v1.jsonl"
OUT = RESULTS / "exp12b_evidence_ladder.jsonl"
DISPROVE = "verifier-disprove"

# (arm, include_adversarial, include_probes)
ARMS = [
    ("E5", False, False),
    ("E0", True, False),
    ("E1", True, True),
]


def _snip_texts(snips):
    return [f"{s.get('title','')} — {s['snippet'][:200]}" for s in snips]


def _user_message(cand, ro, freeze, include_adv, include_probes):
    queries, snippets = [], []
    if include_adv:
        queries += freeze["adversarial_queries"]
        snippets += _snip_texts(freeze["adversarial_snippets"])
    if include_probes:
        queries += freeze["probe_queries"]
        snippets += _snip_texts(freeze["probe_snippets"])
    return vp.build_user_message(
        question_text=cand.question_text, country_name=cand.country_name,
        country_code=cand.country_code, researcher_output=ro,
        substring_result=freeze["substring_v2"], substring_notes=None,
        independent_queries=queries, independent_snippets=snippets,
        strategy=DISPROVE, answer_shape=cand.answer_shape,
        allowed_answers=cand.allowed_answers,
    )


def _run_arm(cand, ro, freeze, arm, prompt_id):
    arm_key, inc_adv, inc_probes = arm
    spec = vp.STRATEGIES[DISPROVE]
    msg = _user_message(cand, ro, freeze, inc_adv, inc_probes)
    try:
        out, usage = call_for_structured(
            system=spec.system, user_message=msg, output_schema=VerifierOutput,
            max_tokens=1500, condition_label=f"exp12b_{arm_key}",
            prompt_version_id=prompt_id,
            usage_context=f"exp12b_{arm_key}:{cand.cand_id}",
        )
    except (StructuredOutputError, ValidationError) as exc:
        return dict(cand_id=cand.cand_id, arm=arm_key, failed=str(exc)[:160])
    return dict(cand_id=cand.cand_id, arm=arm_key,
                verdict=out.verdict, output=out.model_dump(mode="json"))


def _load_freezes():
    fr = {}
    for line in STAGE1.open():
        rec = json.loads(line)
        if rec["kind"] == "freeze":
            fr[rec["cand_id"]] = rec
    return fr


def run(workers):
    RESULTS.mkdir(exist_ok=True)
    freezes = _load_freezes()
    cands = {c.cand_id: c for c in build_candidates()}
    prompt_id = db_helpers.ensure_prompt_version(
        vp.STRATEGIES[DISPROVE].name, vp.STRATEGIES[DISPROVE].version,
        vp.STRATEGIES[DISPROVE].system, vp.STRATEGIES[DISPROVE].description)

    done = set()
    if OUT.exists():
        for line in OUT.open():
            r = json.loads(line)
            done.add((r["cand_id"], r["arm"]))

    work = []
    for cid, fr in freezes.items():
        cand = cands.get(cid)
        if cand is None:
            continue
        ro = _researcher_output(cand)
        if ro is None:
            continue
        for arm in ARMS:
            if (cid, arm[0]) not in done:
                work.append((cand, ro, fr["freeze"], arm))

    print(f"{len(freezes)} candidates, {len(ARMS)} arms, {len(work)} calls pending "
          f"({len(done)} done), workers={workers}")
    f = OUT.open("a")
    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_arm, c, ro, fz, arm, prompt_id): (c.cand_id, arm[0])
                for (c, ro, fz, arm) in work}
        for fut in as_completed(futs):
            n += 1
            try:
                rec = fut.result()
            except Exception as exc:
                cid, ak = futs[fut]
                print(f"  [{n}/{len(work)}] {cid} {ak} ERROR {str(exc)[:60]}")
                continue
            f.write(json.dumps(rec) + "\n"); f.flush()
            if n % 25 == 0:
                print(f"  [{n}/{len(work)}] {rec['cand_id']} {rec['arm']} "
                      f"-> {rec.get('verdict', rec.get('failed','?'))}")
    f.close()
    print(f"Wrote {OUT}")


def analyse():
    freezes = _load_freezes()
    meta = {cid: fr for cid, fr in freezes.items()}
    verdicts = {}  # cid -> arm -> verdict
    for line in OUT.open():
        r = json.loads(line)
        if "verdict" in r:
            verdicts.setdefault(r["cand_id"], {})[r["arm"]] = r["verdict"]

    def metrics(arm, predicate=lambda m: True):
        tp = fp = tn = fn = 0
        passes = fails = 0
        for cid, arms in verdicts.items():
            if arm not in arms:
                continue
            m = meta[cid]
            if not predicate(m):
                continue
            v = arms[arm]
            gold = m["gold_label"]
            if v == "fail":
                fails += 1
            else:
                passes += 1
            if gold == "should_fail" and v == "fail":
                tp += 1
            elif gold == "should_pass" and v == "fail":
                fp += 1
            elif gold == "should_fail" and v == "pass":
                fn += 1
            else:
                tn += 1
        pos, neg = tp + fn, fp + tn
        sens = tp / pos if pos else float("nan")
        spec = tn / neg if neg else float("nan")
        frr = fp / neg if neg else float("nan")
        j = sens + spec - 1 if pos and neg else float("nan")
        cl, ch = stats.wilson_interval(fp, neg) if neg else (float("nan"),) * 2
        return dict(n=tp+fp+tn+fn, tp=tp, fp=fp, tn=tn, fn=fn, sens=sens,
                    spec=spec, frr=frr, frr_lo=cl, frr_hi=ch, j=j,
                    passes=passes, fails=fails, pos=pos, neg=neg)

    print(f"\nEXP-12b evidence ladder ({len(verdicts)} candidates, disprove + substring v2)")
    print(f"{'arm':4} {'n':>4} {'J':>6} {'sens':>5} {'spec':>5} "
          f"{'FRR [Wilson95]':>18} {'pass/fail':>10}")
    for arm, _, _ in ARMS:
        m = metrics(arm)
        print(f"{arm:4} {m['n']:>4} {m['j']:>6.2f} {m['sens']:>5.2f} {m['spec']:>5.2f} "
              f"{m['frr']:>6.2f}[{m['frr_lo']:.2f},{m['frr_hi']:.2f}]   "
              f"{m['passes']}/{m['fails']}")

    print("\nby direction (J):")
    for label, pred in (("no-claims", lambda m: m["absence"]),
                        ("yes-claims", lambda m: not m["absence"])):
        row = "  " + label.ljust(11)
        for arm, _, _ in ARMS:
            row += f" {arm}={metrics(arm, pred)['j']:.2f}"
        print(row)

    print("\nLadder (exact McNemar on verdict-correctness, Holm over 2):")
    def correct(arm):
        d = {}
        for cid, arms in verdicts.items():
            if arm not in arms:
                continue
            want = "fail" if meta[cid]["gold_label"] == "should_fail" else "pass"
            d[cid] = (arms[arm] == want)
        return d
    pvals = []
    for label, x, y in (("E5 vs E0", "E5", "E0"), ("E0 vs E1", "E0", "E1")):
        cx, cy = correct(x), correct(y)
        sh = set(cx) & set(cy)
        b = sum(1 for k in sh if cx[k] and not cy[k])
        c = sum(1 for k in sh if cy[k] and not cx[k])
        pvals.append((label, b, c, stats.mcnemar_exact(b, c)))
    order = sorted(range(len(pvals)), key=lambda i: pvals[i][3])
    holm = [0.0] * len(pvals)
    for rank, i in enumerate(order):
        holm[i] = min(1.0, pvals[i][3] * (len(pvals) - rank))
    for (label, b, c, p), h in zip(pvals, holm):
        better = "2nd better" if c > b else ("1st better" if b > c else "tie")
        print(f"  {label:10} b={b} c={c} p={p:.4f} Holm={h:.4f} ({better})")

    # champion: highest J s.t. FRR not worse than E0
    e0 = metrics("E0")
    best = None
    for arm, _, _ in ARMS:
        m = metrics(arm)
        if m["frr"] <= e0["frr"] + 1e-9 and (best is None or m["j"] > best[1]):
            best = (arm, m["j"])
    print(f"\nChampion (max J with FRR <= E0's {e0['frr']:.2f}): "
          f"{best[0] if best else 'none'} (J={best[1]:.2f})" if best else "none")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--analyse-only", action="store_true")
    args = ap.parse_args()
    if args.analyse_only:
        analyse()
        return
    run(args.workers)
    analyse()


if __name__ == "__main__":
    main()
