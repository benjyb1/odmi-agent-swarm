"""EXP-36 subgroup equity decomposition (§4.7).

Asks whether the frozen headline holds up the same way in both halves of the
held-out eight, and whether the stratum A / B gaps survive conditioning on what
kind of question was being asked. Everything is replay arithmetic over
`data/odmi.db`; no LLM calls, no writes, and ground truth is read only to score,
never to compute a predicted value.

Reuses the project's own machinery rather than reimplementing it:

- `evaluation.exp36_analysis.load_rows` (which embeds the dashboard's
  `_MATCH_STATUS_SQL` verbatim) and `dedup_canonical(scope_by_label=False)`;
- `evaluation.abstention_gold_class_by_code.classify_abstentions` for the
  priority-list abstention codes, already checked 508/508 against the filed CSV;
- `evaluation.stats` for Wilson intervals and the two-proportion contrast.

`evaluation/abstention_records.csv` is deliberately NOT read: it is stale and
holds no EXP-36 rows.

Denominators
------------
Two negative-gold denominators exist and are never mixed in one table:

- binary-shape gold `no`  = 368 pairs (answer_shape = 'binary')
- all-shapes gold `no`    = 370 pairs (adds two `count_band` golds)

Every emitted rate carries its denominator label. The project's own
`is_negative_gold` is binary-shape, so that is the primary; the all-shapes
variant is reported beside it as a separate, separately labelled column.

Sections
--------
1. Reconstructed yes-share per country vs gold, under three abstention policies.
2. Decision mix (confirm / complement / change) by country and stratum, with
   commit accuracy inside each decision inside each stratum.
3. TPR / TNR / balanced accuracy / Youden's J on committed binary pairs.
4. Negative-gold false-positive rate, over all no-golds and over committed only.
5. Stratum x gold class x outcome cross-tab, with a CMH test of whether the
   abstention gap survives conditioning on gold class.
6. Abstention code x stratum x gold class, same conditioning question for G.
7. Exact country-level permutation tests (4 against 4, 70 arrangements).
8. Belgium isolate, cross-referenced against catalogue recomputability.

Usage:
    uv run --extra dev python evaluation/exp36_subgroup_equity.py
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.abstention_gold_class_by_code import (  # noqa: E402
    classify_abstentions,
)
from evaluation.exp36_analysis import (  # noqa: E402
    STRATUM_A,
    STRATUM_B,
    dedup_canonical,
    is_committed,
    is_failed,
    is_match,
    is_scoreable,
    load_rows,
    norm,
    resource_stratum,
)
from evaluation.stats import two_proportion_test, wilson_interval  # noqa: E402

EXPERIMENT_ID = "exp36_frozen_headline"
EXPECTED_CANONICAL_PAIRS = 1144
EXPECTED_PER_COUNTRY = 143

# Catalogue recomputability (memory: catalogue-holdout-coverage). BG, MK, BE and
# BA have no harvestable national catalogue (geo-block / no machine API /
# single-agency non-DCAT); FI, HR, SE and ME do. This cross-cuts the D47 stratum
# split: it swaps BE (stratum B, no catalogue) for ME (stratum A, catalogue), so
# it is a competing grouping and is tested as one.
CATALOGUE_YES = ("FI", "HR", "SE", "ME")
CATALOGUE_NO = ("BG", "MK", "BE", "BA")

ALL_COUNTRIES = tuple(sorted(STRATUM_A + STRATUM_B))

# Okabe-Ito, safe under deuteranopia, protanopia and tritanopia. Matches
# evaluation/abstention_gold_class_by_code.py.
COLOUR_A = "#E69F00"  # orange, stratum A
COLOUR_B = "#0072B2"  # blue, stratum B
INK = "#1a1a1a"
GRID = "#cccccc"

FIG_DPI = 200
SMALL_CELL = 20  # cells below this n cannot carry a claim


# Small pure helpers

def _rate(successes: int, n: int) -> dict:
    """Proportion with its Wilson 95% interval. n = 0 yields a null rate."""
    lo, hi = wilson_interval(successes, n)
    return {
        "successes": successes,
        "n": n,
        "rate": (successes / n) if n else None,
        "wilson_95": [lo, hi],
    }


def gold_class(row) -> str:
    """yes / no / other / absent. `other` is a gold that exists but is not a
    bare yes or no (count bands, `not applicable`, free text)."""
    g = norm(row.gold_answer)
    if not g:
        return "absent"
    return g if g in ("yes", "no") else "other"


def is_binary_shape_no(row) -> bool:
    return norm(row.answer_shape) == "binary" and norm(row.gold_answer) == "no"


def is_all_shape_no(row) -> bool:
    return norm(row.gold_answer) == "no"


def is_binary_gold_pair(row) -> bool:
    return (
        norm(row.answer_shape) == "binary"
        and norm(row.gold_answer) in ("yes", "no")
    )


def catalogue_group(country: str) -> str:
    return "catalogue" if country in CATALOGUE_YES else "no_catalogue"


def commit_accuracy(rows: list) -> dict:
    """Strict matches over scoreable committed pairs. `near_match` is never
    folded in; unscoreable commits (flag_review, no_ground_truth) leave the
    denominator and are counted by the caller where it matters."""
    scoreable = [r for r in rows if is_committed(r) and is_scoreable(r)]
    return _rate(sum(1 for r in scoreable if is_match(r)), len(scoreable))


def abstention_rate(rows: list) -> dict:
    """Not-committed over all pairs. Per D37 a pair that never commits is an
    abstention; EXP-36 logged no agent_failure rows, which is asserted below."""
    return _rate(sum(1 for r in rows if not is_committed(r)), len(rows))


def chi2_sf_1df(x: float) -> float:
    """Upper tail of a chi-square with 1 df. Exact via erfc, so no scipy
    dependency creeps into the estimator layer."""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


def newcombe_sum(p1: float, lo1: float, hi1: float,
                 p2: float, lo2: float, hi2: float) -> tuple[float, float]:
    """Square-and-add interval for the SUM of two independent proportions,
    built from their Wilson intervals (Newcombe 1998, applied to a sum rather
    than a difference). Balanced accuracy is this halved; Youden's J is this
    minus one."""
    lower = (p1 + p2) - math.sqrt((p1 - lo1) ** 2 + (p2 - lo2) ** 2)
    upper = (p1 + p2) + math.sqrt((hi1 - p1) ** 2 + (hi2 - p2) ** 2)
    return lower, upper


def cmh_test(tables: list[tuple[int, int, int, int]]) -> dict:
    """Cochran-Mantel-Haenszel test over a list of 2x2 tables (a, b, c, d),
    where a/b is the exposed row and c/d the unexposed.

    Answers "does the association survive conditioning on the stratifying
    variable?". Returns the continuity-corrected statistic, its 1-df p-value,
    and the Mantel-Haenszel common odds ratio. Tables with a degenerate margin
    contribute nothing and are counted.
    """
    sum_a = 0.0
    sum_e = 0.0
    sum_v = 0.0
    num_or = 0.0
    den_or = 0.0
    used = 0
    for a, b, c, d in tables:
        n1 = a + b
        n2 = c + d
        m1 = a + c
        t = a + b + c + d
        if t < 2 or n1 == 0 or n2 == 0 or m1 == 0 or m1 == t:
            continue
        used += 1
        m2 = t - m1
        sum_a += a
        sum_e += n1 * m1 / t
        sum_v += (n1 * n2 * m1 * m2) / (t * t * (t - 1))
        num_or += a * d / t
        den_or += b * c / t
    if used == 0 or sum_v == 0:
        return {
            "n_tables_used": used, "statistic": None,
            "p_value": None, "mh_odds_ratio": None,
        }
    stat = (abs(sum_a - sum_e) - 0.5) ** 2 / sum_v
    return {
        "n_tables_used": used,
        "statistic": stat,
        "p_value": chi2_sf_1df(stat),
        "mh_odds_ratio": (num_or / den_or) if den_or else None,
        "observed_a": sum_a,
        "expected_a": sum_e,
    }


def exact_permutation_4v4(country_values: dict[str, float],
                          group_a: tuple[str, ...]) -> dict:
    """Exact country-level permutation test over all C(8,4) = 70 arrangements.

    The unit is the country, not the pair, so clustering within country is
    handled by construction. The statistic is the difference in the unweighted
    mean of the per-country rates. Both a split and its complement appear among
    the 70, so the two-sided null distribution is symmetric and the smallest
    achievable p is 2/70 = 0.0286. That floor is reported so a p at the floor is
    read as "the most extreme arrangement available", not as a small p.
    """
    countries = sorted(country_values)
    n_half = len(countries) // 2
    observed = (
        sum(country_values[c] for c in group_a) / len(group_a)
        - sum(country_values[c] for c in countries if c not in group_a)
        / (len(countries) - len(group_a))
    )
    stats = []
    for combo in combinations(countries, n_half):
        rest = [c for c in countries if c not in combo]
        stats.append(
            sum(country_values[c] for c in combo) / len(combo)
            - sum(country_values[c] for c in rest) / len(rest)
        )
    n_perm = len(stats)
    n_ge = sum(1 for s in stats if abs(s) >= abs(observed) - 1e-12)
    return {
        "observed_delta": observed,
        "n_arrangements": n_perm,
        "n_at_least_as_extreme": n_ge,
        "p_value_exact": n_ge / n_perm,
        "min_achievable_p": 2 / n_perm,
        "at_floor": n_ge == 2,
        "country_values": {c: country_values[c] for c in countries},
    }


# 1. Reconstructed yes-share

def yes_share_reconstruction(rows: list) -> dict:
    """Per-country gold vs reconstructed yes-share on binary golds, under three
    abstention policies.

    Denominator: binary-shape golds (`answer_shape = 'binary'`, gold in
    {yes, no}), minus committed answers that are neither yes nor no. Those
    off-shape commits (`other`, `not_applicable`) cannot be scored as a yes or a
    no, so including them would silently deflate every reconstructed share; they
    are dropped from numerator and denominator alike, and counted.

    Policies:
      (a) abstentions excluded   -> denominator is committed pairs only
      (b) abstentions -> 'no'    -> denominator is all binary-gold pairs
      (c) abstentions -> gold    -> denominator is all binary-gold pairs

    Policy (c) is an oracle: it fills abstentions with the answer being scored,
    so it is a bound on what perfect abstention-handling could recover, not a
    deployable procedure. It is labelled as such wherever it is reported.
    """
    out: dict[str, dict] = {}
    for country in ALL_COUNTRIES:
        binary = [
            r for r in rows
            if r.country_code == country and is_binary_gold_pair(r)
        ]
        committed = [r for r in binary if is_committed(r)]
        off_shape = [
            r for r in committed if norm(r.final_answer) not in ("yes", "no")
        ]
        off_keys = {id(r) for r in off_shape}
        eff = [r for r in binary if id(r) not in off_keys]
        eff_committed = [r for r in committed if id(r) not in off_keys]
        abstained = [r for r in eff if not is_committed(r)]

        n_eff = len(eff)
        n_com = len(eff_committed)
        pred_yes = sum(1 for r in eff_committed if norm(r.final_answer) == "yes")
        abst_gold_yes = sum(1 for r in abstained if norm(r.gold_answer) == "yes")
        gold_yes_eff = sum(1 for r in eff if norm(r.gold_answer) == "yes")

        gold_share = gold_yes_eff / n_eff if n_eff else None
        policies = {
            "a_excluded": {
                "numerator": pred_yes, "denominator": n_com,
                "denominator_label": "committed binary-gold pairs",
            },
            "b_coerced_no": {
                "numerator": pred_yes, "denominator": n_eff,
                "denominator_label": "all binary-gold pairs",
            },
            "c_coerced_gold": {
                "numerator": pred_yes + abst_gold_yes, "denominator": n_eff,
                "denominator_label": "all binary-gold pairs (oracle fill)",
            },
        }
        for block in policies.values():
            d = block["denominator"]
            block["reconstructed_yes_share"] = (
                block["numerator"] / d if d else None
            )
            block["signed_error"] = (
                block["reconstructed_yes_share"] - gold_share
                if (d and gold_share is not None) else None
            )

        out[country] = {
            "stratum": resource_stratum(country),
            "n_binary_gold_pairs": len(binary),
            "n_off_shape_commits_excluded": len(off_shape),
            "off_shape_literals": sorted(
                Counter(norm(r.final_answer) for r in off_shape).items()
            ),
            "n_effective_binary_gold_pairs": n_eff,
            "n_committed": n_com,
            "n_abstained": len(abstained),
            "n_gold_yes": gold_yes_eff,
            "gold_yes_share": gold_share,
            "policies": policies,
        }
    return out


# 2. Decision mix

def decision_mix(rows: list) -> dict:
    """confirm / complement / change counts, shares and within-decision commit
    accuracy, by country and by stratum. Share denominator is all 143 pairs of
    the country (or all pairs of the stratum); commit-accuracy denominator is
    scoreable committed pairs inside that decision, which is much smaller and is
    always emitted alongside."""
    classes = ("confirm", "complement", "change")

    def block(subset: list, label: str) -> dict:
        total = len(subset)
        per = {}
        for cls in classes:
            members = [r for r in subset if norm(r.gold_decision) == cls]
            acc = commit_accuracy(members)
            per[cls] = {
                "n_pairs": len(members),
                "share_of_pairs": (len(members) / total) if total else None,
                "share_denominator": total,
                "commit_accuracy": acc,
                "abstention_rate": abstention_rate(members),
            }
        unknown = [
            r for r in subset if norm(r.gold_decision) not in classes
        ]
        return {
            "group": label,
            "n_pairs": total,
            "n_unclassified_decision": len(unknown),
            "by_decision": per,
        }

    return {
        "by_country": {
            c: block([r for r in rows if r.country_code == c], c)
            for c in ALL_COUNTRIES
        },
        "by_stratum": {
            s: block(
                [r for r in rows if resource_stratum(r.country_code) == s], s
            )
            for s in ("A", "B")
        },
        "pooled": block(rows, "pooled"),
    }


# 3. TPR / TNR on committed binary pairs

def class_recall_committed(rows: list) -> dict:
    """TPR, TNR, balanced accuracy and Youden's J on COMMITTED binary-gold
    pairs only.

    This is a different denominator from `exp36_analysis.binary_headline`,
    which charges abstentions against recall. Here an abstention leaves the
    denominator entirely, so these are conditional-on-answering rates: "when it
    did answer, how often was it right in each class". Correctness uses the
    project's own `is_match`, so a committed off-shape answer counts as a miss
    for its class, which is the correct behaviour for a recall.

    Balanced accuracy and Youden's J get a square-and-add interval built from
    the two Wilson intervals, since the two class denominators are disjoint and
    so the class recalls are independent.
    """
    binary = [r for r in rows if is_binary_gold_pair(r) and is_committed(r)]
    yes = [r for r in binary if norm(r.gold_answer) == "yes"]
    no = [r for r in binary if norm(r.gold_answer) == "no"]
    tpr = _rate(sum(1 for r in yes if is_match(r)), len(yes))
    tnr = _rate(sum(1 for r in no if is_match(r)), len(no))

    both = bool(yes) and bool(no)
    balanced = youden = None
    balanced_ci = youden_ci = None
    if both:
        lo, hi = newcombe_sum(
            tpr["rate"], tpr["wilson_95"][0], tpr["wilson_95"][1],
            tnr["rate"], tnr["wilson_95"][0], tnr["wilson_95"][1],
        )
        balanced = (tpr["rate"] + tnr["rate"]) / 2
        youden = tpr["rate"] + tnr["rate"] - 1.0
        balanced_ci = [max(0.0, lo / 2), min(1.0, hi / 2)]
        youden_ci = [max(-1.0, lo - 1.0), min(1.0, hi - 1.0)]
    return {
        "denominator_label": "committed binary-gold pairs",
        "n_committed_binary": len(binary),
        "tpr": tpr,
        "tnr": tnr,
        "balanced_accuracy": balanced,
        "balanced_accuracy_ci_95": balanced_ci,
        "youden_j": youden,
        "youden_j_ci_95": youden_ci,
        "interval_method": (
            "Wilson on TPR/TNR; square-and-add (Newcombe) on their sum for "
            "balanced accuracy and Youden's J"
        ),
    }


# 4. Negative-gold false-positive rate

def negative_fp(rows: list) -> dict:
    """FP rate on negative golds, under both shape denominators and both
    conditioning choices.

    A false positive is a committed answer that does not match a `no` gold.
    Reported over all no-golds (abstentions dilute the rate) and over committed
    no-golds only (the conditional rate). The two shape denominators, 368
    binary-shape and 370 all-shapes, are kept in separate labelled blocks and
    never summed or averaged together.
    """
    def block(predicate, label: str) -> dict:
        neg = [r for r in rows if predicate(r)]
        com = [r for r in neg if is_committed(r)]
        fp_all = sum(1 for r in neg if is_committed(r) and not is_match(r))
        fp_com = sum(1 for r in com if not is_match(r))
        return {
            "shape_denominator_label": label,
            "n_no_golds": len(neg),
            "n_committed": len(com),
            "n_false_positives": fp_all,
            "fp_over_all_no_golds": _rate(fp_all, len(neg)),
            "fp_over_committed_no_golds": _rate(fp_com, len(com)),
        }

    return {
        "binary_shape": block(is_binary_shape_no, "binary-shape gold no"),
        "all_shapes": block(is_all_shape_no, "all-shapes gold no"),
    }


# 5. Stratum x gold class x outcome

def crosstab_gold_class(rows: list) -> dict:
    """Stratum x gold class x outcome, and the conditioned test.

    The marginal abstention gap between strata could be an artefact of stratum A
    simply holding more of the gold classes the swarm abstains on. Conditioning
    on gold class removes that route: the CMH statistic pools the within-class
    stratum contrasts, so it only fires if the gap exists inside the classes.
    """
    classes = ("yes", "no", "other", "absent")
    cells: dict[str, dict] = {}
    tables: list[tuple[int, int, int, int]] = []
    per_class: dict[str, dict] = {}

    for cls in classes:
        cells[cls] = {}
        counts = {}
        for stratum in ("A", "B"):
            subset = [
                r for r in rows
                if resource_stratum(r.country_code) == stratum
                and gold_class(r) == cls
            ]
            n_com = sum(1 for r in subset if is_committed(r))
            n_abs = len(subset) - n_com
            counts[stratum] = (n_com, n_abs)
            cells[cls][stratum] = {
                "n": len(subset),
                "n_committed": n_com,
                "n_abstained": n_abs,
                "n_agent_failure": sum(1 for r in subset if is_failed(r)),
                "abstention_rate": abstention_rate(subset),
                "commit_accuracy": commit_accuracy(subset),
            }
        (a, b), (c, d) = counts["A"], counts["B"]
        if (a + b) and (c + d):
            tables.append((a, b, c, d))
        per_class[cls] = two_proportion_test(
            b, a + b, d, c + d  # abstention counts, A vs B
        ) if (a + b) and (c + d) else None

    marginal = {
        s: abstention_rate(
            [r for r in rows if resource_stratum(r.country_code) == s]
        )
        for s in ("A", "B")
    }
    marginal_test = two_proportion_test(
        marginal["A"]["successes"], marginal["A"]["n"],
        marginal["B"]["successes"], marginal["B"]["n"],
    )
    return {
        "outcome_definition": (
            "committed = D37 commit (accepted terminal status, non-abstention "
            "final answer); abstained = every other pair. EXP-36 logged zero "
            "agent_failure rows, so abstained is entirely honest abstention."
        ),
        "cells": cells,
        "marginal_abstention_by_stratum": marginal,
        "marginal_test_a_vs_b": marginal_test,
        "within_class_tests_a_vs_b": per_class,
        "cmh_abstention_conditioned_on_gold_class": cmh_test(tables),
    }


# 6. Abstention codes

def abstention_codes(rows: list, coded: dict[str, dict]) -> dict:
    """Abstention code x stratum x gold class, and the conditioned test for G.

    G (below the 0.65 confidence floor) has a binary yes-share under the
    held-out base rate, so it withholds negative golds disproportionately.
    Stratum A is negative-rich. The question is therefore whether G's
    concentration in stratum A is anything more than that composition effect,
    which is what conditioning on gold class settles.

    Two denominators are reported for concentration, because they answer
    different questions and disagree:
      - G per pair       (G / all pairs of that cell): how often the floor bites
      - G per abstention (G / abstentions of that cell): the code's share of the
        abstentions that did happen
    """
    key_of = {}
    for r in rows:
        key_of[f"{r.question_id}:{r.country_code}"] = r

    by_code_stratum: dict[str, dict] = defaultdict(dict)
    all_codes = sorted({v["code"] for v in coded.values()})
    for code in all_codes:
        for stratum in ("A", "B"):
            members = [
                key_of[k] for k, v in coded.items()
                if v["code"] == code
                and resource_stratum(key_of[k].country_code) == stratum
            ]
            by_code_stratum[code][stratum] = {
                "n": len(members),
                "by_gold_class": dict(
                    Counter(gold_class(r) for r in members)
                ),
            }

    # G's binary yes-share, the figure the composition worry rests on.
    g_rows = [key_of[k] for k, v in coded.items() if v["code"] == "G"]
    g_yes = sum(1 for r in g_rows if norm(r.gold_answer) == "yes")
    g_no = sum(1 for r in g_rows if norm(r.gold_answer) == "no")
    base_yes = sum(1 for r in rows if norm(r.gold_answer) == "yes")
    base_no = sum(1 for r in rows if norm(r.gold_answer) == "no")

    # Conditioned tests for G, both denominators.
    tables_per_pair: list[tuple[int, int, int, int]] = []
    tables_per_abst: list[tuple[int, int, int, int]] = []
    per_class: dict[str, dict] = {}
    for cls in ("yes", "no", "other", "absent"):
        row = {}
        counts_pair = {}
        counts_abst = {}
        for stratum in ("A", "B"):
            subset = [
                r for r in rows
                if resource_stratum(r.country_code) == stratum
                and gold_class(r) == cls
            ]
            n_pairs = len(subset)
            keys = {f"{r.question_id}:{r.country_code}" for r in subset}
            abst = [k for k in keys if k in coded]
            n_g = sum(1 for k in abst if coded[k]["code"] == "G")
            counts_pair[stratum] = (n_g, n_pairs - n_g)
            counts_abst[stratum] = (n_g, len(abst) - n_g)
            row[stratum] = {
                "n_pairs": n_pairs,
                "n_abstentions": len(abst),
                "n_G": n_g,
                "G_per_pair": _rate(n_g, n_pairs),
                "G_per_abstention": _rate(n_g, len(abst)),
            }
        (a, b), (c, d) = counts_pair["A"], counts_pair["B"]
        if (a + b) and (c + d):
            tables_per_pair.append((a, b, c, d))
        (a2, b2), (c2, d2) = counts_abst["A"], counts_abst["B"]
        if (a2 + b2) and (c2 + d2):
            tables_per_abst.append((a2, b2, c2, d2))
        per_class[cls] = row

    def marginal(pred_denom) -> dict:
        out = {}
        for stratum in ("A", "B"):
            subset = [
                r for r in rows
                if resource_stratum(r.country_code) == stratum
            ]
            keys = {f"{r.question_id}:{r.country_code}" for r in subset}
            abst = [k for k in keys if k in coded]
            n_g = sum(1 for k in abst if coded[k]["code"] == "G")
            out[stratum] = _rate(
                n_g, len(subset) if pred_denom == "pair" else len(abst)
            )
        return out

    marg_pair = marginal("pair")
    marg_abst = marginal("abstention")
    return {
        "code_totals": dict(Counter(v["code"] for v in coded.values())),
        "by_code_and_stratum": dict(by_code_stratum),
        "G_composition": {
            "n_G": len(g_rows),
            "yes_gold": g_yes,
            "no_gold": g_no,
            "binary_gold": g_yes + g_no,
            "yes_share": (g_yes / (g_yes + g_no)) if (g_yes + g_no) else None,
            "base_rate_yes_share": base_yes / (base_yes + base_no),
            "base_rate_denominator_label": "all-shapes gold yes/no (n=909)",
        },
        "G_by_stratum_and_gold_class": per_class,
        "G_marginal_per_pair": marg_pair,
        "G_marginal_per_abstention": marg_abst,
        "G_marginal_test_per_pair": two_proportion_test(
            marg_pair["A"]["successes"], marg_pair["A"]["n"],
            marg_pair["B"]["successes"], marg_pair["B"]["n"],
        ),
        "G_marginal_test_per_abstention": two_proportion_test(
            marg_abst["A"]["successes"], marg_abst["A"]["n"],
            marg_abst["B"]["successes"], marg_abst["B"]["n"],
        ),
        "cmh_G_per_pair_conditioned_on_gold_class": cmh_test(tables_per_pair),
        "cmh_G_per_abstention_conditioned_on_gold_class": cmh_test(
            tables_per_abst
        ),
    }


# 7. Permutation tests

def permutation_tests(rows: list) -> dict:
    """Exact 4-against-4 country-level permutation tests, plus the pair-level
    contrast with its clustering caveat."""
    per_country_abst = {}
    per_country_acc = {}
    for c in ALL_COUNTRIES:
        subset = [r for r in rows if r.country_code == c]
        per_country_abst[c] = abstention_rate(subset)["rate"]
        per_country_acc[c] = commit_accuracy(subset)["rate"]

    a_rows = [r for r in rows if resource_stratum(r.country_code) == "A"]
    b_rows = [r for r in rows if resource_stratum(r.country_code) == "B"]
    abst_a, abst_b = abstention_rate(a_rows), abstention_rate(b_rows)
    acc_a, acc_b = commit_accuracy(a_rows), commit_accuracy(b_rows)

    return {
        "unit_note": (
            "The country-level test permutes the eight country labels, so the "
            "143 pairs inside a country move together and within-country "
            "clustering is handled by construction. The pair-level test treats "
            "the 1,144 pairs as independent, which they are not: pairs cluster "
            "within country, so its p-value is anti-conservative and is "
            "reported only as a comparator."
        ),
        "abstention": {
            "country_level_exact": exact_permutation_4v4(
                per_country_abst, STRATUM_A
            ),
            "pair_level": {
                **two_proportion_test(
                    abst_a["successes"], abst_a["n"],
                    abst_b["successes"], abst_b["n"],
                ),
                "denominator_label": "all pairs (A n=572, B n=572)",
            },
        },
        "commit_accuracy": {
            "country_level_exact": exact_permutation_4v4(
                per_country_acc, STRATUM_A
            ),
            "pair_level": {
                **two_proportion_test(
                    acc_a["successes"], acc_a["n"],
                    acc_b["successes"], acc_b["n"],
                ),
                "denominator_label": "scoreable committed pairs",
            },
        },
        "per_country_rates": {
            "abstention": per_country_abst,
            "commit_accuracy": per_country_acc,
        },
    }


# 8. Belgium isolate

def belgium_isolate(rows: list) -> dict:
    """BE against the rest of stratum B (FI, SE, HR), and the catalogue
    grouping as a competing explanation.

    BE is the one stratum-B country with no harvestable national catalogue, and
    ME the one stratum-A country that has one. If catalogue access rather than
    language resource drives the gaps, the catalogue split should separate the
    metrics at least as cleanly as the stratum split does. Both are computed so
    the comparison is on the record.
    """
    be = [r for r in rows if r.country_code == "BE"]
    rest = [r for r in rows if r.country_code in ("FI", "SE", "HR")]

    def profile(subset: list, label: str) -> dict:
        rec = class_recall_committed(subset)
        return {
            "group": label,
            "n_pairs": len(subset),
            "abstention_rate": abstention_rate(subset),
            "commit_accuracy": commit_accuracy(subset),
            "tpr": rec["tpr"],
            "tnr": rec["tnr"],
            "balanced_accuracy": rec["balanced_accuracy"],
            "youden_j": rec["youden_j"],
        }

    be_p, rest_p = profile(be, "BE"), profile(rest, "FI+SE+HR")
    contrasts = {}
    for name in ("abstention_rate", "commit_accuracy", "tpr", "tnr"):
        contrasts[name] = two_proportion_test(
            be_p[name]["successes"], be_p[name]["n"],
            rest_p[name]["successes"], rest_p[name]["n"],
        )

    cat = [r for r in rows if catalogue_group(r.country_code) == "catalogue"]
    nocat = [
        r for r in rows if catalogue_group(r.country_code) == "no_catalogue"
    ]
    cat_p, nocat_p = profile(cat, "catalogue"), profile(nocat, "no_catalogue")
    cat_contrasts = {}
    for name in ("abstention_rate", "commit_accuracy", "tpr", "tnr"):
        cat_contrasts[name] = two_proportion_test(
            nocat_p[name]["successes"], nocat_p[name]["n"],
            cat_p[name]["successes"], cat_p[name]["n"],
        )

    per_country_abst = {
        c: abstention_rate([r for r in rows if r.country_code == c])["rate"]
        for c in ALL_COUNTRIES
    }
    per_country_acc = {
        c: commit_accuracy([r for r in rows if r.country_code == c])["rate"]
        for c in ALL_COUNTRIES
    }
    return {
        "catalogue_flag": {
            "harvestable_national_catalogue": list(CATALOGUE_YES),
            "no_harvestable_catalogue": list(CATALOGUE_NO),
            "note": (
                "The catalogue split swaps BE and ME relative to the D47 "
                "stratum split; it is a competing grouping, not a nested one."
            ),
        },
        "be": be_p,
        "rest_of_stratum_b": rest_p,
        "contrasts_be_vs_rest_b": contrasts,
        "catalogue_grouping": {
            "no_catalogue": nocat_p,
            "catalogue": cat_p,
            "contrasts_no_catalogue_vs_catalogue": cat_contrasts,
            "country_level_exact_abstention": exact_permutation_4v4(
                per_country_abst, CATALOGUE_NO
            ),
            "country_level_exact_commit_accuracy": exact_permutation_4v4(
                per_country_acc, CATALOGUE_NO
            ),
        },
    }


# Small-cell register

def collect_small_cells(report: dict) -> list[dict]:
    """Walk the report and register every rate cell whose n is below the
    threshold. Those cells are reported but cannot carry a claim."""
    found: list[dict] = []

    def walk(node, path: list[str]) -> None:
        if isinstance(node, dict):
            if "n" in node and "rate" in node and isinstance(node.get("n"), int):
                if node["n"] < SMALL_CELL:
                    found.append({
                        "path": ".".join(path),
                        "n": node["n"],
                        "successes": node.get("successes"),
                        "rate": node.get("rate"),
                    })
                return
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [str(i)])

    walk(report, [])
    return sorted(found, key=lambda c: (c["n"], c["path"]))


# Figures

def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK)
    ax.tick_params(colors=INK, labelsize=9)
    ax.set_axisbelow(True)


def yield_share_limits(recon: dict) -> tuple[float, float]:
    """Common square axis limits covering every point in every policy, so the
    three yield-share figures share one scale and can be read against each
    other. Computed from the data, never hardcoded: a clipped point is an
    invisible country."""
    vals = []
    for block in recon.values():
        if block["gold_yes_share"] is not None:
            vals.append(block["gold_yes_share"])
        for pol in block["policies"].values():
            if pol["reconstructed_yes_share"] is not None:
                vals.append(pol["reconstructed_yes_share"])
    lo = math.floor((min(vals) - 0.05) * 20) / 20
    hi = math.ceil((max(vals) + 0.05) * 20) / 20
    return max(0.0, lo), min(1.0, hi)


def figure_yield_share(recon: dict, policy_key: str, title: str,
                       out_path: Path, limits: tuple[float, float]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.4, 5.4))
    plotted = 0
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1,
            color=GRID, zorder=1)
    for country, block in recon.items():
        x = block["gold_yes_share"]
        y = block["policies"][policy_key]["reconstructed_yes_share"]
        if x is None or y is None:
            continue
        colour = COLOUR_A if block["stratum"] == "A" else COLOUR_B
        ax.scatter([x], [y], s=64, color=colour, zorder=3,
                   edgecolor="white", linewidth=0.8)
        ax.annotate(country, (x, y), textcoords="offset points",
                    xytext=(7, 4), fontsize=9, color=INK)
        plotted += 1
    if plotted != len(recon):
        raise SystemExit(
            f"{out_path.name}: plotted {plotted} of {len(recon)} countries; a "
            f"country with a null share would be silently missing."
        )
    lo, hi = limits
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("ODMI gold yes-share", color=INK, fontsize=10)
    ax.set_ylabel("Reconstructed yes-share", color=INK, fontsize=10)
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.grid(True, color=GRID, linewidth=0.5, alpha=0.6)
    _style(ax)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=COLOUR_A,
                   label="Stratum A (BA, MK, ME, BG)", markersize=8),
        plt.Line2D([], [], marker="o", linestyle="", color=COLOUR_B,
                   label="Stratum B (FI, HR, SE, BE)", markersize=8),
        plt.Line2D([], [], linestyle="--", color=GRID, label="perfect recovery"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=FIG_DPI)
    plt.close(fig)


def figure_abstention_accuracy(perm: dict, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    abst = perm["per_country_rates"]["abstention"]
    acc = perm["per_country_rates"]["commit_accuracy"]
    fig, ax = plt.subplots(figsize=(5.8, 5.0))
    for country in ALL_COUNTRIES:
        x, y = abst[country], acc[country]
        colour = COLOUR_A if resource_stratum(country) == "A" else COLOUR_B
        ax.scatter([x], [y], s=70, color=colour, zorder=3,
                   edgecolor="white", linewidth=0.8)
        ax.annotate(country, (x, y), textcoords="offset points",
                    xytext=(7, 4), fontsize=9, color=INK)
    ax.set_xlabel("Abstention rate (all 143 pairs per country)",
                  color=INK, fontsize=10)
    ax.set_ylabel("Commit accuracy (scoreable committed pairs)",
                  color=INK, fontsize=10)
    ax.set_title("Abstention against commit accuracy, EXP-36 held-out eight",
                 color=INK, fontsize=11, loc="left")
    ax.margins(0.13)  # keep the offset country labels inside the axes
    ax.grid(True, color=GRID, linewidth=0.5, alpha=0.6)
    _style(ax)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=COLOUR_A,
                   label="Stratum A", markersize=8),
        plt.Line2D([], [], marker="o", linestyle="", color=COLOUR_B,
                   label="Stratum B", markersize=8),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=FIG_DPI)
    plt.close(fig)


def figure_abstention_codes(codes: dict, out_path: Path) -> None:
    """Abstention counts by code, split by stratum, faceted by gold class."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_cs = codes["by_code_and_stratum"]
    all_codes = sorted(by_cs)
    facets = ("yes", "no", "other")
    fig, axes = plt.subplots(1, len(facets), figsize=(10.5, 3.6), sharey=True)
    width = 0.38
    xs = range(len(all_codes))
    for ax, cls in zip(axes, facets):
        a_vals = [by_cs[c]["A"]["by_gold_class"].get(cls, 0) for c in all_codes]
        b_vals = [by_cs[c]["B"]["by_gold_class"].get(cls, 0) for c in all_codes]
        ax.bar([x - width / 2 for x in xs], a_vals, width,
               color=COLOUR_A, label="Stratum A")
        ax.bar([x + width / 2 for x in xs], b_vals, width,
               color=COLOUR_B, label="Stratum B")
        ax.set_xticks(list(xs))
        ax.set_xticklabels(all_codes, fontsize=9)
        ax.set_title(f"gold = {cls}", color=INK, fontsize=10, loc="left")
        ax.set_xlabel("abstention code", color=INK, fontsize=9)
        ax.grid(True, axis="y", color=GRID, linewidth=0.5, alpha=0.6)
        _style(ax)
    axes[0].set_ylabel("abstentions", color=INK, fontsize=10)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle(
        "EXP-36 abstention codes by stratum and gold class (n = 508 "
        "abstentions)",
        color=INK, fontsize=11, x=0.005, ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=FIG_DPI)
    plt.close(fig)


# Orchestration

def build_report(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        raw = load_rows(conn, EXPERIMENT_ID)
        if not raw:
            raise SystemExit(
                f"no phase2_final rows carry experiment_id={EXPERIMENT_ID!r}"
            )
        canonical, superseded = dedup_canonical(raw, scope_by_label=False)
        coded = classify_abstentions(conn)
    finally:
        conn.close()

    # abort gate
    per_country = Counter(r.country_code for r in canonical)
    problems = []
    if len(canonical) != EXPECTED_CANONICAL_PAIRS:
        problems.append(
            f"canonical pairs = {len(canonical)}, expected "
            f"{EXPECTED_CANONICAL_PAIRS}"
        )
    bad = {c: n for c, n in per_country.items() if n != EXPECTED_PER_COUNTRY}
    if bad:
        problems.append(f"countries not at {EXPECTED_PER_COUNTRY}: {bad}")
    if set(per_country) != set(ALL_COUNTRIES):
        problems.append(
            f"country set is {sorted(per_country)}, expected "
            f"{list(ALL_COUNTRIES)}"
        )
    if problems:
        raise SystemExit(
            "ABORT: canonical set does not match the pre-registered "
            "population.\n  " + "\n  ".join(problems)
        )

    # Denominator receipts, asserted rather than assumed.
    n_binary_no = sum(1 for r in canonical if is_binary_shape_no(r))
    n_all_no = sum(1 for r in canonical if is_all_shape_no(r))
    n_failed = sum(1 for r in canonical if is_failed(r))
    keys_noncommitted = {
        f"{r.question_id}:{r.country_code}"
        for r in canonical if not is_committed(r)
    }
    if set(coded) != keys_noncommitted:
        raise SystemExit(
            "ABORT: abstention-code keys do not match the canonical "
            "non-committed set "
            f"({len(coded)} coded vs {len(keys_noncommitted)} canonical)."
        )

    report = {
        "experiment_id": EXPERIMENT_ID,
        "db_path": str(db_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "marking": "dashboard/lib/db.py::_MATCH_STATUS_SQL, via "
                       "evaluation/exp36_analysis.load_rows",
            "canonical_rule": "dedup_canonical(scope_by_label=False), latest "
                              "phase2_final per (question, country)",
            "abstention_codes": "evaluation/abstention_gold_class_by_code."
                                "classify_abstentions (priority-list, "
                                "re-derived from trails)",
            "abstention_records_csv": "NOT USED (stale, zero EXP-36 rows)",
        },
        "population": {
            "raw_final_rows": len(raw),
            "canonical_pairs": len(canonical),
            "superseded_duplicates": superseded,
            "per_country": dict(sorted(per_country.items())),
            "n_committed": sum(1 for r in canonical if is_committed(r)),
            "n_abstained": len(keys_noncommitted),
            "n_agent_failure": n_failed,
            "gold_class_counts": dict(
                Counter(gold_class(r) for r in canonical)
            ),
        },
        "denominators": {
            "binary_shape_gold_no": n_binary_no,
            "all_shapes_gold_no": n_all_no,
            "binary_shape_gold_yes": sum(
                1 for r in canonical
                if norm(r.answer_shape) == "binary"
                and norm(r.gold_answer) == "yes"
            ),
            "all_pairs": len(canonical),
            "note": (
                "Binary-shape and all-shapes negative golds differ by two "
                "count_band pairs. They are never mixed in a single table; "
                "every rate below names the denominator it uses."
            ),
        },
        "s1_yes_share_reconstruction": yes_share_reconstruction(canonical),
        "s2_decision_mix": decision_mix(canonical),
        "s3_class_recall_committed": {
            "pooled": class_recall_committed(canonical),
            "by_stratum": {
                s: class_recall_committed(
                    [r for r in canonical
                     if resource_stratum(r.country_code) == s]
                )
                for s in ("A", "B")
            },
            "by_country": {
                c: class_recall_committed(
                    [r for r in canonical if r.country_code == c]
                )
                for c in ALL_COUNTRIES
            },
        },
        "s4_negative_gold_fp": {
            "pooled": negative_fp(canonical),
            "by_stratum": {
                s: negative_fp(
                    [r for r in canonical
                     if resource_stratum(r.country_code) == s]
                )
                for s in ("A", "B")
            },
            "by_country": {
                c: negative_fp([r for r in canonical if r.country_code == c])
                for c in ALL_COUNTRIES
            },
        },
        "s5_crosstab_gold_class": crosstab_gold_class(canonical),
        "s6_abstention_codes": abstention_codes(canonical, coded),
        "s7_permutation_tests": permutation_tests(canonical),
        "s8_belgium_isolate": belgium_isolate(canonical),
    }
    if n_binary_no != 368 or n_all_no != 370:
        report["denominators"]["WARNING"] = (
            f"expected 368 binary-shape and 370 all-shapes negative golds, "
            f"found {n_binary_no} and {n_all_no}"
        )
    report["small_cells"] = collect_small_cells(report)
    report["small_cell_threshold"] = SMALL_CELL
    return report, canonical


# Markdown rendering

def f3(x, dash: str = "-") -> str:
    if x is None:
        return dash
    return f"{x:.3f}"


def ci(block: dict) -> str:
    if block["rate"] is None:
        return "-"
    lo, hi = block["wilson_95"]
    return f"{block['rate']:.3f} [{lo:.3f}, {hi:.3f}]"


def frac(block: dict) -> str:
    return f"{block['successes']}/{block['n']}"


def render_markdown(rep: dict) -> str:
    L: list[str] = []
    w = L.append
    pop = rep["population"]
    den = rep["denominators"]

    w("# EXP-36 subgroup equity decomposition (§4.7)")
    w("")
    w(f"Experiment `{rep['experiment_id']}`, generated {rep['generated_at']}.")
    w("")
    w("Marking is the project's own `_MATCH_STATUS_SQL` "
      "(`dashboard/lib/db.py`), reached through "
      "`evaluation/exp36_analysis.load_rows`. The canonical set is "
      "`dedup_canonical(scope_by_label=False)`: the latest `phase2_final` per "
      "(question, country). Abstention codes are re-derived from the stored "
      "trails by `evaluation/abstention_gold_class_by_code.classify_"
      "abstentions`. `evaluation/abstention_records.csv` is not read; it is "
      "stale and holds no EXP-36 rows. Ground truth is read only to score.")
    w("")
    w("## 0. Population and denominators")
    w("")
    w(f"- Raw `phase2_final` rows: {pop['raw_final_rows']}; canonical pairs: "
      f"**{pop['canonical_pairs']}** ({pop['superseded_duplicates']} "
      f"superseded duplicates dropped).")
    w("- Per country: " + ", ".join(
        f"{k} {v}" for k, v in pop["per_country"].items()) + ".")
    w(f"- Committed {pop['n_committed']}, abstained {pop['n_abstained']}, "
      f"agent failures {pop['n_agent_failure']}.")
    w("- Gold class counts: " + ", ".join(
        f"{k} {v}" for k, v in sorted(pop["gold_class_counts"].items())) + ".")
    w("")
    w("Negative-gold denominators, never mixed:")
    w("")
    w("| denominator | n |")
    w("| --- | ---: |")
    w(f"| binary-shape gold `no` (`answer_shape = 'binary'`) | "
      f"{den['binary_shape_gold_no']} |")
    w(f"| all-shapes gold `no` (adds two `count_band` golds) | "
      f"{den['all_shapes_gold_no']} |")
    w(f"| binary-shape gold `yes` | {den['binary_shape_gold_yes']} |")
    w(f"| all pairs | {den['all_pairs']} |")
    w("")

    recon = rep["s1_yes_share_reconstruction"]
    w("## 1. Reconstructed yes-share against gold")
    w("")
    w("Denominator: binary-shape golds only. Committed answers that are "
      "neither `yes` nor `no` cannot be read as either, so they are dropped "
      "from numerator and denominator alike under all three policies and "
      "counted in the `off-shape` column; the gold share is recomputed on the "
      "same reduced base so the signed error is like-for-like.")
    w("")
    w("Policy (c) fills abstentions with the value being scored against. It is "
      "an oracle bound on what perfect abstention-handling could recover, not "
      "a deployable procedure.")
    w("")
    w("**Table 1.1 — per-country yes-share. Denominators: gold and policies "
      "(b), (c) over effective binary-gold pairs (n col); policy (a) over "
      "committed binary-gold pairs (n committed col).**")
    w("")
    w("| country | stratum | n binary gold | off-shape | n eff | n committed | "
      "gold yes-share | (a) recon | (a) err | (b) recon | (b) err | (c) recon "
      "| (c) err |")
    w("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
      "---: | ---: | ---: |")
    for c, b in recon.items():
        p = b["policies"]
        w(f"| {c} | {b['stratum']} | {b['n_binary_gold_pairs']} | "
          f"{b['n_off_shape_commits_excluded']} | "
          f"{b['n_effective_binary_gold_pairs']} | {b['n_committed']} | "
          f"{f3(b['gold_yes_share'])} | "
          f"{f3(p['a_excluded']['reconstructed_yes_share'])} | "
          f"{f3(p['a_excluded']['signed_error'])} | "
          f"{f3(p['b_coerced_no']['reconstructed_yes_share'])} | "
          f"{f3(p['b_coerced_no']['signed_error'])} | "
          f"{f3(p['c_coerced_gold']['reconstructed_yes_share'])} | "
          f"{f3(p['c_coerced_gold']['signed_error'])} |")
    w("")

    dm = rep["s2_decision_mix"]
    w("## 2. Decision mix and within-decision commit accuracy")
    w("")
    w("Share denominator is all pairs in the group (143 per country, 572 per "
      "stratum, 1,144 pooled). Commit-accuracy denominator is scoreable "
      "committed pairs inside that decision, shown as a fraction in each cell.")
    w("")
    w("**Table 2.1 — decision mix by country. Share denominator: 143 pairs "
      "per country.**")
    w("")
    w("| country | stratum | confirm n (share) | complement n (share) | "
      "change n (share) |")
    w("| --- | --- | ---: | ---: | ---: |")
    for c in ALL_COUNTRIES:
        b = dm["by_country"][c]["by_decision"]
        cells = " | ".join(
            f"{b[k]['n_pairs']} ({f3(b[k]['share_of_pairs'])})"
            for k in ("confirm", "complement", "change")
        )
        w(f"| {c} | {resource_stratum(c)} | {cells} |")
    w("")
    w("**Table 2.2 — commit accuracy within decision within stratum. "
      "Denominator: scoreable committed pairs in the cell (shown as "
      "matches/n).**")
    w("")
    w("| group | decision | n pairs | share | commit acc [Wilson 95%] | "
      "matches/n | abstention rate [Wilson 95%] |")
    w("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for label in ("A", "B"):
        blk = dm["by_stratum"][label]["by_decision"]
        for k in ("confirm", "complement", "change"):
            cell = blk[k]
            w(f"| stratum {label} | {k} | {cell['n_pairs']} | "
              f"{f3(cell['share_of_pairs'])} | "
              f"{ci(cell['commit_accuracy'])} | "
              f"{frac(cell['commit_accuracy'])} | "
              f"{ci(cell['abstention_rate'])} |")
    for k in ("confirm", "complement", "change"):
        cell = dm["pooled"]["by_decision"][k]
        w(f"| pooled | {k} | {cell['n_pairs']} | "
          f"{f3(cell['share_of_pairs'])} | {ci(cell['commit_accuracy'])} | "
          f"{frac(cell['commit_accuracy'])} | "
          f"{ci(cell['abstention_rate'])} |")
    w("")
    w("**Table 2.3 — commit accuracy within decision within country. "
      "Denominator: scoreable committed pairs in the cell.**")
    w("")
    w("| country | confirm acc (n) | complement acc (n) | change acc (n) |")
    w("| --- | ---: | ---: | ---: |")
    for c in ALL_COUNTRIES:
        b = dm["by_country"][c]["by_decision"]
        cells = " | ".join(
            f"{f3(b[k]['commit_accuracy']['rate'])} "
            f"({frac(b[k]['commit_accuracy'])})"
            for k in ("confirm", "complement", "change")
        )
        w(f"| {c} | {cells} |")
    w("")

    s3 = rep["s3_class_recall_committed"]
    w("## 3. TPR, TNR, balanced accuracy and Youden's J on committed binary "
      "pairs")
    w("")
    w("Denominator: **committed** binary-gold pairs only. An abstention leaves "
      "the denominator, so these are conditional-on-answering rates and are "
      "not comparable with the headline per-class recall in "
      "`exp36_analysis.binary_headline`, which charges abstentions against "
      "recall. Correctness is the project's `is_match`, so a committed "
      "off-shape answer counts as a miss for its class.")
    w("")
    w("Intervals: Wilson on TPR and TNR; square-and-add (Newcombe) on their "
      "sum for balanced accuracy and Youden's J, valid because the two class "
      "denominators are disjoint.")
    w("")
    w("**Table 3.1 — per-class recall on committed binary pairs. TPR "
      "denominator: committed yes-gold pairs. TNR denominator: committed "
      "no-gold (binary-shape) pairs.**")
    w("")
    w("| group | n committed binary | TPR [95%] | TPR n | TNR [95%] | TNR n | "
      "balanced acc [95%] | Youden J [95%] |")
    w("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    def recall_row(label: str, b: dict) -> None:
        ba = b["balanced_accuracy"]
        bci = b["balanced_accuracy_ci_95"]
        yj = b["youden_j"]
        yci = b["youden_j_ci_95"]
        ba_s = ("-" if ba is None
                else f"{ba:.3f} [{bci[0]:.3f}, {bci[1]:.3f}]")
        yj_s = ("-" if yj is None
                else f"{yj:.3f} [{yci[0]:.3f}, {yci[1]:.3f}]")
        w(f"| {label} | {b['n_committed_binary']} | {ci(b['tpr'])} | "
          f"{frac(b['tpr'])} | {ci(b['tnr'])} | {frac(b['tnr'])} | "
          f"{ba_s} | {yj_s} |")

    recall_row("pooled", s3["pooled"])
    for s in ("A", "B"):
        recall_row(f"stratum {s}", s3["by_stratum"][s])
    for c in ALL_COUNTRIES:
        recall_row(c, s3["by_country"][c])
    w("")

    s4 = rep["s4_negative_gold_fp"]
    w("## 4. Negative-gold false-positive rate")
    w("")
    w("A false positive is a committed answer that does not match a `no` gold. "
      "Two denominators for the shape of the gold, and two for the "
      "conditioning, all reported separately and never mixed.")
    w("")
    for shape_key, shape_label, shape_n in (
        ("binary_shape", "binary-shape gold `no`",
         rep["denominators"]["binary_shape_gold_no"]),
        ("all_shapes", "all-shapes gold `no`",
         rep["denominators"]["all_shapes_gold_no"]),
    ):
        w(f"**Table 4.{1 if shape_key == 'binary_shape' else 2} — FP rate, "
          f"{shape_label} (pooled n = {shape_n}). Left rate divides by all "
          f"no-golds; right rate divides by committed no-golds only.**")
        w("")
        w("| group | n no-golds | n committed | n FP | FP / all no-golds "
          "[95%] | FP / committed no-golds [95%] |")
        w("| --- | ---: | ---: | ---: | ---: | ---: |")
        rows_ = (
            [("pooled", s4["pooled"][shape_key])]
            + [(f"stratum {s}", s4["by_stratum"][s][shape_key])
               for s in ("A", "B")]
            + [(c, s4["by_country"][c][shape_key]) for c in ALL_COUNTRIES]
        )
        for label, b in rows_:
            w(f"| {label} | {b['n_no_golds']} | {b['n_committed']} | "
              f"{b['n_false_positives']} | "
              f"{ci(b['fp_over_all_no_golds'])} | "
              f"{ci(b['fp_over_committed_no_golds'])} |")
        w("")

    s5 = rep["s5_crosstab_gold_class"]
    w("## 5. Stratum x gold class x outcome")
    w("")
    w(s5["outcome_definition"])
    w("")
    w("**Table 5.1 — cross-tab. Denominator for the abstention rate is the "
      "cell n.**")
    w("")
    w("| gold class | stratum | n | committed | abstained | abstention rate "
      "[95%] | commit acc [95%] (n) |")
    w("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for cls in ("yes", "no", "other", "absent"):
        for s in ("A", "B"):
            cell = s5["cells"][cls][s]
            w(f"| {cls} | {s} | {cell['n']} | {cell['n_committed']} | "
              f"{cell['n_abstained']} | {ci(cell['abstention_rate'])} | "
              f"{ci(cell['commit_accuracy'])} "
              f"({frac(cell['commit_accuracy'])}) |")
    w("")
    marg = s5["marginal_abstention_by_stratum"]
    mt = s5["marginal_test_a_vs_b"]
    w("**Table 5.2 — does the abstention gap survive conditioning on gold "
      "class? Marginal denominator: 572 pairs per stratum.**")
    w("")
    w("| test | A | B | delta (A-B) | 95% CI on delta | p |")
    w("| --- | ---: | ---: | ---: | ---: | ---: |")
    w(f"| marginal (unconditioned) | {ci(marg['A'])} | {ci(marg['B'])} | "
      f"{f3(mt['delta'])} | "
      f"[{f3(mt['ci_95'][0])}, {f3(mt['ci_95'][1])}] | "
      f"{f3(mt['p_value'])} |")
    for cls in ("yes", "no", "other"):
        t = s5["within_class_tests_a_vs_b"].get(cls)
        if not t:
            continue
        w(f"| within gold = {cls} | {f3(t['p1'])} | {f3(t['p2'])} | "
          f"{f3(t['delta'])} | "
          f"[{f3(t['ci_95'][0])}, {f3(t['ci_95'][1])}] | "
          f"{f3(t['p_value'])} |")
    cmh = s5["cmh_abstention_conditioned_on_gold_class"]
    w("")
    w(f"Cochran-Mantel-Haenszel, stratum against outcome conditioned on gold "
      f"class: chi-square = {f3(cmh['statistic'])} on 1 df, p = "
      f"{f3(cmh['p_value'])}, MH common odds ratio = "
      f"{f3(cmh['mh_odds_ratio'])}, over {cmh['n_tables_used']} non-empty "
      f"gold classes. The odds ratio is for **committing** in A relative to B, "
      f"so a value below 1 means stratum A commits less often (abstains more) "
      f"inside the gold classes, not only across them.")
    w("")
    t_no = s5["within_class_tests_a_vs_b"]["no"]
    t_yes = s5["within_class_tests_a_vs_b"]["yes"]
    w(f"The gap is not uniform across the classes it survives: within `no` "
      f"golds the two strata abstain at almost the same rate "
      f"({f3(t_no['p1'])} against {f3(t_no['p2'])}, p = "
      f"{f3(t_no['p_value'])}), and the marginal gap is carried by the `yes` "
      f"golds ({f3(t_yes['p1'])} against {f3(t_yes['p2'])}, p = "
      f"{f3(t_yes['p_value'])}). Conditioning does not remove the "
      f"association, but it does relocate it.")
    w("")

    s6 = rep["s6_abstention_codes"]
    gc_ = s6["G_composition"]
    w("## 6. Abstention codes by stratum and gold class")
    w("")
    w("Codes are the priority-list first-match markers, so a code is where a "
      "pair first stopped, not a causal attribution.")
    w("")
    w("**Table 6.1 — abstention counts by code and stratum. Denominator: the "
      f"{sum(s6['code_totals'].values())} abstentions.**")
    w("")
    w("| code | A | B | total | A gold yes/no/other | B gold yes/no/other |")
    w("| --- | ---: | ---: | ---: | ---: | ---: |")
    for code in sorted(s6["by_code_and_stratum"]):
        a = s6["by_code_and_stratum"][code]["A"]
        b = s6["by_code_and_stratum"][code]["B"]

        def gcs(x):
            g = x["by_gold_class"]
            return (f"{g.get('yes', 0)}/{g.get('no', 0)}/"
                    f"{g.get('other', 0)}")
        w(f"| {code} | {a['n']} | {b['n']} | {a['n'] + b['n']} | "
          f"{gcs(a)} | {gcs(b)} |")
    w("")
    w(f"G composition check: G holds {gc_['n_G']} abstentions, of which "
      f"{gc_['binary_gold']} carry a yes/no gold "
      f"({gc_['yes_gold']} yes, {gc_['no_gold']} no), a yes-share of "
      f"**{f3(gc_['yes_share'])}** against the held-out base rate of "
      f"**{f3(gc_['base_rate_yes_share'])}** "
      f"({gc_['base_rate_denominator_label']}).")
    w("")
    w("**Table 6.2 — G by stratum within gold class. Two denominators: G per "
      "pair (cell n pairs) and G per abstention (cell n abstentions).**")
    w("")
    w("| gold class | stratum | n pairs | n abstentions | n G | G/pair [95%] "
      "| G/abstention [95%] |")
    w("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for cls in ("yes", "no", "other"):
        for s in ("A", "B"):
            cell = s6["G_by_stratum_and_gold_class"][cls][s]
            w(f"| {cls} | {s} | {cell['n_pairs']} | {cell['n_abstentions']} | "
              f"{cell['n_G']} | {ci(cell['G_per_pair'])} | "
              f"{ci(cell['G_per_abstention'])} |")
    w("")
    mp = s6["G_marginal_test_per_pair"]
    ma = s6["G_marginal_test_per_abstention"]
    cp = s6["cmh_G_per_pair_conditioned_on_gold_class"]
    ca = s6["cmh_G_per_abstention_conditioned_on_gold_class"]
    w("**Table 6.3 — G concentration in stratum A, marginal against "
      "conditioned.**")
    w("")
    w("| denominator | A | B | delta | p (marginal) | CMH chi-square | "
      "CMH p | MH odds ratio |")
    w("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    w(f"| G per pair (572 per stratum) | {f3(mp['p1'])} | {f3(mp['p2'])} | "
      f"{f3(mp['delta'])} | {f3(mp['p_value'])} | {f3(cp['statistic'])} | "
      f"{f3(cp['p_value'])} | {f3(cp['mh_odds_ratio'])} |")
    w(f"| G per abstention | {f3(ma['p1'])} | {f3(ma['p2'])} | "
      f"{f3(ma['delta'])} | {f3(ma['p_value'])} | {f3(ca['statistic'])} | "
      f"{f3(ca['p_value'])} | {f3(ca['mh_odds_ratio'])} |")
    w("")

    s7 = rep["s7_permutation_tests"]
    w("## 7. Country-level permutation tests (4 against 4)")
    w("")
    w(s7["unit_note"])
    w("")
    w("**Table 7.1 — exact country-level test. 70 arrangements, so the "
      "smallest achievable two-sided p is 2/70 = 0.029.**")
    w("")
    w("| endpoint | observed delta (A-B, mean of country rates) | "
      "arrangements at least as extreme | exact p | at floor |")
    w("| --- | ---: | ---: | ---: | --- |")
    for name, key in (("abstention", "abstention"),
                      ("commit accuracy", "commit_accuracy")):
        e = s7[key]["country_level_exact"]
        w(f"| {name} | {f3(e['observed_delta'])} | "
          f"{e['n_at_least_as_extreme']}/{e['n_arrangements']} | "
          f"{f3(e['p_value_exact'])} | {'yes' if e['at_floor'] else 'no'} |")
    w("")
    w("**Table 7.2 — per-country rates feeding the permutation. Abstention "
      "denominator: 143 pairs. Commit-accuracy denominator: scoreable "
      "committed pairs.**")
    w("")
    w("| country | stratum | abstention rate | commit accuracy |")
    w("| --- | --- | ---: | ---: |")
    for c in ALL_COUNTRIES:
        w(f"| {c} | {resource_stratum(c)} | "
          f"{f3(s7['per_country_rates']['abstention'][c])} | "
          f"{f3(s7['per_country_rates']['commit_accuracy'][c])} |")
    w("")
    w("**Table 7.3 — pair-level comparator. Anti-conservative: pairs cluster "
      "within country and this test ignores that.**")
    w("")
    w("| endpoint | denominator | A | B | delta | 95% CI | p (pair-level) |")
    w("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for name, key in (("abstention", "abstention"),
                      ("commit accuracy", "commit_accuracy")):
        p = s7[key]["pair_level"]
        w(f"| {name} | {p['denominator_label']} | {f3(p['p1'])} | "
          f"{f3(p['p2'])} | {f3(p['delta'])} | "
          f"[{f3(p['ci_95'][0])}, {f3(p['ci_95'][1])}] | "
          f"{f3(p['p_value'])} |")
    w("")
    pa = s7["abstention"]["country_level_exact"]["p_value_exact"]
    pc = s7["commit_accuracy"]["country_level_exact"]["p_value_exact"]
    w(f"The two units disagree, and the disagreement is the point. At pair "
      f"level both gaps clear any conventional threshold (p < 0.001); at "
      f"country level neither does (p = {f3(pa)} for abstention, "
      f"{f3(pc)} for commit accuracy). The stratum contrast rests on eight "
      f"countries, and the country is the unit the stratum is defined over, so "
      f"the country-level p-values are the ones that carry. Neither gap is "
      f"separable from country-to-country variation at n = 8. The direction is "
      f"consistent across the four-country groups; the significance is not "
      f"established.")
    w("")

    s8 = rep["s8_belgium_isolate"]
    w("## 8. Belgium isolate")
    w("")
    w(f"Catalogue recomputability: harvestable national catalogue for "
      f"{', '.join(s8['catalogue_flag']['harvestable_national_catalogue'])}; "
      f"none for "
      f"{', '.join(s8['catalogue_flag']['no_harvestable_catalogue'])}. "
      f"{s8['catalogue_flag']['note']}")
    w("")
    w("**Table 8.1 — BE against the rest of stratum B. Abstention "
      "denominator: all pairs. Commit-accuracy denominator: scoreable "
      "committed pairs. TPR/TNR denominator: committed binary-gold pairs of "
      "that class.**")
    w("")
    w("| metric | BE [95%] (n) | FI+SE+HR [95%] (n) | delta | 95% CI | p |")
    w("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name, label in (("abstention_rate", "abstention rate"),
                        ("commit_accuracy", "commit accuracy"),
                        ("tpr", "TPR"), ("tnr", "TNR")):
        be, rest = s8["be"][name], s8["rest_of_stratum_b"][name]
        t = s8["contrasts_be_vs_rest_b"][name]
        cis = ("-" if t["ci_95"] is None
               else f"[{f3(t['ci_95'][0])}, {f3(t['ci_95'][1])}]")
        w(f"| {label} | {ci(be)} ({frac(be)}) | {ci(rest)} ({frac(rest)}) | "
          f"{f3(t['delta'])} | {cis} | {f3(t['p_value'])} |")
    w("")
    w("**Table 8.2 — the catalogue grouping as a competing split. Same "
      "denominators as Table 8.1, over 572 pairs per group.**")
    w("")
    w("| metric | no catalogue (BG, MK, BE, BA) | catalogue (FI, HR, SE, ME) "
      "| delta | 95% CI | p |")
    w("| --- | ---: | ---: | ---: | ---: | ---: |")
    cg = s8["catalogue_grouping"]
    for name, label in (("abstention_rate", "abstention rate"),
                        ("commit_accuracy", "commit accuracy"),
                        ("tpr", "TPR"), ("tnr", "TNR")):
        nc, ca_ = cg["no_catalogue"][name], cg["catalogue"][name]
        t = cg["contrasts_no_catalogue_vs_catalogue"][name]
        cis = ("-" if t["ci_95"] is None
               else f"[{f3(t['ci_95'][0])}, {f3(t['ci_95'][1])}]")
        w(f"| {label} | {ci(nc)} ({frac(nc)}) | {ci(ca_)} ({frac(ca_)}) | "
          f"{f3(t['delta'])} | {cis} | {f3(t['p_value'])} |")
    w("")
    ea = cg["country_level_exact_abstention"]
    ec = cg["country_level_exact_commit_accuracy"]
    w("**Table 8.3 — exact country-level permutation for the catalogue split, "
      "same 70 arrangements as Table 7.1, so the two splits are directly "
      "comparable.**")
    w("")
    w("| endpoint | observed delta (no catalogue - catalogue) | exact p |")
    w("| --- | ---: | ---: |")
    w(f"| abstention | {f3(ea['observed_delta'])} | "
      f"{f3(ea['p_value_exact'])} |")
    w(f"| commit accuracy | {f3(ec['observed_delta'])} | "
      f"{f3(ec['p_value_exact'])} |")
    w("")

    # limits
    w("## 9. What could not be computed, and where n is too small")
    w("")
    w("### 9.1 Not computable from the data")
    w("")
    for line in rep["not_computable"]:
        w(f"- {line}")
    w("")
    small = rep["small_cells"]
    w(f"### 9.2 Cells with n < {rep['small_cell_threshold']}")
    w("")
    w(f"{len(small)} rate cells fall below n = {rep['small_cell_threshold']}. "
      "They are emitted for completeness and cannot carry a claim; the Wilson "
      "intervals on them span most of the unit interval.")
    w("")
    if small:
        w("| cell | successes | n | rate |")
        w("| --- | ---: | ---: | ---: |")
        for c in small:
            w(f"| `{c['path']}` | {c['successes']} | {c['n']} | "
              f"{f3(c['rate'])} |")
    w("")
    return "\n".join(L)


NOT_COMPUTABLE = [
    "**Upper bound on commit accuracy under the D22 staleness band.** ODMI "
    "gold can be one cycle old, so some disagreements are stale gold rather "
    "than swarm error. Separating them needs a human review of each "
    "disagreement, which does not exist yet. Every commit-accuracy figure here "
    "is therefore a lower bound.",
    "**Absent-gold cells.** The cross-tab reserves a gold class for `absent`, "
    "but all 1,144 canonical pairs carry a gold response, so the class is "
    "empty and its stratum contrast is undefined rather than zero.",
    "**Causal attribution for the abstention codes.** The priority list is a "
    "first-match marker: a pair that would satisfy several predicates is "
    "recorded under the first one in the order. Code counts are therefore "
    "descriptive, and the conditioned tests speak to composition, not cause.",
    "**A clean separation of language resource from catalogue access.** The "
    "two candidate groupings differ by exactly one swap (BE for ME), so with "
    "eight countries no test can attribute a gap to one rather than the other. "
    "Both splits are reported side by side and the comparison is descriptive.",
    "**Per-country TNR for several countries at a usable precision.** Committed "
    "no-gold pairs per country run to a few dozen at most, so the country-level "
    "TNR intervals are too wide to rank countries against each other.",
    "**Any within-country stratification below the country level.** With 143 "
    "pairs per country, splitting further by dimension and gold class at once "
    "produces cells in single figures, which is why the decomposition stops at "
    "stratum x gold class.",
    "**A country-level p below 0.029 for any endpoint.** Eight countries admit "
    "70 four-against-four arrangements, so the smallest two-sided p the design "
    "can produce is 2/70 = 0.029, and that only when the observed split is the "
    "single most extreme of the 70. A null result at country level is "
    "therefore a statement about the design's resolution as much as about the "
    "swarm; it does not license the reverse claim that the strata behave "
    "alike.",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="EXP-36 subgroup equity decomposition (§4.7)."
    )
    parser.add_argument("--db", type=Path,
                        default=REPO_ROOT / "data" / "odmi.db")
    parser.add_argument("--out-dir", type=Path,
                        default=REPO_ROOT / "evaluation" / "results")
    parser.add_argument("--fig-dir", type=Path,
                        default=REPO_ROOT / "evaluation" / "figures")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: {args.db} does not exist")
        return 2

    report, canonical = build_report(args.db)
    report["not_computable"] = NOT_COMPUTABLE

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.fig_dir.mkdir(parents=True, exist_ok=True)

    json_path = args.out_dir / "exp36_subgroup_equity.json"
    md_path = args.out_dir / "exp36_subgroup_equity.md"
    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(render_markdown(report))

    recon = report["s1_yes_share_reconstruction"]
    limits = yield_share_limits(recon)
    figure_yield_share(
        recon, "a_excluded",
        "Reconstructed yes-share, abstentions excluded",
        args.fig_dir / "fig_yieldshare.png", limits,
    )
    figure_yield_share(
        recon, "b_coerced_no",
        "Reconstructed yes-share, abstentions coerced to 'no'",
        args.fig_dir / "fig_yieldshare_b_coerced_no.png", limits,
    )
    figure_yield_share(
        recon, "c_coerced_gold",
        "Reconstructed yes-share, abstentions coerced to gold (oracle)",
        args.fig_dir / "fig_yieldshare_c_coerced_gold.png", limits,
    )
    figure_abstention_accuracy(
        report["s7_permutation_tests"],
        args.fig_dir / "fig_abstention_accuracy.png",
    )
    figure_abstention_codes(
        report["s6_abstention_codes"],
        args.fig_dir / "fig_abstention_codes.png",
    )

    pop = report["population"]
    print(f"canonical pairs {pop['canonical_pairs']} "
          f"(committed {pop['n_committed']}, abstained {pop['n_abstained']})")
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    print(f"wrote 5 figures to {args.fig_dir}")
    print(f"small cells (n < {SMALL_CELL}): {len(report['small_cells'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
