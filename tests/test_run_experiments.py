"""Unit tests for the experiment orchestrator's preflight and command builder.

These pin the guardrails that make a run trustworthy: the D47 hold-out, the
one-variable rule, the mandatory budget, and the forced cache discipline. Pure
functions only, no DB or dispatch.
"""

from __future__ import annotations

import pytest

from scripts.run_experiments import (
    build_command,
    expand_pairs,
    preflight,
    remaining_pairs,
    unregistered_in_spec,
)


def _valid_spec():
    return {
        "run_id": "t",
        "global_parallel": 8,
        "budget_calls": 1000,
        "experiments": [
            {
                "experiment_id": "x",
                "type": "retrieval",
                "questions": ["I12", "I17"],
                "countries": ["NL"],
                "baseline_knobs": {"max_results_per_query": 5},
                "arms": [
                    {"condition_label": "baseline", "knobs": {}},
                    {"condition_label": "breadth_8", "knobs": {"max_results_per_query": 8}},
                ],
            }
        ],
    }


def test_valid_spec_passes():
    assert preflight(_valid_spec()) == []


def test_held_out_country_blocks():
    spec = _valid_spec()
    spec["experiments"][0]["countries"] = ["NL", "SE"]
    errors = preflight(spec)
    assert any("held-out" in e and "SE" in e for e in errors)


@pytest.mark.parametrize("cc", ["BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"])
def test_every_held_out_country_blocks(cc):
    spec = _valid_spec()
    spec["experiments"][0]["countries"] = [cc]
    assert any("held-out" in e for e in preflight(spec))


def test_two_variables_blocks():
    spec = _valid_spec()
    spec["experiments"][0]["arms"][1]["knobs"] = {
        "max_results_per_query": 8, "num_queries": 4
    }
    assert any("more than one variable" in e for e in preflight(spec))


def test_missing_budget_blocks():
    spec = _valid_spec()
    spec["budget_calls"] = None
    assert any("budget" in e for e in preflight(spec))


def test_duplicate_condition_label_blocks():
    spec = _valid_spec()
    spec["experiments"][0]["arms"][1]["condition_label"] = "baseline"
    assert any("unique 'condition_label'" in e for e in preflight(spec))


def test_bad_type_blocks():
    spec = _valid_spec()
    spec["experiments"][0]["type"] = "vibes"
    assert any("'type' must be" in e for e in preflight(spec))


def test_unknown_country_flagged():
    spec = _valid_spec()
    spec["experiments"][0]["countries"] = ["ES"]  # neither dev nor held-out
    assert any("neither dev nor held-out" in e for e in preflight(spec))


def test_expand_pairs_cross_product():
    exp = {"experiment_id": "x", "questions": ["A", "B"], "countries": ["NL", "AL"]}
    assert set(expand_pairs(exp)) == {"A:NL", "B:NL", "A:AL", "B:AL"}


def test_expand_pairs_explicit():
    exp = {"pairs": ["A:NL", "B:AL"]}
    assert expand_pairs(exp) == ["A:NL", "B:AL"]


def test_build_command_forces_no_cache_for_retrieval():
    exp = {"experiment_id": "x", "type": "retrieval", "baseline_knobs": {}}
    arm = {"condition_label": "c", "knobs": {}}
    cmd = build_command(exp, arm, ["A:NL"], 8)
    assert "--no-cache" in cmd
    assert "--experiment-id" in cmd and "x" in cmd
    assert "--condition-label" in cmd and "c" in cmd


def test_build_command_forces_no_cache_for_cost():
    exp = {"experiment_id": "x", "type": "cost", "baseline_knobs": {}}
    arm = {"condition_label": "c", "knobs": {}}
    assert "--no-cache" in build_command(exp, arm, ["A:NL"], 8)


def test_build_command_accuracy_may_keep_cache():
    exp = {"experiment_id": "x", "type": "accuracy", "baseline_knobs": {}}
    arm = {"condition_label": "c", "knobs": {}}
    assert "--no-cache" not in build_command(exp, arm, ["A:NL"], 8)


def test_unregistered_experiment_blocks():
    # R1: an experiment must be pre-registered in the `experiments` table
    # before it may run. An unknown id is a hard error.
    spec = _valid_spec()  # experiment_id "x"
    errors = unregistered_in_spec(spec, registered={"other"})
    assert any("not pre-registered" in e and "x" in e for e in errors)


def test_registered_experiment_passes():
    spec = _valid_spec()
    assert unregistered_in_spec(spec, registered={"x"}) == []


def test_remaining_pairs_skips_finalised_preserving_order():
    pairs = ["A:NL", "B:NL", "C:NL", "D:NL"]
    done = {"B:NL", "D:NL"}
    assert remaining_pairs(pairs, done) == ["A:NL", "C:NL"]


def _headline_spec(country="FI"):
    return {
        "run_id": "t", "global_parallel": 1, "budget_calls": 100, "headline": True,
        "experiments": [{
            "experiment_id": "exp_h", "type": "accuracy", "questions": ["I12"],
            "countries": [country], "baseline_knobs": {},
            "arms": [{"condition_label": country, "knobs": {}}],
        }],
    }


def test_headline_cache_guard_blocks_dirty_db(monkeypatch):
    import scripts.purge_heldout_cache as ph
    monkeypatch.setattr(ph, "scan",
                        lambda conn: {"fetch": ["u1"], "serp": [], "snippet": ["s1"]})
    errors = preflight(_headline_spec("FI"))
    assert any("held-out cache" in e for e in errors), errors


def test_headline_cache_guard_passes_clean_db(monkeypatch):
    import scripts.purge_heldout_cache as ph
    monkeypatch.setattr(ph, "scan",
                        lambda conn: {"fetch": [], "serp": [], "snippet": []})
    errors = preflight(_headline_spec("FI"))
    assert not any("held-out cache" in e for e in errors), errors


def test_non_headline_spec_skips_cache_guard(monkeypatch):
    """A dev spec must not trigger the (slow) cache scan at all."""
    import scripts.purge_heldout_cache as ph

    def _boom(conn):
        raise AssertionError("cache scan must not run for a non-headline spec")

    monkeypatch.setattr(ph, "scan", _boom)
    spec = _valid_spec()  # no headline flag
    assert preflight(spec) == []


def test_remaining_pairs_none_done_is_identity():
    pairs = ["A:NL", "B:NL"]
    assert remaining_pairs(pairs, set()) == pairs


def test_remaining_pairs_all_done_is_empty():
    pairs = ["A:NL", "B:NL"]
    assert remaining_pairs(pairs, {"A:NL", "B:NL"}) == []


def test_build_command_threads_knobs():
    exp = {
        "experiment_id": "x", "type": "accuracy",
        "baseline_knobs": {"provider": "diy", "max_results_per_query": 5},
    }
    arm = {"condition_label": "c", "knobs": {"max_results_per_query": 8, "chained": True}}
    cmd = build_command(exp, arm, ["A:NL"], 8)
    assert "--provider" in cmd and "diy" in cmd
    # arm knob overrides baseline
    i = cmd.index("--max-results-per-query")
    assert cmd[i + 1] == "8"
    assert "--chained" in cmd
