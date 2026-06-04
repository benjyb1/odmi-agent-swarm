"""Tests for the source-domain trust score (SPEC Q10).

Pins the contract: trusted domains score 1.0, authoritative-looking ones
0.6, the rest 0.3, and deny-listed or malformed URLs 0.0. Also guards the
"www." prefix strip against the lstrip() character-set bug.
"""

from __future__ import annotations

from agents.tools.validator import trust_score


def test_www_prefix_strip_does_not_corrupt_w_hostnames(monkeypatch):
    """lstrip("www.") strips a character SET, so "wales.gov.uk" becomes
    "ales.gov.uk": a leading 'w' is eaten. The literal-prefix strip must
    leave a non-www host untouched. Make the corruption score-visible by
    pinning a trusted list whose only entry starts with 'w'."""
    monkeypatch.setattr(
        "agents.tools.validator._load_country_list",
        lambda cc: ["wales.gov.uk"] if cc == "FR" else [],
    )
    # Correct strip keeps "wales.gov.uk", so it matches the trusted list -> 1.0.
    # The lstrip bug would normalise to "ales.gov.uk" and miss the match.
    assert trust_score("https://wales.gov.uk/open-data", country_code="FR") == 1.0


def test_www_strip_only_removes_leading_prefix(monkeypatch):
    """A trusted host behind www. must still match after stripping the
    literal "www." prefix (and only that prefix)."""
    monkeypatch.setattr(
        "agents.tools.validator._load_country_list",
        lambda cc: ["wales.gov.uk"] if cc == "FR" else [],
    )
    assert trust_score("https://www.wales.gov.uk/x", country_code="FR") == 1.0


def test_europa_eu_via_www_resolves_to_trusted():
    """End-to-end on the real EU seed list: www.europa.eu must score 1.0."""
    assert trust_score("https://www.europa.eu/x", country_code="FR") == 1.0


def test_blocked_url_scores_zero():
    assert trust_score("https://data.europa.eu/odmi", country_code="FR") == 0.0


def test_plain_domain_scores_floor():
    assert trust_score("https://example.com/page", country_code="FR") == 0.3


def test_country_json_trusted_domains_key_is_loaded():
    """The per-country files key the list under "trusted_domains". Reading
    the wrong key returned [] and dropped every national domain to the 0.6
    heuristic. data.gouv.fr is the FR national portal and must score 1.0."""
    assert trust_score("https://data.gouv.fr/dataset/x", country_code="FR") == 1.0


def test_country_json_www_national_domain_is_trusted():
    assert trust_score(
        "https://www.data.gouv.fr/dataset/x", country_code="FR"
    ) == 1.0
