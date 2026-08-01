"""The catalogue metric functions (D30).

Each function takes the harvested datasets plus the question's
`QuestionShape` (for the allowed band labels) and returns a
`MetricResult`: the raw value, numerator, denominator, the assigned band
label, and a human-readable breakdown that becomes the Researcher's
evidence quote.

Band assignment is derived from the question's own `allowed_answers`, not
from any external answer. See `docs/CATALOGUE_METRICS.md`.

This module holds the six presence/count metrics:
Q12, Q13, Q21, Q22, Q25, Q27. The three SHACL conformance metrics
(Q16/Q17/Q18) live in `compute.py` on top of `shacl.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from agents.tools.answer_shapes import NOT_APPLICABLE, QuestionShape
from agents.tools.catalogue import formats, licences
from agents.tools.catalogue.model import HarvestedDataset


@dataclass
class MetricResult:
    question_id: str
    metric_function: str
    raw_value: Optional[float]  # a percentage in [0,100], or a count; None if unmeasurable
    numerator: Optional[int]
    denominator: Optional[int]
    band_label: str
    breakdown: str              # the evidence quote


# Band assignment


def _percent_upper_bound(label: str) -> float:
    """Parse a percentage band label to its inclusive upper bound.

    `<10%` -> 10 (exclusive, handled by caller), `10-30%` -> 30,
    `71-90%` -> 90, `>90%` -> +inf.
    """
    s = label.replace("%", "").strip()
    if s.startswith("<"):
        return float(s[1:])
    if s.startswith(">"):
        return float("inf")
    nums = re.findall(r"\d+", s)
    if nums:
        return float(nums[-1])
    return float("inf")


def band_for_percentage(value: float, allowed: Sequence[str]) -> str:
    """Map a percentage to the band whose range contains it.

    Bands are taken from the question's allowed answers. The bottom `<N%`
    band is exclusive at N; every other band is inclusive at its upper
    bound. Bands are tested low-to-high so the first that contains the
    value wins.
    """
    bands = [b for b in allowed if "%" in b]
    ordered = sorted(bands, key=_percent_upper_bound)
    for i, label in enumerate(ordered):
        upper = _percent_upper_bound(label)
        is_bottom = label.replace("%", "").strip().startswith("<")
        if upper == float("inf"):
            return label
        if (value < upper) if is_bottom else (value <= upper):
            return label
    # Fallback: highest band.
    return ordered[-1] if ordered else (allowed[0] if allowed else "")


def band_for_count(value: int, allowed: Sequence[str]) -> str:
    """Map an integer count to a count band (Q13 style `1-4`/`5-10`/`>10`).

    Ignores non-count labels such as `i don't know`.
    """
    def bounds(label: str) -> tuple[float, float]:
        s = label.strip().lower()
        if s.startswith(">"):
            return float(re.findall(r"\d+", s)[0]) + 1, float("inf")
        if s.startswith("<"):
            return 0.0, float(re.findall(r"\d+", s)[0]) - 1
        nums = re.findall(r"\d+", s)
        if len(nums) >= 2:
            return float(nums[0]), float(nums[1])
        if len(nums) == 1:
            return float(nums[0]), float(nums[0])
        return float("inf"), float("inf")  # non-numeric label, never matches

    count_bands = [b for b in allowed if re.search(r"\d", b)]
    ordered = sorted(count_bands, key=lambda b: bounds(b)[0])
    for label in ordered:
        lo, hi = bounds(label)
        if lo <= value <= hi:
            return label
    # The value fell outside every band. Map it to the nearest band by
    # direction: below the lowest lower-bound -> the lowest band, above the
    # highest -> the highest. The old fallback returned `count_bands[-1]`
    # unconditionally, which mislabelled a count of 0 (below the `1-4` band)
    # as the top band `>10`. See HR/RO Q13 in the June/July harvests.
    if not ordered:
        return allowed[0] if allowed else ""
    return ordered[0] if value < bounds(ordered[0])[0] else ordered[-1]


def _pct(num: int, denom: int) -> float:
    return (100.0 * num / denom) if denom else 0.0


# Field-absence detection
# A field that the route cannot see and a field that is actually empty are
# different measurements. If a whole harvest carries no value at all for a
# field (the SPARQL/DCAT route never emits the predicate, e.g. Croatia has no
# dct:license and no dcat:downloadURL anywhere), a 0% reading is not "0% of
# datasets are licensed" but "we could not observe licensing from this route".
# The metric abstains with `not_applicable` in that case rather than emitting a
# confident bottom band. A genuine 0-of-N, where the field IS present on the
# route but no dataset qualifies (e.g. a licence field that everywhere reads
# `notspecified`), keeps its real bottom band -- the field was observed.


def _corpus_exposes_licence(datasets: Sequence[HarvestedDataset]) -> bool:
    """True if any dataset carries any licence string at all (either level)."""
    return any(d.all_licences() for d in datasets)


def _corpus_exposes_dist_field(
    datasets: Sequence[HarvestedDataset], attr: str
) -> bool:
    """True if any distribution anywhere carries a value for `attr`."""
    return any(
        getattr(dist, attr) for d in datasets for dist in d.distributions
    )


def _corpus_exposes_format(datasets: Sequence[HarvestedDataset]) -> bool:
    return any(
        (dist.fmt or dist.media_type)
        for d in datasets for dist in d.distributions
    )


def _unmeasurable(
    question_id: str, metric_function: str, why: str
) -> MetricResult:
    """A metric whose field is absent from the whole harvest: unmeasurable,
    recorded as `not_applicable` with null raw value (never a 0)."""
    return MetricResult(
        question_id, metric_function,
        raw_value=None, numerator=None, denominator=None,
        band_label=NOT_APPLICABLE,
        breakdown=f"Field not exposed by this route: {why} -> {NOT_APPLICABLE}",
    )


def _percentage_band(
    num: int, denom: int, allowed: Sequence[str]
) -> tuple[float, str]:
    """Percentage and assigned band for `num` of `denom`.

    An empty denominator is not a zero percentage. With nothing to measure
    (a catalogue with no datasets, or none carrying a distribution) the
    metric abstains with `not_applicable` rather than collapsing to the
    bottom band (B3). A real 0-of-N keeps its genuine bottom band.
    """
    if denom == 0:
        return 0.0, NOT_APPLICABLE
    pct = _pct(num, denom)
    return pct, band_for_percentage(pct, allowed)


# Presence / count metrics


def metric_q12_licence_presence(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q12: percentage of datasets carrying licensing information."""
    if datasets and not _corpus_exposes_licence(datasets):
        return _unmeasurable(
            "Q12", "metric_q12_licence_presence",
            "no licence value present anywhere in the harvested metadata",
        )
    denom = len(datasets)
    num = sum(1 for d in datasets if licences.dataset_is_licensed(d))
    pct, band = _percentage_band(num, denom, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets carry licensing information "
        f"= {pct:.1f}% -> {band}"
    )
    return MetricResult("Q12", "metric_q12_licence_presence", pct, num, denom, band, breakdown)


def metric_q13_distinct_licences(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q13: how many distinct licences are used on the portal."""
    if datasets and not _corpus_exposes_licence(datasets):
        return _unmeasurable(
            "Q13", "metric_q13_distinct_licences",
            "no licence value present anywhere in the harvested metadata",
        )
    keys = licences.distinct_licence_keys(datasets)
    n = len(keys)
    band = band_for_count(n, shape.allowed_answers)
    shown = ", ".join(sorted(keys)[:8])
    more = "..." if n > 8 else ""
    breakdown = f"{n} distinct licences in use ({shown}{more}) -> {band}"
    return MetricResult("Q13", "metric_q13_distinct_licences", float(n), n, None, band, breakdown)


def metric_q21_download_url(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q21: percentage of datasets whose metadata provides a download-URL."""
    with_dist = [d for d in datasets if d.has_distributions()]
    if with_dist and not _corpus_exposes_dist_field(datasets, "download_url"):
        # Distributions exist but not one carries a download URL: the route
        # does not expose the field (HR's SPARQL graph). Unmeasurable, not 0%.
        return _unmeasurable(
            "Q21", "metric_q21_download_url",
            "no dcat:downloadURL present on any distribution in the harvest",
        )
    denom = len(with_dist)
    num = sum(
        1 for d in with_dist
        if any(dist.download_url for dist in d.distributions)
    )
    pct, band = _percentage_band(num, denom, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets (with distributions) carry a "
        f"download-URL = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q21", "metric_q21_download_url", pct, num, denom, band, breakdown)


def metric_q22_access_url(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q22: percentage of datasets whose metadata provides an access-URL."""
    with_dist = [d for d in datasets if d.has_distributions()]
    if with_dist and not _corpus_exposes_dist_field(datasets, "access_url"):
        return _unmeasurable(
            "Q22", "metric_q22_access_url",
            "no dcat:accessURL present on any distribution in the harvest",
        )
    denom = len(with_dist)
    num = sum(
        1 for d in with_dist
        if any(dist.access_url for dist in d.distributions)
    )
    pct, band = _percentage_band(num, denom, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets (with distributions) carry an "
        f"access-URL = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q22", "metric_q22_access_url", pct, num, denom, band, breakdown)


def metric_q25_open_licence(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q25: percentage of datasets under an open licence."""
    if datasets and not _corpus_exposes_licence(datasets):
        return _unmeasurable(
            "Q25", "metric_q25_open_licence",
            "no licence value present anywhere in the harvested metadata",
        )
    denom = len(datasets)
    num = sum(1 for d in datasets if licences.dataset_is_open(d))
    pct, band = _percentage_band(num, denom, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets are under an open licence "
        f"= {pct:.1f}% -> {band}"
    )
    return MetricResult("Q25", "metric_q25_open_licence", pct, num, denom, band, breakdown)


def metric_q27_open_format(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q27: percentage of datasets in an open and machine-readable format."""
    with_dist = [d for d in datasets if d.has_distributions()]
    if with_dist and not _corpus_exposes_format(datasets):
        return _unmeasurable(
            "Q27", "metric_q27_open_format",
            "no format or media-type present on any distribution in the harvest",
        )
    denom = len(datasets)
    num = sum(
        1 for d in datasets
        if any(
            formats.is_open_machine_readable(dist.fmt, dist.media_type)
            for dist in d.distributions
        )
    )
    pct, band = _percentage_band(num, denom, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets offer an open, machine-readable "
        f"distribution = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q27", "metric_q27_open_format", pct, num, denom, band, breakdown)


# DCAT-AP conformance metrics (Q16/Q17/Q18). These need a per-dataset
# RDF graph (the dcat_rdf route, or graphs synthesised from JSON for
# NL/EE). Datasets without a graph cannot be assessed; if none have one,
# the function raises so the caller treats conformance as unavailable.

DEFAULT_SHACL_SAMPLE = 1000


def _evenly_spaced_sample(
    items: list, n: Optional[int]
) -> tuple[list, bool]:
    """Deterministic evenly-spaced sample of `n` items. Returns
    (sample, was_sampled). No silent cap: the caller discloses the
    sample size in the breakdown."""
    if n is None or len(items) <= n:
        return items, False
    stride = len(items) / n
    return [items[int(i * stride)] for i in range(n)], True


def _graphed_datasets(datasets: list[HarvestedDataset]) -> list[HarvestedDataset]:
    from agents.tools.catalogue import shacl
    return [
        d for d in datasets
        if d.graph is not None and shacl.has_dataset_node(d.graph)
    ]


def metric_q16_mandatory_conformance(
    datasets: list[HarvestedDataset],
    shape: QuestionShape,
    *,
    sample_size: Optional[int] = DEFAULT_SHACL_SAMPLE,
) -> MetricResult:
    """Q16: percentage of metadata DCAT-AP compliant in mandatory classes."""
    from agents.tools.catalogue import shacl

    graphed = _graphed_datasets(datasets)
    if not graphed:
        raise ValueError("Q16 needs dataset RDF graphs; none available")
    sampled, was_sampled = _evenly_spaced_sample(graphed, sample_size)
    num = sum(1 for d in sampled if shacl.is_mandatory_conformant(d.graph))
    denom = len(sampled)
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    sample_note = (
        f" (sampled {denom:,} of {len(graphed):,})" if was_sampled else ""
    )
    breakdown = (
        f"{num:,} of {denom:,} datasets pass the SEMIC DCAT-AP mandatory "
        f"SHACL shapes{sample_note} = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q16", "metric_q16_mandatory_conformance", pct, num, denom, band, breakdown)


def metric_q17_recommended_usage(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q17: percentage of metadata using DCAT-AP recommended classes."""
    from agents.tools.catalogue import shacl

    graphed = _graphed_datasets(datasets)
    if not graphed:
        raise ValueError("Q17 needs dataset RDF graphs; none available")
    num = sum(1 for d in graphed if shacl.uses_recommended(d.graph))
    denom = len(graphed)
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets exercise a DCAT-AP recommended "
        f"property = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q17", "metric_q17_recommended_usage", pct, num, denom, band, breakdown)


def metric_q18_optional_usage(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q18: percentage of metadata using DCAT-AP optional classes."""
    from agents.tools.catalogue import shacl

    graphed = _graphed_datasets(datasets)
    if not graphed:
        raise ValueError("Q18 needs dataset RDF graphs; none available")
    num = sum(1 for d in graphed if shacl.uses_optional(d.graph))
    denom = len(graphed)
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets exercise a DCAT-AP optional "
        f"property = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q18", "metric_q18_optional_usage", pct, num, denom, band, breakdown)


# Registry of presence/count metrics by question_id.
PRESENCE_METRICS = {
    "Q12": metric_q12_licence_presence,
    "Q13": metric_q13_distinct_licences,
    "Q21": metric_q21_download_url,
    "Q22": metric_q22_access_url,
    "Q25": metric_q25_open_licence,
    "Q27": metric_q27_open_format,
}

# Conformance metrics (need dataset RDF graphs).
CONFORMANCE_METRICS = {
    "Q16": metric_q16_mandatory_conformance,
    "Q17": metric_q17_recommended_usage,
    "Q18": metric_q18_optional_usage,
}
