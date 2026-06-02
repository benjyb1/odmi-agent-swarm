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

from agents.tools.answer_shapes import QuestionShape
from agents.tools.catalogue import formats, licences
from agents.tools.catalogue.model import HarvestedDataset


@dataclass
class MetricResult:
    question_id: str
    metric_function: str
    raw_value: float            # a percentage in [0,100], or a count
    numerator: Optional[int]
    denominator: Optional[int]
    band_label: str
    breakdown: str              # the evidence quote


# ------------------------------------------------------------------
# Band assignment
# ------------------------------------------------------------------


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
    for label in sorted(count_bands, key=lambda b: bounds(b)[0]):
        lo, hi = bounds(label)
        if lo <= value <= hi:
            return label
    return count_bands[-1] if count_bands else (allowed[0] if allowed else "")


def _pct(num: int, denom: int) -> float:
    return (100.0 * num / denom) if denom else 0.0


# ------------------------------------------------------------------
# Presence / count metrics
# ------------------------------------------------------------------


def metric_q12_licence_presence(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q12: percentage of datasets carrying licensing information."""
    denom = len(datasets)
    num = sum(1 for d in datasets if licences.dataset_is_licensed(d))
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets carry licensing information "
        f"= {pct:.1f}% -> {band}"
    )
    return MetricResult("Q12", "metric_q12_licence_presence", pct, num, denom, band, breakdown)


def metric_q13_distinct_licences(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q13: how many distinct licences are used on the portal."""
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
    denom = len(with_dist)
    num = sum(
        1 for d in with_dist
        if any(dist.download_url for dist in d.distributions)
    )
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
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
    denom = len(with_dist)
    num = sum(
        1 for d in with_dist
        if any(dist.access_url for dist in d.distributions)
    )
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets (with distributions) carry an "
        f"access-URL = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q22", "metric_q22_access_url", pct, num, denom, band, breakdown)


def metric_q25_open_licence(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q25: percentage of datasets under an open licence."""
    denom = len(datasets)
    num = sum(1 for d in datasets if licences.dataset_is_open(d))
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets are under an open licence "
        f"= {pct:.1f}% -> {band}"
    )
    return MetricResult("Q25", "metric_q25_open_licence", pct, num, denom, band, breakdown)


def metric_q27_open_format(
    datasets: list[HarvestedDataset], shape: QuestionShape
) -> MetricResult:
    """Q27: percentage of datasets in an open and machine-readable format."""
    denom = len(datasets)
    num = sum(
        1 for d in datasets
        if any(
            formats.is_open_machine_readable(dist.fmt, dist.media_type)
            for dist in d.distributions
        )
    )
    pct = _pct(num, denom)
    band = band_for_percentage(pct, shape.allowed_answers)
    breakdown = (
        f"{num:,} of {denom:,} datasets offer an open, machine-readable "
        f"distribution = {pct:.1f}% -> {band}"
    )
    return MetricResult("Q27", "metric_q27_open_format", pct, num, denom, band, breakdown)


# Registry of presence/count metrics by question_id. The SHACL metrics
# (Q16/Q17/Q18) are registered in compute.py.
PRESENCE_METRICS = {
    "Q12": metric_q12_licence_presence,
    "Q13": metric_q13_distinct_licences,
    "Q21": metric_q21_download_url,
    "Q22": metric_q22_access_url,
    "Q25": metric_q25_open_licence,
    "Q27": metric_q27_open_format,
}
