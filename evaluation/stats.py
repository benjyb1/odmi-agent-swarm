"""Pure statistical estimators for experiment analysis.

Every function here is a pure function: it depends only on its arguments, does
no I/O, and holds no global state. That keeps the dissertation's evaluation
reproducible from logs and trivially unit-testable. Where a formula has a
standard reference, it is named in the docstring so an examiner can check the
working by hand.

Only the standard library is required, except for ``wilcoxon_signed_rank``,
which delegates to scipy when it is installed and otherwise raises
``NotImplementedError`` rather than ship a second-rate reimplementation.
"""
from __future__ import annotations

import itertools
import math
import statistics
from collections import defaultdict


def wilson_interval(
    successes: int, n: int, confidence: float = 0.95
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    The Wilson interval is preferred over the normal (Wald) interval for small
    samples and proportions near 0 or 1, because it never escapes [0, 1] and
    keeps reasonable coverage. See Wilson (1927) and Newcombe (1998).

    Args:
        successes: Number of observed successes (0 <= successes <= n).
        n: Number of trials.
        confidence: Two-sided confidence level, e.g. 0.95.

    Returns:
        A (lower, upper) tuple. For n == 0 the proportion is undefined, so the
        whole unit interval (0.0, 1.0) is returned.
    """
    if n == 0:
        return (0.0, 1.0)

    # Critical value from the standard normal, e.g. 1.95996 for 95%.
    z = statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p_hat = successes / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = (p_hat + z2 / (2 * n)) / denominator
    half_width = (z / denominator) * math.sqrt(
        p_hat * (1 - p_hat) / n + z2 / (4 * n * n)
    )
    lower = centre - half_width
    upper = centre + half_width
    # Clamp against tiny floating-point overshoot at the extremes.
    return (max(0.0, lower), min(1.0, upper))


def _two_sided_binomial_p(k: int, n: int) -> float:
    """Two-sided exact binomial p-value against p = 0.5.

    Under the null the distribution is symmetric, so the two-sided p-value is
    twice the smaller tail, capped at 1.0. ``k`` is taken as the smaller of the
    two counts by the caller.
    """
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact sign test against the null that wins and losses are
    equally likely.

    Ties (trials that are neither a win nor a loss) are assumed already
    excluded by the caller; only the ``wins + losses`` decided trials count.

    Args:
        wins: Number of trials favouring one side.
        losses: Number of trials favouring the other.

    Returns:
        The exact two-sided binomial p-value. Returns 1.0 when no trials were
        decided.
    """
    n = wins + losses
    if n == 0:
        return 1.0
    return _two_sided_binomial_p(min(wins, losses), n)


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar's exact test on a pair of discordant counts.

    For paired binary outcomes, ``b`` and ``c`` are the two off-diagonal
    (discordant) cells of the 2x2 table. The exact test is the two-sided sign
    test over the ``b + c`` discordant pairs against p = 0.5; the concordant
    cells carry no information about a difference and are ignored.

    Args:
        b: Count of one discordant cell.
        c: Count of the other discordant cell.

    Returns:
        The exact two-sided p-value. Returns 1.0 when there are no discordant
        pairs.
    """
    n = b + c
    if n == 0:
        return 1.0
    return _two_sided_binomial_p(min(b, c), n)


def two_proportion_test(
    successes_1: int, n_1: int, successes_2: int, n_2: int,
    confidence: float = 0.95,
) -> dict:
    """Two-sided comparison of two independent binomial proportions.

    Two parts, both standard:

    - **p-value** from the pooled two-proportion z-test (normal approximation
      with the pooled success rate under the null of equal proportions). When
      either sample is empty, or the pooled rate is degenerate (0 or 1, so the
      null variance is zero and the data carry no evidence of a difference),
      the p-value is 1.0.
    - **Interval on the difference** (p1 - p2) by Newcombe's hybrid score
      method (Newcombe 1998, method 10), which combines the two Wilson
      intervals. It respects the [-1, 1] range and behaves at the extremes
      where the Wald interval collapses.

    Args:
        successes_1: Successes in group 1.
        n_1: Trials in group 1.
        successes_2: Successes in group 2.
        n_2: Trials in group 2.
        confidence: Two-sided confidence level for the difference interval.

    Returns:
        A dict with ``p1``, ``p2``, ``delta`` (p1 - p2), ``ci_95`` (the
        Newcombe interval as a [lower, upper] list), ``z`` and ``p_value``.
        With an empty group, ``delta`` and the interval are None.
    """
    if n_1 == 0 or n_2 == 0:
        return {
            "p1": successes_1 / n_1 if n_1 else None,
            "p2": successes_2 / n_2 if n_2 else None,
            "delta": None, "ci_95": None, "z": None, "p_value": 1.0,
        }

    p1 = successes_1 / n_1
    p2 = successes_2 / n_2
    delta = p1 - p2

    # Newcombe hybrid score interval from the two Wilson intervals.
    l1, u1 = wilson_interval(successes_1, n_1, confidence)
    l2, u2 = wilson_interval(successes_2, n_2, confidence)
    lower = delta - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = delta + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)

    # Pooled z-test under the null of equal proportions.
    pooled = (successes_1 + successes_2) / (n_1 + n_2)
    variance = pooled * (1 - pooled) * (1 / n_1 + 1 / n_2)
    if variance == 0:
        z = None
        p_value = 1.0
    else:
        z = delta / math.sqrt(variance)
        p_value = 2 * (1 - statistics.NormalDist().cdf(abs(z)))
    return {
        "p1": p1, "p2": p2, "delta": delta,
        "ci_95": [max(-1.0, lower), min(1.0, upper)],
        "z": z, "p_value": min(1.0, p_value),
    }


def wilcoxon_signed_rank(differences: list[float]) -> tuple[float, float]:
    """Wilcoxon signed-rank test on a list of paired differences.

    Zero differences are dropped first, as the test is undefined for them. The
    computation is delegated to ``scipy.stats.wilcoxon`` because the exact and
    asymptotic variants, tie corrections and continuity corrections are fiddly
    to get right; a hand reimplementation would be a liability in a marked
    dissertation. If scipy is not installed the function raises
    ``NotImplementedError`` so the caller fails loudly rather than silently
    using a worse method.

    Args:
        differences: Paired differences (e.g. metric_a - metric_b per item).

    Returns:
        A (statistic, p_value) tuple from scipy.

    Raises:
        NotImplementedError: If scipy is not importable.
        ValueError: If no non-zero differences remain.
    """
    try:
        from scipy.stats import wilcoxon
    except ImportError as exc:  # pragma: no cover - exercised only without scipy
        raise NotImplementedError(
            "wilcoxon_signed_rank requires scipy. Install it with "
            "'uv add scipy' (or add scipy to the project dependencies) to use "
            "this test."
        ) from exc

    non_zero = [d for d in differences if d != 0]
    if not non_zero:
        raise ValueError("No non-zero differences: the Wilcoxon test is undefined.")

    result = wilcoxon(non_zero)
    return (float(result.statistic), float(result.pvalue))


def krippendorff_alpha(units: list[list], level: str = "nominal") -> float:
    """Krippendorff's alpha reliability coefficient (nominal level).

    Implements the coincidence-matrix formula directly (Krippendorff, Content
    Analysis), so it works for any number of coders per item, not only two.
    Each entry of ``units`` is one item: a list of labels, one per coder, with
    ``None`` marking a missing judgement.

    The coincidence matrix counts every orderable pair of values within an
    item, weighting each by 1 / (m_u - 1) where m_u is the number of present
    values for that item. Alpha is then ``1 - Do / De`` where Do is observed
    disagreement and De is the disagreement expected by chance.

    Args:
        units: Items, each a list of per-coder labels; None means missing.
        level: Measurement level. Only ``"nominal"`` is implemented.

    Returns:
        Alpha in (-inf, 1]. Perfect agreement gives 1.0; chance-level agreement
        gives 0.0; systematic disagreement gives a negative value. Degenerate
        inputs with fewer than two pairable values are defined as 1.0.

    Raises:
        NotImplementedError: For any level other than "nominal".
    """
    if level != "nominal":
        raise NotImplementedError(
            f"krippendorff_alpha supports level='nominal' only, got {level!r}."
        )

    labels = sorted({v for unit in units for v in unit if v is not None})
    if not labels:
        return 1.0

    # Coincidence matrix: counts of label pairs within items, fractional.
    coincidences: dict[tuple, float] = defaultdict(float)
    for unit in units:
        present = [v for v in unit if v is not None]
        m_u = len(present)
        if m_u < 2:
            # A single observation forms no pair, so it cannot disagree.
            continue
        weight = 1.0 / (m_u - 1)
        for value_c, value_k in itertools.permutations(present, 2):
            coincidences[(value_c, value_k)] += weight

    # Marginals n_c and the grand total n.
    n_c = {c: sum(coincidences[(c, k)] for k in labels) for c in labels}
    n_total = sum(n_c.values())
    if n_total < 2:
        return 1.0

    # Nominal disagreement counts every off-diagonal coincidence equally.
    observed = sum(
        coincidences[(c, k)] for c in labels for k in labels if c != k
    )
    expected = sum(
        n_c[c] * n_c[k] for c in labels for k in labels if c != k
    ) / (n_total - 1)

    if expected == 0:
        # No variation across labels: everyone agreed on one value.
        return 1.0
    return 1.0 - observed / expected
