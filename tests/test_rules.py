"""The rule engine must reproduce published house edges for known games."""

import pytest

from bjtoolkit.rules import (
    PRESETS,
    DoubleRule,
    HoleCard,
    RuleSet,
    Surrender,
    base_edge,
    base_edge_range,
    edge_components,
    get_preset,
)

# Published house edges for standard games, and how close we insist on being.
# Sources are the same rule-variation tables the constants come from, so this is
# an internal-consistency check, not an independent validation.
KNOWN_EDGES = [
    ("vegas-strip", -0.0033, 0.0005),
    ("vegas-h17", -0.0055, 0.0005),
    ("vegas-8d", -0.0065, 0.0005),
    ("six-five", -0.0202, 0.0010),
]


@pytest.mark.parametrize("preset,expected,tol", KNOWN_EDGES)
def test_matches_published_edge(preset, expected, tol):
    assert base_edge(get_preset(preset)) == pytest.approx(expected, abs=tol)


def test_six_deck_s17_das_is_about_forty_basis_points():
    """The most-quoted number in blackjack. If this drifts, something broke."""
    r = RuleSet(decks=6, dealer_hits_soft_17=False, double_after_split=True)
    assert base_edge(r) == pytest.approx(-0.0041, abs=0.0003)


def test_h17_costs_about_22_basis_points():
    s17 = RuleSet(decks=6, dealer_hits_soft_17=False)
    h17 = RuleSet(decks=6, dealer_hits_soft_17=True)
    assert base_edge(s17) - base_edge(h17) == pytest.approx(0.0022, abs=0.0002)


def test_fewer_decks_are_better():
    edges = [base_edge(RuleSet(decks=d, penetration_decks_dealt=d * 0.7))
             for d in (1, 2, 4, 6, 8)]
    assert edges == sorted(edges, reverse=True)


def test_six_five_is_catastrophic():
    """6:5 costs more than every other rule in the file combined."""
    fair = RuleSet(decks=6, blackjack_payout=1.5)
    bad = RuleSet(decks=6, blackjack_payout=1.2)
    assert base_edge(fair) - base_edge(bad) > 0.013


def test_enhc_original_only_is_free():
    """OBO gives back exactly what the peek would have; it plays like a US game."""
    peek = RuleSet(decks=6, hole_card=HoleCard.PEEK)
    obo = RuleSet(decks=6, hole_card=HoleCard.ENHC_ORIGINAL_ONLY)
    assert base_edge(peek) == pytest.approx(base_edge(obo))


def test_enhc_all_bets_costs_something():
    peek = RuleSet(decks=6, hole_card=HoleCard.PEEK)
    full = RuleSet(decks=6, hole_card=HoleCard.ENHC_ALL_BETS)
    assert base_edge(peek) - base_edge(full) == pytest.approx(0.0011, abs=0.0003)


def test_early_surrender_beats_late_surrender():
    late = RuleSet(decks=6, surrender=Surrender.LATE_ALL)
    early = RuleSet(decks=6, surrender=Surrender.EARLY_ALL)
    assert base_edge(early) > base_edge(late) + 0.004


def test_edge_range_brackets_the_point_estimate():
    for r in PRESETS.values():
        lo, hi = base_edge_range(r)
        assert lo < base_edge(r) < hi


def test_every_component_is_sourced():
    """No magic numbers. Each contribution must name where it came from."""
    for r in PRESETS.values():
        for name, est in edge_components(r):
            assert est.source, f"{name} has no source"


def test_deck_effect_interpolates_for_unlisted_counts():
    e3 = base_edge(RuleSet(decks=3, penetration_decks_dealt=2.0))
    e2 = base_edge(RuleSet(decks=2, penetration_decks_dealt=1.5))
    e4 = base_edge(RuleSet(decks=4, penetration_decks_dealt=3.0))
    assert e4 < e3 < e2


def test_penetration_must_be_less_than_the_shoe():
    with pytest.raises(ValueError, match="less than decks"):
        RuleSet(decks=6, penetration_decks_dealt=6.0)


def test_table_max_must_exceed_min():
    with pytest.raises(ValueError, match="table_max"):
        RuleSet(table_min=100, table_max=100)


def test_double_restrictions_cost_money():
    free = RuleSet(decks=6, double_rule=DoubleRule.ANY_TWO)
    some = RuleSet(decks=6, double_rule=DoubleRule.NINE_TO_ELEVEN)
    tight = RuleSet(decks=6, double_rule=DoubleRule.TEN_ELEVEN)
    assert base_edge(free) > base_edge(some) > base_edge(tight)


def test_unknown_preset_lists_the_alternatives():
    with pytest.raises(KeyError, match="vegas-strip"):
        get_preset("nonexistent")


def test_preset_returns_a_copy():
    a = get_preset("ambassador")
    a.decks = 2
    assert get_preset("ambassador").decks == 6
