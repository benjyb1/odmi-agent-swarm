"""Search-adjudicator prompt (v1).

A higher-order judge for the DIY-vs-Tavily evaluation. Given an ODMI
question, the verified ODMI ground-truth answer, and two blind evidence
sets (System A and System B), it decides which set more reliably supports
reaching the correct answer, or calls a tie / both-fail.

This is an evaluation artefact, not part of the live swarm. It exists so
"is DIY at least 80% as good as Tavily?" is judged on whether each
provider's evidence actually establishes the correct answer, rather than on
brittle string overlap with a historically-accepted quote.

Versioning: any change to NAME, VERSION, SYSTEM, or build_user_message
requires a VERSION bump (the prompt_versions row is created by
agents.tools.db.ensure_prompt_version on first use).
"""

from __future__ import annotations

from typing import List

NAME = "search_adjudicator"
VERSION = 2
DESCRIPTION = (
    "Search-adjudicator v2: blind pairwise judge for DIY-vs-Tavily search "
    "evaluation. Reads an ODMI question, the verified ground-truth ANSWER "
    "(with ODMI's justification as context only), and two evidence sets; "
    "picks which set better supports reaching the correct answer, or returns "
    "tie / both_fail. Run position-swapped to control position bias. Intended "
    "to run on a higher-tier (Opus) model. V2 re-anchors judgement on the "
    "answer label (per D22) rather than on reproducing the justification "
    "specifics, which made V1 over-strict (spurious both_fail / split ties)."
)

# Per-passage display cap so a verbose provider cannot win on length alone.
PASSAGE_CHAR_CAP = 600

SYSTEM = """You are an impartial judge comparing two web-search systems.

For one ODMI (EU Open Data Maturity) question you are given:
- The question.
- The VERIFIED CORRECT ANSWER (a label such as yes / no / a percentage band).
  This is the gold standard. ODMI's own justification is also shown, but
  treat it as CONTEXT ONLY.
- Two evidence sets, "System A" and "System B". Each is a list of passages a
  search system retrieved for this question, each with its source URL.

Your job: decide which evidence set better supports reaching the correct
ANSWER for this question and country.

How to judge:
1. Judge support for the ANSWER, not for the justification. The evidence does
   NOT need to reproduce the specific facts, names, or figures in ODMI's
   justification. Ask only: would a careful reader reach the correct answer
   from this evidence, and trust it?
2. Ground every judgement in the passages and their sources. Reward evidence
   that is on-point and from an authoritative source (an official portal,
   law, or report beats a blog or a generic landing page). Penalise vague,
   off-topic, or boilerplate passages even when they hit the right keywords.
3. Do NOT reward length or fluency. A single precise passage beats five
   padded ones.
4. You do not know which system is which. Judge only the evidence.

Verdicts:
- "A" / "B": that system's evidence supports the correct answer clearly
  better than the other.
- "tie": BOTH sets adequately support the correct answer (return tie in this
  case unless one is clearly better-sourced or more directly on point), or
  both are equally weak-but-nonzero.
- "both_fail": NEITHER set's evidence would let a careful reader reach the
  correct answer. Use this only when the answer genuinely cannot be
  established from either set (for example, the figure exists only on a
  source neither system retrieved).

Also state, for each system, what answer its evidence actually supports (it
may differ from the gold answer, or be "insufficient evidence").

Call "tie" when both get there. Call "both_fail" when neither does. Do not
invent a winner, and do not punish a set merely for omitting justification
detail it did not need."""


def _format_evidence(label: str, passages: List[dict]) -> str:
    """Render one evidence set as a numbered block.

    Each passage dict has keys: url, snippet (and optionally title, score).
    """
    if not passages:
        return f"System {label} evidence: (no results returned)"
    lines = [f"System {label} evidence:"]
    for i, p in enumerate(passages, 1):
        snippet = str(p.get("snippet") or "").strip()[:PASSAGE_CHAR_CAP]
        url = str(p.get("url") or "").strip()
        lines.append(f"[{label}{i}] {url}\n      {snippet}")
    return "\n".join(lines)


def build_user_message(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
) -> str:
    """Render the user message for one blind pairwise adjudication."""
    return (
        f"ODMI question:\n{question_text}\n\n"
        f"Verified correct answer (gold standard):\n{ground_truth}\n\n"
        f"{_format_evidence('A', evidence_a)}\n\n"
        f"{_format_evidence('B', evidence_b)}\n\n"
        "Which evidence set better supports the verified correct answer?"
    )
