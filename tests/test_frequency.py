import pytest

from bjtoolkit.counting import HI_LO, HI_OPT_II, KO, true_count
from bjtoolkit.frequency import TCDistribution, simulate_tc_distribution
from bjtoolkit.rules import get_preset


def test_hi_lo_is_balanced():
    assert HI_LO.balanced
    assert HI_OPT_II.balanced
    assert not KO.balanced  # KO is unbalanced by design


def test_shoe_has_the_right_number_of_cards():
    for decks in (1, 2, 6, 8):
        assert HI_LO.shoe_tags(decks).size == 52 * decks


def test_shoe_tags_sum_to_zero_for_a_balanced_count():
    assert HI_LO.shoe_tags(6).sum() == 0


def test_true_count_divides_by_decks_remaining():
    assert true_count(10, 260) == pytest.approx(2.0)
    assert true_count(-6, 156) == pytest.approx(-2.0)


def test_half_deck_estimation_rounds_the_divisor():
    # 200 cards remaining is 3.85 decks, which a player would call 4.
    assert true_count(8, 200, estimate_to_half_deck=True) == pytest.approx(2.0)
    assert true_count(8, 200) == pytest.approx(2.08, abs=0.01)


def test_distribution_sums_to_one(dist):
    assert sum(dist.probs.values()) == pytest.approx(1.0)


def test_distribution_is_centred_on_zero():
    """A balanced count over a full shoe has expectation zero.

    Rounds within one shoe are strongly correlated, so the effective sample size
    is the number of shoes, not the number of rounds. At 20k shoes the observed
    standard error of this mean is around 0.007, so 0.025 is a ~3-sigma bound.
    """
    r = get_preset("ambassador")
    d = simulate_tc_distribution(r, n_shoes=20_000, seed=99)
    mean = sum(tc * p for tc, p in d.probs.items())
    assert mean == pytest.approx(0.0, abs=0.025)


def test_distribution_is_roughly_symmetric(dist):
    for tc in (1, 2, 3):
        assert dist.p(tc) == pytest.approx(dist.p(-tc), rel=0.15)


def test_zero_bucket_dominates(dist):
    assert dist.p(0) > 0.35
    assert dist.p(0) == max(dist.probs.values())


def test_deeper_penetration_produces_more_high_counts():
    """The core claim: the cut card is the most leveraged rule in the game."""
    probs = []
    for pen in (3.0, 4.0, 5.0):
        r = get_preset("ambassador")
        r.penetration_decks_dealt = pen
        d = simulate_tc_distribution(r, n_shoes=3000, seed=7)
        probs.append(d.prob_at_or_above(4))
    assert probs == sorted(probs)
    assert probs[-1] > probs[0] * 3


def test_deeper_penetration_gives_more_rounds_per_shoe():
    r1, r2 = get_preset("ambassador"), get_preset("ambassador")
    r1.penetration_decks_dealt, r2.penetration_decks_dealt = 3.0, 5.0
    d1 = simulate_tc_distribution(r1, n_shoes=200, seed=1)
    d2 = simulate_tc_distribution(r2, n_shoes=200, seed=1)
    assert d2.rounds_per_shoe > d1.rounds_per_shoe


def test_fewer_decks_produce_more_extreme_counts():
    """A single deck swings far harder than a six-deck shoe."""
    out = {}
    for name in ("single-deck", "double-deck", "ambassador"):
        r = get_preset(name)
        out[name] = simulate_tc_distribution(r, n_shoes=3000, seed=3).prob_at_or_above(4)
    assert out["single-deck"] > out["double-deck"] > out["ambassador"]


def test_more_players_means_fewer_rounds_per_shoe():
    r1, r2 = get_preset("ambassador"), get_preset("ambassador")
    r1.players_at_table, r2.players_at_table = 1, 6
    d1 = simulate_tc_distribution(r1, n_shoes=200, seed=1)
    d2 = simulate_tc_distribution(r2, n_shoes=200, seed=1)
    assert d1.rounds_per_shoe > d2.rounds_per_shoe * 2


def test_round_trips_through_json(dist):
    restored = TCDistribution.from_dict(dist.to_dict())
    assert restored.probs == dist.probs
    assert restored.penetration_decks_dealt == dist.penetration_decks_dealt


def test_prob_at_or_above_is_a_survival_function(dist):
    assert dist.prob_at_or_above(-99) == pytest.approx(1.0)
    counts = dist.counts()
    vals = [dist.prob_at_or_above(t) for t in counts]
    assert vals == sorted(vals, reverse=True)


def test_normalises_a_distribution_that_does_not_sum_to_one():
    """The spec's fallback table summed to 0.98. Silently accepting that would
    bias every downstream integral, so the constructor renormalises."""
    d = TCDistribution(probs={0: 0.5, 1: 0.48}, decks=6,
                       penetration_decks_dealt=4.5, cards_per_round=5.4,
                       rounds_per_shoe=43)
    assert sum(d.probs.values()) == pytest.approx(1.0)
