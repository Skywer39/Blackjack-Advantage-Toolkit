
import pytest

from bjtoolkit.frequency import simulate_tc_distribution
from bjtoolkit.rules import get_preset
from bjtoolkit.viability import assess, penetration_sweep


@pytest.fixture(scope="module")
def amb():
    return get_preset("ambassador")


@pytest.fixture(scope="module")
def d(amb):
    return simulate_tc_distribution(amb, n_shoes=4000, seed=11)


def test_small_bankroll_is_not_viable_without_wonging(amb, d):
    rep = assess(amb, bankroll=100_000, dist=d)
    assert rep.verdict.startswith("NOT VIABLE")
    assert not any(o.viable for o in rep.options)


def test_wonging_rescues_a_small_bankroll(amb, d):
    """Sitting out negative counts is what makes a high table minimum survivable."""
    rep = assess(amb, bankroll=100_000, wong_out_below=1, dist=d)
    assert rep.verdict.startswith("VIABLE")
    assert any(o.viable for o in rep.options)


def test_a_large_bankroll_is_viable(amb, d):
    rep = assess(amb, bankroll=2_000_000, dist=d)
    assert rep.verdict.startswith("VIABLE")


def test_reports_the_bankroll_shortfall_when_unaffordable(amb, d):
    rep = assess(amb, bankroll=50_000, dist=d)
    assert "NOT VIABLE" in rep.verdict
    assert any(char.isdigit() for char in rep.verdict)


def test_six_five_is_never_viable():
    r = get_preset("six-five")
    dd = simulate_tc_distribution(r, n_shoes=3000, seed=5)
    rep = assess(r, bankroll=10_000_000, dist=dd)
    assert rep.verdict.startswith("NOT VIABLE")
    assert any("blackjack pays" in n for n in rep.notes)


def test_shallow_penetration_is_called_out():
    r = get_preset("ambassador")
    r.penetration_decks_dealt = 3.0
    dd = simulate_tc_distribution(r, n_shoes=3000, seed=6)
    rep = assess(r, bankroll=1_000_000, dist=dd)
    assert any("penetration is only" in n for n in rep.notes)


def test_narrow_table_limits_are_called_out():
    r = get_preset("ambassador")
    r.table_max = 1000.0
    dd = simulate_tc_distribution(r, n_shoes=3000, seed=6)
    rep = assess(r, bankroll=1_000_000, dist=dd)
    assert any("only allows" in n for n in rep.notes)


def test_bigger_spreads_earn_more_and_need_more(amb, d):
    rep = assess(amb, bankroll=None, wong_out_below=1, dist=d)
    earning = [o for o in rep.options if o.win_rate_per_hour > 0]
    assert [o.win_rate_per_hour for o in earning] == sorted(
        o.win_rate_per_hour for o in earning
    )


def test_breakeven_tc_and_advantage_share_are_consistent(amb, d):
    rep = assess(amb, dist=d)
    assert 0 < rep.prob_advantage < 0.5
    assert rep.breakeven_tc > 0


def test_options_over_table_max_are_flagged(amb, d):
    rep = assess(amb, spreads=(10, 40), dist=d)
    assert rep.options[-1].fits_table is False
    assert rep.options[-1].viable is False


def test_penetration_sweep_is_monotonic_in_the_things_that_matter():
    rows = penetration_sweep(
        get_preset("ambassador"), penetrations=(3.0, 4.0, 5.0),
        max_spread=12, n_shoes=2500,
    )
    assert [r["prob_tc_ge_4"] for r in rows] == sorted(r["prob_tc_ge_4"] for r in rows)
    assert [r["win_rate_per_hour"] for r in rows] == sorted(
        r["win_rate_per_hour"] for r in rows
    )


def test_penetration_sweep_skips_impossible_penetrations():
    rows = penetration_sweep(
        get_preset("ambassador"), penetrations=(4.0, 6.0, 9.0), n_shoes=1500
    )
    assert len(rows) == 1


def test_deep_penetration_is_worth_a_lot():
    """Concretely: the cut card is worth more than most rule changes."""
    rows = penetration_sweep(
        get_preset("ambassador"), penetrations=(3.0, 5.0),
        max_spread=16, n_shoes=3000,
    )
    assert rows[1]["win_rate_per_hour"] > rows[0]["win_rate_per_hour"] * 2
