"""EXP-6: Verifier strategy discrimination (signal-detection).

Pre-registered in docs/EXPERIMENTS_VERIFIER.md. Treats the Verifier as a binary
classifier over a Researcher candidate answer (pass = accept, fail = reject) and
measures how well each of the four D15 strategies tells a wrong answer from a
correct one, per unit of token cost.

Design (see the pre-registration for the full rationale):
  - Ground-truth label per candidate from ODMI `ground_truth` via the same logic
    as `_MATCH_STATUS_SQL`: should_pass (Researcher matches gold) /
    should_fail (differs, incl. one band off).
  - Paired: all four strategies judge the identical candidate set.
  - Frozen evidence: substring check + one adversarial query-gen + one search are
    run ONCE per candidate; the identical frozen block feeds all four strategy
    prompts. The only between-arm variable is the system prompt.
  - Retargeted (2026-06-03) to a base-rate-balanced country per rule R4
    (EXPERIMENTS_PROTOCOL.md section 0): primary should_fail comes from Malta
    (English official, ~30 no-gold binary questions), Netherlands is secondary,
    and the France-dominated natural errors plus the injected label-flips are kept
    as a robustness arm, reported separately and never folded into the primary.
  - Roles: primary (MT), secondary (NL), robustness (FR/EE natural + INJ). Each
    role carries a matched should_pass set. Seed 20260603. The Malta dispatch is
    pending search quota, so until it lands the primary strata are empty and only
    the robustness arm is runnable (labelled robustness-only, not the primary J).

Usage:
  uv run python evaluation/verifier_strategies.py            # full run
  uv run python evaluation/verifier_strategies.py --limit 6  # smoke
  uv run python evaluation/verifier_strategies.py --analyse-only PATH.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import ResearcherOutput, VerifierInput, VerifierOutput
from agents.prompts import verifier as verifier_prompt
from agents.tools import answer_shapes
from agents.tools.db import connect
from agents.tools.llm import StructuredOutputError, call_for_structured
from agents.tools.search import search_many
from agents.verifier import _run_substring_check, generate_adversarial_queries
from agents.errors import RateLimitedShutdown
from agents.tools.blocked_domains import is_blocked


def _evidence_blocked(row: dict) -> bool:
    """True if any URL the Researcher cited, fetched, or read in a snippet hits
    the SPEC D24 deny-list (ODMI publications, the EU Data Portal, archive mirrors).

    The leakage risk D22/D24 warns about: a Researcher row whose evidence touched
    data.europa.eu (incl. the ODMI factsheet PDFs, the published answer key) leaks
    the gold answer into the Verifier the judge is grading. Legacy pre-deny-list
    FR/EE/NL runs carry this; excluding them keeps the EXP-6 candidate set clean.
    Checks source_url, fetched_urls, and search_snippet URLs, since the Verifier
    sees all three.
    """
    urls = [row.get("source_url") or ""]
    try:
        urls += [u for u in json.loads(row.get("fetched_urls") or "[]")]
    except Exception:
        pass
    try:
        for s in json.loads(row.get("search_snippets") or "[]"):
            if isinstance(s, dict):
                urls.append(s.get("url") or "")
    except Exception:
        pass
    return any(u and is_blocked(u) for u in urls)

import evaluation.stats as stats


def _call_with_retry(thunk, *, label: str, max_retries: int = 12):
    """Run a thunk that may raise RateLimitedShutdown; sleep through the
    cooldown and retry. The model's 429 carries a `reset_seconds`, so we wait
    that long plus a small buffer rather than guessing. Re-raises anything
    that is not a rate limit, and gives up after max_retries cooldowns."""
    for attempt in range(max_retries + 1):
        try:
            return thunk()
        except RateLimitedShutdown as exc:
            if attempt >= max_retries:
                raise
            m = re.search(r"reset_seconds['\"]?:\s*(\d+)", str(exc))
            wait = (int(m.group(1)) if m else 35) + 5
            print(f"      [rate-limit] {label}: cooling down {wait}s "
                  f"(attempt {attempt + 1}/{max_retries})", flush=True)
            time.sleep(wait)

SEED = 20260603
STRATEGIES = [
    "verifier-disprove",
    "verifier-negation",
    "verifier-steelman",
    "verifier-blind",
]
# Country roles. 2026-06-06 redesign (Benjy): Malta dropped entirely. The
# natural arm is the Netherlands (Dutch is high-resource, so a poor result is
# not a language artefact; 26 no-gold binary questions, R4-viable at 21%
# no-share). France is the injected/robustness arm (high yes-share, so plenty of
# correct binary answers to flip; the flips remove the ODMI-staleness confound).
# Both arms draw from the shared seeded question selection
# data/questions/exp6_question_set.json (71 binary, no self-report, 19 each
# Policy/Portal/Impact + 14 Quality). EE and Malta removed.
PRIMARY_COUNTRIES = ["NL"]
SECONDARY_COUNTRIES = []
ROBUSTNESS_COUNTRIES = ["FR"]
INJ_TARGET = 71
EXPERIMENT_ID = "verifier_strategy_disc_v1"
# Frozen-evidence independent-search provider. MUST be the single provider the
# whole candidate set was generated with, held constant so the only thing that
# varies in the experiment is the Verifier strategy. Pinned to DIY (Serper);
# the run is gated on that provider being available (Serper credits / Tavily
# quota). Brave is deliberately NOT used: mixing providers across the data is a
# confound. See _freeze_evidence and the watertight protocol in
# docs/EXPERIMENTS_VERIFIER.md.
FROZEN_SEARCH_PROVIDER = "diy"


def _role_of(cc: str) -> Optional[str]:
    if cc in PRIMARY_COUNTRIES:
        return "primary"
    if cc in SECONDARY_COUNTRIES:
        return "secondary"
    if cc in ROBUSTNESS_COUNTRIES:
        return "robustness"
    return None
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"


# ============================================================
# Labelling: mirror _MATCH_STATUS_SQL (exact / yes-prefix / no / band-adjacent)
# ============================================================

def _label(researcher_answer: str, gold: str, shape, allowed) -> str:
    """Return 'should_pass' / 'should_fail' / 'abstain' / 'no_gt'."""
    if gold is None or gold.strip() == "":
        return "no_gt"
    a = (researcher_answer or "").strip().lower()
    g = gold.strip().lower()
    if a in ("inconclusive", "not_applicable", ""):
        return "abstain"
    if a == g:
        return "should_pass"
    if a == "yes" and g.startswith("yes"):
        return "should_pass"
    if a == "no" and g == "no":
        return "should_pass"
    # Anything else, incl. an adjacent band, is a fail per the verifier prompts.
    return "should_fail"


# ============================================================
# Candidate construction
# ============================================================

@dataclass
class Candidate:
    cand_id: str
    stratum: str            # NAT-fail | NAT-pass | INJ-fail
    role: str               # primary | secondary | robustness
    gold_label: str         # should_pass | should_fail
    question_id: str
    country_code: str
    country_name: str
    dimension: str
    answer_shape: str
    allowed_answers: list
    researcher_answer: str  # possibly flipped (INJ)
    gold_response: str
    source_row_id: int
    injected: bool
    row: dict = field(default=None, repr=False)


def _load_world():
    qmeta, gold, cname = {}, {}, {}
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        for r in conn.execute(
            "select question_id,dimension,answer_shape,allowed_answers from questions"
        ):
            qmeta[r["question_id"]] = {
                "dim": r["dimension"],
                "shape": r["answer_shape"] or "binary",
                "allowed": json.loads(r["allowed_answers"]) if r["allowed_answers"] else ["yes", "no"],
            }
        for r in conn.execute("select question_id,country_code,response,country_name from ground_truth"):
            gold[(r["question_id"], r["country_code"])] = (r["response"] or "")
            cname[r["country_code"]] = r["country_name"]
        rows = [dict(r) for r in conn.execute(
            "select * from phase2_researcher_runs where answer is not null order by id"
        )]
    return qmeta, gold, cname, rows


def build_candidates(limit: Optional[int] = None):
    qmeta, gold, cname, rows = _load_world()
    rng = random.Random(SEED)

    # Fairness guard 1 (data leakage, D22/D24): drop any Researcher row whose
    # evidence touched the deny-listed answer-key domains. Legacy pre-deny-list
    # runs carry these; the current dispatch path scrubs them, so this only
    # removes stale contaminated rows.
    rows = [r for r in rows if not _evidence_blocked(r)]

    # Fairness guard 2 (one candidate per pair): dedupe by (question_id,
    # country_code), latest clean row winning. The pre-registration defined a
    # candidate as distinct (qid, cc, answer), assuming one dispatch per pair;
    # the Malta/NL double-dispatch produced the SAME pair with two different
    # answers, which then landed in BOTH should_pass and should_fail and broke
    # the independence the J / Wilson / McNemar stats assume. Keeping the latest
    # committed answer restores one canonical candidate per pair (the documented
    # 60 MT / 52 NL framing) and matches the phase2_final dedup rule.
    distinct = {}
    for r in rows:
        key = (r["question_id"], r["country_code"])
        distinct[key] = r  # rows sorted by id asc, so last write = max id

    nat_fail, correct_pool = [], []
    for (qid, cc), r in distinct.items():
        ans = (r["answer"] or "").strip().lower()
        meta = qmeta.get(qid)
        if not meta:
            continue
        g = gold.get((qid, cc))
        lab = _label(ans, g, meta["shape"], meta["allowed"])
        base = dict(
            question_id=qid, country_code=cc,
            country_name=cname.get(cc, cc),
            dimension=meta["dim"], answer_shape=meta["shape"],
            allowed_answers=meta["allowed"],
            researcher_answer=r["answer"], gold_response=g,
            source_row_id=r["id"], row=r,
        )
        if lab == "should_fail":
            nat_fail.append(base)
        elif lab == "should_pass":
            correct_pool.append(base)

    dim_order = ["Policy", "Portal", "Impact", "Quality"]

    # ---- NAT-fail: take every natural error in a targeted country, tagged by role ----
    cands = []
    nat_fail_by_role = Counter()
    for b in sorted(nat_fail, key=lambda x: (x["country_code"], x["question_id"])):
        role = _role_of(b["country_code"])
        if role is None:
            continue
        nat_fail_by_role[role] += 1
        cands.append(Candidate(
            cand_id=f"NATF::{b['question_id']}::{b['country_code']}",
            stratum="NAT-fail", role=role, gold_label="should_fail", injected=False, **b))

    # ---- NAT-pass: matched per role, round-robin across dimension within the role's countries ----
    # Robustness also carries the negatives for the injected arm, so its pass target
    # adds INJ_TARGET. Primary/secondary match their own natural-fail count, so an
    # empty Malta dispatch yields an empty (not unbalanced) primary stratum.
    pass_buckets = defaultdict(list)   # role -> dimension -> [candidate]
    for b in correct_pool:
        role = _role_of(b["country_code"])
        if role is None:
            continue
        pass_buckets[(role, b["dimension"])].append(b)
    for k in pass_buckets:
        rng.shuffle(pass_buckets[k])
    pass_target = {
        "primary": nat_fail_by_role.get("primary", 0),
        "secondary": nat_fail_by_role.get("secondary", 0),
        "robustness": nat_fail_by_role.get("robustness", 0) + INJ_TARGET,
    }
    used_keys = set()
    for role in ("primary", "secondary", "robustness"):
        target = pass_target[role]
        picked = []
        progressing = True
        while len(picked) < target and progressing:
            progressing = False
            for dim in dim_order:
                bk = pass_buckets.get((role, dim))
                if bk:
                    b = bk.pop()
                    used_keys.add((b["question_id"], b["country_code"]))
                    picked.append(b)
                    progressing = True
                    if len(picked) >= target:
                        break
        for b in picked:
            cands.append(Candidate(
                cand_id=f"NATP::{b['question_id']}::{b['country_code']}",
                stratum="NAT-pass", role=role, gold_label="should_pass", injected=False, **b))

    # ---- INJ-fail: flip binary robustness candidates not used in NAT-pass ----
    inj_pool = [
        b for b in correct_pool
        if b["answer_shape"] == "binary"
        and (b["question_id"], b["country_code"]) not in used_keys
        and b["country_code"] in ROBUSTNESS_COUNTRIES
        and (b["researcher_answer"] or "").strip().lower() in ("yes", "no")
    ]
    inj_buckets = defaultdict(list)
    for b in inj_pool:
        inj_buckets[(b["country_code"], b["dimension"])].append(b)
    for k in inj_buckets:
        rng.shuffle(inj_buckets[k])
    inj = []
    progressing = True
    while len(inj) < INJ_TARGET and progressing:
        progressing = False
        for cc in ROBUSTNESS_COUNTRIES:
            for dim in dim_order:
                bk = inj_buckets.get((cc, dim))
                if bk:
                    inj.append(bk.pop())
                    progressing = True
                    if len(inj) >= INJ_TARGET:
                        break
            if len(inj) >= INJ_TARGET:
                break
    for b in inj:
        orig = (b["researcher_answer"] or "").strip().lower()
        flipped = "no" if orig == "yes" else "yes"
        bb = dict(b)
        bb["researcher_answer"] = flipped
        cands.append(Candidate(
            cand_id=f"INJF::{b['question_id']}::{b['country_code']}",
            stratum="INJ-fail", role="robustness", gold_label="should_fail",
            injected=True, **bb))

    # Process primary (Malta) first, then secondary, then robustness. The run
    # is gated on the Claude Max rolling window, so a quota-truncated run must
    # land the primary endpoint before spending budget on the superseded
    # robustness arm. The sort is stable, so within-role order (and the seeded
    # draw) is preserved; order does not affect results, only which records
    # survive truncation. Resume skips already-done candidates regardless.
    _role_rank = {"primary": 0, "secondary": 1, "robustness": 2}
    cands.sort(key=lambda c: _role_rank.get(c.role, 3))

    if limit:
        # Keep a mix across strata for a smoke run.
        by_stratum = defaultdict(list)
        for c in cands:
            by_stratum[c.stratum].append(c)
        smoke = []
        i = 0
        while len(smoke) < limit and any(by_stratum.values()):
            for s in ("NAT-fail", "NAT-pass", "INJ-fail"):
                if by_stratum[s]:
                    smoke.append(by_stratum[s].pop(0))
                    if len(smoke) >= limit:
                        break
        cands = smoke
    return cands


# ============================================================
# FR augmented robustness set (50% label-flip injection)
# ============================================================

FR_AUGMENTED_FILE = REPO_ROOT / "data" / "questions" / "fr_augmented_eval_pairs.json"


def build_fr_augmented_candidates(path: Optional[Path] = None) -> list[Candidate]:
    """Load the committed, class-balanced FR robustness set built by
    scripts/build_fr_augmented_pairs.py and turn each frozen record into a
    Candidate the harness can judge.

    The file is the reproducible artefact (seed 20260603, 30 should_pass / 30
    flipped should_fail). Each record points at a real phase2_researcher_runs row
    by source_row_id, so the four-arm judge replays the identical frozen evidence
    the production Researcher saw, exactly as the on-the-fly INJ stratum does.
    Everything here is role='robustness': it is never folded into the Malta
    primary J (EXP-6 design, section 3).
    """
    path = Path(path) if path else FR_AUGMENTED_FILE
    doc = json.loads(path.read_text())
    qmeta, gold, cname, _ = _load_world()
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rowmap = {}
        for rec in doc["pairs"]:
            r = conn.execute(
                "select * from phase2_researcher_runs where id=?",
                (rec["source_row_id"],),
            ).fetchone()
            if r:
                rowmap[rec["source_row_id"]] = dict(r)

    cands: list[Candidate] = []
    for rec in doc["pairs"]:
        qid, cc = rec["question_id"], rec["country_code"]
        meta = qmeta.get(qid)
        row = rowmap.get(rec["source_row_id"])
        if not meta or row is None:
            print(f"   ! FR-aug skip {qid}/{cc}: "
                  f"{'no question meta' if not meta else 'source row missing'}")
            continue
        if _evidence_blocked(row):
            print(f"   ! FR-aug skip {qid}/{cc}: source row has deny-listed evidence")
            continue
        flipped = bool(rec["flipped"])
        cands.append(Candidate(
            cand_id=f"FRAUG::{qid}::{cc}::{'flip' if flipped else 'keep'}",
            stratum="INJ-fail" if flipped else "NAT-pass",
            role="robustness",
            gold_label=rec["gold_label"],
            question_id=qid, country_code=cc, country_name=cname.get(cc, cc),
            dimension=meta["dim"], answer_shape=meta["shape"],
            allowed_answers=meta["allowed"],
            researcher_answer=rec["researcher_answer"],
            gold_response=rec.get("gold_response") or gold.get((qid, cc), ""),
            source_row_id=rec["source_row_id"], injected=flipped, row=row,
        ))
    return cands


# ============================================================
# Reconstruct ResearcherOutput from a row (tolerant)
# ============================================================

def _researcher_output(row: dict, answer_override: str) -> Optional[ResearcherOutput]:
    quote = (row.get("evidence_quote") or "").strip()
    if len(quote) < 10:
        quote = (quote + " " * 10)[:10] if quote else "(no evidence quote provided)"
    url = row.get("source_url")
    if not url or not str(url).startswith("http"):
        url = "https://example.invalid/no-source"
    try:
        return ResearcherOutput(
            answer=answer_override,
            answer_explanation=(row.get("answer_explanation") or "(none)") or "(none)",
            evidence_quote=quote,
            source_url=url,
            retrieval_confidence=row.get("retrieval_confidence") or 0.0,
            answer_confidence=row.get("answer_confidence") or 0.0,
            search_queries_used=json.loads(row.get("search_queries_used") or "[]"),
            fetched_urls=[u for u in json.loads(row.get("fetched_urls") or "[]")
                          if str(u).startswith("http")],
            domain_trust_score=row.get("domain_trust_score"),
            language_route_used=row.get("language_route_used") or "native",
            notes=row.get("notes"),
        )
    except Exception as e:
        print(f"   ! could not build ResearcherOutput: {type(e).__name__}: {str(e)[:120]}")
        return None


# ============================================================
# Freeze evidence once, then run the four strategies
# ============================================================

def _snippet_to_text(s) -> str:
    """Researcher search_snippets rows are stored either as plain strings or as
    dicts ({title, snippet, url}). Coerce to the text the Researcher read."""
    if isinstance(s, str):
        return s.strip()
    if isinstance(s, dict):
        parts = [str(s.get("title") or ""), str(s.get("snippet") or s.get("text") or "")]
        return " ".join(p for p in parts if p).strip()
    return str(s).strip() if s else ""


def _freeze_evidence(cand: Candidate, ro: ResearcherOutput):
    """Run substring check + one query-gen + one search. Returns frozen block."""
    snippets_raw = cand.row.get("search_snippets")
    researcher_snips = []
    if snippets_raw:
        try:
            parsed = json.loads(snippets_raw)
            for s in parsed:
                txt = _snippet_to_text(s)
                if txt:
                    researcher_snips.append(txt)
        except Exception:
            researcher_snips = []

    sub_result, sub_notes, _ = _run_substring_check(
        str(ro.source_url), ro.evidence_quote,
        researcher_snippets=researcher_snips or None,
    )

    vinp = VerifierInput(
        question_id=cand.question_id, question_text=_question_text(cand.question_id),
        country_code=cand.country_code, country_name=cand.country_name,
        researcher_output=ro, strategy="verifier-disprove",
        answer_shape=cand.answer_shape, allowed_answers=list(cand.allowed_answers),
        researcher_snippets=researcher_snips,
    )
    try:
        queries, qusage = _call_with_retry(
            lambda: generate_adversarial_queries(vinp),
            label=f"query_gen {cand.cand_id}",
        )
    except StructuredOutputError:
        queries, qusage = [], None
    try:
        # Frozen-evidence search provider. Pinned (not "auto") so the evidence is
        # consistent across the whole run and identical across the four arms.
        # Originally DIY (Serper + trafilatura), but Serper credits are now
        # exhausted (400 "Not enough credits") and Tavily's quota was already
        # exhausted, so the pin moves to Brave, the one working provider. Brave
        # results pass the same deny-list scrub (_scrub_blocked), so no
        # answer-key domain re-enters the frozen block. The provider is the same
        # for all four strategy prompts, so it is not a between-arm confound.
        results = search_many(queries, max_results_per_query=5,
                              provider=FROZEN_SEARCH_PROVIDER) if queries else []
    except Exception as e:
        print(f"   ! search failed: {type(e).__name__}: {str(e)[:100]}")
        results = []
    independent_snippets = [f"{r.title} — {r.snippet[:200]}" for r in results]
    return {
        "substring_result": sub_result, "substring_notes": sub_notes,
        "queries": queries, "independent_snippets": independent_snippets,
        "query_gen_tokens": (qusage.output_tokens if qusage else 0),
        "vinp": vinp,
    }


_QTEXT_CACHE = {}

def _question_text(qid: str) -> str:
    if qid in _QTEXT_CACHE:
        return _QTEXT_CACHE[qid]
    with connect() as conn:
        row = conn.execute("select question_text from questions where question_id=?", (qid,)).fetchone()
    txt = row[0] if row else qid
    _QTEXT_CACHE[qid] = txt
    return txt


def _run_strategy(cand: Candidate, ro: ResearcherOutput, frozen: dict, strategy: str) -> dict:
    spec = verifier_prompt.STRATEGIES[strategy]
    user_message = verifier_prompt.build_user_message(
        question_text=frozen["vinp"].question_text,
        country_name=cand.country_name, country_code=cand.country_code,
        researcher_output=ro,
        substring_result=frozen["substring_result"], substring_notes=frozen["substring_notes"],
        independent_queries=frozen["queries"], independent_snippets=frozen["independent_snippets"],
        strategy=strategy, answer_shape=cand.answer_shape,
        allowed_answers=list(cand.allowed_answers),
    )
    try:
        out, usage = _call_with_retry(
            lambda: call_for_structured(
                system=spec.system, user_message=user_message,
                output_schema=VerifierOutput, max_tokens=1500, temperature=0.0,
                condition_label=EXPERIMENT_ID,
                usage_context=f"exp6_{strategy}:{cand.question_id}:{cand.country_code}",
            ),
            label=f"{strategy} {cand.cand_id}",
        )
    except StructuredOutputError as e:
        return {"strategy": strategy, "failure": "schema_invalid", "error": str(e)[:200],
                "verdict": None, "verifier_answer": None}

    # D28 normalisation, mirroring run_verifier.
    shape = answer_shapes.QuestionShape(cand.question_id, cand.answer_shape, tuple(cand.allowed_answers))
    norm = answer_shapes.normalise_answer(out.verifier_answer, shape)
    if norm != out.verifier_answer:
        out = out.model_copy(update={"verifier_answer": norm})

    # Blind post-processing: override to fail on divergence (production logic).
    blind_override = False
    if strategy == "verifier-blind" and out.verifier_answer != ro.answer:
        if out.verdict == "pass":
            blind_override = True
            out = out.model_copy(update={"verdict": "fail"})

    return {
        "strategy": strategy,
        "verdict": out.verdict,
        "verifier_answer": out.verifier_answer,
        "verifier_confidence": out.verifier_confidence,
        "substring_check_result": out.substring_check_result,
        "rejection_reason": (out.rejection_reason or "")[:300],
        "blind_override": blind_override,
        "output_tokens": usage.output_tokens,
        "input_tokens": usage.input_tokens,
        "wall_clock_ms": usage.wall_clock_ms,
        "cost_usd": usage.estimated_cost_usd,
        "failure": None,
    }


# ============================================================
# Registry
# ============================================================

def _register_experiment(n_cands: int, counts: dict):
    try:
        with connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO experiments (experiment_id, name, description, conditions, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (EXPERIMENT_ID,
                 "Verifier strategy discrimination (EXP-6)",
                 "Signal-detection comparison of the four D15 verifier strategies on a "
                 "paired, frozen-evidence candidate set. Primary endpoint Youden's J.",
                 json.dumps({"strategies": STRATEGIES, "seed": SEED,
                             "n_candidates": n_cands, "stratum_counts": counts})),
            )
            conn.commit()
    except Exception as e:
        print(f"[registry] could not register: {e}")


# ============================================================
# Run
# ============================================================

def _assert_serper_available() -> None:
    """Fail loudly if the sole search provider (Serper/DIY) is unavailable.

    EXP-6 holds the search provider constant; Serper is the one provider (no
    silent fallback to Brave/Tavily, which would vary the apparatus). If Serper
    is out of credits, the run STOPS here with a clear message rather than
    degrading. Only enforced when the frozen-evidence provider is the DIY
    (Serper) pipeline.
    """
    if FROZEN_SEARCH_PROVIDER not in ("diy", "serper_raw"):
        return
    from agents.tools.search_serper import check_serper_credits
    ok, reason = check_serper_credits()
    if not ok:
        raise RuntimeError(
            "EXP-6 ABORTED: Serper (the sole, held-constant search provider) is "
            f"unavailable -> {reason}. Top up Serper credits before running; the "
            "experiment will not silently fall back to another provider, because "
            "varying the search backend across the data is a confound."
        )
    print(f"[preflight] Serper available ({reason}). Provider held constant: "
          f"{FROZEN_SEARCH_PROVIDER}.", flush=True)


def run(limit: Optional[int] = None, workers: int = 1,
        cands_override: Optional[list] = None, out_name: Optional[str] = None):
    _assert_serper_available()
    cands = cands_override if cands_override is not None else build_candidates(limit=limit)
    counts = Counter((c.stratum, c.gold_label) for c in cands)
    ccounts = Counter(c.country_code for c in cands)
    dcounts = Counter(c.dimension for c in cands)
    print(f"Built {len(cands)} candidates. Strata: {dict(Counter(c.stratum for c in cands))}")
    print(f"  roles: {dict(Counter(c.role for c in cands))}")
    print(f"  gold labels: {dict(Counter(c.gold_label for c in cands))}")
    print(f"  country: {dict(ccounts)}")
    print(f"  dimension: {dict(dcounts)}")
    n_primary = sum(1 for c in cands if c.role == "primary")
    if n_primary == 0:
        print("  ! WARNING: primary (Malta) stratum is EMPTY -- the Malta dispatch "
              "is pending search quota. Only the robustness arm is runnable; the "
              "primary Youden's J is NOT computable from this run.")
    _register_experiment(len(cands), {f"{k[0]}/{k[1]}": v for k, v in counts.items()})

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / (out_name or f"verifier_strategies_{EXPERIMENT_ID}.jsonl")

    # ---- Resume support: never overwrite a partial run. ----
    done_ids: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("_record") == "candidate":
                done_ids.add(obj.get("cand_id"))
    if done_ids:
        print(f"Resuming: {len(done_ids)} candidates already done, will skip them.")
    fh = out_path.open("a")  # append, do not truncate
    if not done_ids:
        # Fresh file (or only had a stale header): rewrite with a clean header.
        fh.close()
        fh = out_path.open("w")
        fh.write(json.dumps({
            "_record": "header", "experiment_id": EXPERIMENT_ID, "seed": SEED,
            "strategies": STRATEGIES, "n_candidates": len(cands),
            "candidate_ids": [c.cand_id for c in cands],
            "stratum_counts": {f"{k[0]}/{k[1]}": v for k, v in counts.items()},
        }) + "\n")
        fh.flush()

    pending = [(i, cand) for i, cand in enumerate(cands, 1)
               if cand.cand_id not in done_ids]

    def _process(i: int, cand: Candidate):
        """All work for one candidate: freeze evidence once, run the four
        strategies over it. Independent per candidate, so safe to run in a
        thread pool. Returns the record dict, or None to skip (and be retried
        on the next resume)."""
        ro = _researcher_output(cand.row, cand.researcher_answer)
        if ro is None:
            print(f"[{i}/{len(cands)}] SKIP {cand.cand_id} (bad researcher output)")
            return None
        try:
            print(f"[{i}/{len(cands)}] START {cand.cand_id} [{cand.stratum}] "
                  f"gold={cand.gold_label} answer={cand.researcher_answer!r}")
            frozen = _freeze_evidence(cand, ro)
            rec = {
                "_record": "candidate", "cand_id": cand.cand_id, "stratum": cand.stratum,
                "role": cand.role,
                "gold_label": cand.gold_label, "question_id": cand.question_id,
                "country_code": cand.country_code, "dimension": cand.dimension,
                "answer_shape": cand.answer_shape, "researcher_answer": cand.researcher_answer,
                "gold_response": cand.gold_response, "injected": cand.injected,
                "source_row_id": cand.source_row_id,
                "substring_result": frozen["substring_result"],
                "n_independent_snippets": len(frozen["independent_snippets"]),
                "verdicts": {},
            }
            for strategy in STRATEGIES:
                res = _run_strategy(cand, ro, frozen, strategy)
                rec["verdicts"][strategy] = res
                mark = "?" if res["verdict"] is None else (
                    "OK " if (res["verdict"] == ("fail" if cand.gold_label == "should_fail" else "pass")) else "XX ")
                print(f"      {cand.cand_id} {strategy:18s} -> {str(res['verdict']):4s} "
                      f"ans={str(res['verifier_answer'])[:14]:14s} {mark}")
            return rec
        except Exception as e:  # noqa: BLE001 - one bad candidate must not kill the run
            print(f"[{i}/{len(cands)}] ERROR {cand.cand_id}: {e!r} (will retry on resume)")
            return None

    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    write_lock = threading.Lock()

    def _emit(rec):
        if rec is None:
            return
        with write_lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()

    if workers <= 1:
        for i, cand in pending:
            _emit(_process(i, cand))
    else:
        print(f"Running {len(pending)} candidates with {workers} parallel workers.")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_process, i, cand) for i, cand in pending]
            for fut in as_completed(futs):
                _emit(fut.result())

    fh.close()
    print(f"\nWrote {out_path}")
    analyse(out_path)
    return out_path


# ============================================================
# Analysis
# ============================================================

def _confusion(records, strategy, predicate=lambda r: True):
    tp = fp = tn = fn = 0
    n_missing = 0
    for r in records:
        if not predicate(r):
            continue
        v = r["verdicts"].get(strategy, {})
        verdict = v.get("verdict")
        if verdict is None:
            n_missing += 1
            continue
        gold_fail = r["gold_label"] == "should_fail"
        pred_fail = verdict == "fail"
        if gold_fail and pred_fail: tp += 1
        elif gold_fail and not pred_fail: fn += 1
        elif (not gold_fail) and pred_fail: fp += 1
        else: tn += 1
    return tp, fp, tn, fn, n_missing


def _metrics(tp, fp, tn, fn):
    import math
    pos = tp + fn  # should_fail
    neg = tn + fp  # should_pass
    sens = tp / pos if pos else float("nan")   # catch rate
    spec = tn / neg if neg else float("nan")
    fpr = fp / neg if neg else float("nan")     # false-rejection rate
    j = (sens + spec - 1) if (pos and neg) else float("nan")
    bal_acc = (sens + spec) / 2 if (pos and neg) else float("nan")
    denom = math.sqrt((tp+fp)*(tp+fn)*(tn+fp)*(tn+fn))
    mcc = ((tp*tn - fp*fn) / denom) if denom else float("nan")
    return dict(sens=sens, spec=spec, fpr=fpr, youden_j=j, bal_acc=bal_acc, mcc=mcc,
                pos=pos, neg=neg)


def analyse(path):
    path = Path(path)
    records = []
    header = None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("_record") == "header":
            header = obj
        elif obj.get("_record") == "candidate":
            records.append(obj)

    print("\n" + "=" * 78)
    print(f"EXP-6 ANALYSIS  —  {path.name}")
    print("=" * 78)
    print(f"Candidates analysed: {len(records)}  (seed {header['seed'] if header else '?'})")
    print(f"Strata: {dict(Counter(r['stratum'] for r in records))}")
    print(f"Gold:   {dict(Counter(r['gold_label'] for r in records))}")
    print(f"Country:{dict(Counter(r['country_code'] for r in records))}")
    print(f"Dim:    {dict(Counter(r['dimension'] for r in records))}")

    def report(label, predicate):
        sub = [r for r in records if predicate(r)]
        n_fail = sum(1 for r in sub if r["gold_label"] == "should_fail")
        n_pass = sum(1 for r in sub if r["gold_label"] == "should_pass")
        print(f"\n----- {label}  (n={len(sub)}: {n_fail} should_fail, {n_pass} should_pass) -----")
        if not sub or not n_fail or not n_pass:
            print("  (need both classes present; skipped)")
            return {}
        out = {}
        print(f"  {'strategy':20s} {'catch':>11s} {'falseRej':>11s} {'J':>6s} {'MCC':>6s} {'balAcc':>7s} {'passRate':>9s}")
        for s in STRATEGIES:
            tp, fp, tn, fn, miss = _confusion(sub, s, predicate=lambda r: True)
            m = _metrics(tp, fp, tn, fn)
            cl, ch = stats.wilson_interval(tp, m["pos"])
            fl, fh_ = stats.wilson_interval(fp, m["neg"])
            n_pass_verdict = sum(1 for r in sub if r["verdicts"].get(s, {}).get("verdict") == "pass")
            n_tot = sum(1 for r in sub if r["verdicts"].get(s, {}).get("verdict") is not None)
            pass_rate = n_pass_verdict / n_tot if n_tot else float("nan")
            out[s] = dict(tp=tp, fp=fp, tn=tn, fn=fn, miss=miss, pass_rate=pass_rate, **m)
            print(f"  {s:20s} {m['sens']:.2f}[{cl:.2f},{ch:.2f}] "
                  f"{m['fpr']:.2f}[{fl:.2f},{fh_:.2f}] {m['youden_j']:6.2f} "
                  f"{m['mcc']:6.2f} {m['bal_acc']:7.2f} {pass_rate:9.2f}")
        return out

    # Role is the primary axis (R4 retarget). Old JSONL records predate the
    # `role` field, so derive it from the country for backward compatibility.
    def _rec_role(r):
        return r.get("role") or _role_of(r.get("country_code")) or "robustness"

    combined = report("PRIMARY endpoint (Malta natural)", lambda r: _rec_role(r) == "primary")
    report("SECONDARY (Netherlands natural)", lambda r: _rec_role(r) == "secondary")
    report("ROBUSTNESS natural (FR/EE)",
           lambda r: _rec_role(r) == "robustness" and not r.get("injected"))
    report("ROBUSTNESS injected (INJ-fail + robustness pass)",
           lambda r: _rec_role(r) == "robustness" and (r.get("injected") or r["gold_label"] == "should_pass"))
    for dim in ["Policy", "Portal", "Impact", "Quality"]:
        report(f"PRIMARY Dimension={dim}",
               lambda r, d=dim: _rec_role(r) == "primary" and r["dimension"] == d)

    # Paired McNemar on verdict-correctness, Holm-corrected over the 6 pairs.
    # Scoped to the PRIMARY endpoint; if Malta is absent it falls back to the
    # robustness arm with an explicit label so the number is not misread as primary.
    primary_records = [r for r in records if _rec_role(r) == "primary"]
    if primary_records:
        mcnemar_records, mcnemar_scope = primary_records, "PRIMARY (Malta)"
    else:
        mcnemar_records = [r for r in records if _rec_role(r) == "robustness"]
        mcnemar_scope = "ROBUSTNESS only (no Malta dispatch yet; not the primary J)"
    print(f"\n----- Paired strategy comparison, {mcnemar_scope} "
          f"(McNemar exact on verdict-correctness, Holm) -----")
    def correct_vec(s):
        v = {}
        for r in mcnemar_records:
            verdict = r["verdicts"].get(s, {}).get("verdict")
            if verdict is None:
                v[r["cand_id"]] = None
                continue
            want = "fail" if r["gold_label"] == "should_fail" else "pass"
            v[r["cand_id"]] = (verdict == want)
        return v
    vecs = {s: correct_vec(s) for s in STRATEGIES}
    pairs = []
    for i in range(len(STRATEGIES)):
        for k in range(i + 1, len(STRATEGIES)):
            s1, s2 = STRATEGIES[i], STRATEGIES[k]
            b = c = 0  # b: s1 correct & s2 wrong ; c: s2 correct & s1 wrong
            for cid in vecs[s1]:
                a1, a2 = vecs[s1][cid], vecs[s2][cid]
                if a1 is None or a2 is None:
                    continue
                if a1 and not a2: b += 1
                elif a2 and not a1: c += 1
            p = stats.mcnemar_exact(b, c)
            pairs.append((s1, s2, b, c, p))
    # Holm
    pairs_sorted = sorted(pairs, key=lambda x: x[4])
    m = len(pairs_sorted)
    print(f"  {'pair':44s} {'b':>3s} {'c':>3s} {'p':>8s} {'p_holm':>8s}")
    for rank, (s1, s2, b, c, p) in enumerate(pairs_sorted):
        p_holm = min(1.0, p * (m - rank))
        better = s1 if b > c else (s2 if c > b else "tie")
        print(f"  {s1+' vs '+s2:44s} {b:3d} {c:3d} {p:8.4f} {p_holm:8.4f}  ({better} better)")

    # Cost: paired Wilcoxon of output tokens vs disprove baseline.
    print("\n----- Cost: main-call output tokens per candidate -----")
    base = "verifier-disprove"
    tok = {s: [] for s in STRATEGIES}
    lat = {s: [] for s in STRATEGIES}
    for r in records:
        ok = all(r["verdicts"].get(s, {}).get("output_tokens") is not None for s in STRATEGIES)
        if not ok:
            continue
        for s in STRATEGIES:
            tok[s].append(r["verdicts"][s].get("output_tokens") or 0)
            lat[s].append(r["verdicts"][s].get("wall_clock_ms") or 0)
    import statistics as st
    print(f"  {'strategy':20s} {'med_out_tok':>12s} {'mean_out_tok':>13s} {'med_ms':>8s}")
    for s in STRATEGIES:
        if tok[s]:
            print(f"  {s:20s} {st.median(tok[s]):12.0f} {st.mean(tok[s]):13.0f} {st.median(lat[s]):8.0f}")
    print(f"\n  Wilcoxon signed-rank, output tokens vs {base}:")
    for s in STRATEGIES:
        if s == base or not tok[s]:
            continue
        diffs = [tok[s][k] - tok[base][k] for k in range(len(tok[s]))]
        try:
            W, p = stats.wilcoxon_signed_rank(diffs)
            med = st.median(diffs)
            print(f"    {s:20s} median delta {med:+7.0f} tok   W={W:.1f} p={p:.4f}")
        except Exception as e:
            print(f"    {s:20s} (wilcoxon unavailable: {e})")

    # Winner
    if combined:
        best = max(combined.items(), key=lambda kv: (kv[1]["youden_j"] if kv[1]["youden_j"] == kv[1]["youden_j"] else -9))
        print(f"\n>>> Highest Youden's J (combined): {best[0]} "
              f"(J={best[1]['youden_j']:.2f}, catch={best[1]['sens']:.2f}, "
              f"falseRej={best[1]['fpr']:.2f}, MCC={best[1]['mcc']:.2f})")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="smoke run: cap candidates")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel candidate workers (each does 4 strategy calls). "
                         "Resilient to proxy connection blips via the SDK retry bump.")
    ap.add_argument("--analyse-only", default=None, help="re-analyse an existing JSONL")
    ap.add_argument("--fr-augmented", nargs="?", const=str(FR_AUGMENTED_FILE),
                    default=None,
                    help="Run the four-arm judge over the committed, class-balanced "
                         "FR robustness set (data/questions/fr_augmented_eval_pairs.json) "
                         "instead of the default seeded draw. Robustness arm only, "
                         "written to its own JSONL; the primary run is untouched.")
    args = ap.parse_args()
    if args.analyse_only:
        analyse(args.analyse_only)
    elif args.fr_augmented:
        cands = build_fr_augmented_candidates(Path(args.fr_augmented))
        run(workers=args.workers, cands_override=cands,
            out_name="verifier_strategies_fr_augmented.jsonl")
    else:
        run(limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
