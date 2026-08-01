"""Adjudicated DIY-vs-Tavily search evaluation.

Measures whether the DIY pipeline retrieves evidence that answers ODMI
questions at least as well as Tavily, judged by a higher-order Opus
adjudicator rather than by string overlap with a historically-accepted
quote (which penalises a different-but-valid passage).

For each (question, country) pair in a dimension-stratified sample of the
swarm's finalised pairs:
  1. fetch top-k evidence from DIY and from Tavily for the same query,
  2. show both sets BLIND (System A / System B) to the adjudicator, with
     the verified ODMI answer as the gold standard,
  3. run the judge twice with positions swapped to control position bias,
  4. combine into one verdict (diy / tavily / tie / both_fail).

Primary endpoint (EXP-1, pre-registration section 5): the DIY win share of
DECIDED head-to-heads, reported as a point estimate with a Wilson 95%
confidence interval and an exact binomial sign test against 0.5. Ties are
never counted as DIY successes.

What "decided" means here, stated precisely: a pair is decided when its
COMBINED two-orientation verdict (see ``combine_orientations``) is diy or
tavily, i.e. the DIY-signed score over the two position-swapped judgements is
non-zero. A single-orientation ``both_fail`` does NOT exclude a pair: it
scores zero, so it is overridden when the other orientation is decisive. Only
a both-orientation ``both_fail`` and a pure diy/tavily position flip (which
nets to a tie) are excluded. On the frozen EXP-1 run this lenient rule gives
49/55 = 89% [78, 95]. As a sensitivity check, requiring BOTH orientations to
be decisive (dropping the 10 pairs where one orientation was ``both_fail``)
gives 42/45 = 93% [82, 98]: the conclusion is unchanged either way. The full
four-way distribution and the per-dimension spread are reported alongside.

Robustness on a seeded 30% subsample (section 4): an answer-blind re-judge
(leakage control) and, where the Gemini key authenticates, a cross-family
re-judge with Krippendorff's alpha (same-family self-preference control).

Evidence sets, both raw verdicts, and reasoning are written to a JSONL so
every judgement is auditable (receipts per the dissertation standard).

Usage:
    uv run python evaluation/diy_vs_tavily.py --limit 40
    uv run python evaluation/diy_vs_tavily.py --countries FR --limit 2  # smoke
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Sequence

from evaluation.stats import krippendorff_alpha, sign_test, wilson_interval

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "odmi.db"
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"
CACHE_PATH = REPO_ROOT / "evaluation" / ".cache_diy_vs_tavily.json"

GOLD_EXPLANATION_CAP = 800

# Reliability subsample (pre-registration section 5): a simple random sample
# without replacement, 30% of judged pairs, RNG seed 20260602. Both are fixed
# here and exposed as CLI overrides; the seed and selected pair IDs are written
# into the JSONL so the draw is reproducible and verifiably not post hoc.
SUBSAMPLE_SEED = 20260602
SUBSAMPLE_FRAC = 0.30

# Dimensions excluded from the E2 head-to-head by default (section 3): Quality
# gold answers live on the deny-listed data.europa.eu MQA or are national
# self-reports, so they both-fail and carry no retrieval-quality signal.
DEFAULT_EXCLUDE_DIMENSIONS = ["Quality"]


# Pure logic (unit-tested in tests/test_diy_vs_tavily_eval.py)

def dimension_of(question_id: str) -> str:
    """Leading alpha prefix of a question id: I / P / PT / Q."""
    m = re.match(r"^[A-Za-z]+", question_id)
    return m.group(0) if m else "?"


def filter_pairs(
    pairs: List[dict],
    countries: Optional[Sequence[str]] = None,
    exclude_dimensions: Optional[Sequence[str]] = None,
) -> List[dict]:
    """Filter pairs by country and drop excluded ODMI dimensions.

    Pure so it is unit-testable without a DB. ``countries=None`` keeps every
    country; otherwise the match is case-insensitive on the two-letter code.
    ``exclude_dimensions`` is matched case-insensitively against the
    human-readable ``dimension`` column ("Quality", "Policy", ...), so the
    web-answerable stratum is a single objective column filter (section 3),
    not an investigator call.
    """
    keep_cc = {c.upper() for c in countries} if countries else None
    drop_dim = {d.lower() for d in (exclude_dimensions or [])}
    out = []
    for p in pairs:
        if keep_cc is not None and p["country_code"].upper() not in keep_cc:
            continue
        if (p.get("dimension") or "").lower() in drop_dim:
            continue
        out.append(p)
    return out


def stratify_pairs(pairs: List[dict], limit: int) -> List[dict]:
    """Dedupe by (question, country), then round-robin across ODMI dimensions.

    The sample is approximately balanced across Policy/Portal/Quality/Impact,
    not even: round-robin cannot equalise counts when the dimensions are
    uneven (once the smallest is exhausted the tail fills from the rest), so
    the achieved per-dimension counts are reported with the result."""
    seen = set()
    uniq = []
    for p in pairs:
        key = (p["question_id"], p["country_code"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    groups: dict[str, list] = defaultdict(list)
    for p in uniq:
        groups[dimension_of(p["question_id"])].append(p)

    out: List[dict] = []
    dims = list(groups.keys())
    idx = {d: 0 for d in dims}
    while len(out) < limit:
        progressed = False
        for d in dims:
            if idx[d] < len(groups[d]):
                out.append(groups[d][idx[d]])
                idx[d] += 1
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
    return out


Frame = Literal["diy", "tavily", "tie", "both_fail"]


def orientation_to_diy(winner: str, *, diy_is: Literal["A", "B"]) -> Frame:
    """Map a blind A/B/tie/both_fail verdict into the DIY frame."""
    if winner in ("tie", "both_fail"):
        return winner  # type: ignore[return-value]
    return "diy" if winner == diy_is else "tavily"


_SCORE = {"diy": 1, "tavily": -1, "tie": 0, "both_fail": 0}


def combine_orientations(o1: Frame, o2: Frame) -> dict:
    """Combine the two position-swapped verdicts into one.

    Pure both_fail in both orientations => both_fail. Otherwise sum a
    DIY-signed score: positive => diy, negative => tavily, zero => tie.
    Note that a single-orientation both_fail scores zero, so a pair where
    one orientation is both_fail and the other is decisive resolves to that
    decisive side (the both_fail does not veto it). A diy/tavily
    disagreement (pure position flip) nets to a tie and is flagged
    inconsistent.
    """
    if o1 == "both_fail" and o2 == "both_fail":
        return {"verdict": "both_fail", "consistent": True}
    s = _SCORE[o1] + _SCORE[o2]
    verdict = "diy" if s > 0 else "tavily" if s < 0 else "tie"
    return {"verdict": verdict, "consistent": o1 == o2}


def aggregate(verdicts: List[dict]) -> dict:
    """Counts and descriptive rates over a list of combined verdicts.

    Reports the raw four-way counts (diy/tavily/tie/both_fail), the decisive
    count (n - both_fail), the DIY strict-win rate over all pairs, and the
    position-consistency rate. The head-to-head win share with its Wilson CI
    and sign test is computed separately by ``decided_stats`` over the strictly
    decided subset, so ties can never leak into a "DIY success" numerator."""
    n = len(verdicts)
    counts = {"diy": 0, "tavily": 0, "tie": 0, "both_fail": 0}
    consistent = 0
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        if v.get("consistent"):
            consistent += 1
    decisive = n - counts["both_fail"]
    return {
        "n": n,
        **counts,
        "decisive": decisive,
        "diy_win_rate": counts["diy"] / n if n else 0.0,
        "consistency_rate": consistent / n if n else 0.0,
    }


def decided_stats(
    diy_wins: int, tavily_wins: int, confidence: float = 0.95
) -> dict:
    """Primary E2 statistic: DIY win share of STRICTLY DECIDED head-to-heads.

    The denominator is ``diy_wins + tavily_wins`` only, counting the COMBINED
    two-orientation verdict (see ``combine_orientations``). A combined tie and
    a combined both_fail are excluded; a single-orientation both_fail that was
    overridden by a decisive other orientation is NOT excluded (it lands in
    diy_wins or tavily_wins). See the module docstring for the strict-exclusion
    sensitivity check. Pure, so it is unit-testable.

    Returns the strictly-decided count, the DIY win share, its Wilson
    ``confidence`` interval, and the exact two-sided binomial sign-test p-value
    against the null of symmetry (0.5).
    """
    decided = diy_wins + tavily_wins
    share = diy_wins / decided if decided else 0.0
    low, high = wilson_interval(diy_wins, decided, confidence=confidence)
    return {
        "decided_strict": decided,
        "diy_wins": diy_wins,
        "tavily_wins": tavily_wins,
        "diy_win_share": share,
        "confidence": confidence,
        "wilson_low": low,
        "wilson_high": high,
        "sign_test_p": sign_test(diy_wins, tavily_wins),
    }


def select_subsample(
    records: List[dict], seed: int = SUBSAMPLE_SEED, frac: float = SUBSAMPLE_FRAC
) -> List[dict]:
    """Deterministic simple random sample without replacement (section 5).

    Draws ``round(frac * len(records))`` records with ``random.Random(seed)``,
    so a fixed seed reproduces the draw exactly. A non-empty input yields at
    least one record even when ``round`` would floor to zero, so the robustness
    checks always have something to run on. The selection preserves the input
    order of the chosen records for stable, replayable output.
    """
    n = len(records)
    if n == 0:
        return []
    k = round(frac * n)
    k = max(1, min(k, n))
    rng = random.Random(seed)
    chosen_idx = sorted(rng.sample(range(n), k))
    return [records[i] for i in chosen_idx]


# Live harness (network + DB + LLM)

# Join researcher runs to finals on pair_run_id, the per-(question,country)
# attempt key. NB: run_id is a BATCH id shared across many questions, so
# joining on it mis-associates queries with questions (every prr row in the
# batch matches). pair_run_id is unique to one pair's attempt, so the query
# always belongs to the right question.
_PAIR_QUERY = """
SELECT pf.question_id, pf.country_code, prr.search_queries_used,
       q.question_text, q.dimension, gt.response, gt.explanation
FROM phase2_final pf
JOIN phase2_researcher_runs prr ON pf.pair_run_id = prr.pair_run_id
JOIN questions q ON q.question_id = pf.question_id
LEFT JOIN ground_truth gt
       ON gt.question_id = pf.question_id AND gt.country_code = pf.country_code
WHERE pf.terminal_status IN ('accepted_by_verifier', 'accepted_by_adjudicator')
  AND prr.search_queries_used IS NOT NULL
GROUP BY pf.question_id, pf.country_code
ORDER BY pf.created_at DESC
"""


def _first_query(queries_json: str) -> Optional[str]:
    try:
        qs = json.loads(queries_json) if queries_json else []
    except (TypeError, json.JSONDecodeError):
        return None
    return qs[0] if qs else None


def _trim_question(text: str) -> str:
    # Drop the questionnaire's "For Explanation: ..." filler addressed to the
    # human respondent; keep only the question itself.
    return re.split(r"For Explanation", text)[0].strip()


def _gold(response: Optional[str], explanation: Optional[str]) -> Optional[str]:
    """Gold standard for the judge: the ANSWER label first (this is what D22
    scores), then ODMI's justification flagged as context only so the judge
    does not treat it as a checklist."""
    if not response:
        return None
    exp = (explanation or "").strip()[:GOLD_EXPLANATION_CAP]
    gold = f"ANSWER: {response}"
    if exp:
        gold += (
            "\n\nODMI's justification (context only, the evidence need not "
            f"repeat these specifics): {exp}"
        )
    return gold


def build_eval_set(
    db_path: Path,
    countries: Optional[Sequence[str]] = None,
    exclude_dimensions: Optional[Sequence[str]] = None,
) -> List[dict]:
    """Read finalised pairs with a query and ground truth, then filter.

    Applies the country filter and the dimension exclusion (section 3) before
    returning. No stratify or subsample yet. ``exclude_dimensions=None`` means
    no exclusion here; the CLI passes its default explicitly."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(_PAIR_QUERY).fetchall()
    out = []
    for qid, cc, queries_json, qtext, dim, resp, expl in rows:
        query = _first_query(queries_json)
        gold = _gold(resp, expl)
        if not query or not gold:
            continue  # cannot search or cannot judge against truth
        out.append({
            "question_id": qid,
            "country_code": cc,
            "dimension": dim,
            "query": query,
            "question_text": _trim_question(qtext or qid),
            "gold": gold,
        })
    return filter_pairs(out, countries=countries, exclude_dimensions=exclude_dimensions)


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def get_evidence(query: str, provider: str, *, max_results: int, cache: dict) -> List[dict]:
    """Top-k evidence for one query/provider, cached to disk so the run is
    re-playable and Tavily quota is spent at most once per query."""
    from agents.tools.search import search

    key = f"{provider}::{max_results}::{query}"
    if key in cache:
        return cache[key]
    results = search(query, max_results=max_results, provider=provider)
    evidence = [
        {"url": r.url, "snippet": r.snippet, "title": r.title, "score": r.score}
        for r in results
    ]
    cache[key] = evidence
    return evidence


def _judge_orientations(
    judge_fn,
    *,
    question_text: str,
    gold: str,
    diy_ev: List[dict],
    tav_ev: List[dict],
    answer_blind: bool = False,
) -> dict:
    """Run one judge twice with DIY/Tavily positions swapped and combine.

    ``judge_fn`` is any adjudicator with the shared signature (adjudicate or
    adjudicate_gemini). The blind/position-swap/verdict-combination logic is
    identical across judges and answer-blind modes; only the judge and the
    answer_blind flag change. Returns the combined verdict and both raw
    orientations in the DIY frame.
    """
    # Orientation 1: A = DIY, B = Tavily
    v1, _ = judge_fn(
        question_text=question_text, ground_truth=gold,
        evidence_a=diy_ev, evidence_b=tav_ev, answer_blind=answer_blind,
    )
    o1 = orientation_to_diy(v1.winner, diy_is="A")

    # Orientation 2: A = Tavily, B = DIY (positions swapped)
    v2, _ = judge_fn(
        question_text=question_text, ground_truth=gold,
        evidence_a=tav_ev, evidence_b=diy_ev, answer_blind=answer_blind,
    )
    o2 = orientation_to_diy(v2.winner, diy_is="B")

    combined = combine_orientations(o1, o2)
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


def judge_pair(pair: dict, *, max_results: int, model: str, cache: dict) -> dict:
    """Fetch both providers' evidence and run the position-swapped Opus judge.

    Freezes both arms' evidence into the record (single-pass snapshot) so a
    later answer-blind or cross-family re-judge reads the identical passages.
    """
    from functools import partial

    from evaluation.adjudication_cache import cached_adjudicate

    diy_ev = get_evidence(pair["query"], "diy", max_results=max_results, cache=cache)
    tav_ev = get_evidence(pair["query"], "tavily", max_results=max_results, cache=cache)

    judged = _judge_orientations(
        partial(cached_adjudicate, model=model),
        question_text=pair["question_text"], gold=pair["gold"],
        diy_ev=diy_ev, tav_ev=tav_ev, answer_blind=False,
    )
    return {
        "question_id": pair["question_id"],
        "country_code": pair["country_code"],
        "dimension": pair["dimension"],
        "query": pair["query"],
        "question_text": pair["question_text"],
        "gold": pair["gold"],
        "diy_n": len(diy_ev),
        "tavily_n": len(tav_ev),
        "verdict": judged["verdict"],
        "consistent": judged["consistent"],
        "orientation_1": judged["orientation_1"],
        "orientation_2": judged["orientation_2"],
        "diy_evidence": diy_ev,
        "tavily_evidence": tav_ev,
    }


def _pair_id(rec: dict) -> str:
    """Stable pair identifier for the subsample manifest: question/country."""
    return f"{rec['question_id']}/{rec['country_code']}"


def run_answer_blind_subsample(subsample: List[dict], *, model: str) -> dict:
    """Re-judge the frozen evidence answer-blind (leakage control, section 4).

    Reuses each record's frozen DIY/Tavily evidence, so the only change from
    the main run is that the gold label is withheld. Reports the answer-blind
    verdict per pair, the raw agreement with the answer-given verdict, and the
    count of verdict flips.
    """
    from functools import partial

    from evaluation.adjudication_cache import cached_adjudicate

    judge = partial(cached_adjudicate, model=model)
    per_pair = []
    agree = 0
    flips = 0
    for rec in subsample:
        blind = _judge_orientations(
            judge,
            question_text=rec.get("question_text", rec["question_id"]),
            gold=rec["gold"],
            diy_ev=rec["diy_evidence"], tav_ev=rec["tavily_evidence"],
            answer_blind=True,
        )
        same = blind["verdict"] == rec["verdict"]
        agree += int(same)
        flips += int(not same)
        per_pair.append({
            "pair_id": _pair_id(rec),
            "answer_given_verdict": rec["verdict"],
            "answer_blind_verdict": blind["verdict"],
            "consistent": blind["consistent"],
            "orientation_1": blind["orientation_1"],
            "orientation_2": blind["orientation_2"],
        })
    n = len(subsample)
    return {
        "n": n,
        "agreement_rate": agree / n if n else 0.0,
        "flips": flips,
        "per_pair": per_pair,
    }


def run_gemini_subsample(subsample: List[dict], *, answer_blind: bool = False) -> dict:
    """Cross-family Gemini re-judge of the frozen evidence (section 4, 5).

    Probes the Gemini key first. If auth fails (e.g. zero quota), records the
    precise upstream reason under ``gemini_status`` and SKIPS gracefully rather
    than crash the run. On success, re-judges every subsample pair, reports the
    Opus-vs-Gemini raw agreement and Krippendorff's alpha (nominal, four
    categories), and writes the per-pair Gemini verdicts.
    """
    from agents.tools.search_adjudicator_gemini import adjudicate_gemini, probe_auth

    probe = probe_auth()
    if not probe.get("ok"):
        reason = probe.get("error", "unknown Gemini auth failure")
        return {"ran": False, "gemini_status": reason}

    per_pair = []
    units: List[list] = []
    agree = 0
    for rec in subsample:
        try:
            judged = _judge_orientations(
                adjudicate_gemini,
                question_text=rec.get("question_text", rec["question_id"]),
                gold=rec["gold"],
                diy_ev=rec["diy_evidence"], tav_ev=rec["tavily_evidence"],
                answer_blind=answer_blind,
            )
        except Exception as exc:  # noqa: BLE001 - one bad pair must not sink the rest
            per_pair.append({"pair_id": _pair_id(rec),
                             "error": f"{type(exc).__name__}: {exc}"})
            continue
        agree += int(judged["verdict"] == rec["verdict"])
        units.append([rec["verdict"], judged["verdict"]])
        per_pair.append({
            "pair_id": _pair_id(rec),
            "opus_verdict": rec["verdict"],
            "gemini_verdict": judged["verdict"],
            "consistent": judged["consistent"],
            "orientation_1": judged["orientation_1"],
            "orientation_2": judged["orientation_2"],
        })
    n_judged = len(units)
    return {
        "ran": True,
        "gemini_status": "ok",
        "model": probe.get("model"),
        "answer_blind": answer_blind,
        "n_judged": n_judged,
        "agreement_rate": agree / n_judged if n_judged else 0.0,
        "krippendorff_alpha": krippendorff_alpha(units, level="nominal") if units else None,
        "per_pair": per_pair,
    }


def _git_commit_sha() -> Optional[str]:
    """Current commit SHA for the reproducibility stamp; None on any failure."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 - git absent / not a repo / timeout
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Adjudicated DIY-vs-Tavily evaluation")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=40, help="eval-set size (stratified)")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--model", type=str, default=None,
                        help="adjudicator model override (default: Opus)")
    parser.add_argument("--countries", nargs="*", default=None,
                        help="restrict to these country codes (default: all)")
    parser.add_argument("--exclude-dimensions", nargs="*",
                        default=list(DEFAULT_EXCLUDE_DIMENSIONS),
                        help="ODMI dimensions to drop (default: Quality)")
    parser.add_argument("--subsample-seed", type=int, default=SUBSAMPLE_SEED,
                        help="RNG seed for the reliability subsample")
    parser.add_argument("--subsample-frac", type=float, default=SUBSAMPLE_FRAC,
                        help="fraction of judged pairs in the reliability subsample")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from agents.tools.search_adjudicator import ADJUDICATOR_MODEL
    model = args.model or ADJUDICATOR_MODEL

    full = build_eval_set(
        args.db, countries=args.countries,
        exclude_dimensions=args.exclude_dimensions,
    )
    pairs = stratify_pairs(full, args.limit)
    print(f"Eval set: {len(pairs)} pairs (from {len(full)} judgeable), "
          f"adjudicator model={model}")
    print(f"Filters: countries={args.countries or 'all'} "
          f"exclude_dimensions={args.exclude_dimensions or 'none'}")
    # Achieved per-dimension and per-country counts on the selected sample.
    dist = defaultdict(int)
    bycc = defaultdict(int)
    for p in pairs:
        dist[p["dimension"]] += 1
        bycc[p["country_code"]] += 1
    print(f"Achieved dimension counts: {dict(sorted(dist.items()))}")
    print(f"Achieved country counts  : {dict(sorted(bycc.items()))}")

    cache = _load_cache()
    records = []
    for i, pair in enumerate(pairs, 1):
        tag = f"{pair['question_id']}/{pair['country_code']}"
        try:
            rec = judge_pair(pair, max_results=args.max_results, model=model, cache=cache)
            records.append(rec)
            flag = "" if rec["consistent"] else "  (position-inconsistent)"
            print(f"  [{i}/{len(pairs)}] {tag}: {rec['verdict']}"
                  f"  diy={rec['diy_n']} tav={rec['tavily_n']}{flag}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(pairs)}] {tag}: ERROR {type(exc).__name__}: {exc}")
        finally:
            _save_cache(cache)

    agg = aggregate([{"verdict": r["verdict"], "consistent": r["consistent"]}
                     for r in records])
    # Primary E2 statistic: win share of STRICTLY DECIDED head-to-heads
    # (ties and both_fail excluded), with a Wilson CI and a sign test.
    stats = decided_stats(agg["diy"], agg["tavily"])

    print("\n=== DIY vs Tavily (adjudicated) ===")
    print(f"  judged pairs           : {agg['n']}")
    print(f"  DIY wins               : {agg['diy']}")
    print(f"  ties                   : {agg['tie']}")
    print(f"  Tavily wins            : {agg['tavily']}")
    print(f"  both failed            : {agg['both_fail']}  "
          f"(question unanswerable from open web / answer on deny-list)")
    print(f"  decided (strict)       : {stats['decided_strict']}  "
          f"(diy_wins + tavily_wins; ties and both_fail excluded)")
    print(f"  DIY WIN SHARE (decided): {stats['diy_win_share']:.0%}  "
          f"<- primary endpoint")
    print(f"  Wilson 95% CI          : [{stats['wilson_low']:.0%}, "
          f"{stats['wilson_high']:.0%}]")
    print(f"  sign-test p (vs 0.5)   : {stats['sign_test_p']:.4f}")
    print(f"  DIY strict win rate    : {agg['diy_win_rate']:.0%}  (over all pairs)")
    print(f"  position consistency   : {agg['consistency_rate']:.0%}")

    # Per-dimension verdict spread (shows the both_fail concentration).
    bydim: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in records:
        bydim[r["dimension"]][r["verdict"]] += 1
    print("\n  per-dimension verdicts (diy/tie/tavily/both_fail):")
    for dim in sorted(bydim):
        d = bydim[dim]
        print(f"    {dim:<8} {d['diy']}/{d['tie']}/{d['tavily']}/{d['both_fail']}")

    # Seeded 30% subsample: robustness checks (section 4)
    subsample = select_subsample(records, seed=args.subsample_seed,
                                 frac=args.subsample_frac)
    subsample_ids = [_pair_id(r) for r in subsample]
    print(f"\n=== Robustness subsample (seed {args.subsample_seed}, "
          f"frac {args.subsample_frac:.0%}, n={len(subsample)}) ===")
    print(f"  pairs: {subsample_ids}")

    blind = run_answer_blind_subsample(subsample, model=model) if subsample else {
        "n": 0, "agreement_rate": 0.0, "flips": 0, "per_pair": []}
    if subsample:
        print(f"  answer-blind vs answer-given agreement : "
              f"{blind['agreement_rate']:.0%}  ({blind['flips']} verdict flips)")

    gemini = run_gemini_subsample(subsample) if subsample else {
        "ran": False, "gemini_status": "no subsample"}
    if gemini.get("ran"):
        alpha = gemini.get("krippendorff_alpha")
        alpha_str = f"{alpha:.3f}" if alpha is not None else "n/a"
        print(f"  Gemini cross-family agreement          : "
              f"{gemini['agreement_rate']:.0%}  (n={gemini['n_judged']})")
        print(f"  Krippendorff alpha (Opus vs Gemini)    : {alpha_str}")
    else:
        print(f"  Gemini cross-family judge SKIPPED: {gemini.get('gemini_status')}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.out or (RESULTS_DIR / f"diy_vs_tavily_{stamp}.jsonl")
    summary = {
        "summary": agg,
        "decided_stats": stats,
        "model": model,
        "generated_at": stamp,
        "git_commit": _git_commit_sha(),
        "filters": {
            "countries": list(args.countries) if args.countries else None,
            "exclude_dimensions": list(args.exclude_dimensions or []),
            "limit": args.limit,
            "max_results": args.max_results,
        },
        "subsample": {
            "seed": args.subsample_seed,
            "frac": args.subsample_frac,
            "pair_ids": subsample_ids,
        },
        "answer_blind": blind,
        "gemini": gemini,
    }
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} judged records to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
