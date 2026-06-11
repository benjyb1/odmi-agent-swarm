"""EXP-12c: shape-conditional evidence recipe (POST-HOC, in-sample).

The EXP-12b direction split (probes help absence claims, search hurts
presence claims) suggests routing evidence by answer shape:
  absence answer (no / none / bottom band) -> E1 (adversarial + probes)
  presence answer (yes / non-bottom)        -> E5 (no independent search)

This is NOT a confirmatory experiment: the routing rule was derived from
the same 150 MT+NO candidates it is scored on, so the estimate is
optimistic and in-sample by construction (R1 cannot be met). It needs no
new calls: EC's verdict per candidate IS the already-paid E1 or E5
verdict (temperature 0, same prompt, same evidence block), so this is an
exact recombination, not an approximation.

Purpose: a screen. If the in-sample ceiling does not clearly beat E0
under the false-rejection guard, the lead dies and no held-out dispatch
is justified. If it does, a held-out country dispatch becomes the
(future, separately pre-registered) confirmatory test.

  uv run python evaluation/exp12c_conditional.py
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import stats

RESULTS = Path(__file__).resolve().parent / "results"
STAGE1 = RESULTS / "verifier_redesign_verifier_tristate_v1.jsonl"
LADDER = RESULTS / "exp12b_evidence_ladder.jsonl"


def _meta():
    m = {}
    for line in STAGE1.open():
        r = json.loads(line)
        if r["kind"] == "freeze":
            m[r["cand_id"]] = dict(absence=r["absence"], gold=r["gold_label"])
    return m


def _verdicts():
    v = {}
    for line in LADDER.open():
        r = json.loads(line)
        if "verdict" in r:
            v.setdefault(r["cand_id"], {})[r["arm"]] = r["verdict"]
    return v


def _metrics(verdict_of, meta, predicate=lambda m: True):
    tp = fp = tn = fn = 0
    for cid, m in meta.items():
        if not predicate(m):
            continue
        v = verdict_of(cid, m)
        if v is None:
            continue
        gold = m["gold"]
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
    lo, hi = stats.wilson_interval(fp, neg) if neg else (float("nan"),) * 2
    return dict(n=tp + fp + tn + fn, j=j, sens=sens, spec=spec, frr=frr,
                frr_lo=lo, frr_hi=hi)


def main():
    meta, vd = _meta(), _verdicts()

    def fixed(arm):
        return lambda cid, m: vd.get(cid, {}).get(arm)

    def conditional(cid, m):
        return vd.get(cid, {}).get("E1" if m["absence"] else "E5")

    print("EXP-12c shape-conditional recipe (POST-HOC, IN-SAMPLE; screen only)")
    print("  routing: absence -> E1 (adversarial+probes), presence -> E5 (no search)\n")
    print(f"  {'recipe':22} {'J':>6} {'sens':>5} {'spec':>5} {'FRR [Wilson95]':>18}")
    for label, vof in (("E0 (status quo)", fixed("E0")),
                       ("E5 (no search)", fixed("E5")),
                       ("E1 (+probes)", fixed("E1")),
                       ("EC (conditional)", conditional)):
        m = _metrics(vof, meta)
        print(f"  {label:22} {m['j']:>6.2f} {m['sens']:>5.2f} {m['spec']:>5.2f} "
              f"{m['frr']:>6.2f}[{m['frr_lo']:.2f},{m['frr_hi']:.2f}]")

    # paired McNemar EC vs E0 on verdict-correctness
    def correct(vof):
        d = {}
        for cid, m in meta.items():
            v = vof(cid, m)
            if v is None:
                continue
            want = "fail" if m["gold"] == "should_fail" else "pass"
            d[cid] = (v == want)
        return d
    ce, c0 = correct(conditional), correct(fixed("E0"))
    sh = set(ce) & set(c0)
    b = sum(1 for k in sh if c0[k] and not ce[k])
    c = sum(1 for k in sh if ce[k] and not c0[k])
    print(f"\n  EC vs E0 (exact McNemar on verdict-correctness): "
          f"b={b} c={c} p={stats.mcnemar_exact(b, c):.4f}")

    e0 = _metrics(fixed("E0"), meta)
    ec = _metrics(conditional, meta)
    print("\n  Decision (screen): a held-out dispatch is justified only if EC's "
          "in-sample J\n  clearly exceeds E0 AND FRR <= E0's.")
    better = ec["j"] > e0["j"] + 0.05
    guard = ec["frr"] <= e0["frr"] + 1e-9
    print(f"    EC J={ec['j']:.2f} vs E0 J={e0['j']:.2f} (gap {ec['j']-e0['j']:+.2f}); "
          f"EC FRR={ec['frr']:.2f} vs E0 {e0['frr']:.2f}")
    if better and guard:
        print("    -> ceiling clears the bar; a held-out confirmatory dispatch is "
              "worth pre-registering.")
    else:
        reason = []
        if not better:
            reason.append("J gain under 0.05 even in-sample")
        if not guard:
            reason.append("FRR exceeds E0's")
        print(f"    -> lead does NOT clear the bar ({'; '.join(reason)}); close it, "
              "no dispatch.")


if __name__ == "__main__":
    main()
