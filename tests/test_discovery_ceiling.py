"""Ceiling-lift analysis for the discovery experiment.

Pure-core tests: given ground-truth rows, the per-question answerability
class and two registry sets (before and after discovery), the analysis
reports each country's open-web accuracy ceiling and the lift discovery
buys. Mirrors evaluation/answerable_share.py's classification rules:
`n/a` golds are not scoreable, and a `catalogue` question is answerable
only when the country has a portal registry.
"""

from __future__ import annotations

import pytest

from evaluation.discovery_ceiling import ceiling, lift_table

# (country_code, question_id, gold response)
_GT = [
    ("AA", "W1", "yes"),
    ("AA", "C1", "71-90%"),
    ("AA", "C2", "&gt;90%"),
    ("AA", "S1", "yes"),
    ("AA", "N1", "Not applicable"),
    ("BB", "W1", "no"),
    ("BB", "C1", "&lt;10%"),
    ("BB", "C2", "10-30%"),
    ("BB", "S1", "yes"),
    ("BB", "N1", "yes"),
]

_CLASS = {"W1": "web", "C1": "catalogue", "C2": "catalogue",
          "S1": "self_report", "N1": "web"}


def test_ceiling_counts_catalogue_only_with_registry():
    c = ceiling(_GT, _CLASS, registries={"AA"})
    # AA: N1 is n/a -> scoreable 4; web 1 + catalogue 2 answerable.
    assert c["AA"].scoreable == 4
    assert c["AA"].answerable == 3
    assert c["AA"].ceiling == pytest.approx(3 / 4)
    # BB has no registry: catalogue questions blocked, N1 scoreable.
    assert c["BB"].scoreable == 5
    assert c["BB"].answerable == 2  # W1 + N1
    assert c["BB"].ceiling == pytest.approx(2 / 5)


def test_lift_table_reports_gain_for_newly_discovered():
    rows = lift_table(_GT, _CLASS, before={"AA"}, after={"AA", "BB"})
    by_cc = {r["country_code"]: r for r in rows}
    assert by_cc["AA"]["ceiling_before"] == pytest.approx(0.75)
    assert by_cc["AA"]["ceiling_after"] == pytest.approx(0.75)
    assert by_cc["AA"]["lift"] == pytest.approx(0.0)
    assert by_cc["BB"]["ceiling_before"] == pytest.approx(0.4)
    assert by_cc["BB"]["ceiling_after"] == pytest.approx(0.8)
    assert by_cc["BB"]["lift"] == pytest.approx(0.4)
