#!/usr/bin/env python3
"""Adversarial second pass over the NL false-positive audit.

The first pass (nl_fp_audit.py) classified 20 of 22 NL false positives as
"definitional_gap" with the gold 'no' defensible. That is a uniform result on a
category that could be a charitable dumping ground, and it underwrites a claim
that partly contradicts the deep dive's measurement-mismatch reframe. So this
pass stress-tests it from the OPPOSITE direction: Opus is told to act as an
advocate hired to DEFEND the swarm's 'yes' and argue ODMI's 'no' is wrong or
outdated, then to say honestly whether that defence holds. The category names
from the first pass are not shown, to avoid anchoring.

If the advocate still concedes the swarm over-read on ~20, the first pass is
robust. If many flip to "gold wrong" or "genuinely ambiguous", it is fragile and
the writeup must say so. Same frozen evidence, same model, one call per question.

  uv run python evaluation/nl_fp_audit_adversarial.py --limit 1   # reachability
  uv run python evaluation/nl_fp_audit_adversarial.py             # full
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

MAIN_ENV = Path("/Users/benjyb/Desktop/MscProject/.env")
load_dotenv(MAIN_ENV, override=True)
_base = os.environ.get("ANTHROPIC_BASE_URL", "")
if "localhost" not in _base and "127.0.0.1" not in _base:
    sys.exit(f"REFUSING TO RUN: ANTHROPIC_BASE_URL is {_base!r}, not the local proxy.")

CANONICAL_DB = "/Users/benjyb/Desktop/MscProject/data/odmi.db"
MODEL = "claude-opus-4-6"
RESULTS = Path(__file__).resolve().parent / "results" / "nl_fp_audit_adversarial.jsonl"

from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from agents.tools.llm import call_for_structured  # noqa: E402
from evaluation.nl_fp_audit import load_fps  # noqa: E402


class Defence(BaseModel):
    best_case_for_swarm: str = Field(..., max_length=2500,
        description="the strongest evidence-grounded argument that the swarm's 'yes' is right")
    holds: Literal["gold_wrong", "ambiguous", "swarm_over_read"] = Field(...,
        description="gold_wrong = the swarm's yes is actually the better answer to the question as "
                    "asked; ambiguous = reasonable assessors could land either way; swarm_over_read "
                    "= even arguing for the swarm, its yes does not meet what the question asks and "
                    "ODMI's no stands")
    reason: str = Field(..., max_length=2000, description="why the defence does or does not hold")


SYS = (
    "You are an advocate. Your job is to make the STRONGEST possible "
    "evidence-grounded case that an automated research swarm gave the RIGHT answer "
    "to a yes/no question about a national open data portal, and that the EU Open "
    "Data Maturity Index (ODMI) gold answer of 'no' is wrong, outdated, or overly "
    "strict. The swarm answered 'yes' and cited the evidence shown. Build the best "
    "case you honestly can from that evidence.\n\n"
    "Then judge, against your own best case, which of three holds:\n"
    "- gold_wrong: the swarm's 'yes' is actually the better answer to the question "
    "as literally asked; ODMI's 'no' does not stand.\n"
    "- ambiguous: a reasonable assessor could land on either answer; the question "
    "wording or evidence genuinely underdetermines it.\n"
    "- swarm_over_read: even making the swarm's case, the cited evidence does not "
    "meet what the question specifically asks, so ODMI's 'no' stands and the swarm "
    "over-read adjacent or insufficient evidence as a 'yes'.\n\n"
    "Do not be charitable to the swarm beyond what the evidence supports. Absence "
    "of a mention is not proof. Decide honestly."
)


def build_user(q_text, country, quote, snippets):
    blocks = "\n\n".join(f"[{i+1}] {s[:600]}" for i, s in enumerate(snippets[:8]))
    return (f"Country: {country}\n"
            f"Question: {q_text}\n\n"
            f"The swarm answered: yes\n"
            f"Evidence quote it cited: {quote!r}\n\n"
            f"Search snippets it read:\n{blocks}\n\n"
            f"ODMI gold answer: no\n\n"
            f"Make the best case the swarm's 'yes' is right and ODMI's 'no' is wrong, "
            f"then judge whether that case holds.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=CANONICAL_DB)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    fps, max_id = load_fps(con)
    con.close()
    if args.limit:
        fps = fps[:args.limit]

    print(f"Adversarial NL FP defence: {len(fps)} questions  (snapshot max id={max_id})  Model: {MODEL}")
    RESULTS.parent.mkdir(exist_ok=True)
    rows = []
    with RESULTS.open("w") as fh:
        for i, c in enumerate(fps):
            try:
                out, _ = call_for_structured(
                    system=SYS,
                    user_message=build_user(c["q_text"], "Netherlands", c["quote"], c["snippets"]),
                    output_schema=Defence, model=MODEL, max_tokens=1500, temperature=0.0,
                    condition_label="nl_fp_audit_adversarial",
                    usage_context=f"nl_fp_adv:{c['qid']}:NL")
                rec = dict(qid=c["qid"], final_id=c["final_id"], decision=c["decision"],
                           holds=out.holds, reason=out.reason, best_case=out.best_case_for_swarm)
            except Exception as e:  # noqa: BLE001
                rec = dict(qid=c["qid"], error=f"{type(e).__name__}: {e}")
            rows.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"  [{i+1}/{len(fps)}] {c['qid']:6s} -> {rec.get('holds', rec.get('error'))}")

    ok = [r for r in rows if "error" not in r]
    if ok:
        ctr = Counter(r["holds"] for r in ok)
        print(f"\nAdversarial verdicts (n={len(ok)}):")
        for v in ("swarm_over_read", "ambiguous", "gold_wrong"):
            qs = [r["qid"] for r in ok if r["holds"] == v]
            print(f"  {v:16s} {ctr.get(v,0):2d}  {sorted(qs)}")
        over = ctr.get("swarm_over_read", 0)
        print(f"\n  swarm_over_read (gold stands, swarm wrong): {over}/{len(ok)} = {over/len(ok):.0%}")
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    main()
