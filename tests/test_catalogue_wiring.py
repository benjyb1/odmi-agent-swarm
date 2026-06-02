"""Researcher/Verifier wiring for catalogue-computed answers (D30).

Monkeypatches the catalogue compute so no network or LLM call happens; if
the short-circuit failed, the Researcher would try to call the LLM and the
test would error, which is itself the assertion.
"""

from __future__ import annotations

import pytest

from agents.models import ResearcherInput, ResearcherOutput, VerifierInput
from agents.researcher import run_researcher
from agents.tools.catalogue import compute as catalogue_compute
from agents.tools.catalogue.compute import CATALOGUE_NOTE_TAG, CatalogueComputation
from agents.tools.catalogue.metrics import MetricResult
from agents.verifier import run_verifier


def _fake_comp(band: str) -> CatalogueComputation:
    result = MetricResult(
        question_id="Q12",
        metric_function="metric_q12_licence_presence",
        raw_value=94.2,
        numerator=4812,
        denominator=5109,
        band_label=band,
        breakdown="4,812 of 5,109 datasets carry licensing information = 94.2% -> " + band,
    )
    return CatalogueComputation(
        question_id="Q12",
        country_code="FR",
        result=result,
        source_url="https://www.data.gouv.fr/api/1/site/catalog.ttl?page=1&page_size=100",
        snapshot_id="FR-test",
        partial=False,
    )


def _researcher_input() -> ResearcherInput:
    return ResearcherInput(
        question_id="Q12",
        question_text="What percentage of the open data carries licensing information?",
        dimension="Quality",
        indicator="quality_monitoring",
        response_scoring="{'>90%': 20}",
        country_code="FR",
        country_name="France",
        country_language="fr",
        answer_shape="percentage_band",
        allowed_answers=[">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )


def test_researcher_routes_to_catalogue(monkeypatch):
    monkeypatch.setattr(catalogue_compute, "is_computable", lambda q, c: True)
    monkeypatch.setattr(catalogue_compute, "compute", lambda q, c: _fake_comp(">90%"))

    result = run_researcher(_researcher_input())
    assert result.failure_mode is None
    assert result.output is not None
    assert result.output.answer == ">90%"
    assert CATALOGUE_NOTE_TAG in (result.output.notes or "")
    assert "data.gouv.fr" in str(result.output.source_url)
    # No LLM usage recorded: the web path was never entered.
    assert result.main_usage is None
    assert result.query_gen_usage is None


def _verifier_input(researcher_answer: str) -> VerifierInput:
    ro = ResearcherOutput(
        answer=researcher_answer,
        answer_explanation="Computed from the catalogue.",
        evidence_quote="4,812 of 5,109 datasets carry a licence = 94.2% -> " + researcher_answer,
        source_url="https://www.data.gouv.fr/api/1/site/catalog.ttl?page=1&page_size=100",
        retrieval_confidence=1.0,
        answer_confidence=0.95,
        notes=CATALOGUE_NOTE_TAG,
    )
    return VerifierInput(
        question_id="Q12",
        question_text="What percentage carries licensing information?",
        country_code="FR",
        country_name="France",
        researcher_output=ro,
        answer_shape="percentage_band",
        allowed_answers=[">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )


def test_verifier_recompute_pass_on_match(monkeypatch):
    monkeypatch.setattr(catalogue_compute, "is_computable", lambda q, c: True)
    monkeypatch.setattr(catalogue_compute, "compute",
                        lambda q, c, write_receipt=True: _fake_comp(">90%"))

    result = run_verifier(_verifier_input(">90%"))
    assert result.output is not None
    assert result.output.verdict == "pass"
    assert result.main_usage is None  # no LLM call


def test_verifier_recompute_fail_on_mismatch(monkeypatch):
    monkeypatch.setattr(catalogue_compute, "is_computable", lambda q, c: True)
    monkeypatch.setattr(catalogue_compute, "compute",
                        lambda q, c, write_receipt=True: _fake_comp("71-90%"))

    result = run_verifier(_verifier_input(">90%"))
    assert result.output is not None
    assert result.output.verdict == "fail"
    assert result.output.verifier_answer == "71-90%"
    assert result.output.rejection_reason is not None
