"""Public entry point for the catalogue-metrics tool (D30).

`compute(question_id, country_code)` returns a `CatalogueComputation` for a
catalogue-derivable band/count question, or None when the question is not
catalogue-computable (so the caller falls back to web search). It harvests
(or replays the cache), runs the metric, and writes a `catalogue_metrics`
receipt row.

The tool never reads `ground_truth` and ODMI's answer never feeds the
computation. The band is assigned from the question's own allowed answers.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from agents.tools import answer_shapes
from agents.tools.catalogue import metrics, synthesise
from agents.tools.catalogue.harvest import Snapshot, get_snapshot
from agents.tools.catalogue.metrics import MetricResult
from agents.tools.catalogue.registry import PortalConfig, available_countries, load_portal
from agents.tools.db import connect

# A tag stamped on the Researcher output's `notes` so the Verifier knows
# to recompute deterministically rather than search the web.
CATALOGUE_NOTE_TAG = "catalogue_computed"

# The nine questions the tool computes in v1 (see docs/CATALOGUE_METRICS.md).
COMPUTABLE_QUESTIONS = frozenset(
    {"Q12", "Q13", "Q16", "Q17", "Q18", "Q21", "Q22", "Q25", "Q27"}
)
_CONFORMANCE = frozenset({"Q16", "Q17", "Q18"})


@dataclass
class CatalogueComputation:
    question_id: str
    country_code: str
    result: MetricResult
    source_url: str
    snapshot_id: str
    partial: bool

    @property
    def band(self) -> str:
        return self.result.band_label

    @property
    def evidence_quote(self) -> str:
        return self.result.breakdown


def is_computable(question_id: str, country_code: str) -> bool:
    """True if this (question, country) can be computed from the catalogue."""
    if question_id not in COMPUTABLE_QUESTIONS:
        return False
    return country_code.upper() in available_countries()


def _resolve_source_url(config: PortalConfig) -> str:
    base = config.dcat_catalog_url or config.native_api_url or config.portal_base
    try:
        return base.format(page=1, page_size=config.page_size, start=0)
    except Exception:  # noqa: BLE001 - template without placeholders
        return base


def _metric_for(question_id: str):
    if question_id in metrics.PRESENCE_METRICS:
        return metrics.PRESENCE_METRICS[question_id]
    if question_id in metrics.CONFORMANCE_METRICS:
        return metrics.CONFORMANCE_METRICS[question_id]
    return None


def compute(
    question_id: str,
    country_code: str,
    *,
    refresh: bool = False,
    write_receipt: bool = True,
    snapshot: Optional[Snapshot] = None,
) -> Optional[CatalogueComputation]:
    """Compute one metric for a (question, country). None if not computable
    or if the harvest yielded nothing usable."""
    cc = country_code.upper()
    if not is_computable(question_id, cc):
        return None

    metric_fn = _metric_for(question_id)
    if metric_fn is None:
        return None

    config = load_portal(cc)
    shape = answer_shapes.load_question_shape(question_id)

    try:
        if snapshot is None:
            snapshot = get_snapshot(cc, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - harvest failure -> fall back
        print(f"[catalogue] harvest failed for {cc}: {exc}", file=sys.stderr)
        return None

    if not snapshot.datasets:
        return None

    datasets = snapshot.datasets
    if question_id in _CONFORMANCE:
        # JSON routes carry no graph; synthesise one. RDF datasets keep theirs.
        synthesise.attach_graphs(datasets)

    try:
        result = metric_fn(datasets, shape)
    except ValueError as exc:
        # e.g. conformance asked but no graphs could be built.
        print(f"[catalogue] {question_id}/{cc} not computable: {exc}", file=sys.stderr)
        return None

    comp = CatalogueComputation(
        question_id=question_id,
        country_code=cc,
        result=result,
        source_url=_resolve_source_url(config),
        snapshot_id=snapshot.snapshot_id,
        partial=snapshot.partial,
    )

    if write_receipt:
        _write_receipt(comp)

    return comp


def _write_receipt(comp: CatalogueComputation) -> None:
    r = comp.result
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO catalogue_metrics (
                    snapshot_id, question_id, country_code, metric_function,
                    raw_value, numerator, denominator, band_label, breakdown,
                    computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comp.snapshot_id, comp.question_id, comp.country_code,
                    r.metric_function, r.raw_value, r.numerator, r.denominator,
                    r.band_label, r.breakdown,
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort receipt
        print(f"[catalogue] receipt write failed: {exc}", file=sys.stderr)
