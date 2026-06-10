"""Dispatch N parallel Coordinator subprocesses.

The higher-order entry point. Spawns one `run_coordinator.py` subprocess
per (question, country) pair, up to `--parallel` at a time. Holds a
semaphore. Re-checks the rolling 5-hour cost before each new spawn.
Catches EXIT_CODE_RATE_LIMITED (42) from any child and terminates the
remaining batch cleanly.

Usage:
    uv run python scripts/dispatch_subtrios.py \\
        --questions Q2 Q3 Q4 Q5 \\
        --countries FR RO DE \\
        --strategy verifier-disprove \\
        --parallel 4

Used by both the dashboard and the CLI. The dashboard imports
`dispatch_subtrios.dispatch(...)` and never shells out to argparse.
"""

from __future__ import annotations

import argparse
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.errors import EXIT_CODE_RATE_LIMITED, EXIT_CODE_BLOCKER
from agents.tools.db import DB_PATH, connect
from dashboard.lib.currency import format_gbp


# Cold-start default per spec §6.1: conservative upper bound based on
# the P1 / I1 baseline runs (~$0.085 per subtrio with one Researcher +
# one Verifier).
COLD_START_COST_PER_SUBTRIO = 0.10
DEFAULT_RETRY_UPLIFT = 1.2

# Runaway guards (D41). These are circuit breakers, not a budget: set far
# above any real experiment so a normal run never trips them, and they fire
# only on a clearly misspecified dispatch that would eat the 5-hour Claude
# Max window. They replace the dollar soft limit (D40), including the $20
# raise that landed concurrently on main, which is moot once the limit is
# removed: a guess at a flat subscription's equivalent cost never tracked a
# real balance, so it was friction without protection.
#
# A single dispatch above this many pairs is refused unless allow_large is
# set. The biggest legitimate runs are ~100-150 pairs (a full single
# country); the all-questions x all-countries cross-product accident is
# 5,148 pairs. 500 sits cleanly between, so it catches the footgun without
# nagging a real run.
MAX_PAIRS_PER_DISPATCH = 500


# ============================================================
# Cost prediction
# ============================================================
#
# The dispatcher predicts and reports spend, but does NOT enforce a cap.
# The only real ceiling is whatever Claude Max enforces; a local soft
# limit only ever got in the way, so it was removed. The rolling-window
# cost is still computed and logged as information.

@dataclass
class CostEstimate:
    per_subtrio_usd: float
    projected_total_usd: float
    rolling_window_cost_usd: float
    fallback_level: str  # "tuple" / "model-triple" / "model-pair" / "cold_start"
    sample_size: int


def estimate_pair_cost(
    *,
    researcher_model: str,
    verifier_model: str,
    adjudicator_model: str,
    strategy: str,
    n_pairs: int,
    retry_uplift: float = DEFAULT_RETRY_UPLIFT,
) -> CostEstimate:
    """Estimate per-subtrio cost from history, with three fallback levels.

    Per spec §6.1: match on the exact model/strategy tuple first; fall
    back to looser matches; ultimately use the cold-start default. This is
    a projection for display only; it never blocks a dispatch.
    """
    with connect() as conn:
        # Level 1: exact tuple
        rows = conn.execute(
            """SELECT cumulative_cost_usd FROM subtrio_status
               WHERE researcher_model = ? AND verifier_model = ?
                 AND adjudicator_model = ? AND verifier_strategy = ?
                 AND stage IN ('done', 'failed')
                 AND cumulative_cost_usd IS NOT NULL
               ORDER BY started_at DESC LIMIT 50""",
            (researcher_model, verifier_model, adjudicator_model, strategy),
        ).fetchall()
        if len(rows) >= 5:
            mean_cost = sum(r[0] for r in rows) / len(rows)
            fallback = "tuple"
        else:
            # Level 2: model triple, ignore strategy
            rows = conn.execute(
                """SELECT cumulative_cost_usd FROM subtrio_status
                   WHERE researcher_model = ? AND verifier_model = ?
                     AND adjudicator_model = ?
                     AND stage IN ('done', 'failed')
                     AND cumulative_cost_usd IS NOT NULL
                   ORDER BY started_at DESC LIMIT 50""",
                (researcher_model, verifier_model, adjudicator_model),
            ).fetchall()
            if len(rows) >= 5:
                mean_cost = sum(r[0] for r in rows) / len(rows)
                fallback = "model-triple"
            else:
                # Level 3: researcher + verifier model only
                rows = conn.execute(
                    """SELECT cumulative_cost_usd FROM subtrio_status
                       WHERE researcher_model = ? AND verifier_model = ?
                         AND stage IN ('done', 'failed')
                         AND cumulative_cost_usd IS NOT NULL
                       ORDER BY started_at DESC LIMIT 50""",
                    (researcher_model, verifier_model),
                ).fetchall()
                if len(rows) >= 5:
                    mean_cost = sum(r[0] for r in rows) / len(rows)
                    fallback = "model-pair"
                else:
                    mean_cost = COLD_START_COST_PER_SUBTRIO
                    fallback = "cold_start"
                    rows = []

    rolling_cost = rolling_window_cost_usd()
    return CostEstimate(
        per_subtrio_usd=mean_cost,
        projected_total_usd=mean_cost * n_pairs * retry_uplift,
        rolling_window_cost_usd=rolling_cost,
        fallback_level=fallback,
        sample_size=len(rows),
    )


def rolling_window_cost_usd(window_hours: float = 5.0) -> float:
    """Sum of estimated_cost_usd from the last `window_hours`."""
    cutoff = (datetime.utcnow() - timedelta(hours=window_hours))\
        .isoformat(timespec="seconds") + "Z"
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) "
            "FROM claude_usage_log WHERE timestamp > ?",
            (cutoff,),
        ).fetchone()
    return float(row[0]) if row else 0.0


# ============================================================
# Dispatch
# ============================================================

@dataclass
class SubtrioJob:
    subtrio_id: str
    batch_id: str
    question_id: str
    country_code: str
    process: Optional[subprocess.Popen] = None
    exit_code: Optional[int] = None


@dataclass
class DispatchResult:
    batch_id: str
    jobs: List[SubtrioJob]
    rate_limited: bool = False
    blocked: bool = False
    aborted_oversize: bool = False
    calls_capped: bool = False
    messages: List[str] = field(default_factory=list)


def dispatch(
    *,
    questions: Sequence[str] = (),
    countries: Sequence[str] = (),
    pairs: Optional[Sequence[tuple[str, str]]] = None,
    strategy: str = "verifier-disprove",
    researcher_model: Optional[str] = None,
    verifier_model: Optional[str] = None,
    adjudicator_model: Optional[str] = None,
    researcher_escalation_model: Optional[str] = None,
    verifier_escalation_model: Optional[str] = None,
    prompt_variant: str = "full",
    parallel_limit: int = 4,
    max_retries: int = 3,
    provider: str = "auto",
    max_results_per_query: int = 5,
    num_queries: Optional[int] = None,
    no_cache: bool = False,
    chained: bool = False,
    batch_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    condition_label: Optional[str] = None,
    allow_large: bool = False,
    max_calls: Optional[int] = None,
    on_message: Optional[Callable[[str], None]] = None,
) -> DispatchResult:
    """Spawn one Coordinator subprocess per pair.

    Pass `pairs=[(qid, cc), ...]` to dispatch an explicit sparse set,
    or `questions` + `countries` to dispatch the full cross product.
    `pairs` takes precedence if both are given.

    Returns when all subprocesses have exited (or rate-limit shutdown
    triggered a global terminate). There is no cost budget: the pre-flight
    estimate is logged for information only. The only guards are runaway
    circuit breakers (D41), set far above any real run:

    - A dispatch above `MAX_PAIRS_PER_DISPATCH` pairs is refused unless
      `allow_large=True`, to catch a misspecified cross-product before it
      spends anything.
    - If `max_calls` is set, the loop stops spawning new subtrios once this
      batch's logged Claude calls reach it (a mid-flight breaker for a
      runaway retry/chaining loop). Off by default.

    The real ceiling remains Claude Max's own rate limit, which surfaces as
    a 429 and a clean interrupted-and-resumable shutdown.
    """
    batch_id = batch_id or str(uuid.uuid4())
    log = on_message or (lambda m: print(f"[dispatch] {m}", flush=True))

    if pairs is not None:
        normalised_pairs = [(q, c.upper()) for q, c in pairs]
    else:
        normalised_pairs = [
            (q, c.upper()) for q in questions for c in countries
        ]

    pairs = normalised_pairs
    if not pairs:
        return DispatchResult(batch_id=batch_id, jobs=[],
                              messages=["no pairs to dispatch"])

    # Runaway guard (D41): refuse an oversized dispatch before spending
    # anything. Almost always a misspecified cross-product.
    if len(pairs) > MAX_PAIRS_PER_DISPATCH and not allow_large:
        msg = (
            f"REFUSED: {len(pairs)} pairs in one dispatch exceeds the "
            f"{MAX_PAIRS_PER_DISPATCH}-pair runaway guard. This is almost "
            f"always a misspecified cross-product (e.g. all questions x all "
            f"countries). Re-run with allow_large=True / --allow-large if you "
            f"really mean it, or split it into smaller batches."
        )
        log(msg)
        return DispatchResult(
            batch_id=batch_id, jobs=[], aborted_oversize=True, messages=[msg],
        )

    # Resolve model defaults from the DB if any are None.
    researcher_model = researcher_model or _read_default("researcher")
    verifier_model = verifier_model or _read_default("verifier")
    adjudicator_model = adjudicator_model or _read_default("adjudicator")

    # Pre-flight cost projection (informational; never blocks a dispatch).
    estimate = estimate_pair_cost(
        researcher_model=researcher_model,
        verifier_model=verifier_model,
        adjudicator_model=adjudicator_model,
        strategy=strategy,
        n_pairs=len(pairs),
    )
    log(
        f"pre-flight: {len(pairs)} pairs, est "
        f"{format_gbp(estimate.per_subtrio_usd, places=3)}/pair "
        f"(fallback={estimate.fallback_level}, n={estimate.sample_size}), "
        f"projected {format_gbp(estimate.projected_total_usd)}, "
        f"window-used {format_gbp(estimate.rolling_window_cost_usd)} (5h)"
    )

    # Build the job list.
    jobs: List[SubtrioJob] = [
        SubtrioJob(
            subtrio_id=str(uuid.uuid4()),
            batch_id=batch_id,
            question_id=q,
            country_code=c,
        ) for (q, c) in pairs
    ]

    # The dispatch loop. Run with a semaphore equal to parallel_limit.
    sem = threading.Semaphore(parallel_limit)
    rate_limited = False
    blocked = False
    calls_capped = False
    all_subtrio_ids = [j.subtrio_id for j in jobs]

    def spawn(job: SubtrioJob) -> None:
        nonlocal rate_limited, blocked, calls_capped
        sem.acquire()
        try:
            if rate_limited or blocked or calls_capped:
                return

            # Mid-flight runaway breaker (D41): stop spawning once this
            # batch's logged calls reach the cap. Off unless max_calls is set.
            if max_calls is not None:
                spent = _batch_call_count(all_subtrio_ids)
                if spent >= max_calls:
                    if not calls_capped:
                        log(
                            f"max-calls breaker: {spent} >= {max_calls} calls "
                            f"this batch; stopping new spawns"
                        )
                    calls_capped = True
                    return

            cmd = [
                sys.executable, str(REPO_ROOT / "scripts" / "run_coordinator.py"),
                job.question_id, job.country_code,
                "--strategy", strategy,
                "--max-retries", str(max_retries),
                "--subtrio-id", job.subtrio_id,
                "--batch-id", job.batch_id,
            ]
            if researcher_model:
                cmd += ["--researcher-model", researcher_model]
            if verifier_model:
                cmd += ["--verifier-model", verifier_model]
            if adjudicator_model:
                cmd += ["--adjudicator-model", adjudicator_model]
            if researcher_escalation_model:
                cmd += ["--researcher-escalation-model",
                        researcher_escalation_model]
            if verifier_escalation_model:
                cmd += ["--verifier-escalation-model",
                        verifier_escalation_model]
            if prompt_variant and prompt_variant != "full":
                cmd += ["--prompt-variant", prompt_variant]
            if provider and provider != "auto":
                cmd += ["--provider", provider]
            cmd += ["--max-results-per-query", str(max_results_per_query)]
            if num_queries is not None:
                cmd += ["--num-queries", str(num_queries)]
            if no_cache:
                # Cold-cache mode (EXP-2): tell each child to bypass DIY cache
                # reads so its measured search cost is not understated by a
                # prior condition's cached hits.
                cmd += ["--no-cache"]
            if chained:
                # EXP-7 evidence-accumulation arm; default off, so the
                # baseline batch is byte-identical to the independent loop.
                cmd += ["--chained"]
            if experiment_id:
                cmd += ["--experiment-id", experiment_id]
            if condition_label:
                cmd += ["--condition-label", condition_label]

            log(f"spawn {job.question_id}/{job.country_code} subtrio={job.subtrio_id[:8]}")
            job.process = subprocess.Popen(
                cmd, cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            job.exit_code = job.process.wait()
            if job.exit_code == EXIT_CODE_RATE_LIMITED:
                log(f"!! RATE LIMIT on {job.question_id}/{job.country_code}")
                rate_limited = True
            elif job.exit_code == EXIT_CODE_BLOCKER:
                # DIY fetch blocker (D43): stop the whole batch, same as a 429.
                log(f"!! DIY BLOCKER (>30s fetch) on "
                    f"{job.question_id}/{job.country_code} - stopping batch")
                blocked = True
        finally:
            sem.release()

    threads: List[threading.Thread] = []
    for job in jobs:
        if rate_limited or blocked or calls_capped:
            break
        t = threading.Thread(target=spawn, args=(job,))
        t.start()
        threads.append(t)
        # Tiny stagger so the mid-flight breaker can take effect.
        time.sleep(0.05)

    # Wait for everything to finish.
    for t in threads:
        t.join()

    # If we hit a global stop (429 or DIY blocker), terminate any still-alive
    # children just in case.
    if rate_limited or blocked:
        for job in jobs:
            if job.process and job.process.poll() is None:
                try:
                    job.process.terminate()
                    job.process.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    pass
                _mark_interrupted(job.subtrio_id)

    result = DispatchResult(
        batch_id=batch_id,
        jobs=jobs,
        rate_limited=rate_limited,
        blocked=blocked,
        calls_capped=calls_capped,
        messages=[],
    )

    # Ship the new DB rows to the public dashboard. Per D25.
    publish_to_main(result, log=log)

    return result


def _read_default(role: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT model FROM model_defaults WHERE agent_role = ?",
            (role,),
        ).fetchone()
    return row[0] if row else "claude-sonnet-4-6"


def _batch_call_count(subtrio_ids: List[str]) -> int:
    """Total Claude calls logged so far for this batch's subtrios.

    Used by the optional mid-flight --max-calls runaway breaker (D41). Counts
    rows in claude_usage_log scoped to the batch, so it measures this batch's
    own spend, not the whole rolling window.
    """
    if not subtrio_ids:
        return 0
    placeholders = ",".join("?" * len(subtrio_ids))
    with connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM claude_usage_log "
            f"WHERE subtrio_id IN ({placeholders})",
            tuple(subtrio_ids),
        ).fetchone()
    return int(row[0]) if row else 0


def _mark_interrupted(subtrio_id: str) -> None:
    try:
        with connect() as conn:
            conn.execute(
                """UPDATE subtrio_status
                   SET stage = 'interrupted_rate_limit',
                       final_verdict = 'interrupted_rate_limit',
                       ended_at = ?, updated_at = ?
                   WHERE subtrio_id = ? AND ended_at IS NULL""",
                (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    subtrio_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[dispatch] _mark_interrupted failed: {exc}", file=sys.stderr)


# ============================================================
# Auto-publish to the public dashboard (per D25)
# ============================================================

def publish_to_main(
    result: DispatchResult,
    *,
    log: Callable[[str], None] = lambda m: print(f"[publish] {m}", flush=True),
) -> None:
    """Commit data/odmi.db and push to origin/main so Streamlit Cloud redeploys.

    Skips silently if `ODMI_SKIP_AUTO_PUBLISH` is set, the working tree is
    not on main, or odmi.db has not changed. Push failures are logged, not
    raised; the next batch will sweep them up.
    """
    if os.environ.get("ODMI_SKIP_AUTO_PUBLISH"):
        log("auto-publish disabled (ODMI_SKIP_AUTO_PUBLISH set)")
        return

    # Checkpoint the WAL so the .db file on disk contains every write.
    try:
        wal_con = sqlite3.connect(str(DB_PATH))
        try:
            wal_con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            wal_con.close()
    except Exception as exc:  # noqa: BLE001
        log(f"WAL checkpoint failed (continuing anyway): {exc}")

    def _git(*args: str) -> tuple[int, str]:
        proc = subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    rc, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or branch != "main":
        log(f"skipped (current branch is '{branch}', deploy only fires from main)")
        return

    rc, _ = _git("diff", "HEAD", "--quiet", "--", str(DB_PATH))
    if rc == 0:
        log("nothing to publish (odmi.db unchanged vs HEAD)")
        return

    qids = sorted({j.question_id for j in result.jobs})
    countries = sorted({j.country_code for j in result.jobs})
    n_ok = sum(1 for j in result.jobs if j.exit_code == 0)
    n_total = len(result.jobs)
    q_label = ",".join(qids[:4]) + (f"+{len(qids) - 4}" if len(qids) > 4 else "")
    c_label = ",".join(countries[:6]) + (f"+{len(countries) - 6}" if len(countries) > 6 else "")
    flags = []
    if result.rate_limited:
        flags.append("rate-limited")
    if result.calls_capped:
        flags.append("calls-capped")
    suffix = f" [{', '.join(flags)}]" if flags else ""
    msg = f"Batch: {q_label} x {c_label} ({n_ok}/{n_total} ok){suffix}"

    rc, out = _git("add", str(DB_PATH))
    if rc != 0:
        log(f"git add failed, skipping push: {out}")
        return

    rc, out = _git("commit", "-m", msg)
    if rc != 0:
        log(f"git commit failed, skipping push: {out}")
        return
    log(f"committed '{msg}'")

    rc, out = _git("push", "origin", "main")
    if rc != 0:
        log(f"git push failed (commit is local; next batch will retry): {out}")
        return
    log("pushed to origin/main; Streamlit Cloud will rebuild in ~30 s")


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch N coordinator subprocesses.")
    parser.add_argument(
        "--questions", nargs="+", default=[],
        help="Question IDs. Combined with --countries as a cross product "
             "unless --pairs is given.",
    )
    parser.add_argument(
        "--countries", nargs="+", default=[],
        help="Country codes. Combined with --questions as a cross product "
             "unless --pairs is given.",
    )
    parser.add_argument(
        "--pairs", nargs="+", default=None,
        metavar="QID:CC",
        help="Explicit pair list (e.g. P1:FR P2:DE). Overrides the "
             "cross product. Use this when you want a sparse set.",
    )
    parser.add_argument("--strategy", default="verifier-disprove")
    parser.add_argument("--researcher-model", default=None)
    parser.add_argument("--verifier-model", default=None)
    parser.add_argument("--adjudicator-model", default=None)
    parser.add_argument("--researcher-escalation-model", default=None,
                        help="EXP-8 model-fallback: Researcher model on a retry "
                             "after a Verifier reject (attempt 0 uses the base "
                             "model). Unset = hold one model.")
    parser.add_argument("--verifier-escalation-model", default=None,
                        help="EXP-8 model-fallback: Verifier model on a retry. "
                             "Unset = hold one model.")
    parser.add_argument("--prompt-variant", default="full",
                        choices=["full", "compressed"],
                        help="Researcher system prompt (EXP-8 prompt-compressed "
                             "arm). 'full' baseline; 'compressed' is leaner.")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--provider", default="auto",
                        choices=["auto", "tavily", "brave", "diy", "serper_raw"],
                        help="Search provider for the swarm (D27 experiment knob).")
    parser.add_argument("--max-results-per-query", type=int, default=5,
                        help="Results per search query (cost/recall knob).")
    parser.add_argument("--num-queries", type=int, default=None,
                        help="Cap generated search queries to this many (cost knob).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Cold-cache mode (EXP-2): disable DIY cache reads "
                             "for every pair in this batch so each condition "
                             "pays its own full search cost. Forwarded to each "
                             "run_coordinator subprocess. Default OFF.")
    parser.add_argument("--chained", action="store_true",
                        help="EXP-7 evidence-accumulation arm: feed the "
                             "Verifier's counter-evidence back to the "
                             "Researcher, carry a corpus across rounds, and "
                             "adjudicate over the whole corpus. Forwarded to "
                             "each run_coordinator subprocess. Default OFF, so "
                             "the baseline batch is byte-identical.")
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--experiment-id", default=None,
                        help="Tag every child row with this experiment_id (D27). "
                             "NULL means a main-results run.")
    parser.add_argument("--condition-label", default=None,
                        help="Per-condition label inside an experiment (e.g. "
                             "'disprove' vs 'approve').")
    parser.add_argument("--allow-large", action="store_true",
                        help=f"Override the {MAX_PAIRS_PER_DISPATCH}-pair "
                             f"runaway guard (D41). Needed only for a "
                             f"deliberately huge single dispatch; normal runs "
                             f"never approach it.")
    parser.add_argument("--max-calls", type=int, default=None,
                        help="Mid-flight runaway breaker (D41): stop spawning "
                             "new subtrios once this batch has logged this many "
                             "Claude calls. Default off. A normal pair is ~5 "
                             "calls (~17 worst case), so set this well above "
                             "n_pairs x 17 if you use it.")
    args = parser.parse_args()

    explicit_pairs = None
    if args.pairs:
        try:
            explicit_pairs = [tuple(p.split(":", 1)) for p in args.pairs]
        except ValueError:
            parser.error("--pairs entries must be QID:CC")
        bad = [p for p in explicit_pairs if len(p) != 2 or not p[0] or not p[1]]
        if bad:
            parser.error(f"--pairs entries must be QID:CC; bad: {bad}")
    elif not (args.questions and args.countries):
        parser.error(
            "either --pairs or both --questions and --countries are required"
        )

    result = dispatch(
        questions=args.questions,
        countries=args.countries,
        pairs=explicit_pairs,
        strategy=args.strategy,
        researcher_model=args.researcher_model,
        verifier_model=args.verifier_model,
        adjudicator_model=args.adjudicator_model,
        researcher_escalation_model=args.researcher_escalation_model,
        verifier_escalation_model=args.verifier_escalation_model,
        prompt_variant=args.prompt_variant,
        parallel_limit=args.parallel,
        max_retries=args.max_retries,
        provider=args.provider,
        max_results_per_query=args.max_results_per_query,
        num_queries=args.num_queries,
        no_cache=args.no_cache,
        chained=args.chained,
        batch_id=args.batch_id,
        experiment_id=args.experiment_id,
        condition_label=args.condition_label,
        allow_large=args.allow_large,
        max_calls=args.max_calls,
    )

    print(f"\n=== DISPATCH COMPLETE ===")
    print(f"batch_id: {result.batch_id}")
    print(f"jobs: {len(result.jobs)}")
    print(f"rate_limited: {result.rate_limited}")
    if result.blocked:
        print(f"blocked (DIY fetch >30s): {result.blocked}")
    if result.aborted_oversize:
        print(f"aborted_oversize: {result.aborted_oversize}")
    if result.calls_capped:
        print(f"calls_capped: {result.calls_capped}")
    if result.rate_limited:
        return EXIT_CODE_RATE_LIMITED
    if result.blocked:
        return EXIT_CODE_BLOCKER
    return 0


if __name__ == "__main__":
    sys.exit(main())
