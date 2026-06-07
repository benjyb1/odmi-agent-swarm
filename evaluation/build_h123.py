"""Build the EXP-6 H1+H2+H3 verifier-test dataset (2026-06-07).

Each candidate carries a known verdict (gold_label) and everything needed to
build a VerifierInput at test time.

  H1 grounding  : FAIL = a correct answer whose evidence_quote is replaced by a
                  real-but-non-proving fragment of the SAME snippet (LLM-picked);
                  PASS = a correct answer with its genuine supporting quote.
                  H1-fail and H1-pass use disjoint questions.
  H2 confident  : FAIL = confidently-wrong commits (conf>=0.70); PASS = confidently
                  -correct commits.
  H3 yes-bias   : FAIL = no-gold questions the swarm wrongly answered 'yes';
                  PASS = correct 'yes' answers.

H1-fail items are CORRECT answers with swapped evidence, so they never collide
with H2/H3 fails (which are genuinely wrong answers). Pass items are assigned to
one stratum each (no double-count).

Output: data/questions/exp6_h123_dataset.json
Usage:  uv run python evaluation/build_h123.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from agents.tools.db import connect
from agents.tools.llm import call_for_structured

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "questions" / "exp6_h123_dataset.json"
CONF_FLOOR = 0.70
H1_TARGET = 45  # per side (fail/pass)


def _correct(a: str, g: str) -> bool:
    a = (a or "").strip().lower(); g = (g or "").strip().lower()
    return (a == g or (a == "yes" and g.startswith("yes"))
            or (a.startswith("yes") and g.startswith("yes")) or (a == "no" and g == "no"))


def _snip_texts(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except Exception:
        return []
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append(str(it.get("snippet") or ""))
        else:
            out.append(str(it))
    return [s for s in out if s]


class _Swap(BaseModel):
    quote: str = Field(..., description=(
        "A verbatim substring (one or two sentences) copied EXACTLY from the "
        "provided snippet text that is real and on-topic but does NOT establish "
        "the claimed answer to the question. Must appear character-for-character "
        "in the snippet."))


_SWAP_SYS = (
    "You build adversarial test items for a fact-verifier. Given an ODMI "
    "question, the claimed answer, and a snippet the researcher read, extract a "
    "VERBATIM fragment of the snippet that is genuine and topically related but "
    "does NOT actually prove the claimed answer. Do not invent text; copy it "
    "exactly from the snippet. Prefer a fragment that looks plausibly relevant "
    "but is non-probative.")


def main() -> None:
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            """
            SELECT f.question_id, f.country_code, f.final_answer ans,
                   f.final_answer_confidence conf, f.final_evidence_quote quote,
                   f.final_source_url url, f.pair_run_id,
                   gt.response gold, gt.country_name cname,
                   q.dimension dim, q.answer_shape shape, q.allowed_answers allowed,
                   q.question_text qtext
            FROM phase2_final f
            JOIN ground_truth gt ON gt.question_id=f.question_id AND gt.country_code=f.country_code
            JOIN questions q ON q.question_id=f.question_id
            WHERE f.country_code IN ('NL','FR') AND f.experiment_id IS NULL
            """)]
        # attach snippets from the latest researcher row of each pair
        for r in rows:
            sn = conn.execute(
                "SELECT search_snippets FROM phase2_researcher_runs "
                "WHERE pair_run_id=? ORDER BY id DESC LIMIT 1", (r["pair_run_id"],)
            ).fetchone()
            r["snips"] = _snip_texts(sn[0] if sn else None)

    def base(r, ans, quote, stratum, gold_label, swapped=False):
        return {
            "stratum": stratum, "gold_label": gold_label, "swapped": swapped,
            "question_id": r["question_id"], "country_code": r["country_code"],
            "country_name": r["cname"], "question_text": r["qtext"],
            "answer_shape": r["shape"] or "binary",
            "allowed_answers": json.loads(r["allowed"]) if r["allowed"] else ["yes", "no"],
            "researcher_answer": ans, "evidence_quote": quote or "",
            "source_url": r["url"] or "https://example.invalid/none",
            "snippets": r["snips"], "answer_confidence": r["conf"] or 0.0,
        }

    committed = [r for r in rows if (r["ans"] or "").strip().lower() not in ("", "inconclusive", "none")]
    correct = [r for r in committed if _correct(r["ans"], r["gold"]) and r["snips"]]
    wrong = [r for r in committed if not _correct(r["ans"], r["gold"])]

    used_q: set = set()
    cands: list[dict] = []

    # ---- H3 fail: no-gold answered yes (wrong) ----
    for r in wrong:
        if (r["gold"] or "").strip().lower() == "no" and (r["ans"] or "").strip().lower() == "yes":
            cands.append(base(r, r["ans"], r["quote"], "H3", "should_fail")); used_q.add((r["question_id"], r["country_code"]))
    # ---- H2 fail: confidently wrong ----
    for r in wrong:
        k = (r["question_id"], r["country_code"])
        if k in used_q: continue
        if (r["conf"] or 0) >= CONF_FLOOR:
            cands.append(base(r, r["ans"], r["quote"], "H2", "should_fail")); used_q.add(k)

    # ---- H1 fail: correct answers, evidence swapped to non-proving (LLM) ----
    swaps_done = []
    h1_fail_pool = [r for r in correct if (r["question_id"], r["country_code"]) not in used_q][:H1_TARGET]
    for r in h1_fail_pool:
        snip = "\n\n".join(r["snips"])[:3000]
        if not snip:
            continue
        user = (f"Question: {r['qtext']}\nClaimed answer: {r['ans']}\n\nSnippet:\n{snip}\n\n"
                "Return a verbatim non-proving fragment.")
        try:
            out, _ = call_for_structured(system=_SWAP_SYS, user_message=user, output_schema=_Swap,
                                         max_tokens=300, usage_context=f"h1_swap:{r['question_id']}:{r['country_code']}")
            q = out.quote.strip()
            if len(q) < 15:
                continue
            cands.append(base(r, r["ans"], q, "H1", "should_fail", swapped=True))
            used_q.add((r["question_id"], r["country_code"]))
            swaps_done.append((r, q))
        except Exception as e:
            print(f"  swap failed {r['question_id']}/{r['country_code']}: {e}")

    # ---- passes: assign each correct answer to one stratum ----
    pass_pool = [r for r in correct if (r["question_id"], r["country_code"]) not in used_q]
    # H1 pass (disjoint questions, with genuine quote)
    h1_pass = pass_pool[:H1_TARGET]
    for r in h1_pass:
        cands.append(base(r, r["ans"], r["quote"], "H1", "should_pass")); used_q.add((r["question_id"], r["country_code"]))
    rest = [r for r in correct if (r["question_id"], r["country_code"]) not in used_q]
    # H2 pass: confident-correct
    n_h2_fail = sum(1 for c in cands if c["stratum"] == "H2" and c["gold_label"] == "should_fail")
    h2_pass = [r for r in rest if (r["conf"] or 0) >= CONF_FLOOR][:max(n_h2_fail, 8)]
    for r in h2_pass:
        cands.append(base(r, r["ans"], r["quote"], "H2", "should_pass")); used_q.add((r["question_id"], r["country_code"]))
    rest = [r for r in correct if (r["question_id"], r["country_code"]) not in used_q]
    # H3 pass: correct yes
    n_h3_fail = sum(1 for c in cands if c["stratum"] == "H3" and c["gold_label"] == "should_fail")
    h3_pass = [r for r in rest if (r["ans"] or "").strip().lower() == "yes"][:max(n_h3_fail, 8)]
    for r in h3_pass:
        cands.append(base(r, r["ans"], r["quote"], "H3", "should_pass")); used_q.add((r["question_id"], r["country_code"]))

    OUT.write_text(json.dumps({"candidates": cands}, indent=2) + "\n")

    from collections import Counter
    summ = Counter((c["stratum"], c["gold_label"]) for c in cands)
    print(f"wrote {OUT}  ({len(cands)} candidates)")
    for k in sorted(summ): print(f"  {k[0]} {k[1]}: {summ[k]}")
    print("\n--- sample H1 evidence swaps (correct answer, non-proving requote) ---")
    for r, q in swaps_done[:4]:
        print(f"\n[{r['country_code']} {r['question_id']}] Q: {r['qtext'][:90]}")
        print(f"   answer: {r['ans']}")
        print(f"   ORIGINAL (supporting) quote: {(r['quote'] or '')[:160]}")
        print(f"   SWAPPED  (non-proving) quote: {q[:160]}")


if __name__ == "__main__":
    main()
