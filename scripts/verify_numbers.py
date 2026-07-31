"""Check the dissertation's numeric claims for arithmetic and source agreement.

Benjy's rule for this pass: a number is a finding only when it contradicts the
source, or contradicts itself elsewhere in the document. Rounding and
simplification are his editorial choice, so "you should state the base" is never
reported.

Three checks, in descending order of how much they can be trusted:

1. ARITHMETIC. Sentences that state a percentage and its fraction ("87.0% of
   295/339", "339 of 539") are self-checking. Either the division agrees with
   the stated percentage or it does not. No ledger, no judgement, no false
   positives. This is the check that earns its keep.

2. LEDGER. Whether a value appears at all in the canonical analysis packs. Only
   exact and rounding-equal matches count. Nearest-value matching was tried and
   removed: with ~1,200 ledger values every number finds a spurious neighbour,
   which produces confident nonsense.

3. RESIDUE. Numbers that are neither self-checking nor present in the ledger.
   These are listed for a human or an agent to source. Being on this list is not
   an accusation, it means the script could not confirm it either way.

Usage:
    python3 scripts/verify_numbers.py --qa build/qa/report.json --out build/qa
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict

LEDGER_SOURCES = [
    "evaluation/results/exp36_headline.json",
    "evaluation/results/confidence_gates_summary.json",
    "evaluation/results/exp36_fp_audit.json",
    "evaluation/results/exp41_stability.json",
]


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out[prefix] = float(obj)
    return out


def build_ledger(root="."):
    ledger = defaultdict(list)
    for rel in LEDGER_SOURCES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for k, v in flatten(data).items():
            ledger[round(v, 10)].append(f"{os.path.basename(rel)}::{k}")
    return ledger


# --------------------------------------------------------------------------
# 1. arithmetic
# --------------------------------------------------------------------------

FRACTION_PATTERNS = [
    re.compile(r"(?<![\d.])(\d[\d,]*)\s*/\s*(\d[\d,]*)(?![\d.])"),
    re.compile(r"(?<![\d.])(\d[\d,]*)\s+(?:of|out of)\s+(\d[\d,]*)(?![\d.])"),
]
ADJACENCY = 45  # characters between a percentage and the fraction that explains it

PCT_PATTERN = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|per cent|percent)")


def _f(s):
    return float(s.replace(",", ""))


# Words that mark a new quantity rather than a restatement of the same one.
SEPARATORS = re.compile(
    r"[.,;]|\b(?:and|against|versus|vs|while|whereas|but|so|then|plus|of which"
    r"|compared|drops?|falls?|rises?|climbs?)\b", re.I)


def _same_quantity(sent, ppos, plen, fraction):
    """True when the gap between a percentage and a fraction holds nothing that
    would introduce a different statistic."""
    _num, _den, ftxt, fpos = fraction
    lo, hi = (ppos + plen, fpos) if fpos > ppos else (fpos + len(ftxt), ppos)
    return not SEPARATORS.search(sent[lo:hi])


def check_arithmetic(claims):
    """Percentages stated alongside their fraction must agree with the division."""
    seen, out = set(), []
    for c in claims:
        sent = c["sentence"]
        if sent in seen:
            continue
        seen.add(sent)

        fractions = []
        for pat in FRACTION_PATTERNS:
            for m in pat.finditer(sent):
                num, den = _f(m.group(1)), _f(m.group(2))
                if den > 0 and num <= den:
                    fractions.append((num, den, m.group(0), m.start()))
        if not fractions:
            continue
        pcts = [(_f(m.group(1)), m.group(0), m.start())
                for m in PCT_PATTERN.finditer(sent)]
        if not pcts:
            continue

        for pval, ptxt, ppos in pcts:
            # A fraction is the percentage's base only when nothing separates
            # them but the noun they describe. "committed on 339 of 539 and
            # agreed on 87.0%" reads 87.0% of the 339, and "100% abstention,
            # 0 of 16 correct" is two statistics in one row. Distance alone
            # cannot tell those from "69% on Land Tenure (17 of 25)", so the
            # gap text is what decides.
            near = [f for f in fractions
                    if abs(f[3] - ppos) <= ADJACENCY
                    and _same_quantity(sent, ppos, len(ptxt), f)]
            if not near:
                continue

            explained, best = False, None
            for num, den, ftxt, _pos in near:
                computed = num / den * 100.0
                decimals = len(ptxt.split(".")[1].rstrip("%").strip()) if "." in ptxt else 0
                if abs(round(computed, decimals) - pval) < 10 ** -max(decimals, 1) * 1.01:
                    explained = True
                    break
                delta = abs(computed - pval)
                if best is None or delta < best[0]:
                    best = (delta, num, den, ftxt, computed)
            if explained:
                out.append({"verdict": "ARITHMETIC_OK", "chapter": c["chapter"],
                            "paragraph": c["paragraph"], "stated": ptxt,
                            "sentence": sent})
            elif best and best[0] > 0.15:
                delta, num, den, ftxt, computed = best
                out.append({
                    "verdict": "ARITHMETIC_MISMATCH",
                    "chapter": c["chapter"], "paragraph": c["paragraph"],
                    "stated": ptxt, "fraction": ftxt,
                    "computed": f"{computed:.4g}%", "delta": round(delta, 3),
                    "sentence": sent,
                })
    return out


# --------------------------------------------------------------------------
# 2. ledger
# --------------------------------------------------------------------------

def ledger_lookup(ledger, value, unit):
    """Exact or rounding-equal presence in the canonical packs.

    The packs store proportions and the document writes percentages, so both
    readings are tried. Nearest-neighbour matching is deliberately absent.
    """
    readings = [value, value / 100.0] if unit == "%" else [value, value * 100.0]
    for r in readings:
        if round(r, 10) in ledger:
            return "EXACT", ledger[round(r, 10)][0]
    for r in readings:
        for lv, paths in ledger.items():
            if lv == 0:
                continue
            for dp in (1, 2, 3, 4):
                if round(lv, dp) == round(r, dp) and abs(lv - r) < 10 ** -dp:
                    return "ROUNDED", f"{paths[0]} = {lv:.6g}"
    return "UNSOURCED", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", default="build/qa/report.json")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="build/qa")
    args = ap.parse_args()

    with open(args.qa) as f:
        qa = json.load(f)
    claims = qa["number_claims"]

    arith = check_arithmetic(claims)
    mismatches = [a for a in arith if a["verdict"] == "ARITHMETIC_MISMATCH"]
    ok = [a for a in arith if a["verdict"] == "ARITHMETIC_OK"]

    ledger = build_ledger(args.root)
    ledger_results, counts = [], defaultdict(int)
    for c in claims:
        try:
            val = float(c["value"].replace(",", ""))
        except ValueError:
            continue
        verdict, path = ledger_lookup(ledger, val, c["unit"])
        counts[verdict] += 1
        ledger_results.append({
            "verdict": verdict, "value": c["value"] + c["unit"],
            "chapter": c["chapter"], "paragraph": c["paragraph"],
            "ledger": path, "sentence": c["sentence"],
        })

    print(f"ledger values loaded: {sum(len(v) for v in ledger.values())}")
    print(f"\n1. ARITHMETIC  self-checking sentences: {len(arith)}")
    print(f"   agree: {len(ok)}   MISMATCH: {len(mismatches)}")
    print(f"\n2. LEDGER  {dict(counts)}")

    if mismatches:
        print("\n=== ARITHMETIC MISMATCHES (stated % does not equal its fraction) ===")
        for m in sorted(mismatches, key=lambda x: -x["delta"]):
            print(f"  {m['chapter'][:20]:22} stated {m['stated']:>8}  "
                  f"{m['fraction']} = {m['computed']}  (off by {m['delta']})")
            print(f"     {m['sentence'][:165]}")
    else:
        print("\n=== no arithmetic mismatches ===")

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "numbers_verified.json"), "w") as f:
        json.dump({"arithmetic": arith, "ledger": ledger_results}, f, indent=1)
    print(f"\nwritten to {args.out}/numbers_verified.json")


if __name__ == "__main__":
    main()
