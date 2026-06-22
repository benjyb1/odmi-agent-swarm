#!/usr/bin/env python3
"""ODMI experiment orchestrator.

One process owns every arm of an experiment run, so the two concurrency catches
are solved by construction instead of by remembering a flag:

  1. Shared-cache contamination. The DIY search cache is keyed on query/url, not
     on experiment_id, so two arms that vary retrieval would read each other's
     snippets. Any experiment whose `type` is `retrieval` or `cost` is forced to
     --no-cache, and the preflight refuses to start it warm.

  2. Search-side concurrency ceiling. Arms run SEQUENTIALLY, each internally
     parallel up to one global in-flight cap. The binding limit is a global cap
     on concurrent DIY pipelines (Serper quota and target-site WAFs, not the
     shared Claude budget, which is linear per D42), so sequential-at-cap gives
     the same throughput as concurrent-at-global-cap, with clean per-arm cost,
     natural reflection points between arms, and no cross-arm cache race.

It also enforces the D47 hold-out (the eight eval countries can never appear in
a development run), a per-run Claude-call budget so nothing runs away, health
checks with a stop-and-think pause when an arm comes back unhealthy, and a
manifest plus JSONL event log so every run replays from disk.

Spec format and the methodology this enforces live in docs/EXPERIMENT_RUNBOOK.md.

Usage:
    uv run python scripts/run_experiments.py path/to/spec.json
    uv run python scripts/run_experiments.py path/to/spec.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "odmi.db"
RUNS_DIR = REPO / "evaluation" / "runs"

# D47 held-out evaluation set. These may never appear in a development run.
HELD_OUT = {"BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"}
# D47 in-sample development set. Experiments draw from here.
DEV = {"NL", "MT", "NO", "FR", "AL"}

# Experiment types whose endpoint is contaminated by a warm shared cache.
CACHE_MUST_BE_OFF = {"retrieval", "cost"}

# Worst-case Claude calls per pair (a normal pair is ~5; the retry ceiling is
# ~17). Used for the budget guard so an arm cannot silently overrun.
CALLS_PER_PAIR_WORST = 17

# Health thresholds. An arm that breaches either comes back as a PAUSE: the run
# stops so a human or the experiment agent can diagnose before more is spent.
BLOCKER_RATE_PAUSE = 0.25   # fraction of pairs stuck on blocker/rate-limit/fail
FINALISE_RATE_FLOOR = 0.60  # fraction of expected pairs that must finalise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Spec loading and pair expansion
# --------------------------------------------------------------------------- #

def load_spec(path: Path) -> Dict[str, Any]:
    spec = json.loads(path.read_text())
    spec.setdefault("global_parallel", 8)
    spec.setdefault("budget_calls", None)
    if not spec.get("run_id"):
        raise ValueError("spec needs a 'run_id'")
    if not spec.get("experiments"):
        raise ValueError("spec needs a non-empty 'experiments' list")
    return spec


def _questions_from_file(p: Path) -> List[str]:
    data = json.loads(p.read_text())
    pairs = data.get("pairs", data) if isinstance(data, dict) else data
    seen, out = set(), []
    for row in pairs:
        qid = row["question_id"] if isinstance(row, dict) else str(row)
        if qid not in seen:
            seen.add(qid)
            out.append(qid)
    return out


def expand_pairs(exp: Dict[str, Any]) -> List[str]:
    """Return a list of 'QID:CC' strings for one experiment."""
    if exp.get("pairs"):
        return list(exp["pairs"])
    if exp.get("questions"):
        questions = list(exp["questions"])
    elif exp.get("questions_from"):
        questions = _questions_from_file(REPO / exp["questions_from"])
    else:
        raise ValueError(
            f"experiment {exp.get('experiment_id')!r} needs 'pairs', "
            f"'questions', or 'questions_from'"
        )
    countries = exp.get("countries")
    if not countries:
        raise ValueError(
            f"experiment {exp.get('experiment_id')!r} needs 'countries'"
        )
    return [f"{q}:{c}" for c in countries for q in questions]


# --------------------------------------------------------------------------- #
# Preflight: the methodological gate (see EXPERIMENT_RUNBOOK.md)
# --------------------------------------------------------------------------- #

def preflight(spec: Dict[str, Any]) -> List[str]:
    """Return a list of hard errors. An empty list means the run may proceed."""
    errors: List[str] = []

    if spec.get("budget_calls") is None:
        errors.append(
            "no 'budget_calls' ceiling set; every run declares a hard call "
            "budget so it cannot run away"
        )

    try:
        import agents.tools.blocked_domains  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        errors.append(f"deny-list module not importable ({exc}); D24 unverified")

    for exp in spec["experiments"]:
        eid = exp.get("experiment_id")
        if not eid:
            errors.append("an experiment is missing 'experiment_id'")
            continue
        exp_type = exp.get("type")
        if exp_type not in {"accuracy", "retrieval", "cost", "replay"}:
            errors.append(
                f"{eid}: 'type' must be accuracy|retrieval|cost|replay, "
                f"got {exp_type!r}"
            )

        try:
            pairs = expand_pairs(exp)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        # D47 hold-out: no eval country may appear in a development run.
        bad = sorted({p.split(":", 1)[1] for p in pairs} & HELD_OUT)
        if bad:
            errors.append(
                f"{eid}: held-out D47 eval countries present {bad}; these are "
                f"frozen until the headline run and must never appear here"
            )
        unknown = sorted({p.split(":", 1)[1] for p in pairs} - DEV - HELD_OUT)
        if unknown:
            errors.append(
                f"{eid}: countries {unknown} are neither dev nor held-out; "
                f"confirm they belong in a development run before proceeding"
            )

        arms = exp.get("arms", [])
        if len(arms) < 1:
            errors.append(f"{eid}: needs at least one arm")
        labels = [a.get("condition_label") for a in arms]
        if len(set(labels)) != len(labels) or None in labels:
            errors.append(f"{eid}: each arm needs a unique 'condition_label'")

        # One-variable check: every arm should differ from the baseline in at
        # most one knob, or the comparison is confounded (see runbook).
        if exp_type != "replay" and len(arms) > 1:
            base = arms[0].get("knobs", {})
            for a in arms[1:]:
                diff = {
                    k for k in set(base) | set(a.get("knobs", {}))
                    if base.get(k) != a.get("knobs", {}).get(k)
                }
                if len(diff) > 1:
                    errors.append(
                        f"{eid}/{a.get('condition_label')}: differs from the "
                        f"baseline in {sorted(diff)} (more than one variable); "
                        f"split into separate experiments or fix the confound"
                    )

    return errors


# --------------------------------------------------------------------------- #
# DB health and budget
# --------------------------------------------------------------------------- #

def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))

def calls_since(ts: str) -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM claude_usage_log WHERE timestamp >= ?", (ts,)
        ).fetchone()[0]


def arm_health(experiment_id: str, condition_label: str, expected: int) -> Dict[str, Any]:
    with _conn() as c:
        finalised = c.execute(
            "SELECT COUNT(*) FROM phase2_final WHERE experiment_id IS ? "
            "AND pair_run_id IN (SELECT subtrio_id FROM subtrio_status "
            "WHERE experiment_id IS ? )",
            (experiment_id, experiment_id),
        ).fetchone()[0]
        rows = c.execute(
            "SELECT stage, COUNT(*) FROM subtrio_status WHERE experiment_id IS ? "
            "GROUP BY stage", (experiment_id,),
        ).fetchall()
    stages = {s: n for s, n in rows}
    total = sum(stages.values()) or 1
    blocked = sum(
        stages.get(s, 0)
        for s in ("interrupted_blocker", "interrupted_rate_limit", "failed", "orphaned")
    )
    blocker_rate = blocked / total
    finalise_rate = finalised / expected if expected else 0.0
    healthy = blocker_rate <= BLOCKER_RATE_PAUSE and finalise_rate >= FINALISE_RATE_FLOOR
    return {
        "finalised": finalised,
        "expected": expected,
        "finalise_rate": round(finalise_rate, 3),
        "blocked": blocked,
        "blocker_rate": round(blocker_rate, 3),
        "stages": stages,
        "healthy": healthy,
    }


# --------------------------------------------------------------------------- #
# Dispatch one arm
# --------------------------------------------------------------------------- #

def build_command(exp: Dict[str, Any], arm: Dict[str, Any], pairs: List[str],
                  global_parallel: int) -> List[str]:
    knobs = {**exp.get("baseline_knobs", {}), **arm.get("knobs", {})}
    cmd = [
        "uv", "run", "python", "scripts/dispatch_subtrios.py",
        "--pairs", *pairs,
        "--parallel", str(global_parallel),
        "--experiment-id", exp["experiment_id"],
        "--condition-label", arm["condition_label"],
        "--max-calls", str(len(pairs) * CALLS_PER_PAIR_WORST + 50),
    ]
    # Cache discipline: forced off for retrieval/cost; honoured otherwise.
    if exp["type"] in CACHE_MUST_BE_OFF or knobs.get("no_cache"):
        cmd.append("--no-cache")
    flag_map = {
        "provider": "--provider", "strategy": "--strategy",
        "max_results_per_query": "--max-results-per-query",
        "num_queries": "--num-queries", "max_retries": "--max-retries",
        "prompt_variant": "--prompt-variant",
        "researcher_model": "--researcher-model",
        "verifier_model": "--verifier-model",
        "adjudicator_model": "--adjudicator-model",
        "researcher_escalation_model": "--researcher-escalation-model",
        "verifier_escalation_model": "--verifier-escalation-model",
    }
    for key, flag in flag_map.items():
        if key in knobs and knobs[key] is not None:
            cmd += [flag, str(knobs[key])]
    if knobs.get("chained"):
        cmd.append("--chained")
    return cmd


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def run(spec: Dict[str, Any], dry_run: bool) -> int:
    run_dir = RUNS_DIR / spec["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "events.jsonl"
    started = _now()

    def log(event: str, **fields: Any) -> None:
        rec = {"ts": _now(), "event": event, **fields}
        with log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{event}] " + " ".join(f"{k}={v}" for k, v in fields.items()))

    # Flatten to an ordered arm queue with expanded pairs.
    queue = []
    for exp in spec["experiments"]:
        pairs = expand_pairs(exp)
        for arm in exp["arms"]:
            queue.append((exp, arm, pairs))

    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": spec["run_id"], "started": started,
        "global_parallel": spec["global_parallel"],
        "budget_calls": spec["budget_calls"],
        "arms": [
            {"experiment_id": e["experiment_id"],
             "condition_label": a["condition_label"], "n_pairs": len(p)}
            for e, a, p in queue
        ],
    }, indent=2))

    total_pairs = sum(len(p) for _, _, p in queue)
    log("run_start", run_id=spec["run_id"], arms=len(queue),
        total_pairs=total_pairs, budget_calls=spec["budget_calls"],
        global_parallel=spec["global_parallel"])

    if dry_run:
        for exp, arm, pairs in queue:
            cmd = build_command(exp, arm, pairs, spec["global_parallel"])
            log("dry_run_arm", experiment_id=exp["experiment_id"],
                condition_label=arm["condition_label"], n_pairs=len(pairs),
                no_cache="--no-cache" in cmd, command=" ".join(cmd[:12]) + " ...")
        log("dry_run_done")
        return 0

    for exp, arm, pairs in queue:
        eid, label = exp["experiment_id"], arm["condition_label"]
        spent = calls_since(started)
        projected = spent + len(pairs) * CALLS_PER_PAIR_WORST
        if spec["budget_calls"] is not None and projected > spec["budget_calls"]:
            log("PAUSE_budget", reason="next arm would breach the call budget",
                spent=spent, projected=projected, budget=spec["budget_calls"],
                next_arm=f"{eid}/{label}")
            print("\nPAUSED on budget. Raise budget_calls or trim the queue, "
                  "then re-run the same spec (completed arms are skipped).")
            return 2

        log("arm_start", experiment_id=eid, condition_label=label,
            n_pairs=len(pairs), calls_spent=spent)
        cmd = build_command(exp, arm, pairs, spec["global_parallel"])
        result = subprocess.run(cmd, cwd=str(REPO))
        if result.returncode != 0:
            log("PAUSE_dispatch_error", experiment_id=eid, condition_label=label,
                returncode=result.returncode)
            print("\nPAUSED: dispatch returned non-zero. Inspect the arm before "
                  "continuing; re-run the spec to resume.")
            return 3

        health = arm_health(eid, label, len(pairs))
        log("arm_done", experiment_id=eid, condition_label=label, **health)
        if not health["healthy"]:
            log("PAUSE_health", experiment_id=eid, condition_label=label,
                reason="arm came back unhealthy; stop and diagnose",
                blocker_rate=health["blocker_rate"],
                finalise_rate=health["finalise_rate"])
            print(
                "\nPAUSED on health. Likely causes to check before resuming:\n"
                "  - high blocker_rate -> search-side overload; lower "
                "global_parallel and resume\n"
                "  - low finalise_rate -> thin web / deny-list / self-report "
                "ceiling, or a real bug; read events.jsonl and the failure_modes\n"
                "Re-run the same spec to resume from here."
            )
            return 4

    log("run_done", calls_spent=calls_since(started))
    print(f"\nRun complete. Log: {log_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ODMI experiment orchestrator")
    ap.add_argument("spec", type=Path, help="path to the experiment spec JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="preflight and print the planned commands, dispatch nothing")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    errors = preflight(spec)
    if errors:
        print("PREFLIGHT FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("Preflight passed.")
    return run(spec, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
