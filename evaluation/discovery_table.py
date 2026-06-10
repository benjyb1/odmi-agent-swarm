"""Merge discovery chunk reports and print the per-country outcome table.

The 36-country discovery experiment runs in kill-resilient chunks, each
writing `evaluation/results/discovery_chunk_<n>.json`. This merges them
into `discovery_report.json` (one entry per country, last chunk wins on
duplicates) and prints the harvestability table: which national portals
the catalogue tool can scrape today, through which route, and why the
rest cannot be scraped.

Run: `uv run python -m evaluation.discovery_table`
"""

from __future__ import annotations

import json
from pathlib import Path

_RESULTS = Path(__file__).resolve().parent / "results"
_MERGED = _RESULTS / "discovery_report.json"


def merge_chunks() -> list[dict]:
    by_cc: dict[str, dict] = {}
    for path in sorted(_RESULTS.glob("discovery_chunk_*.json")):
        for entry in json.loads(path.read_text()):
            by_cc[entry["country_code"]] = entry
    merged = sorted(by_cc.values(), key=lambda e: e["country_code"])
    _MERGED.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return merged


def _why(entry: dict) -> str:
    if entry["status"] == "verified":
        c = entry["chosen"]
        cavs = ", ".join(c["caveats"]) if c["caveats"] else "none"
        return f"caveats: {cavs}"
    if entry["status"] == "needs_new_adapter":
        return "stack recognised, no adapter: " + ", ".join(entry["new_stacks"])
    reasons = [r["reason"] for r in entry.get("rejected", [])]
    if reasons:
        return "; ".join(reasons)[:120]
    return entry.get("error") or "no stack fingerprint matched"


def print_table(merged: list[dict]) -> None:
    print(f"{'CC':<4}{'portal':<36}{'outcome':<19}{'route':<13}detail")
    for e in merged:
        route = e["chosen"]["route"] if e.get("chosen") else "-"
        host = e["portal_base"].removeprefix("https://")
        print(f"{e['country_code']:<4}{host:<36}{e['status']:<19}{route:<13}{_why(e)}")
    counts: dict[str, int] = {}
    for e in merged:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    print(f"\n{len(merged)} countries: {counts}")


if __name__ == "__main__":
    print_table(merge_chunks())
