"""Multi-provider adjudicated A/B search evaluation (EXP-4, EXP-5).

A generalisation of ``evaluation/diy_vs_tavily.py`` from two arms to N. EXP-4
compares three search providers (diy, tavily, brave); EXP-5 compares four
(diy, tavily, brave, serper). The two-arm harness ranks by a single DIY win
share, which does not extend to three or more arms, so this module instead runs
a PAIRWISE round-robin and ranks the providers by Copeland count.

For each (question, country) pair in a dimension-stratified sample of the
swarm's finalised pairs:
  1. probe every requested provider once on a trivial query and DROP any that
     cannot return results (missing key, exhausted quota), with a warning;
  2. fetch top-k evidence from every LIVE provider ONCE and freeze it into the
     record (single-pass snapshot, pre-registration section 4);
  3. for each unordered pair of live providers, run the blind position-swapped
     Opus judge (the same two-orientation logic as the two-arm harness) and
     record a per-arm-pair verdict in {provider_x, provider_y, tie, both_fail};
  4. aggregate per provider by Copeland count (arm-pairs won minus arm-pairs
     lost), ties broken by total decided wins, and report any intransitive
     triple (x>y>z>x) rather than silently resolving it (section 5).

Robustness on a seeded 30% subsample (section 4): an answer-blind re-judge
(leakage control) and, where the Gemini key authenticates, a cross-family
re-judge. The Gemini step probes auth first and SKIPS gracefully on failure
(the project's Gemini key has zero quota), so the run never crashes on it.

Evidence sets, both raw verdicts, the Copeland ranking, the head-to-head
matrix, and the git SHA are written to a JSONL so every judgement is auditable
(receipts per the dissertation standard).

This reuses the two-arm harness's pure helpers (``build_eval_set``,
``filter_pairs``, ``stratify_pairs``, ``get_evidence``, ``select_subsample``)
so the eval-set construction, evidence fetch/cache, and subsample draw are
identical to EXP-1; only the arm count and the aggregation differ.

Usage:
    uv run python evaluation/provider_ab.py --providers diy tavily brave \\
        --countries FR --exclude-dimensions Quality --limit 40        # EXP-4
    uv run python evaluation/provider_ab.py --providers diy tavily brave serper \\
        --countries FR --limit 40                                      # EXP-5
    uv run python evaluation/provider_ab.py --providers diy tavily brave \\
        --countries FR --limit 2                                       # smoke
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from evaluation.diy_vs_tavily import (
    DEFAULT_EXCLUDE_DIMENSIONS,
    RESULTS_DIR,
    SUBSAMPLE_FRAC,
    SUBSAMPLE_SEED,
    _git_commit_sha,
    _load_cache,
    _pair_id,
    _save_cache,
    build_eval_set,
    get_evidence,
    select_subsample,
    stratify_pairs,
)
from evaluation.stats import krippendorff_alpha, wilson_interval

# Probe every provider on this throwaway query before judging. It must be
# answerable by any general web index so a zero-result reply means the provider
# is unavailable (no key / exhausted quota), not that the query was too obscure.
PROBE_QUERY = "open data"
PROBE_MAX_RESULTS = 3

# User-facing provider names accepted on the CLI. The search() backend literal
# for Serper is "serper_raw"; everywhere else (records, ranking, JSONL) the
# harness carries the friendlier "serper". diy/tavily/brave map one-to-one.
_SEARCH_NAME = {"serper": "serper_raw"}
_ALIAS = {"serper_raw": "serper"}


# ===========================================================================
# Pure logic (unit-tested in tests/test_provider_ab.py)
# ===========================================================================

def normalise_provider(name: str) -> str:
    """Canonical user-facing provider key: lower-cased, serper_raw -> serper."""
    low = name.strip().lower()
    return _ALIAS.get(low, low)


def search_provider_name(name: str) -> str:
    """Map a user-facing provider name to the search() backend literal.

    Only Serper differs (the search module spells it "serper_raw"); diy, tavily
    and brave pass through unchanged.
    """
    canon = normalise_provider(name)
    return _SEARCH_NAME.get(canon, canon)


PairFrame = Literal["x", "y", "tie", "both_fail"]


def orientation_to_x(winner: str, *, x_is: Literal["A", "B"]) -> PairFrame:
    """Map a blind A/B/tie/both_fail verdict into the x-provider frame.

    Generalises ``diy_vs_tavily.orientation_to_diy`` to an arbitrary unordered
    pair (x, y): the provider in slot ``x_is`` is "x", the other is "y".
    """
    if winner in ("tie", "both_fail"):
        return winner  # type: ignore[return-value]
    return "x" if winner == x_is else "y"


_PAIR_SCORE = {"x": 1, "y": -1, "tie": 0, "both_fail": 0}


def combine_pair_orientations(o1: PairFrame, o2: PairFrame) -> dict:
    """Combine two position-swapped per-pair verdicts into one.

    Mirrors ``diy_vs_tavily.combine_orientations`` but in the generic x/y frame.
    Pure both_fail in both orientations => both_fail. Otherwise sum an x-signed
    score: positive => x, negative => y, zero => tie. An x/y disagreement (a
    pure position flip) nets to a tie and is flagged inconsistent.
    """
    if o1 == "both_fail" and o2 == "both_fail":
        return {"verdict": "both_fail", "consistent": True}
    s = _PAIR_SCORE[o1] + _PAIR_SCORE[o2]
    verdict = "x" if s > 0 else "y" if s < 0 else "tie"
    return {"verdict": verdict, "consistent": o1 == o2}


def head_to_head_stats(
    x_wins: int, y_wins: int, ties: int, both_fail: int, confidence: float = 0.95
) -> dict:
    """One head-to-head's win share with a Wilson CI, over DECIDED pairs only.

    The denominator is ``x_wins + y_wins``. Ties and both_fail are reported but
    excluded from the share (section 5), so they can never inflate a "win"
    numerator. Pure, so it is unit-testable.
    """
    decided = x_wins + y_wins
    share = x_wins / decided if decided else 0.0
    low, high = wilson_interval(x_wins, decided, confidence=confidence)
    return {
        "x_wins": x_wins,
        "y_wins": y_wins,
        "ties": ties,
        "both_fail": both_fail,
        "decided": decided,
        "x_win_share": share,
        "wilson_low": low,
        "wilson_high": high,
    }


def _resolve_pair_verdict(rec: dict) -> Optional[str]:
    """Winning provider name for one arm-pair record, or None if undecided.

    ``rec['verdict']`` is one of {provider_x, provider_y, "tie", "both_fail"}.
    A decided verdict returns the winning provider; "tie"/"both_fail" return
    None (they move no Copeland score).
    """
    v = rec["verdict"]
    if v in ("tie", "both_fail"):
        return None
    return v


def copeland_ranking(
    providers: Sequence[str], verdicts: List[dict], *, full: bool = False
):
    """Rank providers by Copeland count over a pairwise verdict list.

    Each verdict is a dict ``{"provider_x", "provider_y", "verdict"}`` where
    ``verdict`` is the winning provider name, "tie", or "both_fail". The
    Copeland score of a provider is (arm-pairs won) - (arm-pairs lost) across
    all its head-to-heads; ties and both_fail decide nothing and move no score.
    Providers are ordered by Copeland score descending, ties broken by total
    decided wins descending, then by name for a stable, replayable order.

    Pairwise verdicts can be intransitive under a noisy judge (x>y>z>x), so any
    intransitive triple is detected and reported rather than silently resolved
    (pre-registration section 5).

    Args:
        providers: All providers in the comparison (the full arm set).
        verdicts: One record per played arm-pair.
        full: If False (default) return just the ranking list. If True return
            ``{"ranking": [...], "intransitive_triples": [[a, b, c], ...]}``.

    Returns:
        A list of per-provider rows (best first), each
        ``{provider, copeland, wins, losses, decided_wins}``; or, with
        ``full=True``, the dict described above.
    """
    provs = [normalise_provider(p) for p in providers]
    wins: Dict[str, int] = {p: 0 for p in provs}
    losses: Dict[str, int] = {p: 0 for p in provs}
    # beats[a] = set of providers a beat head-to-head (for cycle detection).
    beats: Dict[str, set] = {p: set() for p in provs}

    for rec in verdicts:
        winner = _resolve_pair_verdict(rec)
        if winner is None:
            continue
        px = normalise_provider(rec["provider_x"])
        py = normalise_provider(rec["provider_y"])
        loser = py if winner == px else px
        winner = normalise_provider(winner)
        loser = normalise_provider(loser)
        wins.setdefault(winner, 0)
        losses.setdefault(loser, 0)
        beats.setdefault(winner, set())
        wins[winner] += 1
        losses[loser] += 1
        beats[winner].add(loser)

    rows = []
    for p in provs:
        rows.append({
            "provider": p,
            "copeland": wins[p] - losses[p],
            "wins": wins[p],
            "losses": losses[p],
            "decided_wins": wins[p],
        })
    # Copeland desc, then decided-wins desc, then name asc (stable tiebreak).
    rows.sort(key=lambda r: (-r["copeland"], -r["decided_wins"], r["provider"]))

    if not full:
        return rows

    # Detect intransitive triples: for every unordered {a, b, c}, a strict
    # 3-cycle a>b>c>a (in either rotational direction) is intransitive.
    triples: List[List[str]] = []
    for a, b, c in itertools.combinations(provs, 3):
        forward = (b in beats[a] and c in beats[b] and a in beats[c])
        backward = (c in beats[a] and b in beats[c] and a in beats[b])
        if forward or backward:
            triples.append(sorted([a, b, c]))
    return {"ranking": rows, "intransitive_triples": triples}


def filter_live_providers(
    requested: Sequence[str], probes: Dict[str, dict]
) -> Tuple[List[str], List[str]]:
    """Split requested providers into (live, dropped) using probe outcomes.

    A provider is LIVE only if its probe both authenticated (``ok``) and
    returned at least one result (``n_results > 0``): a provider that
    authenticates but returns nothing for the trivial probe cannot serve the
    experiment. A provider with no probe entry is dropped. Input order is
    preserved so the run is deterministic. Pure, so it is unit-testable.
    """
    live, dropped = [], []
    for name in requested:
        canon = normalise_provider(name)
        p = probes.get(canon) or probes.get(name)
        if p and p.get("ok") and (p.get("n_results") or 0) > 0:
            live.append(canon)
        else:
            dropped.append(canon)
    return live, dropped


# ===========================================================================
# Live harness (network + DB + LLM)
# ===========================================================================

def probe_provider(name: str, *, query: str = PROBE_QUERY,
                   max_results: int = PROBE_MAX_RESULTS) -> dict:
    """One live search call to check a provider can return results.

    Returns ``{ok, n_results, error, provider}``. Never raises: any exception
    (missing key, HTTP error, quota) is caught and reported as ``ok=False`` with
    the upstream reason, so the caller can drop the arm and continue.
    """
    from agents.tools.search import search

    backend = search_provider_name(name)
    try:
        results = search(query, max_results=max_results, provider=backend)
        return {"provider": normalise_provider(name), "ok": True,
                "n_results": len(results), "error": None}
    except Exception as exc:  # noqa: BLE001 - a dead provider must not crash the run
        return {"provider": normalise_provider(name), "ok": False,
                "n_results": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}


def probe_all(providers: Sequence[str]) -> Dict[str, dict]:
    """Probe every requested provider once, keyed by canonical name."""
    out: Dict[str, dict] = {}
    for name in providers:
        out[normalise_provider(name)] = probe_provider(name)
    return out


def _print_probe_table(requested: Sequence[str], probes: Dict[str, dict]) -> None:
    """Print the provider liveness table (the most load-bearing diagnostic)."""
    print("\n=== Provider probe (one live call each) ===")
    print(f"  query={PROBE_QUERY!r}  max_results={PROBE_MAX_RESULTS}")
    print(f"  {'provider':<10} {'live':<6} {'results':<8} detail")
    for name in requested:
        canon = normalise_provider(name)
        p = probes.get(canon, {})
        live = "yes" if p.get("ok") and (p.get("n_results") or 0) > 0 else "NO"
        detail = "" if p.get("ok") else (p.get("error") or "no probe")
        if p.get("ok") and not (p.get("n_results") or 0) > 0:
            detail = "authenticated but 0 results"
        print(f"  {canon:<10} {live:<6} {p.get('n_results', 0):<8} {detail}")


def snapshot_evidence(
    pair: dict, providers: Sequence[str], *, max_results: int, cache: dict
) -> Dict[str, List[dict]]:
    """Fetch evidence from every live provider ONCE and freeze it (section 4).

    Returns ``{provider: evidence_list}``. A provider that fails on this pair
    yields an empty list (its head-to-heads on this pair then both_fail or lose
    on the merits), so one flaky page does not sink the whole pair.
    """
    snap: Dict[str, List[dict]] = {}
    for name in providers:
        canon = normalise_provider(name)
        backend = search_provider_name(name)
        try:
            snap[canon] = get_evidence(
                pair["query"], backend, max_results=max_results, cache=cache,
            )
        except Exception as exc:  # noqa: BLE001 - record empty, keep the pair
            print(f"      ! {canon} fetch failed: {type(exc).__name__}: {exc}")
            snap[canon] = []
    return snap


def _judge_provider_pair(
    judge_fn, *, question_text: str, gold: str,
    ev_x: List[dict], ev_y: List[dict], answer_blind: bool = False,
) -> dict:
    """Run one judge twice with x/y positions swapped and combine (generic).

    Mirrors ``diy_vs_tavily._judge_orientations`` but in the provider-agnostic
    x/y frame. The adjudicator equalises passage count per call internally
    (``_equalise_counts``), so each arm-pair is equalised at judge time, which
    is what the pairwise design needs. Returns the combined verdict and both
    raw orientations in the x frame.
    """
    # Orientation 1: A = x, B = y
    v1, _ = judge_fn(
        question_text=question_text, ground_truth=gold,
        evidence_a=ev_x, evidence_b=ev_y, answer_blind=answer_blind,
    )
    o1 = orientation_to_x(v1.winner, x_is="A")

    # Orientation 2: A = y, B = x (positions swapped)
    v2, _ = judge_fn(
        question_text=question_text, ground_truth=gold,
        evidence_a=ev_y, evidence_b=ev_x, answer_blind=answer_blind,
    )
    o2 = orientation_to_x(v2.winner, x_is="B")

    combined = combine_pair_orientations(o1, o2)
    return {
        "verdict": combined["verdict"],          # x / y / tie / both_fail
        "consistent": combined["consistent"],
        "orientation_1": {"winner": v1.winner, "x_frame": o1,
                          "x_supports": v1.answer_supported_by_a,
                          "y_supports": v1.answer_supported_by_b,
                          "reasoning": v1.reasoning, "confidence": v1.confidence},
        "orientation_2": {"winner": v2.winner, "x_frame": o2,
                          "y_supports": v2.answer_supported_by_a,
                          "x_supports": v2.answer_supported_by_b,
                          "reasoning": v2.reasoning, "confidence": v2.confidence},
    }


def _named_verdict(verdict: PairFrame, provider_x: str, provider_y: str) -> str:
    """Resolve an x/y/tie/both_fail verdict to a provider name or pass-through."""
    if verdict == "x":
        return provider_x
    if verdict == "y":
        return provider_y
    return verdict


def judge_pair(
    pair: dict, providers: Sequence[str], *, max_results: int, model: str,
    cache: dict,
) -> dict:
    """Snapshot every live provider's evidence, then judge every arm-pair.

    Freezes the evidence first (single-pass snapshot), then runs the blind
    position-swapped Opus judge for each unordered provider pair against the
    frozen snapshot. Records a per-arm-pair verdict resolved to the winning
    provider name (or tie / both_fail), plus the evidence and both raw
    orientations.
    """
    from functools import partial

    from agents.tools.search_adjudicator import adjudicate

    canon = [normalise_provider(p) for p in providers]
    snap = snapshot_evidence(pair, canon, max_results=max_results, cache=cache)
    judge = partial(adjudicate, model=model)

    arm_pairs = []
    for px, py in itertools.combinations(canon, 2):
        judged = _judge_provider_pair(
            judge, question_text=pair["question_text"], gold=pair["gold"],
            ev_x=snap[px], ev_y=snap[py], answer_blind=False,
        )
        arm_pairs.append({
            "provider_x": px,
            "provider_y": py,
            "verdict": _named_verdict(judged["verdict"], px, py),
            "frame_verdict": judged["verdict"],
            "consistent": judged["consistent"],
            "x_n": len(snap[px]),
            "y_n": len(snap[py]),
            "orientation_1": judged["orientation_1"],
            "orientation_2": judged["orientation_2"],
        })

    return {
        "question_id": pair["question_id"],
        "country_code": pair["country_code"],
        "dimension": pair["dimension"],
        "query": pair["query"],
        "question_text": pair["question_text"],
        "gold": pair["gold"],
        "evidence": snap,
        "arm_pairs": arm_pairs,
    }


def aggregate_matrix(records: List[dict], providers: Sequence[str]) -> dict:
    """Build the head-to-head matrix and Copeland ranking over all records.

    Tallies, per unordered provider pair, x_wins / y_wins / ties / both_fail
    across every pair record, computes each head-to-head's win share with a
    Wilson CI (``head_to_head_stats``), then ranks the providers by Copeland
    count and reports any intransitive triple.
    """
    canon = [normalise_provider(p) for p in providers]
    # Per unordered (px, py) tally, with px < py by the combinations order.
    tally: Dict[Tuple[str, str], dict] = {}
    for px, py in itertools.combinations(canon, 2):
        tally[(px, py)] = {"x_wins": 0, "y_wins": 0, "tie": 0, "both_fail": 0}

    flat_verdicts: List[dict] = []
    for rec in records:
        for ap in rec["arm_pairs"]:
            px, py = ap["provider_x"], ap["provider_y"]
            key = (px, py) if (px, py) in tally else (py, px)
            if key not in tally:  # provider not in the requested set; skip
                continue
            bucket = tally[key]
            v = ap["verdict"]
            if v == key[0]:
                bucket["x_wins"] += 1
            elif v == key[1]:
                bucket["y_wins"] += 1
            elif v == "tie":
                bucket["tie"] += 1
            else:
                bucket["both_fail"] += 1
            flat_verdicts.append({"provider_x": px, "provider_y": py,
                                  "verdict": v})

    head_to_head = []
    for (px, py), b in tally.items():
        stats = head_to_head_stats(b["x_wins"], b["y_wins"], b["tie"],
                                   b["both_fail"])
        head_to_head.append({"provider_x": px, "provider_y": py, **stats})

    ranked = copeland_ranking(canon, flat_verdicts, full=True)
    return {
        "providers": canon,
        "head_to_head": head_to_head,
        "ranking": ranked["ranking"],
        "intransitive_triples": ranked["intransitive_triples"],
    }


def run_answer_blind_subsample(
    subsample: List[dict], providers: Sequence[str], *, model: str
) -> dict:
    """Re-judge every arm-pair of the frozen subsample answer-blind (section 4).

    Reuses each record's frozen evidence, so the only change is that the gold
    label is withheld. Reports per-pair, per-arm-pair answer-blind verdicts and
    the raw agreement against the answer-given verdict at arm-pair granularity.
    """
    from functools import partial

    from agents.tools.search_adjudicator import adjudicate

    judge = partial(adjudicate, model=model)
    canon = [normalise_provider(p) for p in providers]
    per_pair = []
    agree = 0
    total = 0
    for rec in subsample:
        snap = rec["evidence"]
        given = {(ap["provider_x"], ap["provider_y"]): ap["verdict"]
                 for ap in rec["arm_pairs"]}
        ap_out = []
        for px, py in itertools.combinations(canon, 2):
            if px not in snap or py not in snap:
                continue
            blind = _judge_provider_pair(
                judge, question_text=rec.get("question_text", rec["question_id"]),
                gold=rec["gold"], ev_x=snap[px], ev_y=snap[py],
                answer_blind=True,
            )
            blind_named = _named_verdict(blind["verdict"], px, py)
            given_named = given.get((px, py)) or given.get((py, px))
            same = blind_named == given_named
            agree += int(same)
            total += 1
            ap_out.append({
                "provider_x": px, "provider_y": py,
                "answer_given_verdict": given_named,
                "answer_blind_verdict": blind_named,
                "consistent": blind["consistent"],
            })
        per_pair.append({"pair_id": _pair_id(rec), "arm_pairs": ap_out})
    return {
        "n_pairs": len(subsample),
        "n_arm_pairs": total,
        "agreement_rate": agree / total if total else 0.0,
        "per_pair": per_pair,
    }


def run_gemini_subsample(
    subsample: List[dict], providers: Sequence[str], *, answer_blind: bool = False
) -> dict:
    """Cross-family Gemini re-judge of the frozen subsample (section 4, 5).

    Probes the Gemini key first; on auth failure (e.g. zero quota) records the
    precise reason and SKIPS gracefully rather than crash. On success, re-judges
    every arm-pair, reports the Opus-vs-Gemini raw agreement and Krippendorff's
    alpha (nominal) over the per-arm-pair verdict units.
    """
    from agents.tools.search_adjudicator_gemini import (
        adjudicate_gemini, probe_auth,
    )

    probe = probe_auth()
    if not probe.get("ok"):
        return {"ran": False,
                "gemini_status": probe.get("error", "unknown Gemini auth failure")}

    canon = [normalise_provider(p) for p in providers]
    per_pair = []
    units: List[list] = []
    agree = 0
    for rec in subsample:
        snap = rec["evidence"]
        given = {(ap["provider_x"], ap["provider_y"]): ap["verdict"]
                 for ap in rec["arm_pairs"]}
        ap_out = []
        for px, py in itertools.combinations(canon, 2):
            if px not in snap or py not in snap:
                continue
            try:
                judged = _judge_provider_pair(
                    adjudicate_gemini,
                    question_text=rec.get("question_text", rec["question_id"]),
                    gold=rec["gold"], ev_x=snap[px], ev_y=snap[py],
                    answer_blind=answer_blind,
                )
            except Exception as exc:  # noqa: BLE001 - one bad pair must not sink the rest
                ap_out.append({"provider_x": px, "provider_y": py,
                               "error": f"{type(exc).__name__}: {exc}"})
                continue
            gem_named = _named_verdict(judged["verdict"], px, py)
            opus_named = given.get((px, py)) or given.get((py, px))
            agree += int(gem_named == opus_named)
            units.append([opus_named, gem_named])
            ap_out.append({"provider_x": px, "provider_y": py,
                           "opus_verdict": opus_named,
                           "gemini_verdict": gem_named,
                           "consistent": judged["consistent"]})
        per_pair.append({"pair_id": _pair_id(rec), "arm_pairs": ap_out})
    n = len(units)
    return {
        "ran": True,
        "gemini_status": "ok",
        "model": probe.get("model"),
        "answer_blind": answer_blind,
        "n_arm_pairs": n,
        "agreement_rate": agree / n if n else 0.0,
        "krippendorff_alpha": krippendorff_alpha(units, level="nominal") if units else None,
        "per_pair": per_pair,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-provider adjudicated A/B search evaluation "
                    "(EXP-4, EXP-5)")
    parser.add_argument("--db", type=Path, default=None,
                        help="SQLite DB path (default: data/odmi.db)")
    parser.add_argument("--providers", nargs="+", default=["diy", "tavily", "brave"],
                        help="providers to compare (default: diy tavily brave)")
    parser.add_argument("--limit", type=int, default=40,
                        help="eval-set size (stratified)")
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

    from evaluation.diy_vs_tavily import DEFAULT_DB
    db_path = args.db or DEFAULT_DB

    from agents.tools.search_adjudicator import ADJUDICATOR_MODEL
    model = args.model or ADJUDICATOR_MODEL

    requested = [normalise_provider(p) for p in args.providers]
    print(f"Requested providers: {requested}")

    # --- Provider probe FIRST: drop any arm that cannot return results -----
    probes = probe_all(requested)
    _print_probe_table(requested, probes)
    live, dropped = filter_live_providers(requested, probes)
    for d in dropped:
        reason = (probes.get(d) or {}).get("error") or "0 results on probe"
        print(f"  WARNING: dropping provider {d!r} ({reason})")
    if len(live) < 2:
        print(f"\nERROR: need at least 2 live providers for a pairwise "
              f"comparison, got {live}. Aborting.")
        return 2
    print(f"\nLive providers ({len(live)}): {live}")

    full = build_eval_set(
        db_path, countries=args.countries,
        exclude_dimensions=args.exclude_dimensions,
    )
    pairs = stratify_pairs(full, args.limit)
    print(f"Eval set: {len(pairs)} pairs (from {len(full)} judgeable), "
          f"adjudicator model={model}")
    print(f"Filters: countries={args.countries or 'all'} "
          f"exclude_dimensions={args.exclude_dimensions or 'none'}")
    dist = defaultdict(int)
    bycc = defaultdict(int)
    for p in pairs:
        dist[p["dimension"]] += 1
        bycc[p["country_code"]] += 1
    print(f"Achieved dimension counts: {dict(sorted(dist.items()))}")
    print(f"Achieved country counts  : {dict(sorted(bycc.items()))}")
    n_arm_pairs = len(list(itertools.combinations(live, 2)))
    print(f"Arm-pairs per pair: {n_arm_pairs} "
          f"({', '.join('/'.join(p) for p in itertools.combinations(live, 2))})")

    cache = _load_cache()
    records = []
    for i, pair in enumerate(pairs, 1):
        tag = f"{pair['question_id']}/{pair['country_code']}"
        try:
            rec = judge_pair(pair, live, max_results=args.max_results,
                            model=model, cache=cache)
            records.append(rec)
            summary = "  ".join(
                f"{ap['provider_x']}/{ap['provider_y']}:{ap['verdict']}"
                for ap in rec["arm_pairs"]
            )
            print(f"  [{i}/{len(pairs)}] {tag}: {summary}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(pairs)}] {tag}: ERROR {type(exc).__name__}: {exc}")
        finally:
            _save_cache(cache)

    # --- Aggregate: head-to-head matrix + Copeland ranking -----------------
    matrix = aggregate_matrix(records, live)

    print("\n=== Provider ranking (Copeland) ===")
    print(f"  {'rank':<5} {'provider':<10} {'copeland':<9} {'W-L':<8} decided_wins")
    for rank, row in enumerate(matrix["ranking"], 1):
        wl = f"{row['wins']}-{row['losses']}"
        print(f"  {rank:<5} {row['provider']:<10} {row['copeland']:<9} "
              f"{wl:<8} {row['decided_wins']}")
    if matrix["intransitive_triples"]:
        print(f"  INTRANSITIVE TRIPLES (reported, not resolved): "
              f"{matrix['intransitive_triples']}")
    else:
        print("  no intransitive triples")

    print("\n=== Head-to-head (decided win share, x over y) ===")
    for hh in matrix["head_to_head"]:
        print(f"  {hh['provider_x']} vs {hh['provider_y']}: "
              f"{hh['x_wins']}-{hh['y_wins']} "
              f"(tie {hh['ties']}, both_fail {hh['both_fail']}), "
              f"x share {hh['x_win_share']:.0%} "
              f"CI [{hh['wilson_low']:.0%}, {hh['wilson_high']:.0%}]")

    # --- Seeded 30% subsample: robustness checks (section 4) ---------------
    subsample = select_subsample(records, seed=args.subsample_seed,
                                 frac=args.subsample_frac)
    subsample_ids = [_pair_id(r) for r in subsample]
    print(f"\n=== Robustness subsample (seed {args.subsample_seed}, "
          f"frac {args.subsample_frac:.0%}, n={len(subsample)}) ===")
    print(f"  pairs: {subsample_ids}")

    blind = (run_answer_blind_subsample(subsample, live, model=model)
             if subsample else {"n_pairs": 0, "n_arm_pairs": 0,
                                "agreement_rate": 0.0, "per_pair": []})
    if subsample:
        print(f"  answer-blind vs answer-given agreement : "
              f"{blind['agreement_rate']:.0%}  "
              f"({blind['n_arm_pairs']} arm-pairs)")

    gemini = (run_gemini_subsample(subsample, live)
              if subsample else {"ran": False, "gemini_status": "no subsample"})
    if gemini.get("ran"):
        alpha = gemini.get("krippendorff_alpha")
        alpha_str = f"{alpha:.3f}" if alpha is not None else "n/a"
        print(f"  Gemini cross-family agreement          : "
              f"{gemini['agreement_rate']:.0%}  (n={gemini['n_arm_pairs']})")
        print(f"  Krippendorff alpha (Opus vs Gemini)    : {alpha_str}")
    else:
        print(f"  Gemini cross-family judge SKIPPED: {gemini.get('gemini_status')}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.out or (RESULTS_DIR / f"provider_ab_{stamp}.jsonl")
    summary = {
        "experiment": "provider_ab",
        "model": model,
        "generated_at": stamp,
        "git_commit": _git_commit_sha(),
        "requested_providers": requested,
        "live_providers": live,
        "dropped_providers": dropped,
        "provider_probes": probes,
        "filters": {
            "countries": list(args.countries) if args.countries else None,
            "exclude_dimensions": list(args.exclude_dimensions or []),
            "limit": args.limit,
            "max_results": args.max_results,
        },
        "ranking": matrix["ranking"],
        "head_to_head": matrix["head_to_head"],
        "intransitive_triples": matrix["intransitive_triples"],
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
