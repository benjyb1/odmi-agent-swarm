#!/usr/bin/env python3
"""NL false-positive audit: is each NL false positive a genuine swarm error, a
definitional gap, or a defensible answer against a self-reported / stale gold?

The deep dive (docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md, section 1A) showed the NL
false positives are not caught by any confidence number because they are mostly
measurement mismatches: the swarm reads the live portal, the gold encodes the
country's self-reported internal action. That was an aggregate argument. This
audits each distinct NL FP question individually, so the headline can report a
*true* swarm error rate separate from the self-report-contaminated FP count.

For each NL question with a committed binary false positive (swarm `yes`, gold
`no`), the most recent such pair is adjudicated by Opus over the FROZEN stored
evidence (the researcher's quote and search snippets) plus ODMI's own published
answer and explanation. Opus is asked to decide who is right and, if the gold
stands, why the swarm diverged. It is one classification call per question.

This is an adjudication of a KNOWN disagreement, not a blind correctness test, so
Opus is shown the gold and ODMI's explanation deliberately. No web search, no
swarm run, so the evaluation-cycle deny-list is not engaged.

Safety: forces the proxy base URL from the main .env and refuses to run against
the real Anthropic API. Reads the canonical DB read-only; the exact phase2_final
row ids audited are pinned in the output for reproducibility.

  uv run python evaluation/nl_fp_audit.py --limit 1     # reachability
  uv run python evaluation/nl_fp_audit.py               # full audit
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

# env: force the proxy, never the real API
MAIN_ENV = Path("/Users/benjyb/Desktop/MscProject/.env")
load_dotenv(MAIN_ENV, override=True)
_base = os.environ.get("ANTHROPIC_BASE_URL", "")
if "localhost" not in _base and "127.0.0.1" not in _base:
    sys.exit(f"REFUSING TO RUN: ANTHROPIC_BASE_URL is {_base!r}, not the local "
             f"proxy. Aborting to avoid real-API billing.")

CANONICAL_DB = "/Users/benjyb/Desktop/MscProject/data/odmi.db"
MODEL = "claude-opus-4-6"  # Sonnet exhausted; Opus served via the Max proxy (EXP-9, EXP-25 smoke)
RESULTS = Path(__file__).resolve().parent / "results" / "nl_fp_audit.jsonl"

from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from agents.tools.llm import call_for_structured  # noqa: E402

ABST = {"inconclusive", "not_applicable", "not applicable", "other",
        "i don't know", "idk", "", None}

VERDICTS = ("genuine_error", "definitional_gap", "defensible_or_stale_gold")


def norm(s):
    return (s or "").strip().lower()


class Audit(BaseModel):
    verdict: Literal["genuine_error", "definitional_gap", "defensible_or_stale_gold"] = Field(
        ..., description="the classification of this swarm-vs-ODMI disagreement")
    swarm_evidence_supports_yes: bool = Field(
        ..., description="does the quoted web evidence, on a strict reading, actually establish 'yes'?")
    gold_is_self_report: bool = Field(
        ..., description="does the gold 'no' appear to rest on the country's self-reported internal "
                         "state, a different assessment period, or information not on the open web?")
    reason: str = Field(..., max_length=1200,
                        description="one or two sentences justifying the verdict")


SYS = (
    "You are auditing a disagreement between an automated open-data research swarm "
    "and the EU Open Data Maturity Index (ODMI) published answer for one yes/no "
    "question about a country's national open data portal. The swarm answered "
    "'yes'; ODMI's gold answer is 'no'. ODMI is a country self-report "
    "questionnaire validated by assessors: a gold answer may encode the country's "
    "own statement about its internal activity in a specific assessment period, "
    "which is not always visible on the open web.\n\n"
    "Judge the disagreement and assign exactly one verdict:\n"
    "- genuine_error: the gold 'no' is correct and the swarm should have reached "
    "it from the SAME evidence. The quoted web evidence does not actually "
    "establish 'yes' (the swarm over-read a passing mention, cited tangential or "
    "adjacent material, or misread the portal).\n"
    "- definitional_gap: the swarm found something real and related, but it does "
    "not meet the question's specific definition (for example impact STORIES when "
    "the question asks for impact DATA, or a mention of a concept versus its "
    "formal adoption). The dispute is about what the question requires, not about "
    "the facts; the gold 'no' is defensible on a strict reading.\n"
    "- defensible_or_stale_gold: the swarm's 'yes' is well supported by the "
    "current portal/web evidence, and the gold 'no' rests on the country's "
    "self-reported internal state, a different assessment period, or information "
    "not published on the open web. This is a measurement mismatch, not a swarm "
    "error: the swarm could not have known the gold from the open web.\n\n"
    "Be strict and concrete. Absence of a mention is not proof of a 'no'. Base "
    "the verdict only on the evidence and explanation shown."
)


def build_user(q_text, country, quote, snippets, gold, explanation):
    blocks = "\n\n".join(f"[{i+1}] {s[:600]}" for i, s in enumerate(snippets[:8]))
    expl = explanation.strip() if explanation and explanation.strip() else "(ODMI gave no written explanation for this answer.)"
    return (f"Country: {country}\n"
            f"Question: {q_text}\n\n"
            f"SWARM answer: yes\n"
            f"Evidence quote the swarm cited: {quote!r}\n\n"
            f"Search snippets the swarm read:\n{blocks}\n\n"
            f"ODMI gold answer: {gold!r}\n"
            f"ODMI explanation: {expl}\n\n"
            f"Adjudicate: is the swarm's 'yes' a genuine_error, a definitional_gap, "
            f"or defensible_or_stale_gold against this gold?")


def load_fps(con):
    """Latest committed binary false positive (swarm yes, gold no) per NL question.
    Returns the rows plus the max phase2_final id seen, to pin the snapshot."""
    shape = {r["question_id"]: (r["answer_shape"] or "binary")
             for r in con.execute("SELECT question_id, answer_shape FROM questions")}
    qtext = {r["question_id"]: r["question_text"]
             for r in con.execute("SELECT question_id, question_text FROM questions")}
    gt = {r["question_id"]: r
          for r in con.execute("SELECT * FROM ground_truth WHERE country_code='NL'")}
    # latest committed researcher run per pair (snippets + quote)
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
        g = gt.get(f["question_id"])
        if not g or norm(g["response"]) != "no" or norm(f["final_answer"]) != "yes":
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
        g = gt[q]
        out.append(dict(
            qid=q, final_id=f["id"], pair_run_id=f["pair_run_id"],
            q_text=qtext.get(q, q), gold=g["response"], decision=g["decision"],
            explanation=g["explanation"] or "", answer_confidence=f["final_answer_confidence"],
            quote=(rr["evidence_quote"] if rr else "") or "", snippets=snips,
            has_evidence=bool(snips)))
    return out, max_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=CANONICAL_DB)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--tag", default="", help="suffix for output file + condition label")
    args = ap.parse_args()
    results_path = RESULTS.parent / f"nl_fp_audit{args.tag}.jsonl"

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    fps, max_id = load_fps(con)
    con.close()
    if args.limit:
        fps = fps[:args.limit]

    print(f"Base URL: {os.environ['ANTHROPIC_BASE_URL']}  Model: {args.model}")
    print(f"NL FP audit: {len(fps)} distinct questions  (DB snapshot max phase2_final.id={max_id})")
    no_ev = [c["qid"] for c in fps if not c["has_evidence"]]
    if no_ev:
        print(f"  note: {len(no_ev)} have no stored snippets, audited on quote only: {no_ev}")
    results_path.parent.mkdir(exist_ok=True)
    rows = []
    with results_path.open("w") as fh:
        for i, c in enumerate(fps):
            try:
                out, _ = call_for_structured(
                    system=SYS,
                    user_message=build_user(c["q_text"], "Netherlands", c["quote"],
                                            c["snippets"], c["gold"], c["explanation"]),
                    output_schema=Audit, model=args.model, max_tokens=500,
                    temperature=0.0, condition_label=f"nl_fp_audit{args.tag}",
                    usage_context=f"nl_fp_audit:{c['qid']}:NL")
                rec = dict(qid=c["qid"], final_id=c["final_id"], decision=c["decision"],
                           answer_confidence=c["answer_confidence"], has_evidence=c["has_evidence"],
                           verdict=out.verdict,
                           swarm_evidence_supports_yes=out.swarm_evidence_supports_yes,
                           gold_is_self_report=out.gold_is_self_report, reason=out.reason)
            except Exception as e:  # noqa: BLE001
                rec = dict(qid=c["qid"], final_id=c["final_id"], decision=c["decision"],
                           error=f"{type(e).__name__}: {e}")
            rows.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            tag = rec.get("error") or f"{rec['verdict']:24s} (dec={rec['decision']})"
            print(f"  [{i+1}/{len(fps)}] {c['qid']:6s} -> {tag}")

    ok = [r for r in rows if "error" not in r]
    if ok:
        ctr = Counter(r["verdict"] for r in ok)
        print(f"\nVerdict counts (n={len(ok)} adjudicated):")
        for v in VERDICTS:
            qs = [r["qid"] for r in ok if r["verdict"] == v]
            print(f"  {v:26s} {ctr.get(v,0):2d}  {sorted(qs)}")
        genuine = ctr.get("genuine_error", 0)
        print(f"\n  genuine swarm errors: {genuine}/{len(ok)} = {genuine/len(ok):.0%} of audited NL FPs")
        print(f"  self-report / definitional (not a clean swarm error): "
              f"{len(ok)-genuine}/{len(ok)} = {(len(ok)-genuine)/len(ok):.0%}")
        bydec = Counter((r["decision"] or "(null)", r["verdict"]) for r in ok)
        print("\n  verdict x ODMI decision:")
        for (d, v), n in sorted(bydec.items()):
            print(f"    {d:10s} {v:26s} {n}")
    print(f"\nWrote {results_path}")


if __name__ == "__main__":
    main()
