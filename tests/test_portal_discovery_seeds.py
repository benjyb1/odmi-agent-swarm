"""Integrity of the committed 36-country portal seed file.

The seed list is itself infrastructure metadata under the D24 leakage
rule: it must cover exactly the 36 ODMI-assessed countries, every URL
must be clean of the deny-list, and every entry must say how it was
sourced, because "where did this URL come from" is an examiner question.
"""

from __future__ import annotations

import pytest

from agents.tools.blocked_domains import is_blocked
from agents.tools.catalogue.discovery.seeds import Seed, load_seeds

# The 36 ODMI-assessed countries (ground_truth's distinct country codes),
# pinned here so the test does not depend on the SQLite file.
ODMI_COUNTRIES = frozenset({
    "AL", "AT", "BA", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "EL",
    "ES", "FI", "FR", "HR", "HU", "IE", "IS", "IT", "LT", "LU", "LV", "ME",
    "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS", "SE", "SI", "SK", "UA",
})


@pytest.fixture(scope="module")
def seeds() -> list[Seed]:
    return load_seeds()


def test_exactly_the_36_assessed_countries(seeds):
    codes = [s.country_code for s in seeds]
    assert len(codes) == 36
    assert len(set(codes)) == 36, "duplicate country codes in seed file"
    assert set(codes) == ODMI_COUNTRIES


def test_every_seed_url_is_https_and_clean_of_the_denylist(seeds):
    for s in seeds:
        urls = [s.portal_base, *s.alternates, *(
            v for v in s.hints.values() if isinstance(v, str) and "://" in v
        )]
        for url in urls:
            assert url.startswith("https://"), f"{s.country_code}: {url}"
            assert not is_blocked(url), f"{s.country_code}: deny-listed {url}"


def test_no_seed_points_at_the_eu_aggregator_even_indirectly(seeds):
    for s in seeds:
        joined = " ".join([s.portal_base, *s.alternates, s.source, s.notes])
        assert "europa.eu" not in joined.lower(), (
            f"{s.country_code}: seed references the EU aggregator"
        )


def test_every_seed_is_annotated_with_its_source(seeds):
    for s in seeds:
        assert len(s.source.strip()) >= 20, (
            f"{s.country_code}: missing or trivial source annotation"
        )


def test_load_seeds_refuses_a_denylisted_entry(tmp_path):
    poisoned = tmp_path / "seeds.json"
    poisoned.write_text(
        '{"seeds": [{"country_code": "XX", "country_name": "X",'
        ' "portal_base": "https://data.europa.eu", "source": "x"}]}'
    )
    with pytest.raises(Exception):
        load_seeds(poisoned)
