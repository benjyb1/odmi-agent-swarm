"""Validate the Albania catalogue route against ODMI ground truth.

Albania's national portal (opendata.gov.al) is an Angular SPA, invisible to
the static retrieval stack, so the swarm abstained on every AL Quality
question (see docs/LANGUAGE_FRAMEWORK_DEEPDIVE.md section F). This harvests
the portal's DCAT JSON API through the `al_dcat_api` adapter and runs the
nine deterministic catalogue metrics, comparing each computed band to the
ODMI expert answer. No LLM call, no swarm run.

Run: uv run python evaluation/validate_catalogue_al.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agents.tools import answer_shapes
from agents.tools.catalogue import metrics, synthesise
from agents.tools.catalogue.adapters import al_dcat_api
from agents.tools.catalogue.registry import load_portal

DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"
QUESTIONS = ["Q12", "Q13", "Q21", "Q22", "Q25", "Q27", "Q16", "Q17", "Q18"]


def main() -> None:
    cfg = load_portal("AL")
    datasets = list(al_dcat_api.harvest(cfg))
    synthesise.attach_graphs(datasets)  # JSON route: synthesise RDF for SHACL
    n_dist = sum(len(d.distributions) for d in datasets)
    print(f"AL harvest: {len(datasets)} datasets, {n_dist} distributions\n")

    con = sqlite3.connect(str(DB))
    gt = dict(
        con.execute(
            "SELECT question_id, response FROM ground_truth WHERE country_code='AL'"
        ).fetchall()
    )

    print(f"{'Q':<5}{'computed':<12}{'ODMI GT':<12}{'match':<7}breakdown")
    print("-" * 96)
    matches = 0
    for q in QUESTIONS:
        fn = metrics.PRESENCE_METRICS.get(q) or metrics.CONFORMANCE_METRICS.get(q)
        try:
            res = fn(datasets, answer_shapes.load_question_shape(q))
            band, breakdown = res.band_label, res.breakdown
        except Exception as exc:  # noqa: BLE001
            band, breakdown = f"ERR:{type(exc).__name__}", str(exc)[:60]
        g = gt.get(q, "(no GT)")
        hit = bool(band and g and str(band).strip().lower() == str(g).strip().lower())
        matches += hit
        print(f"{q:<5}{str(band):<12}{str(g):<12}{'=' if hit else '':<7}{breakdown[:64]}")
    print(f"\nexact band matches vs ODMI: {matches}/{len(QUESTIONS)}")


if __name__ == "__main__":
    main()
