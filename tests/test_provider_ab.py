"""Pure-logic tests for the multi-provider A/B judge harness (EXP-4, EXP-5).

No network, no DB, no LLM. Covers the parts where a bug would silently
corrupt the headline ranking: the generalised orientation mapping and verdict
combination for an arbitrary provider pair, the Copeland ranking (clear case
and an intransitive triple, whose cycle must be reported), the head-to-head
win-share statistic, and the provider-drop logic that keeps only live arms.
"""
from __future__ import annotations

from evaluation.provider_ab import (
    orientation_to_x,
    combine_pair_orientations,
    copeland_ranking,
    head_to_head_stats,
    filter_live_providers,
    normalise_provider,
    search_provider_name,
)


# --- normalise_provider / search_provider_name -----------------------------

def test_normalise_provider_lowercases_and_aliases_serper():
    assert normalise_provider("Serper") == "serper"
    assert normalise_provider("serper_raw") == "serper"
    assert normalise_provider("DIY") == "diy"


def test_search_provider_name_maps_serper_to_serper_raw():
    # The search() backend literal for Serper is "serper_raw"; the harness
    # carries the user-facing "serper" everywhere else.
    assert search_provider_name("serper") == "serper_raw"
    assert search_provider_name("diy") == "diy"
    assert search_provider_name("tavily") == "tavily"
    assert search_provider_name("brave") == "brave"


# --- orientation_to_x: blind A/B verdict -> the x-provider frame -----------

def test_orientation_winner_a_when_x_is_a():
    assert orientation_to_x("A", x_is="A") == "x"


def test_orientation_winner_a_when_x_is_b():
    # x sat in slot B, so a win for A is a win for the OTHER provider (y).
    assert orientation_to_x("A", x_is="B") == "y"


def test_orientation_tie_and_both_fail_passthrough():
    assert orientation_to_x("tie", x_is="A") == "tie"
    assert orientation_to_x("both_fail", x_is="B") == "both_fail"


# --- combine_pair_orientations: two swapped runs -> one verdict ------------

def test_combine_agreement_x_wins_both_orientations():
    out = combine_pair_orientations("x", "x")
    assert out["verdict"] == "x"
    assert out["consistent"] is True


def test_combine_position_flip_is_tie_and_inconsistent():
    # Judge picked whoever sat in slot A both times -> pure position bias.
    out = combine_pair_orientations("x", "y")
    assert out["verdict"] == "tie"
    assert out["consistent"] is False


def test_combine_x_and_tie_leans_x():
    out = combine_pair_orientations("x", "tie")
    assert out["verdict"] == "x"
    assert out["consistent"] is False


def test_combine_both_fail_when_both_orientations_fail():
    out = combine_pair_orientations("both_fail", "both_fail")
    assert out["verdict"] == "both_fail"
    assert out["consistent"] is True


def test_combine_one_both_fail_one_decided_takes_the_decided_side():
    # One orientation called both_fail, the other gave x the win: net x.
    out = combine_pair_orientations("both_fail", "x")
    assert out["verdict"] == "x"
    assert out["consistent"] is False


# --- copeland_ranking: clear, transitive case ------------------------------

def test_copeland_clear_total_order():
    """diy beats both, tavily beats brave, so diy > tavily > brave.

    Verdicts are per arm-pair, already resolved to the winning provider name
    (or 'tie' / 'both_fail').
    """
    verdicts = [
        {"provider_x": "diy", "provider_y": "tavily", "verdict": "diy"},
        {"provider_x": "diy", "provider_y": "brave", "verdict": "diy"},
        {"provider_x": "tavily", "provider_y": "brave", "verdict": "tavily"},
    ]
    # Default form returns the ranking list directly, ordered best-first.
    ranking = copeland_ranking(["diy", "tavily", "brave"], verdicts)
    scores = {r["provider"]: r["copeland"] for r in ranking}
    assert scores["diy"] == 2      # 2 wins, 0 losses
    assert scores["tavily"] == 0   # 1 win, 1 loss
    assert scores["brave"] == -2   # 0 wins, 2 losses
    assert [r["provider"] for r in ranking] == ["diy", "tavily", "brave"]


def test_copeland_ranking_is_ordered_and_reports_no_cycle_when_transitive():
    verdicts = [
        {"provider_x": "diy", "provider_y": "tavily", "verdict": "diy"},
        {"provider_x": "diy", "provider_y": "brave", "verdict": "diy"},
        {"provider_x": "tavily", "provider_y": "brave", "verdict": "tavily"},
    ]
    result = copeland_ranking(["diy", "tavily", "brave"], verdicts, full=True)
    assert [r["provider"] for r in result["ranking"]] == ["diy", "tavily", "brave"]
    assert result["intransitive_triples"] == []


def test_copeland_tie_in_score_broken_by_decided_wins():
    """Two providers share a Copeland score; the one with more decided wins
    ranks higher.

    Five arms, no cycle. a goes 2W 2L (Copeland 0, two decided wins); b goes
    1W 1L (Copeland 0, one decided win). a and b tie on Copeland, so the
    decided-wins tiebreak must rank a above b.
    """
    verdicts = [
        # a: beats c, beats e; loses to b, loses to d  -> 2W 2L, copeland 0
        {"provider_x": "a", "provider_y": "c", "verdict": "a"},
        {"provider_x": "a", "provider_y": "e", "verdict": "a"},
        {"provider_x": "a", "provider_y": "b", "verdict": "b"},
        {"provider_x": "a", "provider_y": "d", "verdict": "d"},
        # b: beats a, beats... loses one -> keep b at 1W 1L (copeland 0)
        {"provider_x": "b", "provider_y": "c", "verdict": "c"},
        # remaining head-to-heads resolved as ties so they move no score
        {"provider_x": "b", "provider_y": "d", "verdict": "tie"},
        {"provider_x": "b", "provider_y": "e", "verdict": "tie"},
        {"provider_x": "c", "provider_y": "d", "verdict": "tie"},
        {"provider_x": "c", "provider_y": "e", "verdict": "tie"},
        {"provider_x": "d", "provider_y": "e", "verdict": "tie"},
    ]
    # a: W{c,e} L{b,d}      -> copeland 0, decided wins 2
    # b: W{a}   L{c}        -> copeland 0, decided wins 1
    # a and b tie on Copeland; a has more decided wins, so a ranks above b.
    result = copeland_ranking(["a", "b", "c", "d", "e"], verdicts, full=True)
    by_provider = {r["provider"]: r for r in result["ranking"]}
    assert by_provider["a"]["copeland"] == 0
    assert by_provider["b"]["copeland"] == 0
    assert by_provider["a"]["decided_wins"] == 2
    assert by_provider["b"]["decided_wins"] == 1
    order = [r["provider"] for r in result["ranking"]]
    assert order.index("a") < order.index("b")


# --- copeland_ranking: intransitive triple ---------------------------------

def test_copeland_reports_intransitive_triple():
    """A rock-paper-scissors cycle: x>y, y>z, z>x. Copeland is 0 for all three;
    the cycle must be reported, not silently resolved."""
    verdicts = [
        {"provider_x": "x", "provider_y": "y", "verdict": "x"},
        {"provider_x": "y", "provider_y": "z", "verdict": "y"},
        {"provider_x": "z", "provider_y": "x", "verdict": "z"},
    ]
    result = copeland_ranking(["x", "y", "z"], verdicts, full=True)
    # All three have one win and one loss -> Copeland 0 each.
    assert all(r["copeland"] == 0 for r in result["ranking"])
    # The cycle is detected and reported.
    triples = result["intransitive_triples"]
    assert len(triples) == 1
    assert set(triples[0]) == {"x", "y", "z"}


def test_copeland_ignores_ties_and_both_fail_in_winloss():
    """Ties and both_fail decide no head-to-head, so they move no Copeland score."""
    verdicts = [
        {"provider_x": "a", "provider_y": "b", "verdict": "tie"},
        {"provider_x": "a", "provider_y": "c", "verdict": "both_fail"},
        {"provider_x": "b", "provider_y": "c", "verdict": "b"},
    ]
    result = copeland_ranking(["a", "b", "c"], verdicts, full=True)
    scores = {r["provider"]: r["copeland"] for r in result["ranking"]}
    assert scores["a"] == 0   # tie + both_fail -> no decided head-to-head
    assert scores["b"] == 1   # one win over c
    assert scores["c"] == -1  # one loss to b


# --- head_to_head_stats: win share + Wilson CI -----------------------------

def test_head_to_head_stats_win_share_and_wilson():
    from evaluation.stats import wilson_interval

    out = head_to_head_stats(x_wins=9, y_wins=3, ties=2, both_fail=1)
    assert out["decided"] == 12
    assert out["x_win_share"] == 0.75
    lo, hi = wilson_interval(9, 12)
    assert out["wilson_low"] == lo
    assert out["wilson_high"] == hi
    # Ties and both_fail are reported but excluded from the decided denominator.
    assert out["ties"] == 2
    assert out["both_fail"] == 1


def test_head_to_head_stats_zero_decided_is_safe():
    out = head_to_head_stats(x_wins=0, y_wins=0, ties=0, both_fail=3)
    assert out["decided"] == 0
    assert out["x_win_share"] == 0.0
    assert out["wilson_low"] == 0.0
    assert out["wilson_high"] == 1.0


# --- filter_live_providers: keep only arms that returned results -----------

def test_filter_live_providers_keeps_only_live():
    probes = {
        "diy": {"ok": True, "n_results": 5},
        "tavily": {"ok": True, "n_results": 4},
        "brave": {"ok": False, "n_results": 0, "error": "no key"},
        "serper": {"ok": True, "n_results": 3},
    }
    requested = ["diy", "tavily", "brave", "serper"]
    live, dropped = filter_live_providers(requested, probes)
    assert live == ["diy", "tavily", "serper"]   # order preserved, brave dropped
    assert dropped == ["brave"]


def test_filter_live_providers_zero_results_counts_as_dead():
    # A provider that authenticated but returned nothing for the trivial probe
    # cannot serve the experiment, so it is dropped too.
    probes = {
        "diy": {"ok": True, "n_results": 2},
        "tavily": {"ok": True, "n_results": 0},
    }
    live, dropped = filter_live_providers(["diy", "tavily"], probes)
    assert live == ["diy"]
    assert dropped == ["tavily"]


def test_filter_live_providers_missing_probe_is_dropped():
    probes = {"diy": {"ok": True, "n_results": 1}}
    live, dropped = filter_live_providers(["diy", "brave"], probes)
    assert live == ["diy"]
    assert dropped == ["brave"]
