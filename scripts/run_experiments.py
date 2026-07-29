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

# Worst-case Claude calls per pair. Used for the budget guard and the
# per-dispatch --max-calls cap so an arm cannot silently overrun.
#
# Corrected 2026-07-13 from 17 -> 45. The old 17 counted only the four core
# agent calls (Researcher/Verifier query-gen + main) x the retry ceiling and
# silently omitted the snippet picker, which fires once per fetched page and is
# ~80% of real call volume under the current production config (picker on,
# verifier_search=always, num_queries=3). Measured on the d50_neg_licence_confirm
# run: ~43 calls/pair (5,836 logged calls / 135 finalised pairs). The 17 figure
# capped dispatches at ~40% of the work they were sized for. See the picker
# subtrio_id logging fix (same date) which first made the true count visible.
CALLS_PER_PAIR_WORST = 45

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

    # D47 second touch (EXP-42). The frozen set had one door, `headline: true`,
    # which EXP-36 has already used and which a later run must not claim: the
    # headline is the receipt for the reported result, so a second flag would
    # corrupt it. A characterisation re-measurement therefore needs its own
    # door, and it is a door rather than a removed check: the flag alone is not
    # enough, a justification is logged with it so the second touch is visible
    # in the run record and in the dissertation's limitations.
    second_touch = spec.get("heldout_second_touch") is True
    justification = (spec.get("heldout_second_touch_justification") or "").strip()
    if second_touch and not justification:
        errors.append(
            "heldout_second_touch is set without "
            "'heldout_second_touch_justification'; a second touch of the D47 "
            "frozen set is only admissible with a logged reason naming the "
            "sign-off, so it can be disclosed"
        )
    if second_touch and spec.get("headline") is True:
        errors.append(
            "heldout_second_touch and headline are both set; EXP-36 is the "
            "headline and a second claim on it corrupts the receipts. A "
            "second touch is characterisation, never the headline"
        )
    second_touch_ok = second_touch and bool(justification) and spec.get("headline") is not True

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

        # D47 hold-out: no eval country may appear in a development run. Two
        # sanctioned exceptions, both requiring that EVERY country in the
        # experiment is held-out: the frozen headline run (EXP-21, later
        # EXP-36) via `headline: true`, and a disclosed second touch via
        # `heldout_second_touch` plus its justification (EXP-42). A development
        # run can never lift the guard by accident, since any dev country in
        # the mix breaks the subset condition and shuts both doors.
        countries_in_exp = {p.split(":", 1)[1] for p in pairs}
        all_held_out = countries_in_exp <= HELD_OUT
        headline_ok = spec.get("headline") is True and all_held_out
        second_touch_arm_ok = second_touch_ok and all_held_out
        bad = sorted(countries_in_exp & HELD_OUT)
        if bad and not (headline_ok or second_touch_arm_ok):
            errors.append(
                f"{eid}: held-out D47 eval countries present {bad}; these are "
                f"frozen until the headline run and must never appear here"
            )
        unknown = sorted(countries_in_exp - DEV - HELD_OUT)
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

        # Banned-model check: no arm may pin a cut model (Sonnet 5, D59). This
        # is defence in depth over the llm.py call-time guard, so a stale spec
        # fails at dry-run rather than mid-dispatch. Every model-valued knob is
        # scanned across baseline and per-arm overrides.
        model_knobs = (
            "researcher_model", "verifier_model", "adjudicator_model",
            "picker_model", "query_gen_model",
            "researcher_escalation_model", "verifier_escalation_model",
        )
        for a in arms:
            knobs = {**exp.get("baseline_knobs", {}), **a.get("knobs", {})}
            for k in model_knobs:
                v = knobs.get(k)
                if v and str(v).lower().startswith("claude-sonnet-5"):
                    errors.append(
                        f"{eid}/{a.get('condition_label')}: knob {k}={v!r} pins a "
                        f"cut model (Sonnet 5, D59); production is "
                        f"claude-sonnet-4-6"
                    )

    # Held-out cache guard for the headline run. A headline dispatch reads the
    # eight held-out countries once; if the dispatch DB still carries held-out
    # cache and no_cache were ever off, the run would read voided evidence. This
    # fails the preflight (at dry-run) rather than trusting the operator to have
    # purged, turning the runbook's manual purge step into an enforced gate. Only
    # runs for a headline spec, since it scans the cache tables.
    if spec.get("headline") is True:
        try:
            import sqlite3
            from scripts.purge_heldout_cache import scan as _scan_heldout
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            try:
                n = {k: len(v) for k, v in _scan_heldout(conn).items()}
            finally:
                conn.close()
            if any(n.values()):
                errors.append(
                    f"headline run: dispatch DB still carries held-out cache "
                    f"(fetch={n['fetch']} serp={n['serp']} snippet={n['snippet']}); "
                    f"run `scripts/purge_heldout_cache.py --db {DB_PATH} --apply` "
                    f"and re-check before dispatch"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"headline run: could not verify the dispatch DB is purged of "
                f"held-out cache ({exc}); resolve before dispatch"
            )

    return errors


# --------------------------------------------------------------------------- #
# Pre-registration (R1) and idempotent resume
# --------------------------------------------------------------------------- #

def unregistered_in_spec(spec: Dict[str, Any], registered: set) -> List[str]:
    """Return an error per experiment_id absent from the `experiments` table.

    R1 (EXPERIMENTS_PROTOCOL.md) requires every experiment to be pre-registered
    with its endpoints and adoption rule before it runs, so the analysis plan
    is fixed blind. The orchestrator enforces this by construction: an
    unregistered id is a hard preflight error, not a thing to remember.
    """
    errors: List[str] = []
    for exp in spec["experiments"]:
        eid = exp.get("experiment_id")
        if eid and eid not in registered:
            errors.append(
                f"{eid}: not pre-registered; add a row to the `experiments` "
                f"table (id, name, description with endpoints and the adoption "
                f"rule, conditions) before running (R1)"
            )
    return errors


def remaining_pairs(pairs: List[str], finalised: set) -> List[str]:
    """Drop already-finalised pairs, preserving order.

    Re-running a spec is the sanctioned resume path. Skipping pairs that
    already wrote a `phase2_final` row for this arm makes a resume idempotent:
    no duplicate finalisations, no re-spend on completed work. The canonical
    row for analysis is then simply the one finalisation per (question,
    country, condition); duplicates from older interrupted runs are superseded
    by the latest.
    """
    return [p for p in pairs if p not in finalised]


# --------------------------------------------------------------------------- #
# DB health and budget
# --------------------------------------------------------------------------- #

def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def registered_experiment_ids() -> set:
    """The set of experiment_ids pre-registered in the `experiments` table."""
    try:
        with _conn() as c:
            return {
                r[0] for r in c.execute(
                    "SELECT experiment_id FROM experiments"
                ).fetchall()
            }
    except sqlite3.Error:
        return set()


def finalised_pairs(experiment_id: str, condition_label: str) -> set:
    """The 'QID:CC' pairs already finalised for one arm (resume skip set).

    Scoped by experiment_id and condition_label (the latter via the Researcher
    rows, since phase2_final carries no condition_label) so one arm never
    treats another arm's finalisations as its own.
    """
    with _conn() as c:
        return {
            f"{r[0]}:{r[1]}" for r in c.execute(
                "SELECT DISTINCT f.question_id, f.country_code FROM phase2_final f "
                "JOIN phase2_researcher_runs r ON r.pair_run_id = f.pair_run_id "
                "WHERE f.experiment_id IS ? AND r.condition_label IS ?",
                (experiment_id, condition_label),
            ).fetchall()
        }

def calls_since(ts: str) -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM claude_usage_log WHERE timestamp >= ?", (ts,)
        ).fetchone()[0]


def arm_health(experiment_id: str, condition_label: str, expected: int) -> Dict[str, Any]:
    with _conn() as c:
        # Per-arm finalised count: join to the Researcher rows that carry this
        # arm's condition_label (phase2_final has no condition_label). Counting
        # experiment-wide would let a finished arm mask a later failed one.
        finalised = c.execute(
            "SELECT COUNT(DISTINCT f.pair_run_id) FROM phase2_final f "
            "JOIN phase2_researcher_runs r ON r.pair_run_id = f.pair_run_id "
            "WHERE f.experiment_id IS ? AND r.condition_label IS ?",
            (experiment_id, condition_label),
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
        "verifier_prompt_variant": "--verifier-prompt-variant",
        "researcher_model": "--researcher-model",
        "verifier_model": "--verifier-model",
        "adjudicator_model": "--adjudicator-model",
        "researcher_escalation_model": "--researcher-escalation-model",
        "verifier_escalation_model": "--verifier-escalation-model",
        "verifier_search": "--verifier-search",
        "query_language": "--query-language",
        "search_strategy": "--search-strategy",
        "picker_model": "--picker-model",
        "adjudicator_selection": "--adjudicator-selection",
        "pipeline_mode": "--pipeline-mode",
        "seed_experiment_id": "--seed-experiment-id",
        "seed_condition_label": "--seed-condition-label",
        "snippet_picker": "--snippet-picker",
        "max_snippet_chars": "--max-snippet-chars",
        "picker_max_chunks": "--picker-max-chunks",
        "page_text_cap": "--page-text-cap",
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

    manifest = {
        "run_id": spec["run_id"], "started": started,
        "global_parallel": spec["global_parallel"],
        "budget_calls": spec["budget_calls"],
        "arms": [
            {"experiment_id": e["experiment_id"],
             "condition_label": a["condition_label"], "n_pairs": len(p)}
            for e, a, p in queue
        ],
    }
    # A second touch of the D47 frozen set is recorded in the run's own
    # receipts, not just in the spec, so the disclosure survives alongside the
    # rows it produced. Preflight has already refused a flag with no reason.
    if spec.get("heldout_second_touch") is True:
        manifest["heldout_second_touch"] = True
        manifest["heldout_second_touch_justification"] = (
            spec.get("heldout_second_touch_justification")
        )
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    total_pairs = sum(len(p) for _, _, p in queue)
    log("run_start", run_id=spec["run_id"], arms=len(queue),
        total_pairs=total_pairs, budget_calls=spec["budget_calls"],
        global_parallel=spec["global_parallel"])
    if spec.get("heldout_second_touch") is True:
        log("heldout_second_touch",
            justification=spec.get("heldout_second_touch_justification"))

    if dry_run:
        for exp, arm, pairs in queue:
            eid, label = exp["experiment_id"], arm["condition_label"]
            done = finalised_pairs(eid, label)
            todo = remaining_pairs(pairs, done)
            cmd = build_command(exp, arm, todo or pairs, spec["global_parallel"])
            log("dry_run_arm", experiment_id=eid, condition_label=label,
                n_pairs=len(pairs), already_finalised=len(pairs) - len(todo),
                remaining=len(todo), no_cache="--no-cache" in cmd,
                command=" ".join(cmd[:12]) + " ...")
        log("dry_run_done")
        return 0

    for exp, arm, pairs in queue:
        eid, label = exp["experiment_id"], arm["condition_label"]
        # Idempotent resume: skip pairs this arm has already finalised, so a
        # re-run neither re-spends on completed work nor writes duplicate rows.
        done = finalised_pairs(eid, label)
        todo = remaining_pairs(pairs, done)
        if not todo:
            log("arm_skipped", experiment_id=eid, condition_label=label,
                reason="all pairs already finalised", n_pairs=len(pairs))
            continue
        if done:
            log("arm_resume", experiment_id=eid, condition_label=label,
                already_finalised=len(done), remaining=len(todo))
        spent = calls_since(started)
        projected = spent + len(todo) * CALLS_PER_PAIR_WORST
        if spec["budget_calls"] is not None and projected > spec["budget_calls"]:
            log("PAUSE_budget", reason="next arm would breach the call budget",
                spent=spent, projected=projected, budget=spec["budget_calls"],
                next_arm=f"{eid}/{label}")
            print("\nPAUSED on budget. Raise budget_calls or trim the queue, "
                  "then re-run the same spec (completed arms are skipped).")
            return 2

        log("arm_start", experiment_id=eid, condition_label=label,
            n_pairs=len(todo), calls_spent=spent)
        cmd = build_command(exp, arm, todo, spec["global_parallel"])
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
    errors = preflight(spec) + unregistered_in_spec(spec, registered_experiment_ids())
    if errors:
        print("PREFLIGHT FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("Preflight passed.")
    return run(spec, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
