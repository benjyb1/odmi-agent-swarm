"""Per-country structurally-unanswerable share and the implied accuracy ceiling.

An honest accuracy figure needs its ceiling stated beside it: some
(question, country) pairs cannot be answered from the open web at all, because
the gold answer is a questionnaire self-report or an MQA metric on the
deny-listed data.europa.eu. The catalogue route (D30) recovers the latter, but
only for countries that have a portal registry; without one, those pairs are
unanswerable for that country too.

This computes, per country, how the 143 questions split across `web`,
`catalogue` (D30-computable) and `self_report`, and the resulting open-web
accuracy ceiling = (web + catalogue-with-registry) / scoreable. `n/a` golds are
excluded from the scoreable denominator (ODMI itself judged them not
applicable). The per-question answerability class is country-invariant (from
`data/questions/answerability.json`); what varies per country is whether a
catalogue registry exists, so a `catalogue` question is answerable for FR/DE/...
but blocked for a country with no registry file yet (e.g. NO, MT).

Run: `uv run python -m evaluation.answerable_share`
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

_NA_GOLDS = {"not applicable", "n/a", "na"}


@dataclass
class CountryShare:
    country_code: str
    scoreable: int
    web: int
    catalogue_answerable: int
    catalogue_blocked: int
    self_report: int
    na: int

    @property
    def answerable(self) -> int:
        return self.web + self.catalogue_answerable

    @property
    def ceiling(self) -> float | None:
        if self.scoreable == 0:
            return None
        return self.answerable / self.scoreable


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("_", " ")


def country_answerable(
    gt_rows: list[tuple[str, str, str]],
    question_class: dict[str, str],
    catalogue_countries: set[str],
) -> dict[str, CountryShare]:
    """Pure core. `gt_rows` are (country_code, question_id, response).

    A `catalogue` question counts as answerable for a country only if that
    country has a portal registry; otherwise it is `catalogue_blocked`. `n/a`
    golds are not scoreable.
    """
    acc: dict[str, CountryShare] = {}
    for cc, qid, response in gt_rows:
        s = acc.get(cc)
        if s is None:
            s = CountryShare(cc, 0, 0, 0, 0, 0, 0)
            acc[cc] = s
        if _norm(response) in _NA_GOLDS or not _norm(response):
            s.na += 1
            continue
        s.scoreable += 1
        klass = question_class.get(qid, "web")
        if klass == "web":
            s.web += 1
        elif klass == "self_report":
            s.self_report += 1
        elif klass == "catalogue":
            if cc in catalogue_countries:
                s.catalogue_answerable += 1
            else:
                s.catalogue_blocked += 1
    return acc


def _load_question_class() -> dict[str, str]:
    data = json.loads(_ANSWERABILITY.read_text())
    return {q["question_id"]: q["answerability"] for q in data["questions"]}


def _load_catalogue_countries() -> set[str]:
    return {p.stem.upper() for p in _PORTALS_DIR.glob("*.json")}


def _load_gt_rows(db_path: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT country_code, question_id, response FROM ground_truth"
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def main() -> None:
    question_class = _load_question_class()
    catalogue_countries = _load_catalogue_countries()
    gt_rows = _load_gt_rows(_DB_PATH)
    shares = country_answerable(gt_rows, question_class, catalogue_countries)

    print(f"Catalogue registries present: {sorted(catalogue_countries)}")
    print(
        f"{'CC':<4}{'score':>6}{'web':>5}{'cat_ok':>7}{'cat_blk':>8}"
        f"{'self_rep':>9}{'n/a':>5}{'ceiling':>9}"
    )
    for cc in sorted(shares):
        s = shares[cc]
        ceil = f"{s.ceiling:.1%}" if s.ceiling is not None else "-"
        print(
            f"{cc:<4}{s.scoreable:>6}{s.web:>5}{s.catalogue_answerable:>7}"
            f"{s.catalogue_blocked:>8}{s.self_report:>9}{s.na:>5}{ceil:>9}"
        )


if __name__ == "__main__":
    main()
