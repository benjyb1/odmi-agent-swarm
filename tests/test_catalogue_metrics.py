"""Tests for the catalogue presence/count metrics and band assignment (D30)."""

from __future__ import annotations

from agents.tools.answer_shapes import NOT_APPLICABLE, QuestionShape
from agents.tools.catalogue import formats, licences, metrics
from agents.tools.catalogue.model import Distribution, HarvestedDataset

PCT_BANDS = (">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%")
COUNT_BANDS = ("1-4", "5-10", ">10", "i don't know")


def _pct_shape(qid: str = "Q12") -> QuestionShape:
    return QuestionShape(question_id=qid, shape="percentage_band", allowed_answers=PCT_BANDS)


def _count_shape() -> QuestionShape:
    return QuestionShape(question_id="Q13", shape="count_band", allowed_answers=COUNT_BANDS)


# ------------------------------------------------------------------
# Band assignment
# ------------------------------------------------------------------


def test_band_for_percentage_boundaries():
    b = metrics.band_for_percentage
    assert b(100.0, PCT_BANDS) == ">90%"
    assert b(94.2, PCT_BANDS) == ">90%"
    assert b(90.0, PCT_BANDS) == "71-90%"   # 90 is the top of 71-90, not >90
    assert b(90.01, PCT_BANDS) == ">90%"
    assert b(71.0, PCT_BANDS) == "71-90%"
    assert b(70.0, PCT_BANDS) == "51-70%"
    assert b(30.0, PCT_BANDS) == "10-30%"
    assert b(10.0, PCT_BANDS) == "10-30%"
    assert b(9.99, PCT_BANDS) == "<10%"
    assert b(0.0, PCT_BANDS) == "<10%"


def test_band_for_count():
    b = metrics.band_for_count
    assert b(1, COUNT_BANDS) == "1-4"
    assert b(4, COUNT_BANDS) == "1-4"
    assert b(5, COUNT_BANDS) == "5-10"
    assert b(10, COUNT_BANDS) == "5-10"
    assert b(11, COUNT_BANDS) == ">10"
    assert b(250, COUNT_BANDS) == ">10"


# ------------------------------------------------------------------
# Licence helpers
# ------------------------------------------------------------------


def test_licence_family_open_and_restricted():
    assert licences.licence_family("http://creativecommons.org/licenses/by/4.0/deed.nl") == "cc-by"
    assert licences.licence_family("CC_BY_SA_4.0") == "cc-by-sa"
    assert licences.licence_family("cc-nc") == "cc-by-nc"        # NC: not open
    assert licences.licence_family("lov2") == "etalab"
    assert licences.licence_family("http://dcat-ap.de/def/licenses/dl-by-de/2.0") == "dl-de-by"
    assert licences.licence_family("OGL-ROU-1.0") == "ogl"
    assert licences.licence_family("http://creativecommons.org/publicdomain/zero/1.0/deed.nl") == "cc0"


def test_licence_sentinels():
    assert licences.licence_family("notspecified") == "sentinel"
    assert licences.licence_family("http://standaarden.overheid.nl/owms/terms/licentieonbekend") == "sentinel"
    assert licences.licence_family("") is None
    assert licences.is_sentinel_raw("") is True
    assert licences.is_sentinel_raw("cc-by") is False


def test_is_open_licence():
    assert licences.is_open_licence("cc-by") is True
    assert licences.is_open_licence("CC_BY_SA_4.0") is True
    assert licences.is_open_licence("cc-nc") is False           # NC restricted
    assert licences.is_open_licence("notspecified") is False


def test_canonical_licence_versions_kept():
    assert licences.canonical_licence("CC_BY_4.0") == "cc-by-4.0"
    assert licences.canonical_licence("http://creativecommons.org/licenses/by-sa/3.0/") == "cc-by-sa-3.0"
    assert licences.canonical_licence("lov2") == "etalab-2"
    assert licences.canonical_licence("notspecified") == "sentinel"


# ------------------------------------------------------------------
# Format helpers
# ------------------------------------------------------------------


def test_open_machine_readable_formats():
    omr = formats.is_open_machine_readable
    assert omr("CSV") is True
    assert omr("http://publications.europa.eu/resource/authority/file-type/JSON") is True
    assert omr(None, "text/csv") is True
    assert omr("PDF") is False
    assert omr("HTML") is False
    assert omr("SHP") is False        # machine-readable but not open; excluded


# ------------------------------------------------------------------
# Metric functions over small fixtures
# ------------------------------------------------------------------


def _ds(identifier, dataset_lics=None, dists=None):
    return HarvestedDataset(
        identifier=identifier,
        dataset_licences=dataset_lics or [],
        distributions=dists or [],
    )


def test_q12_licence_presence():
    datasets = [
        _ds("a", ["cc-by"]),
        _ds("b", ["notspecified"]),               # sentinel -> unlicensed
        _ds("c", [], [Distribution(licence="cc-zero")]),   # distribution-level
        _ds("d", [""]),                            # empty -> unlicensed
    ]
    r = metrics.metric_q12_licence_presence(datasets, _pct_shape("Q12"))
    assert r.numerator == 2 and r.denominator == 4
    assert r.raw_value == 50.0
    assert r.band_label == "31-50%"


def test_q13_distinct_licences():
    datasets = [
        _ds("a", ["CC_BY_4.0"]),
        _ds("b", ["cc-by-4.0"]),                   # same canonical as a
        _ds("c", ["CC_BY_SA_3.0"]),
        _ds("d", ["notspecified"]),                # excluded
        _ds("e", [], [Distribution(licence="cc-zero")]),
    ]
    r = metrics.metric_q13_distinct_licences(datasets, _count_shape())
    # cc-by-4.0, cc-by-sa-3.0, cc0 -> 3 distinct
    assert r.numerator == 3
    assert r.band_label == "1-4"


def test_q21_q22_url_presence_denominator_excludes_no_distribution():
    datasets = [
        _ds("a", dists=[Distribution(access_url="https://x/a", download_url="https://x/a.csv")]),
        _ds("b", dists=[Distribution(access_url="https://x/b")]),   # access only
        _ds("c"),                                                   # no distributions -> excluded
    ]
    q21 = metrics.metric_q21_download_url(datasets, _pct_shape("Q21"))
    q22 = metrics.metric_q22_access_url(datasets, _pct_shape("Q22"))
    assert q21.denominator == 2 and q21.numerator == 1   # only 'a' has download_url
    assert q22.denominator == 2 and q22.numerator == 2   # both have access_url


def test_q25_open_licence():
    datasets = [
        _ds("a", ["cc-by"]),          # open
        _ds("b", ["cc-nc"]),          # restricted, not open
        _ds("c", ["notspecified"]),   # none
        _ds("d", ["cc-zero"]),        # open
    ]
    r = metrics.metric_q25_open_licence(datasets, _pct_shape("Q25"))
    assert r.numerator == 2 and r.denominator == 4
    assert r.band_label == "31-50%"


def test_q27_open_format():
    datasets = [
        _ds("a", dists=[Distribution(fmt="CSV")]),
        _ds("b", dists=[Distribution(fmt="PDF"), Distribution(fmt="JSON")]),  # has JSON
        _ds("c", dists=[Distribution(fmt="PDF")]),                            # none open
        _ds("d"),                                                             # no dist
    ]
    r = metrics.metric_q27_open_format(datasets, _pct_shape("Q27"))
    assert r.numerator == 2 and r.denominator == 4
    assert r.band_label == "31-50%"


# ------------------------------------------------------------------
# Empty denominator (B3): abstain, never the bottom band
# ------------------------------------------------------------------


def test_empty_denominator_abstains_not_bottom_band():
    """B3: a percentage metric with an empty denominator (nothing to
    measure) must abstain with `not_applicable`, not collapse to the
    bottom `<10%` band. A real 0-of-N is a different case and stays a
    genuine bottom band."""
    # Zero datasets harvested -> Q12's denominator is 0.
    q12 = metrics.metric_q12_licence_presence([], _pct_shape("Q12"))
    assert q12.denominator == 0
    assert q12.band_label != "<10%"
    assert q12.band_label == NOT_APPLICABLE

    # Realistic trigger: datasets exist but none carry a distribution,
    # so Q21's download-URL denominator is empty.
    no_dists = [_ds("a"), _ds("b")]
    q21 = metrics.metric_q21_download_url(no_dists, _pct_shape("Q21"))
    assert q21.denominator == 0
    assert q21.band_label == NOT_APPLICABLE
