"""Cross-family inter-rater reliability backfill for EXP-1 (DIY vs Tavily).

EXP-1 was judged by Claude Opus and is finished: its result JSONL froze the
evidence and recorded a seeded 30% reliability subsample. The same-family
self-preference control planned for that subsample (pre-registration section 4)
was meant to be a Gemini cross-family re-judge, but Gemini's free quota is zero,
so that arm was skipped (HTTP 429). Two further cross-family judges are wired in
their place, selected with ``--judge``: Groq-hosted Llama 3.3 70B and Mistral
Large. Both are clearly independent of Anthropic. Groq enforces its free-tier
token cap **per organisation, not per key**, so once its one daily pool is spent
every key in the organisation is blocked (HTTP 429); Mistral is a separate
family on a separate quota and is the fallback when Groq's daily pool is gone.

This script re-judges the SAME frozen subsample with the selected judge, reading
the evidence straight out of the EXP-1 result JSONL. Nothing is re-fetched and
EXP-1 is not re-run: the evidence each judge sees is byte-identical, so the only
thing that changes between the Opus verdict and the cross-family verdict is the
judge. That is the point of the check. It rebuts "the Claude judge favours
Claude-built DIY evidence" by showing whether a cross-family judge agrees.

Procedure, per subsample pair:
  1. read the frozen DIY and Tavily evidence and the gold answer,
  2. run the cross-family judge position-swapped exactly as the Opus judge did:
     orientation 1 with evidence_a=DIY, evidence_b=Tavily; orientation 2 swapped,
  3. map each blind A/B/tie/both_fail verdict into the DIY frame with
     ``orientation_to_diy`` and combine with ``combine_orientations`` into one
     judge verdict, in the same DIY frame as the recorded Opus verdict,
  4. answer-given (NOT answer-blind), to match the Opus ``verdict`` field.

It then pairs (opus_verdict, judge_verdict) per pair and reports raw agreement,
Krippendorff's alpha (nominal, four categories diy/tavily/tie/both_fail) and a
confusion breakdown. A pair on which the judge errors is recorded with its
error, excluded from the alpha and agreement denominators, and counted.

Verdicts are cached via ``cached_adjudicate`` keyed by model, so the run is
resumable, replays already-judged orientations for free, and never collides
across judges (each judge model is a separate cache key).

Usage:
    uv run python evaluation/cross_family_backfill.py \
        --result evaluation/results/diy_vs_tavily_20260602_175403.jsonl \
        --judge mistral
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import List, Optional

from agents.tools.search_adjudicator_groq import GROQ_JUDGE_MODEL, adjudicate_groq
from agents.tools.search_adjudicator_mistral import (
    MISTRAL_JUDGE_MODEL,
    adjudicate_mistral,
)
from evaluation.adjudication_cache import cached_adjudicate
from evaluation.diy_vs_tavily import (
    _pair_id,
    combine_orientations,
    orientation_to_diy,
)
from evaluation.stats import krippendorff_alpha

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"

# The cross-family judges this backfill can run, selected with ``--judge``. Each
# maps to its ``adjudicate_*`` function and default model. Both are independent
# of Anthropic (section 4). Groq's free tier caps tokens per organisation, so
# Mistral is the fallback when Groq's daily pool is exhausted.
JUDGES = {
    "groq": (adjudicate_groq, GROQ_JUDGE_MODEL),
    "mistral": (adjudicate_mistral, MISTRAL_JUDGE_MODEL),
}
DEFAULT_JUDGE = "groq"

# EXP-1 is a single finished run, so the backfill defaults to its result file
# and writes one fixed (date-free) artefact, overwritten on a re-run rather than
# a dated series. Both are overridable on the CLI.
DEFAULT_RESULT = RESULTS_DIR / "diy_vs_tavily_20260602_175403.jsonl"
DEFAULT_OUT = RESULTS_DIR / "cross_family_exp1.jsonl"

# The four verdict categories in the DIY frame, fixed so the confusion matrix
# and the alpha computation cover every cell even when a category is unobserved.
VERDICTS = ("diy", "tavily", "tie", "both_fail")


# Frozen-result parsing

def load_result(path: Path) -> tuple[dict, dict[str, dict]]:
    """Read an EXP-1 result JSONL into its summary line and a record index.

    Returns ``(summary, by_pair_id)`` where ``summary`` is the first JSON line
    (which carries the ``subsample`` manifest and the Opus ``model``) and
    ``by_pair_id`` maps each per-pair record's ``question_id/country_code`` to
    the record. Raises ValueError if the file is empty, so a wrong path fails
    loud rather than silently producing an empty backfill.
    """
    summary: Optional[dict] = None
    by_pair_id: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if i == 0:
                summary = obj
                continue
            by_pair_id[_pair_id(obj)] = obj
    if summary is None:
        raise ValueError(f"{path} is empty: no summary line to read the subsample from.")
    return summary, by_pair_id


def subsample_records(summary: dict, by_pair_id: dict[str, dict]) -> List[dict]:
    """Resolve the summary's subsample pair_ids to their per-pair records.

    The subsample manifest is the frozen draw recorded by EXP-1, so re-judging
    exactly these pairs reproduces the pre-registered reliability sample. A
    pair_id in the manifest with no matching per-pair record is a corrupt result
    file, so it raises rather than quietly shrink the sample.
    """
    sub = summary.get("subsample") or {}
    pair_ids = sub.get("pair_ids") or []
    out: List[dict] = []
    missing: List[str] = []
    for pid in pair_ids:
        rec = by_pair_id.get(pid)
        if rec is None:
            missing.append(pid)
            continue
        out.append(rec)
    if missing:
        raise ValueError(
            "Subsample pair_ids absent from the per-pair records: "
            f"{missing}. The result file is inconsistent."
        )
    return out


# Cross-family re-judge of one frozen pair

def judge_verdict_for(
    rec: dict,
    *,
    adjudicate_fn=adjudicate_groq,
    model: str = GROQ_JUDGE_MODEL,
) -> dict:
    """Re-judge one frozen pair cross-family, position-swapped, in the DIY frame.

    Runs the cross-family judge twice on the record's frozen evidence:
    orientation 1 with DIY as evidence_a and Tavily as evidence_b, orientation 2
    swapped. Answer-given (answer_blind=False) to match the Opus ``verdict``
    recorded in the result file. Each blind A/B verdict is mapped into the DIY
    frame with ``orientation_to_diy`` (DIY is "A" in orientation 1, "B" in
    orientation 2) and the two are combined with ``combine_orientations``
    exactly as the main Opus judge combines them, so the cross-family verdict
    and the Opus verdict are formed identically and are directly comparable.

    ``adjudicate_fn`` and ``model`` select the judge (``adjudicate_groq`` /
    ``GROQ_JUDGE_MODEL`` by default, ``adjudicate_mistral`` /
    ``MISTRAL_JUDGE_MODEL`` for the fallback). Calls route through
    ``cached_adjudicate`` so verdicts are cached, keyed separately by model
    (no cross-judge collision), and the run is resumable.
    """
    judge = partial(cached_adjudicate, model=model, adjudicate_fn=adjudicate_fn)
    diy_ev = rec.get("diy_evidence") or []
    tav_ev = rec.get("tavily_evidence") or []
    gold = rec["gold"]
    question_text = rec.get("question_text") or rec["question_id"]

    # Orientation 1: A = DIY, B = Tavily.
    v1, _ = judge(
        question_text=question_text, ground_truth=gold,
        evidence_a=diy_ev, evidence_b=tav_ev, answer_blind=False,
    )
    o1 = orientation_to_diy(v1.winner, diy_is="A")

    # Orientation 2: A = Tavily, B = DIY (positions swapped).
    v2, _ = judge(
        question_text=question_text, ground_truth=gold,
        evidence_a=tav_ev, evidence_b=diy_ev, answer_blind=False,
    )
    o2 = orientation_to_diy(v2.winner, diy_is="B")

    combined = combine_orientations(o1, o2)
    # Store the full orientation receipt (raw winner, supports flags, reasoning,
    # confidence) in the same shape EXP-1 records its Opus orientations, so a
    # marker can audit every Groq judgement, not only the DIY-frame label.
    return {
        "verdict": combined["verdict"],
        "consistent": combined["consistent"],
        "orientation_1": {"winner": v1.winner, "diy_frame": o1,
                          "diy_supports": v1.answer_supported_by_a,
                          "tavily_supports": v1.answer_supported_by_b,
                          "reasoning": v1.reasoning, "confidence": v1.confidence},
        "orientation_2": {"winner": v2.winner, "diy_frame": o2,
                          "tavily_supports": v2.answer_supported_by_a,
                          "diy_supports": v2.answer_supported_by_b,
                          "reasoning": v2.reasoning, "confidence": v2.confidence},
    }


# Pairing + agreement + alpha (pure, unit-tested)

def compute_reliability(per_pair: List[dict]) -> dict:
    """Raw agreement, Krippendorff's alpha, and a confusion breakdown.

    ``per_pair`` is one dict per subsample pair. A judged pair carries both an
    ``opus_verdict`` and a ``judge_verdict``; a pair on which the judge errored
    carries an ``error`` key and no judge verdict. Errored pairs are excluded
    from both the agreement denominator and the alpha units and counted under
    ``n_errors``, so a judge failure never silently distorts the statistics.

    Returns the subsample size, the judged count, the error count, raw agreement
    (fraction of judged pairs with identical verdicts), Krippendorff's alpha
    over the judged pairs (nominal, the four DIY-frame categories), and a
    confusion breakdown as a nested ``opus -> judge -> count`` mapping plus a
    flat ``(opus, judge) -> count`` list for the printout.
    """
    judged = [p for p in per_pair if "error" not in p and p.get("judge_verdict") is not None]
    errored = [p for p in per_pair if p not in judged]

    units = [[p["opus_verdict"], p["judge_verdict"]] for p in judged]
    agree = sum(1 for p in judged if p["opus_verdict"] == p["judge_verdict"])
    n_judged = len(judged)

    confusion: dict[str, dict[str, int]] = {
        o: {g: 0 for g in VERDICTS} for o in VERDICTS
    }
    for p in judged:
        o, g = p["opus_verdict"], p["judge_verdict"]
        confusion.setdefault(o, {}).setdefault(g, 0)
        confusion[o][g] += 1

    return {
        "n_subsample": len(per_pair),
        "n_judged": n_judged,
        "n_errors": len(errored),
        "raw_agreement": agree / n_judged if n_judged else 0.0,
        "krippendorff_alpha": (
            krippendorff_alpha(units, level="nominal") if units else None
        ),
        "confusion": confusion,
    }


def _confusion_lines(confusion: dict[str, dict[str, int]]) -> List[str]:
    """Human-readable off-zero confusion cells, agreements first then misses."""
    diag = [
        f"    {v:<10} agree: {confusion.get(v, {}).get(v, 0)}"
        for v in VERDICTS
        if confusion.get(v, {}).get(v, 0)
    ]
    off = [
        f"    opus={o:<10} judge={g:<10} : {confusion[o][g]}"
        for o in VERDICTS
        for g in VERDICTS
        if o != g and confusion.get(o, {}).get(g, 0)
    ]
    return diag + off


# Driver

def run_backfill(
    result_path: Path,
    *,
    judge: str = DEFAULT_JUDGE,
    model: Optional[str] = None,
) -> dict:
    """Re-judge the frozen subsample cross-family and compute reliability.

    Reads the EXP-1 result file, resolves the subsample, re-judges each pair
    with the selected cross-family judge (position-swapped, answer-given), and
    returns a result dict ready to serialise: a ``summary`` block plus a
    ``per_pair`` list. A judge error on a single pair is caught, recorded
    against that pair, and does not stop the rest, so one bad pair cannot sink
    the run.

    ``judge`` names the judge family in ``JUDGES`` (``groq`` default, ``mistral``
    fallback); ``model`` overrides that family's default model when given.
    """
    if judge not in JUDGES:
        raise ValueError(f"Unknown judge {judge!r}; choose one of {sorted(JUDGES)}.")
    adjudicate_fn, default_model = JUDGES[judge]
    model = model or default_model

    summary, by_pair_id = load_result(result_path)
    opus_model = summary.get("model")
    records = subsample_records(summary, by_pair_id)

    per_pair: List[dict] = []
    for i, rec in enumerate(records, 1):
        pid = _pair_id(rec)
        opus_verdict = rec["verdict"]
        try:
            judged = judge_verdict_for(rec, adjudicate_fn=adjudicate_fn, model=model)
        except Exception as exc:  # noqa: BLE001 - one bad pair must not sink the rest
            per_pair.append({
                "pair_id": pid,
                "opus_verdict": opus_verdict,
                "judge_verdict": None,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  [{i}/{len(records)}] {pid}: {judge.upper()} ERROR "
                  f"{type(exc).__name__}: {exc}")
            continue
        per_pair.append({
            "pair_id": pid,
            "opus_verdict": opus_verdict,
            "judge_verdict": judged["verdict"],
            "judge_consistent": judged["consistent"],
            "judge_orientation_1": judged["orientation_1"],
            "judge_orientation_2": judged["orientation_2"],
        })
        agree_mark = "==" if judged["verdict"] == opus_verdict else "!="
        flag = "" if judged["consistent"] else "  (position-inconsistent)"
        print(f"  [{i}/{len(records)}] {pid}: opus={opus_verdict} {agree_mark} "
              f"{judge}={judged['verdict']}{flag}")

    rel = compute_reliability(per_pair)
    summary_out = {
        "result_file": str(result_path),
        "opus_model": opus_model,
        "judge_family": judge,
        "judge_model": model,
        "n_subsample": rel["n_subsample"],
        "n_judged": rel["n_judged"],
        "n_errors": rel["n_errors"],
        "raw_agreement": rel["raw_agreement"],
        "krippendorff_alpha": rel["krippendorff_alpha"],
        "confusion": rel["confusion"],
        "generated_at": datetime.now().strftime("%Y%m%d_%H%M%S"),
    }
    return {"summary": summary_out, "per_pair": per_pair}


def _print_summary(summary: dict) -> None:
    """Print the human-readable summary block to stdout."""
    alpha = summary["krippendorff_alpha"]
    alpha_str = f"{alpha:.3f}" if alpha is not None else "n/a"
    family = summary.get("judge_family", "?")
    print(f"\n=== Cross-family backfill: Opus vs {family} (EXP-1 reliability subsample) ===")
    print(f"  result file            : {summary['result_file']}")
    print(f"  Opus judge (frozen)    : {summary['opus_model']}")
    print(f"  cross-family judge     : {summary['judge_model']}  (family: {family})")
    print(f"  subsample pairs        : {summary['n_subsample']}")
    print(f"  judged cross-family    : {summary['n_judged']}")
    print(f"  judge errors           : {summary['n_errors']}  "
          f"(excluded from agreement and alpha)")
    print(f"  RAW AGREEMENT          : {summary['raw_agreement']:.0%}  "
          f"(fraction of judged pairs with identical verdicts)")
    print(f"  Krippendorff alpha     : {alpha_str}  (nominal, 4 categories)")
    print(f"  confusion (opus vs {family}):")
    for ln in _confusion_lines(summary["confusion"]):
        print(ln)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-family re-judge of a frozen EXP-1 subsample"
    )
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT,
                        help="EXP-1 DIY-vs-Tavily result JSONL to re-judge "
                             "(default: the 20260602 run)")
    parser.add_argument("--judge", type=str, default=DEFAULT_JUDGE,
                        choices=sorted(JUDGES),
                        help=f"cross-family judge family (default: {DEFAULT_JUDGE}; "
                             "use 'mistral' when Groq's daily org cap is spent)")
    parser.add_argument("--model", type=str, default=None,
                        help="judge model override (default: the family's "
                             f"default, e.g. {GROQ_JUDGE_MODEL} / {MISTRAL_JUDGE_MODEL})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="output JSONL (default: cross_family_exp1.jsonl)")
    args = parser.parse_args(argv)

    if not args.result.exists():
        print(f"Result file not found: {args.result}", file=sys.stderr)
        return 2

    out = run_backfill(args.result, judge=args.judge, model=args.model)
    summary = out["summary"]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out
    with out_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        for p in out["per_pair"]:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    _print_summary(summary)
    print(f"\nWrote {len(out['per_pair'])} per-pair records to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
