#!/usr/bin/env python3
"""EXP-22 (entailment gate) and EXP-24 (argue-the-opposite) confirmatory replays.

Both are frozen-evidence replays sharing ONE scoring pass: for each NL committed
binary pair, a single production-Sonnet Verifier-side call scores how strongly
the cited evidence establishes the PROPOSED answer (entailment_for) and the
OPPOSITE answer (entailment_against). The two experiments are then two decision
rules applied offline to the same scores, each compared against the production
commit (the answer_confidence>=0.65 floor, i.e. the stored finalised outcome):

  EXP-22 entailment_gate: keep the commit iff entailment_for >= 0.70.
  EXP-24 argue_opposite:  keep the commit iff (for - against) >= 0.25.

Both gates can only turn a commit into an abstention, never flip a label, so the
question is whether they abstain false positives faster than they abstain correct
commits. Pre-registered in the `experiments` table (exp22_entailment_gate,
exp24_argue_opposite) and docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md section 6.

Endpoints (fixed pre-result): primary negative-gold FP rate per gate vs baseline,
McNemar exact on the paired negative pairs; co-primary abstention rate and
balanced accuracy (Youden J); Wilson 95% intervals. UNDERPOWERED by construction:
deduped to one row per question, NL has only ~12 committed negative golds (the
deep-dive's 266 were non-independent pooled-across-arms rows). Reported as such.

Model is production Sonnet (claude-sonnet-4-6), not the Opus the deep-dive named
for the smoke (Sonnet was exhausted then); this removes the model confound vs the
production Verifier. Reads canonical DB read-only; usage logs to the worktree DB.

  uv run python evaluation/confidence_gates.py --limit 1   # reachability
  uv run python evaluation/confidence_gates.py             # full run
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

MAIN_ENV = Path("/Users/benjyb/Desktop/MscProject/.env")
load_dotenv(MAIN_ENV, override=True)
_base = os.environ.get("ANTHROPIC_BASE_URL", "")
if "localhost" not in _base and "127.0.0.1" not in _base:
    sys.exit(f"REFUSING TO RUN: ANTHROPIC_BASE_URL is {_base!r}, not the local proxy.")

CANONICAL_DB = "/Users/benjyb/Desktop/MscProject/data/odmi.db"
MODEL = "claude-sonnet-4-6"  # production Verifier model; quota restored 2026-06-25
RESULTS = Path(__file__).resolve().parent / "results" / "confidence_gates.jsonl"
SUMMARY = Path(__file__).resolve().parent / "results" / "confidence_gates_summary.json"

TAU_FOR = 0.70      # EXP-22 gate, fixed pre-result
TAU_MARGIN = 0.25   # EXP-24 gate, fixed pre-result

from pydantic import BaseModel, Field  # noqa: E402

from agents.tools.llm import call_for_structured  # noqa: E402
from evaluation.stats import mcnemar_exact, wilson_interval  # noqa: E402

ABST = {"inconclusive", "not_applicable", "not applicable", "other",
        "i don't know", "idk", "", None}


def norm(s):
    return (s or "").strip().lower()


class Entailment(BaseModel):
    entailment_for: float = Field(..., ge=0.0, le=1.0,
                                  description="P(the evidence establishes the PROPOSED answer)")
    entailment_against: float = Field(..., ge=0.0, le=1.0,
                                      description="P(the same evidence establishes the OPPOSITE answer)")
    reason: str = Field(..., max_length=1500)


SYS = (
    "You score how strongly a body of quoted web evidence supports a specific "
    "answer to a yes/no question about a national open data portal. You are NOT "
    "told the correct answer and must not guess it from outside knowledge; judge "
    "only what the evidence in front of you establishes. Score two numbers in "
    "[0,1]: entailment_for = the probability the evidence positively establishes "
    "the PROPOSED answer, and entailment_against = the probability the same "
    "evidence establishes the OPPOSITE answer. Be strict. Evidence that is "
    "tangential, that merely fails to mention the feature, or that describes "
    "something adjacent, is LOW entailment_for, not high. Absence of a mention is "
    "not proof of a 'no'. Give a one-sentence reason."
)


def build_user(q_text, country, proposed, quote, snippets):
    blocks = "\n\n".join(f"[{i+1}] {s[:600]}" for i, s in enumerate(snippets[:8]))
    return (f"Country: {country}\n"
            f"Question: {q_text}\n"
            f"Proposed answer: {proposed!r}\n"
            f"Evidence quote the researcher cited: {quote!r}\n\n"
            f"Search snippets the researcher read:\n{blocks}\n\n"
            f"Score entailment_for (does the evidence establish {proposed!r}?) and "
            f"entailment_against (does it establish the opposite?).")


def is_correct(proposed, gold):
    a, g = norm(proposed), norm(gold)
    return a == g or (a == "yes" and g.startswith("yes")) or (a == "no" and g == "no")


def load_pairs(con):
    """Latest COMMITTED binary yes/no pair per NL question, across all arms.
    One row per question = independent units. Pins final_id; loads frozen evidence."""
    shape = {r["question_id"]: (r["answer_shape"] or "binary")
             for r in con.execute("SELECT question_id, answer_shape FROM questions")}
    qtext = {r["question_id"]: r["question_text"]
             for r in con.execute("SELECT question_id, question_text FROM questions")}
    gt = {r["question_id"]: norm(r["response"])
          for r in con.execute("SELECT question_id, response FROM ground_truth WHERE country_code='NL'")}
    res = {}
    for r in con.execute(
        "SELECT pair_run_id, retry_count, id, answer, evidence_quote, search_snippets "
        "FROM phase2_researcher_runs WHERE country_code='NL' ORDER BY retry_count, id"):
        if norm(r["answer"]) not in ABST:
            res[r["pair_run_id"]] = r

    best, max_id = {}, 0
    for f in con.execute("SELECT * FROM phase2_final WHERE country_code='NL'"):
        max_id = max(max_id, f["id"])
        if shape.get(f["question_id"]) != "binary":
            continue
        if gt.get(f["question_id"]) not in ("yes", "no"):
            continue
        if norm(f["final_answer"]) in ABST:           # committed only
            continue
        q = f["question_id"]
        if q not in best or f["id"] > best[q]["id"]:
            best[q] = f

    out = []
    for q in sorted(best):
        f = best[q]
        rr = res.get(f["pair_run_id"])
        snips = []
        if rr and rr["search_snippets"]:
            try:
                snips = [d.get("snippet", "") if isinstance(d, dict) else str(d)
                         for d in json.loads(rr["search_snippets"])]
                snips = [s for s in snips if s]
            except Exception:
                snips = []
        if not snips:
            continue
        proposed, gold = norm(f["final_answer"]), gt[q]
        out.append(dict(
            qid=q, final_id=f["id"], q_text=qtext.get(q, q),
            proposed=proposed, gold=gold, correct=is_correct(proposed, gold),
            is_fp=(proposed == "yes" and gold == "no"),
            answer_confidence=f["final_answer_confidence"],
            quote=(rr["evidence_quote"] if rr else "") or "", snippets=snips))
    return out, max_id


def evaluate(pairs, keep):
    """keep(p)->bool: does this arm commit pair p? Three-outcome + balance-aware."""
    committed = [p for p in pairs if keep(p)]
    nt, nc = len(pairs), len(committed)
    neg = [p for p in committed if p["gold"] == "no"]
    pos = [p for p in committed if p["gold"] == "yes"]
    fp = [p for p in neg if p["proposed"] == "yes"]
    tnr = (len(neg) - len(fp)) / len(neg) if neg else 0.0
    tpr = sum(1 for p in pos if p["proposed"] == "yes") / len(pos) if pos else 0.0
    return dict(
        n_total=nt, n_committed=nc, abstention_rate=round(1 - nc / nt, 3) if nt else 0,
        acc_committed=round(sum(p["correct"] for p in committed) / nc, 3) if nc else 0,
        n_neg_committed=len(neg), fp=len(fp),
        fp_rate=round(len(fp) / len(neg), 3) if neg else 0.0,
        fp_ci=[round(x, 3) for x in wilson_interval(len(fp), len(neg))],
        tpr=round(tpr, 3), tnr=round(tnr, 3), youden_j=round(tpr + tnr - 1, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=CANONICAL_DB)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    pairs, max_id = load_pairs(con)
    con.close()
    if args.limit:
        pairs = pairs[:args.limit]

    print(f"Base URL: {os.environ['ANTHROPIC_BASE_URL']}  Model: {MODEL}")
    print(f"NL committed binary pairs: {len(pairs)}  (snapshot max phase2_final.id={max_id})")
    RESULTS.parent.mkdir(exist_ok=True)
    scored = []
    with RESULTS.open("w") as fh:
        for i, p in enumerate(pairs):
            try:
                out, _ = call_for_structured(
                    system=SYS,
                    user_message=build_user(p["q_text"], "Netherlands", p["proposed"],
                                            p["quote"], p["snippets"]),
                    output_schema=Entailment, model=MODEL, max_tokens=300,
                    temperature=0.0, condition_label="confidence_gates",
                    usage_context=f"confidence_gates:{p['qid']}:NL")
                p["for"] = out.entailment_for
                p["against"] = out.entailment_against
                p["margin"] = round(out.entailment_for - out.entailment_against, 3)
                rec = dict(qid=p["qid"], final_id=p["final_id"], gold=p["gold"],
                           proposed=p["proposed"], outcome=("fp" if p["is_fp"] else
                           ("correct" if p["correct"] else "fn_or_other")),
                           answer_confidence=p["answer_confidence"],
                           entailment_for=p["for"], entailment_against=p["against"],
                           margin=p["margin"], reason=out.reason)
                scored.append(p)
            except Exception as e:  # noqa: BLE001
                rec = dict(qid=p["qid"], error=f"{type(e).__name__}: {e}")
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            tag = rec.get("error") or (f"conf={rec['answer_confidence']:.2f} for={rec['entailment_for']:.2f} "
                                       f"margin={rec['margin']:+.2f} [{rec['outcome']}]")
            print(f"  [{i+1}/{len(pairs)}] {p['qid']:6s} -> {tag}")

    if not scored:
        print("no pairs scored"); return

    base = evaluate(scored, lambda p: True)
    e22 = evaluate(scored, lambda p: p["for"] >= TAU_FOR)
    e24 = evaluate(scored, lambda p: (p["for"] - p["against"]) >= TAU_MARGIN)

    def paired_neg(keep):
        # gates only abstain, never create FPs: c=0, b = baseline FP that the gate drops
        b = sum(1 for p in scored if p["gold"] == "no" and p["is_fp"] and not keep(p))
        return b, 0, mcnemar_exact(b, 0)

    b22, c22, p22 = paired_neg(lambda p: p["for"] >= TAU_FOR)
    b24, c24, p24 = paired_neg(lambda p: (p["for"] - p["against"]) >= TAU_MARGIN)
    hi_conf_caught_24 = sum(1 for p in scored if p["gold"] == "no" and p["is_fp"]
                            and (p["for"] - p["against"]) < TAU_MARGIN
                            and (p["answer_confidence"] or 0) >= 0.80)

    def adopt(base, arm, b):
        fp_drop = (base["fp_rate"] - arm["fp_rate"]) * 100
        abst_rise = (arm["abstention_rate"] - base["abstention_rate"]) * 100
        j_fall = base["youden_j"] - arm["youden_j"]
        return dict(fp_drop_pp=round(fp_drop, 1), abst_rise_pp=round(abst_rise, 1),
                    youden_fall=round(j_fall, 3), fps_caught=b,
                    adopt=(fp_drop >= 15 and j_fall <= 0 and abst_rise <= 10))

    summary = dict(
        model=MODEL, n_scored=len(scored), snapshot_max_final_id=max_id,
        baseline=base,
        exp22_entailment_gate=dict(arm=e22, mcnemar_b=b22, mcnemar_p=round(p22, 4),
                                   decision=adopt(base, e22, b22)),
        exp24_argue_opposite=dict(arm=e24, mcnemar_b=b24, mcnemar_p=round(p24, 4),
                                  high_conf_fps_caught=hi_conf_caught_24,
                                  decision=adopt(base, e24, b24)))
    SUMMARY.write_text(json.dumps(summary, indent=2))

    def row(name, e):
        print(f"  {name:18s} commit={e['n_committed']:3d}/{e['n_total']:<3d} "
              f"abst={e['abstention_rate']:.0%} acc={e['acc_committed']:.0%} "
              f"negFP={e['fp']}/{e['n_neg_committed']} ({e['fp_rate']:.0%} "
              f"CI[{e['fp_ci'][0]:.0%},{e['fp_ci'][1]:.0%}]) J={e['youden_j']:+.2f}")
    print(f"\n=== Results (n={len(scored)} committed pairs, {base['n_neg_committed']} negative golds) ===")
    row("baseline (0.65)", base)
    row("EXP-22 for>=.70", e22)
    print(f"     adoption: {summary['exp22_entailment_gate']['decision']}  McNemar p={p22:.3f} (b={b22})")
    row("EXP-24 margin>=.25", e24)
    print(f"     adoption: {summary['exp24_argue_opposite']['decision']}  McNemar p={p24:.3f} (b={b24})  hi-conf FPs caught={hi_conf_caught_24}")
    print(f"\nWrote {RESULTS}\nWrote {SUMMARY}")


if __name__ == "__main__":
    main()
