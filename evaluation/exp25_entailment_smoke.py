#!/usr/bin/env python3
"""EXP-25 smoke: does an explicit Verifier ENTAILMENT score separate correct
commits from confident false positives, where answer_confidence cannot?

The deep dive showed answer_confidence is a near-chance correctness ranker
(AUROC ~0.55) and that correct commits and false positives carry the same
confidence (0.775 vs 0.767). Step 1 showed no stored signal does better. This
probes the one thing nothing in the DB measures: P(the quoted evidence actually
establishes the proposed answer), scored by an LLM that is NOT shown the gold.

This is a FEASIBILITY SMOKE on a small, deliberately balanced NL sample, not the
confirmatory EXP-25. The confirmatory run (full NL, fixed tau, adoption rule)
must be pre-registered first. The smoke exists to (a) prove the Opus path works,
(b) check the entailment score discriminates before any large quota spend.

Safety: forces the proxy base URL from the main .env and refuses to run against
the real Anthropic API. Reads the canonical DB read-only; usage logging lands in
the worktree DB (llm.py resolves its path relative to itself), so the canonical
DB is never written.

  uv run python evaluation/exp25_entailment_smoke.py --limit 1     # reachability
  uv run python evaluation/exp25_entailment_smoke.py --limit 12    # the smoke
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

# --- env: force the proxy, never the real API -------------------------------
MAIN_ENV = Path("/Users/benjyb/Desktop/MscProject/.env")
load_dotenv(MAIN_ENV, override=True)
_base = os.environ.get("ANTHROPIC_BASE_URL", "")
if "localhost" not in _base and "127.0.0.1" not in _base:
    sys.exit(f"REFUSING TO RUN: ANTHROPIC_BASE_URL is {_base!r}, not the local "
             f"proxy. Aborting to avoid real-API billing.")

CANONICAL_DB = "/Users/benjyb/Desktop/MscProject/data/odmi.db"
MODEL = "claude-opus-4-6"  # Sonnet exhausted; Opus permitted (EXP-9 confirmed served)
RESULTS = Path(__file__).resolve().parent / "results" / "exp25_entailment_smoke.jsonl"

from pydantic import BaseModel, Field  # noqa: E402

from agents.tools.llm import call_for_structured  # noqa: E402

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


def is_correct_binary(ans, gold):
    a, g = norm(ans), norm(gold)
    if a in ABST or not g:
        return False
    return a == g or (a == "yes" and g.startswith("yes")) or (a == "no" and g == "no")


def load_sample(con, limit):
    """Balanced NL binary smoke: false positives first (the failure mode),
    then correct-yes, correct-no, false-negatives. Deterministic order."""
    shape = {r["question_id"]: (r["answer_shape"] or "binary")
             for r in con.execute("SELECT question_id, answer_shape FROM questions")}
    qtext = {r["question_id"]: r["question_text"]
             for r in con.execute("SELECT question_id, question_text FROM questions")}
    gt = {(r["question_id"], r["country_code"]): r["response"]
          for r in con.execute("SELECT question_id, country_code, response FROM ground_truth")}
    # latest committed researcher run per pair (snippets + quote)
    res = {}
    for r in con.execute(
        "SELECT pair_run_id, retry_count, id, answer, evidence_quote, search_snippets "
        "FROM phase2_researcher_runs WHERE country_code='NL' ORDER BY retry_count, id"):
        if norm(r["answer"]) not in ABST:
            res[r["pair_run_id"]] = r

    cands = []
    for f in con.execute("SELECT * FROM phase2_final WHERE country_code='NL'"):
        if shape.get(f["question_id"]) != "binary":
            continue
        gold = gt.get((f["question_id"], f["country_code"]))
        if norm(gold) not in ("yes", "no") or norm(f["final_answer"]) in ABST:
            continue
        rr = res.get(f["pair_run_id"])
        if not rr or not rr["search_snippets"]:
            continue
        try:
            snips = [d.get("snippet", "") if isinstance(d, dict) else str(d)
                     for d in json.loads(rr["search_snippets"])]
            snips = [s for s in snips if s]
        except Exception:
            continue
        if not snips:
            continue
        ans = f["final_answer"]
        correct = is_correct_binary(ans, gold)
        if correct and norm(ans) == "yes":
            outcome = "correct_yes"
        elif correct and norm(ans) == "no":
            outcome = "correct_no"
        elif norm(ans) == "yes" and norm(gold) == "no":
            outcome = "false_positive"
        else:
            outcome = "false_negative"
        cands.append(dict(
            pair_run_id=f["pair_run_id"], qid=f["question_id"],
            q_text=qtext.get(f["question_id"], f["question_id"]),
            proposed=ans, gold=gold, outcome=outcome,
            answer_confidence=f["final_answer_confidence"],
            quote=rr["evidence_quote"] or "", snippets=snips))

    # deterministic balanced draw
    order = {"false_positive": 0, "correct_yes": 1, "correct_no": 2, "false_negative": 3}
    by = {k: sorted([c for c in cands if c["outcome"] == k], key=lambda c: c["pair_run_id"])
          for k in order}
    quota = {"false_positive": 5, "correct_yes": 3, "correct_no": 2, "false_negative": 2}
    out = []
    for k in order:
        out.extend(by[k][:quota[k]])
    return out[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=CANONICAL_DB)
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sample = load_sample(con, args.limit)
    con.close()

    print(f"Base URL: {os.environ['ANTHROPIC_BASE_URL']}  Model: {MODEL}")
    print(f"Smoke sample: {len(sample)} NL binary pairs")
    RESULTS.parent.mkdir(exist_ok=True)
    rows = []
    with RESULTS.open("w") as fh:
        for i, c in enumerate(sample):
            try:
                out, _ = call_for_structured(
                    system=SYS,
                    user_message=build_user(c["q_text"], "Netherlands", c["proposed"],
                                            c["quote"], c["snippets"]),
                    output_schema=Entailment, model=MODEL, max_tokens=300,
                    temperature=0.0, condition_label="exp25_entailment_smoke",
                    usage_context=f"exp25_smoke:{c['qid']}:NL")
                rec = dict(qid=c["qid"], outcome=c["outcome"], gold=c["gold"],
                           proposed=c["proposed"], answer_confidence=c["answer_confidence"],
                           entailment_for=out.entailment_for,
                           entailment_against=out.entailment_against,
                           margin=round(out.entailment_for - out.entailment_against, 3),
                           reason=out.reason)
            except Exception as e:  # noqa: BLE001
                rec = dict(qid=c["qid"], outcome=c["outcome"], error=f"{type(e).__name__}: {e}")
            rows.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            tag = rec.get("error") or (f"conf={rec['answer_confidence']:.2f}  "
                                       f"ent_for={rec['entailment_for']:.2f}  "
                                       f"margin={rec['margin']:+.2f}")
            print(f"  [{i+1}/{len(sample)}] {c['qid']:6s} {c['outcome']:15s} -> {tag}")

    ok = [r for r in rows if "error" not in r]
    if ok:
        def mean(sel, k):
            v = [r[k] for r in sel]
            return sum(v) / len(v) if v else float("nan")
        for grp in ("correct_yes", "correct_no", "false_positive", "false_negative"):
            g = [r for r in ok if r["outcome"] == grp]
            if g:
                print(f"  {grp:15s} n={len(g)}  mean ent_for={mean(g,'entailment_for'):.2f}  "
                      f"mean margin={mean(g,'margin'):+.2f}  "
                      f"mean answer_conf={mean(g,'answer_confidence'):.2f}")
        corr = [r for r in ok if r["outcome"] in ("correct_yes", "correct_no")]
        fp = [r for r in ok if r["outcome"] == "false_positive"]
        if corr and fp:
            print(f"\n  CORRECT vs FALSE-POSITIVE separation:")
            print(f"    entailment_for : correct {mean(corr,'entailment_for'):.2f}  vs  FP {mean(fp,'entailment_for'):.2f}")
            print(f"    margin         : correct {mean(corr,'margin'):+.2f}  vs  FP {mean(fp,'margin'):+.2f}")
            print(f"    answer_conf    : correct {mean(corr,'answer_confidence'):.2f}  vs  FP {mean(fp,'answer_confidence'):.2f}  (the floor's blind spot)")
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    main()
