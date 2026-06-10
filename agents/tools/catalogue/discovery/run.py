"""Discovery orchestration and CLI.

`discover_country(seed)` probes the seed's primary base, then each
alternate, and returns the best outcome (verified beats needs_new_adapter
beats failed). The CLI drives one country or the whole seed list, writes
a JSON report, and optionally emits registries for verified outcomes.

A full catalogue harvest never happens here: verification samples one
page per candidate route, so a 36-country run stays in the hundreds of
requests, throttled.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from agents.tools.catalogue.discovery import probes as _probes
from agents.tools.catalogue.discovery.emit import emit_registry
from agents.tools.catalogue.discovery.seeds import Seed, load_seeds
from agents.tools.catalogue.discovery.verify import (
    DiscoveryOutcome,
    choose_and_verify,
    live_sampler,
)
from agents.tools.catalogue.registry import available_countries

_STATUS_RANK = {"verified": 2, "needs_new_adapter": 1, "failed": 0}

Prober = Callable[[str, Optional[dict]], list]
Verifier = Callable[[str, str, str, list], DiscoveryOutcome]


def _default_prober(base: str, hints: Optional[dict]) -> list:
    return _probes.probe_all(base, hints=hints)


def _default_verifier(
    cc: str, name: str, base: str, evidence: list
) -> DiscoveryOutcome:
    return choose_and_verify(
        cc, name, base, evidence, sampler=live_sampler(max_pages=1)
    )


def discover_country(
    seed: Seed,
    *,
    prober: Prober = _default_prober,
    verifier: Verifier = _default_verifier,
) -> DiscoveryOutcome:
    """Probe and verify one country, trying alternates after the primary.

    The first verified base wins. Probe and verification errors on one
    base are recorded and the next base is tried; only when every base
    fails is the country failed.
    """
    best: Optional[DiscoveryOutcome] = None
    for base in (seed.portal_base, *seed.alternates):
        try:
            evidence = prober(base, seed.hints or None)
            outcome = verifier(
                seed.country_code, seed.country_name, base, evidence
            )
        except Exception as exc:  # noqa: BLE001 - a dead base is an outcome
            outcome = DiscoveryOutcome(
                seed.country_code, seed.country_name, base, "failed",
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
        if outcome.status == "verified":
            return outcome
        if best is None or _STATUS_RANK[outcome.status] > _STATUS_RANK[best.status]:
            best = outcome
    assert best is not None
    return best


def _outcome_dict(o: DiscoveryOutcome) -> dict:
    d = dataclasses.asdict(o)
    if o.chosen is not None:
        # The probe evidence's config_fields already appear in the registry;
        # keep the report compact and JSON-clean.
        d["chosen"]["evidence"] = {
            "stack": o.chosen.evidence.stack,
            "endpoint": o.chosen.evidence.endpoint,
            "detail": o.chosen.evidence.detail,
        }
    return d


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Discover national portal routes for the catalogue tool (D30)."
    )
    parser.add_argument("country_codes", nargs="*",
                        help="Country codes to discover (e.g. AT IE SI). Empty with --all runs every seed.")
    parser.add_argument("--all", action="store_true",
                        help="Run every country in the seed file.")
    parser.add_argument("--emit", action="store_true",
                        help="Write data/catalogue/portals/<CC>.json for verified outcomes.")
    parser.add_argument("--force", action="store_true",
                        help="Allow --emit to overwrite an existing registry file.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip countries that already have a registry file.")
    parser.add_argument("--report", type=Path, default=None,
                        help="Write a JSON report of all outcomes to this path.")
    parser.add_argument("--delay-s", type=float, default=2.0,
                        help="Pause between countries (politeness).")
    args = parser.parse_args()

    seeds = load_seeds()
    if args.all:
        selected = seeds
    else:
        wanted = {c.upper() for c in args.country_codes}
        selected = [s for s in seeds if s.country_code in wanted]
        missing = wanted - {s.country_code for s in selected}
        if missing:
            print(f"No seed for: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    if args.skip_existing:
        have = set(available_countries())
        selected = [s for s in selected if s.country_code not in have]
    if not selected:
        print("Nothing to do.", file=sys.stderr)
        return 2

    outcomes: list[DiscoveryOutcome] = []
    for i, seed in enumerate(selected):
        print(f"[{i + 1}/{len(selected)}] {seed.country_code} {seed.portal_base} ...",
              flush=True)
        outcome = discover_country(seed)
        outcomes.append(outcome)
        line = f"  -> {outcome.status}"
        if outcome.chosen:
            line += (f" route={outcome.chosen.route}"
                     f" licence_share={outcome.chosen.stats.licence_share:.0%}"
                     f" caveats={outcome.chosen.caveats}")
        if outcome.new_stacks:
            line += f" new_stacks={outcome.new_stacks}"
        if outcome.error:
            line += f" error={outcome.error}"
        print(line, flush=True)

        if args.emit and outcome.status == "verified":
            try:
                path = emit_registry(outcome, force=args.force)
                print(f"  emitted {path}", flush=True)
            except FileExistsError:
                print(f"  registry exists for {outcome.country_code}; "
                      "not overwriting without --force", flush=True)
        if args.delay_s and i < len(selected) - 1:
            time.sleep(args.delay_s)

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    print(f"\nSummary: {counts}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(
            [_outcome_dict(o) for o in outcomes], indent=2, ensure_ascii=False
        ) + "\n")
        print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
