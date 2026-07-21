"""Unattended EXP-41 runner: staged dispatch with a hard gate between stages.

Runs the remaining replicates without supervision. Every stage is followed by
`audit_exp41_gate.py`, and a non-zero exit from that audit halts the whole
chain. Nothing proceeds past a failed check, which is the point: an overnight
run that keeps going after a gate fails is worse than one that stops, because
it spends the budget and produces data nobody can trust.

Stage sizes are cumulative and nested, so the orchestrator's idempotent resume
carries earlier stages forward: stage 2 skips the pairs stage 1 finalised and
runs only the remainder.

The search cache is archived and purged before every replicate. `--no-cache`
disables cache reads but not writes, so each run refills it and the purge has
to repeat, not run once.

    uv run python scripts/run_exp41_overnight.py --replicates rep2 rep3
    uv run python scripts/run_exp41_overnight.py --replicates rep2 --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "evaluation" / "specs"
RUNS = REPO / "evaluation" / "runs"
DB = REPO / "data" / "odmi.db"

# 5% / 40% / 100% of 156. The first two are gates; the last completes the arm.
STAGE_FRACTIONS = (0.05, 0.40, 1.00)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_pairs(pairs: list[str], frac: float, stratified: bool) -> list[str]:
    """Cumulative slice of the battery for one stage.

    `stratified` takes the slice proportionally from each country rather than
    off the front of the list. The battery is ordered MT 60, NL 52, AL 44, so a
    prefix slice of 5% is entirely Malta -- the hardest of the three and the
    one whose baseline failure rate is 11.7% against Netherlands' 0%. A gate
    that only ever sees Malta cannot tell a broken run from a normal one.

    The cost of stratifying is that pair ORDER differs from a prefix dispatch.
    That only matters if order affects outcomes; see the pre-registration.
    """
    n = round(len(pairs) * frac)
    if not stratified or frac >= 1.0:
        return pairs[:n]

    by_cc: dict[str, list[str]] = {}
    for p in pairs:  # insertion order preserved, so within-country order is kept
        by_cc.setdefault(p.split(":")[1], []).append(p)

    out: list[str] = []
    for cc, group in by_cc.items():
        take = max(1, round(len(group) * frac))
        out.extend(group[:take])
    # Keep the battery's own ordering rather than the grouping order.
    order = {p: i for i, p in enumerate(pairs)}
    return sorted(set(out), key=lambda p: order[p])


def write_stage_spec(base: dict, eid: str, pairs: list[str], stage: int) -> Path:
    spec = json.loads(json.dumps(base))  # deep copy
    spec["run_id"] = f"{eid}_stage{stage}"
    spec["experiments"][0]["pairs"] = pairs
    spec["description"] = (
        f"{spec.get('description','')} STAGE {stage}: {len(pairs)} of "
        f"{len(base['experiments'][0]['pairs'])} pairs. Cumulative and nested; "
        f"the orchestrator's resume skips pairs finalised by an earlier stage."
    )
    path = SPECS / f"_staged_{eid}_stage{stage}.json"
    path.write_text(json.dumps(spec, indent=2) + "\n")
    return path


def run(cmd: list[str], logfile: Path | None = None) -> int:
    log(f"$ {' '.join(cmd[:8])}{' ...' if len(cmd) > 8 else ''}")
    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a") as fh:
            return subprocess.run(cmd, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT).returncode
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def wait_for_quiet(timeout_s: int = 14400) -> bool:
    """Block until no dispatch is running. A replicate must not overlap another:
    concurrent dispatches contend for the same search capacity, which changes
    retrieval for both and breaks the one-thing-differs claim."""
    waited = 0
    while waited < timeout_s:
        r = subprocess.run(["pgrep", "-f", "dispatch_subtrios.py"], capture_output=True)
        if r.returncode != 0:
            return True
        if waited % 300 == 0:
            log("waiting for the running dispatch to finish...")
        time.sleep(30)
        waited += 30
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replicates", nargs="+", required=True,
                    help="Short names, e.g. rep2 rep3")
    # Prefix by default, and the reason matters. Cumulative prefix stages
    # process pairs 0-8, then 8-62, then 62-156: exactly the order an unstaged
    # dispatch uses, so a staged replicate and the unstaged replicate 1 see the
    # same pair sequence and differ only by the pauses. Stratified stages give a
    # better-balanced gate but permute the order, which would make staging
    # itself a difference between the arms. Gate quality is recovered instead by
    # comparing per country against both the exp34 baseline and replicate 1.
    ap.add_argument("--stratified", action="store_true", default=False,
                    help="Slice each stage proportionally per country. Permutes "
                         "pair order relative to an unstaged run; not the default.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for short in args.replicates:
        eid = f"exp41_stability_{short}"
        base_spec = SPECS / f"{eid}.json"
        if not base_spec.exists():
            log(f"FATAL: {base_spec} not found")
            return 2
        base = json.loads(base_spec.read_text())
        pairs = base["experiments"][0]["pairs"]

        log(f"===== {eid} =====")
        # A dry-run only validates specs and preflight, so it must not block on
        # a dispatch that is legitimately still running.
        if not args.dry_run and not wait_for_quiet():
            log("FATAL: a dispatch is still running after the timeout; stopping")
            return 1

        # Cache: archive as this replicate's retrieval receipt, then empty it.
        archive = RUNS / eid / "search_cache_pre.db"
        purge = [
            "uv", "run", "python", "scripts/purge_search_cache.py",
            "--db", str(DB), "--apply", "--archive", str(archive),
        ]
        if args.dry_run:
            log(f"DRY-RUN would purge: {' '.join(purge[4:])}")
        else:
            if archive.exists():
                log(f"archive {archive} already exists; keeping it, purging without re-archiving")
                purge = purge[:-2]
            if run(purge) != 0:
                log("FATAL: cache purge failed; refusing to dispatch with a warm cache")
                return 1

        for i, frac in enumerate(STAGE_FRACTIONS, start=1):
            sp = stage_pairs(pairs, frac, args.stratified)
            spec_path = write_stage_spec(base, eid, sp, i)
            log(f"stage {i}: {len(sp)} pairs ({frac:.0%}) -> {spec_path.name}")

            if args.dry_run:
                rc = run(["uv", "run", "python", "scripts/run_experiments.py",
                          str(spec_path), "--dry-run"])
                if rc != 0:
                    log(f"FATAL: dry-run preflight failed for stage {i}")
                    return 1
                continue

            rc = run(["uv", "run", "python", "scripts/run_experiments.py", str(spec_path)],
                     logfile=RUNS / eid / f"stage{i}.log")
            if rc != 0:
                log(f"FATAL: dispatch returned {rc} on stage {i}; stopping the chain")
                return 1

            log(f"stage {i} dispatched; running gate audit")
            rc = run(["uv", "run", "python", "scripts/audit_exp41_gate.py",
                      "--experiment-id", eid, "--expect", str(len(sp))])
            if rc != 0:
                log(f"GATE FAILED after stage {i} of {eid}. Chain halted. "
                    f"Nothing further will be dispatched.")
                return 1
            log(f"stage {i} gate PASSED")

        log(f"{eid} complete, all stages gated clean")

    log("all requested replicates complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
