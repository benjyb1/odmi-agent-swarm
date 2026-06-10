"""Open-web accuracy ceiling lift from portal discovery.

Companion to `evaluation/answerable_share.py` (the per-country
answerable-share analysis): same classification rules, but parameterised
by the registry set so the before/after of the discovery experiment is
one table. A `catalogue` question (D30-computable) is answerable for a
country only when a portal registry exists for it; discovery grows that
set, which raises the ceiling for every country it lands a route on.

`n/a` golds are excluded from the scoreable denominator. HTML entities in
the gold responses (the xlsx mirrors `&gt;90%` style strings) do not
matter here because only the n/a sentinel is matched.

Run after a discovery run:
    uv run python -m evaluation.discovery_ceiling \
        --report evaluation/results/discovery_report.json
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ANSWERABILITY = _REPO_ROOT / "data" / "questions" / "answerability.json"
_PORTALS_DIR = _REPO_ROOT / "data" / "catalogue" / "portals"
_DB_PATH = _REPO_ROOT / "data" / "odmi.db"

# The six registries that existed before discovery (hand-authored, D30).
HAND_AUTHORED = frozenset({"DE", "EE", "FR", "HU", "NL", "RO"})

_NA_GOLDS = {"not applicable", "n/a", "na"}


@dataclass
class CountryCeiling:
    country_code: str
    scoreable: int = 0
    answerable: int = 0
    catalogue_answerable: int = 0
    catalogue_blocked: int = 0

    @property
    def ceiling(self) -> float | None:
        if self.scoreable == 0:
            return None
        return self.answerable / self.scoreable


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("_", " ")


def ceiling(
    gt_rows: list[tuple[str, str, str]],
    question_class: dict[str, str],
    registries: set[str],
) -> dict[str, CountryCeiling]:
    """Pure core. `gt_rows` are (country_code, question_id, gold response)."""
    acc: dict[str, CountryCeiling] = {}
    for cc, qid, response in gt_rows:
        s = acc.setdefault(cc, CountryCeiling(cc))
        if _norm(response) in _NA_GOLDS or not _norm(response):
            continue
        s.scoreable += 1
        klass = question_class.get(qid, "web")
        if klass == "web":
            s.answerable += 1
        elif klass == "catalogue":
            if cc in registries:
                s.answerable += 1
                s.catalogue_answerable += 1
            else:
                s.catalogue_blocked += 1
    return acc


def lift_table(
    gt_rows: list[tuple[str, str, str]],
    question_class: dict[str, str],
    before: set[str],
    after: set[str],
) -> list[dict]:
    """Per-country ceiling before and after discovery, sorted by lift."""
    b = ceiling(gt_rows, question_class, before)
    a = ceiling(gt_rows, question_class, after)
    rows = []
    for cc in sorted(b):
        cb, ca = b[cc].ceiling, a[cc].ceiling
        rows.append({
            "country_code": cc,
            "scoreable": b[cc].scoreable,
            "ceiling_before": cb,
            "ceiling_after": ca,
            "lift": (ca - cb) if cb is not None and ca is not None else None,
            "registry_before": cc in before,
            "registry_after": cc in after,
        })
    rows.sort(key=lambda r: (-(r["lift"] or 0), r["country_code"]))
    return rows


def _load_gt_rows() -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT country_code, question_id, response FROM ground_truth"
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None,
                        help="discovery_report.json; verified countries there "
                             "are added to the after-set (else the portals dir is used).")
    args = parser.parse_args()

    question_class = {
        q["question_id"]: q["answerability"]
        for q in json.loads(_ANSWERABILITY.read_text())["questions"]
    }
    if args.report:
        outcomes = json.loads(args.report.read_text())
        discovered = {
            o["country_code"] for o in outcomes if o["status"] == "verified"
        }
    else:
        discovered = {p.stem.upper() for p in _PORTALS_DIR.glob("*.json")}
    before = set(HAND_AUTHORED)
    after = before | discovered

    rows = lift_table(_load_gt_rows(), question_class, before, after)
    print(f"{'CC':<4}{'scoreable':>10}{'before':>9}{'after':>8}{'lift':>8}  registry")
    for r in rows:
        cb = f"{r['ceiling_before']:.1%}" if r["ceiling_before"] is not None else "-"
        ca = f"{r['ceiling_after']:.1%}" if r["ceiling_after"] is not None else "-"
        lf = f"{r['lift']:+.1%}" if r["lift"] is not None else "-"
        reg = ("hand" if r["country_code"] in HAND_AUTHORED
               else "discovered" if r["registry_after"] else "none")
        print(f"{r['country_code']:<4}{r['scoreable']:>10}{cb:>9}{ca:>8}{lf:>8}  {reg}")

    lifted = [r for r in rows if (r["lift"] or 0) > 0]
    if lifted:
        avg = sum(r["lift"] for r in lifted) / len(lifted)
        print(f"\n{len(lifted)} countries lifted; mean lift among them {avg:+.1%}.")


if __name__ == "__main__":
    main()
