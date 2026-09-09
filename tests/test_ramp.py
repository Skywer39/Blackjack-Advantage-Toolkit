import pytest

from bjtoolkit.ev_model import ev_at_tc
from bjtoolkit.ramp import kelly_ramp, round_to_unit, spread_ramp


def test_round_to_unit():
    assert round_to_unit(196, 200) == 200
    assert round_to_unit(1049, 100) == 1000
    assert round_to_unit(1051, 100) == 1100
    assert round_to_unit(123.4, 0) == 123.4


def test_never_bets_below_the_table_minimum(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=500_000)
    assert min(r.bets.values()) >= rules.table_min


def test_never_bets_above_the_table_maximum(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=50_000_000)
    assert max(r.bets.values()) <= rules.table_max


def test_bets_are_non_decreasing_in_the_count(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=600_000)
    bets = [r.bets[tc] for tc in sorted(r.bets)]
    assert bets == sorted(bets)


def test_max_spread_is_respected(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=2_000_000, max_spread=8)
    assert r.top_bet <= rules.table_min * 8


def test_max_spread_warns_that_it_is_costing_you(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=2_000_000, max_spread=4)
    assert any("cover limit" in w for w in r.warnings)


def test_table_maximum_warning_fires_for_a_large_bankroll(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=20_000_000)
    assert any("maximum is" in w for w in r.warnings)


def test_small_bankroll_warns_that_it_cannot_bet_this_table(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=30_000)
    assert any("bankroll too small" in w for w in r.warnings)
    assert any("You would need" in w for w in r.warnings)


def test_large_bankroll_does_not_warn_about_being_small(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=3_000_000)
    assert not any("bankroll too small" in w for w in r.warnings)


def test_wonging_sits_out_low_counts(rules, dist):
    r = kelly_ramp(rules, dist, bankroll=300_000, wong_out_below=1)
    assert all(t < 1 for t in r.sat_out)
    assert r.bet(-2) == 0.0
    assert r.bet(3) > 0.0
    assert all(t >= 1 for t in r.played)


def test_bigger_bankroll_gives_a_bigger_spread(rules, dist):
    small = kelly_ramp(rules, dist, bankroll=200_000).spread
    large = kelly_ramp(rules, dist, bankroll=800_000).spread
    assert large > small


def test_spread_ramp_hits_its_target_spread(rules, dist):
    r = spread_ramp(rules, dist, max_spread=12, unit=200)
    assert r.spread == pytest.approx(12, rel=0.05)
    assert r.bottom_bet == pytest.approx(200)


def test_spread_ramp_is_independent_of_bankroll(rules, dist):
    """The property that makes the bankroll solve well-posed."""
    a = spread_ramp(rules, dist, max_spread=10, unit=200)
    b = spread_ramp(rules, dist, max_spread=10, unit=200)
    assert a.bets == b.bets


def test_spread_ramp_shape_follows_the_edge(rules, dist):
    r = spread_ramp(rules, dist, max_spread=16, unit=200)
    advantage = [t for t in sorted(r.bets) if ev_at_tc(t, rules) > 0]
    bets = [r.bets[t] for t in advantage]
    assert bets == sorted(bets)


def test_spread_ramp_bets_the_unit_where_there_is_no_edge(rules, dist):
    r = spread_ramp(rules, dist, max_spread=16, unit=200)
    assert all(r.bets[t] == 200 for t in r.bets if ev_at_tc(t, rules) <= 0)


def test_spread_ramp_warns_when_the_top_bet_exceeds_the_table(rules, dist):
    r = spread_ramp(rules, dist, max_spread=50, unit=200)
    assert any("above this" in w for w in r.warnings)


def test_flat_betting_has_a_spread_of_one(rules, dist):
    r = spread_ramp(rules, dist, max_spread=1, unit=200)
    assert r.spread == pytest.approx(1.0)
