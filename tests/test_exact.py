"""Exact enumeration is the project's ground truth, so these tests are mostly
about it agreeing with things known independently."""

import pytest

from bjtoolkit import constants as C
from bjtoolkit.cards import fresh_deck
from bjtoolkit.exact import _initial_deals, ev_curve, exact_edge, fit_linear
from bjtoolkit.rules import HoleCard, RuleSet, base_edge, get_preset


def test_initial_deals_form_a_probability_distribution():
    deals = _initial_deals(fresh_deck(6))
    assert sum(p for _, _, p in deals) == pytest.approx(1.0)
    assert all(p > 0 for _, _, p in deals)


def test_initial_deals_cover_every_pair_and_upcard():
    deals = _initial_deals(fresh_deck(6))
    hands = {cards for cards, _, _ in deals}
    assert len(hands) == 55            # 10 ranks, unordered with repeats
    assert len({up for _, up, _ in deals}) == 10


def test_a_ten_is_the_likeliest_upcard():
    deals = _initial_deals(fresh_deck(6))
    by_up: dict[int, float] = {}
    for _, up, p in deals:
        by_up[up] = by_up.get(up, 0.0) + p
    assert max(by_up, key=lambda u: by_up[u]) == 8      # the ten group
    assert by_up[8] == pytest.approx(16 / 52, abs=0.005)


# --- the headline: do the model's constants survive enumeration? ----------

@pytest.mark.slow
@pytest.mark.parametrize("preset", [
    "vegas-strip", "vegas-8d", "ambassador", "uk-enhc", "double-deck",
])
def test_modelled_edge_matches_exact_enumeration(preset):
    """The rule-effect constants in constants.py, checked against the real game.

    Tolerance is a tenth of a percent, which is the resolution the analyzer's
    own documented approximations allow.
    """
    r = get_preset(preset)
    assert exact_edge(r) == pytest.approx(base_edge(r), abs=0.001)


@pytest.mark.slow
def test_worse_rules_really_are_worse():
    order = ["vegas-strip", "ambassador", "uk-enhc", "vegas-h17", "vegas-8d",
             "six-five"]
    edges = [exact_edge(get_preset(p)) for p in order]
    assert edges == sorted(edges, reverse=True)


@pytest.mark.slow
def test_peek_and_original_bet_only_have_the_same_edge():
    """OBO returns exactly what the peek would have, so the games are equal."""
    peek = RuleSet(decks=6, hole_card=HoleCard.PEEK)
    obo = RuleSet(decks=6, hole_card=HoleCard.ENHC_ORIGINAL_ONLY)
    assert exact_edge(peek) == pytest.approx(exact_edge(obo), abs=1e-9)


@pytest.mark.slow
def test_full_enhc_costs_about_a_tenth_of_a_percent():
    peek = RuleSet(decks=6, hole_card=HoleCard.PEEK)
    enhc = RuleSet(decks=6, hole_card=HoleCard.ENHC_ALL_BETS)
    assert exact_edge(peek) - exact_edge(enhc) == pytest.approx(
        C.ENHC_ALL_BETS_LOST.value * -1, abs=0.0005
    )


@pytest.mark.slow
def test_resplitting_is_worth_something():
    """Regression guard. Modelling splits without resplits understated the
    edge by roughly 0.05% -- five times every other error combined."""
    to_four = RuleSet(decks=6, max_split_hands=4)
    to_two = RuleSet(decks=6, max_split_hands=2)
    gain = exact_edge(to_four) - exact_edge(to_two)
    assert gain > 0.0002


@pytest.mark.slow
def test_six_five_is_worth_over_a_percent():
    fair = RuleSet(decks=6, blackjack_payout=1.5)
    bad = RuleSet(decks=6, blackjack_payout=1.2)
    assert exact_edge(fair) - exact_edge(bad) > 0.012


@pytest.mark.slow
def test_breakdown_shares_add_up():
    b = exact_edge(get_preset("vegas-strip"), breakdown=True)
    assert sum(b.frequency_of.values()) == pytest.approx(1.0)
    assert b.frequency_of["blackjack"] == pytest.approx(0.0475, abs=0.004)
    assert b.blackjack_share > 0


# --- the linear EV model --------------------------------------------------

def test_ev_curve_increases_with_the_count():
    # Three points is enough for monotonicity; the full curve is fitted in the
    # slow suite, where each point costs a whole enumeration.
    curve = ev_curve(get_preset("ambassador"), (-2.0, 0.0, 3.0))
    values = [curve[tc] for tc in sorted(curve)]
    assert values == sorted(values)


@pytest.mark.slow
def test_measured_slope_matches_the_constant():
    """HILO_SLOPE is now derived from this computation, so this pins it."""
    curve = ev_curve(get_preset("ambassador"), tuple(range(-3, 7)))
    _, slope, _ = fit_linear(curve)
    assert slope == pytest.approx(C.HILO_SLOPE.value, abs=0.0004)
    assert C.HILO_SLOPE.low <= slope <= C.HILO_SLOPE.high


@pytest.mark.slow
def test_the_ev_curve_is_convex():
    """The real curve steepens at high counts, so a straight line understates
    the edge exactly where the bets are biggest. That is the safe direction."""
    r = get_preset("ambassador")
    low = fit_linear(ev_curve(r, tuple(range(-3, 4))))[1]
    high = fit_linear(ev_curve(r, tuple(range(6, 11))))[1]
    assert high > low * 1.15


@pytest.mark.slow
def test_the_slope_is_stable_across_shoe_depth():
    """True count is supposed to normalise for how much shoe is left. If the
    slope drifted with depth, the whole true-count convention would be suspect."""
    r = get_preset("ambassador")
    slopes = [
        fit_linear(ev_curve(r, tuple(range(-3, 7)), cards_remaining=int(d * 52)))[1]
        for d in (1.5, 2.0, 3.0, 4.0)
    ]
    assert max(slopes) - min(slopes) < 0.0002


def test_fit_linear_recovers_a_known_line():
    curve = {float(x): 0.01 + 0.005 * x for x in range(-4, 7)}
    intercept, slope, worst = fit_linear(curve)
    assert intercept == pytest.approx(0.01)
    assert slope == pytest.approx(0.005)
    assert worst == pytest.approx(0.0, abs=1e-12)


@pytest.mark.slow
def test_a_partly_dealt_neutral_shoe_beats_a_full_one():
    """Not a bug: fewer cards left plays like a smaller game, which favours the
    player. It is why the curve's TC-0 point is not the off-the-top edge."""
    r = get_preset("ambassador")
    full = exact_edge(r)
    half = ev_curve(r, (0.0,))[0.0]
    assert half > full
