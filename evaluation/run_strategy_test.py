"""Un-frozen verifier-strategy test (2026-06-07).

Unlike the frozen EXP-6 harness, this runs the PRODUCTION verifier
(`run_verifier`) per (candidate, strategy), so EACH strategy does its OWN live
counter-search, which is the whole point of the verifier and the only way
disprove and negation actually differ.

Dataset: data/questions/exp6_h123_dataset.json (build_h123.py).
Verdict truth: gold_label should_fail -> correct verdict is 'fail';
should_pass -> 'pass'. Confusion matrix + Youden's J per strategy and per stratum.

Usage:
  uv run python evaluation/run_strategy_test.py --demo            # one negation, show its queries
  uv run python evaluation/run_strategy_test.py --strategies verifier-disprove verifier-negation
  uv run python evaluation/run_strategy_test.py --limit 40 ...    # pilot
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from agents.models import ResearcherOutput, VerifierInput
from agents.verifier import run_verifier

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data" / "questions" / "exp6_h123_dataset.json"


def _researcher_output(c: dict) -> ResearcherOutput:
    quote = (c["evidence_quote"] or "")[:] or "(no quote)"
    if len(quote) < 10:
        quote = (quote + " " * 10)[:10]
    url = c["source_url"] if str(c["source_url"]).startswith("http") else "https://example.invalid/none"
    return ResearcherOutput(
        answer=c["researcher_answer"], answer_explanation="(test item)",
        evidence_quote=quote, source_url=url,
        retrieval_confidence=c.get("answer_confidence") or 0.5,
        answer_confidence=c.get("answer_confidence") or 0.5,
        search_queries_used=[], fetched_urls=[u for u in [url] if u.startswith("http")],
        domain_trust_score=None, language_route_used="native")


def _vinput(c: dict, strategy: str) -> VerifierInput:
    return VerifierInput(
        question_id=c["question_id"], question_text=c["question_text"],
        country_code=c["country_code"], country_name=c["country_name"],
        researcher_output=_researcher_output(c), strategy=strategy,
        answer_shape=c["answer_shape"], allowed_answers=c["allowed_answers"],
        researcher_snippets=c.get("snippets", []))


def demo(cands):
    # pick a should_fail H3 item (a real wrong 'yes' on a no-gold question)
    c = next((x for x in cands if x["stratum"] == "H3" and x["gold_label"] == "should_fail"), cands[0])
    print(f"=== NEGATION demo on [{c['country_code']} {c['question_id']}] ===")
    print(f"Q: {c['question_text']}")
    print(f"Researcher answer: {c['researcher_answer']}  (gold says this is {'WRONG' if c['gold_label']=='should_fail' else 'right'})")
    seen = {}
    def on_step(e, p):
        if e == "query_gen_complete":
            seen["queries"] = p.get("queries")
            print("\nNEGATED QUERIES (verifier searching for the opposite):")
            for q in p.get("queries", []): print(f"   - {q}")
        if e == "search_complete":
            print(f"\nlive counter-search: {p.get('n_results')} results; top: {p.get('top_titles', [])[:3]}")
    r = run_verifier(_vinput(c, "verifier-negation"), provider="diy", on_step=on_step)
    o = r.output
    print(f"\nVERDICT: {o.verdict}  (conf {o.verifier_confidence:.2f})")
    if o.verdict == "fail":
        print(f"rejection: {o.rejection_reason}")
        print(f"counter-evidence: {(o.counter_evidence_quote or '')[:200]}")
    print(f"\n=> negation { 'CAUGHT the error' if (o.verdict=='fail' and c['gold_label']=='should_fail') else 'verdict='+o.verdict }")


def run(cands, strategies):
    # cm[strategy] = dict of tp/fp/fn/tn; also per stratum
    cm = {s: defaultdict(int) for s in strategies}
    cm_str = {s: defaultdict(lambda: defaultdict(int)) for s in strategies}
    for i, c in enumerate(cands):
        for s in strategies:
            try:
                o = run_verifier(_vinput(c, s), provider="diy").output
                v = o.verdict if o else "error"
            except Exception as e:
                v = "error"; print(f"  err {c['question_id']}/{c['country_code']}/{s}: {str(e)[:80]}")
            fail_gold = c["gold_label"] == "should_fail"
            cell = ("tp" if (fail_gold and v == "fail") else "fn" if (fail_gold and v == "pass")
                    else "fp" if (not fail_gold and v == "fail") else "tn" if v == "pass" else "err")
            cm[s][cell] += 1; cm_str[s][c["stratum"]][cell] += 1
        if (i + 1) % 10 == 0: print(f"  ...{i+1}/{len(cands)}")
    def report(d):
        tp, fn, fp, tn = d["tp"], d["fn"], d["fp"], d["tn"]
        sens = tp / (tp + fn) if tp + fn else float("nan")
        spec = tn / (tn + fp) if tn + fp else float("nan")
        return tp, fn, fp, tn, sens, spec, (sens + spec - 1)
    print("\n================ RESULTS ================")
    for s in strategies:
        tp, fn, fp, tn, sens, spec, j = report(cm[s])
        print(f"\n{s}:  TP={tp} FN={fn} FP={fp} TN={tn}")
        print(f"   catch(sens)={sens:.2f}  specificity={spec:.2f}  Youden J={j:.2f}")
        for st in ("H1", "H2", "H3"):
            if cm_str[s][st]:
                t, f, p, n, se, sp, jj = report(cm_str[s][st])
                print(f"     {st}: TP={t} FN={f} FP={p} TN={n}  J={jj:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--strategies", nargs="+", default=["verifier-disprove", "verifier-negation"])
    a = ap.parse_args()
    cands = json.loads(DATA.read_text())["candidates"]
    if a.limit:
        # balanced, seeded subsample so a small --limit has both classes
        import random
        fails = [c for c in cands if c["gold_label"] == "should_fail"]
        passes = [c for c in cands if c["gold_label"] == "should_pass"]
        rng = random.Random(20260607)
        rng.shuffle(fails); rng.shuffle(passes)
        half = a.limit // 2
        cands = fails[:half] + passes[:a.limit - half]
        rng.shuffle(cands)
    if a.demo:
        demo(cands)
    else:
        print(f"running {len(a.strategies)} strategies x {len(cands)} candidates (live counter-search)")
        run(cands, a.strategies)


if __name__ == "__main__":
    main()
