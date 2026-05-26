"""Tests for agents/tools/extract.py — trafilatura boilerplate-stripping wrapper."""
from __future__ import annotations

import pytest

from agents.tools.extract import extract_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REALISTIC_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>EU Open Data Portal</title></head>
<body>
  <nav>
    <ul>
      <li><a href="/">Home</a></li>
      <li><a href="/datasets">Datasets</a></li>
    </ul>
  </nav>

  <article>
    <h1>Open Data Maturity Report 2024</h1>
    <p>
      The Open Data Maturity (ODM) assessment evaluates how EU member states
      progress in making data available as open data. In 2024, France achieved
      a score of 87% in the Policy dimension.
    </p>
    <p>
      Several countries demonstrated significant improvement compared to the
      previous cycle, particularly in the Impact dimension.
    </p>
  </article>

  <footer>
    <p>Cookie policy | Privacy notice | Contact</p>
    <p>&copy; European Commission 2024</p>
  </footer>
</body>
</html>
"""

TABLE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>ODMI Scores</title></head>
<body>
  <h1>Country Scores</h1>
  <table>
    <thead>
      <tr><th>Country</th><th>Score</th><th>Dimension</th></tr>
    </thead>
    <tbody>
      <tr><td>France</td><td>87</td><td>Policy</td></tr>
      <tr><td>Germany</td><td>82</td><td>Policy</td></tr>
      <tr><td>Netherlands</td><td>91</td><td>Portal</td></tr>
    </tbody>
  </table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_strips_boilerplate():
    """Article body should be preserved; nav and footer boilerplate should be dropped."""
    result = extract_text(REALISTIC_HTML, url="https://data.europa.eu/report")

    # Core content must be present
    assert "Open Data Maturity" in result
    assert "France achieved" in result or "France" in result

    # Nav and footer boilerplate should not dominate (trafilatura may keep some
    # structural text, but cookie-banner phrases and nav link lists should be gone)
    assert "Cookie policy" not in result
    assert "Privacy notice" not in result


def test_extract_returns_empty_on_garbage():
    """Minimal/empty HTML should return an empty string, not raise."""
    result = extract_text("<html></html>", url="https://example.com")
    assert result == ""


def test_extract_returns_empty_on_empty_input():
    """Empty string input must return empty string without error."""
    result = extract_text("", url="https://example.com")
    assert result == ""


def test_extract_passthrough_when_is_html_false():
    """When is_html=False, content must be returned verbatim with no modification."""
    cleaned = "This text was already extracted from the page."
    result = extract_text(cleaned, url="https://example.com", is_html=False)
    assert result == cleaned


def test_extract_passthrough_preserves_exact_content():
    """Passthrough must not strip whitespace or alter multi-line strings."""
    multiline = "Line one.\nLine two.\n\nParagraph break."
    result = extract_text(multiline, url="https://example.com", is_html=False)
    assert result == multiline


def test_extract_includes_tables():
    """Table cell data should be present in extracted output for EU policy pages."""
    result = extract_text(TABLE_HTML, url="https://data.europa.eu/scores")

    # Country names and scores within the table should survive extraction
    assert "France" in result
    assert "Germany" in result
    assert "87" in result or "82" in result
