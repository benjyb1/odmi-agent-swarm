"""Hard deny-list for ODMI data leakage (SPEC D24).

These tests pin the contract: known forbidden URLs are blocked at the
URL-parsing layer; legitimate sources are not.
"""

from __future__ import annotations

import pytest

from agents.tools.blocked_domains import (
    BLOCKED_DOMAINS,
    BLOCKED_PATH_FRAGMENTS,
    blocked_reason,
    filter_blocked,
    is_blocked,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://data.europa.eu/en/open-data-maturity/2024",
        "http://data.europa.eu/en/news-events",
        "https://www.data.europa.eu/anything",
        "https://en.data.europa.eu/foo",
        "https://publications.europa.eu/odm-report.pdf",
        "https://op.europa.eu/whatever",
        "https://europeandataportal.eu/legacy/page",
        "https://web.archive.org/web/2024/https://data.gov.fr/...",
        "https://archive.org/details/odmi-2024",
        "https://archive.today/abc",
        "https://archive.ph/xyz",
        "https://archive.is/foo",
        "https://webcache.googleusercontent.com/search?q=cache:foo",
    ],
)
def test_known_forbidden_hosts(url: str) -> None:
    assert is_blocked(url), f"expected blocked: {url}"
    assert blocked_reason(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        # Path-fragment catches third-party republishing of ODMI material.
        "https://capgemini.com/blog/open-data-maturity-2024",
        # D60: the slug may carry a prefix before "open-data-maturity"
        # (here "2025-"), so the fragment must match without a leading
        # slash. This national-portal page reporting the 2025 ODMI results
        # slipped the old "/open-data-maturity" fragment.
        "https://digitalskills.mdia.gov.mt/article/2025-open-data-maturity-highlights-progress-in-the-eu-countries/",
        "https://media.example.com/path/open-data-maturity-report-2024.pdf",
        "https://datos.gob.es/en/etiquetas/open-data-maturity",
        # Path-fragment catches ODMI factsheet PDFs by filename.
        "https://example.org/files/2025_odm_questionnaire_data.xlsx",
        "https://example.org/files/merged_responses.xlsx",
        # `/odmi` slug catches generic ODMI-themed pages.
        "https://example.org/odmi/results",
    ],
)
def test_blocked_path_fragments(url: str) -> None:
    assert is_blocked(url), f"expected blocked on path: {url}"


@pytest.mark.parametrize(
    "url",
    [
        "https://data.gouv.fr/dataset/foo",
        "https://etalab.gouv.fr/",
        "https://digital-strategy.ec.europa.eu/policy",
        "https://example.com/some/page",
        "https://www.gov.uk/data",
        "https://ec.europa.eu/info/open-data",
        "https://example.gov.fr/some/page",
        # Open-data Wikipedia article uses underscores, not the
        # blocked `open-data-maturity` slug.
        "https://en.wikipedia.org/wiki/Open_data_in_Estonia",
        # D60 must not over-block generic open-data pages: the ODMI-specific
        # compound "open-data-maturity" differs from a plain "open-data" slug.
        "https://example.com/open-data-portal-launch",
    ],
)
def test_legitimate_urls_pass(url: str) -> None:
    assert not is_blocked(url), f"expected allowed: {url}"
    assert blocked_reason(url) is None


@pytest.mark.parametrize(
    "url",
    [
        # A trailing-dot FQDN must not bypass the deny-list.
        "https://data.europa.eu./x",
        "https://data.europa.eu.../x",
        "https://www.data.europa.eu./y",
    ],
)
def test_trailing_dot_fqdn_still_blocked(url: str) -> None:
    assert is_blocked(url), f"expected blocked despite trailing dot: {url}"
    assert blocked_reason(url) is not None


def test_empty_and_malformed() -> None:
    assert is_blocked("") is False
    assert is_blocked("not a url") is False
    assert blocked_reason("") is None


def test_filter_blocked_splits() -> None:
    urls = [
        "https://data.gouv.fr/x",
        "https://data.europa.eu/y",
        "https://example.com/odmi-results",
    ]
    allowed, dropped = filter_blocked(urls)
    assert allowed == ["https://data.gouv.fr/x"]
    assert len(dropped) == 2
    assert all(reason for _, reason in dropped)


def test_deny_list_includes_data_europa_eu() -> None:
    # Belt-and-braces: pin the primary leak source so a future edit can't
    # silently remove it.
    assert "data.europa.eu" in BLOCKED_DOMAINS
    assert "open-data-maturity" in BLOCKED_PATH_FRAGMENTS
