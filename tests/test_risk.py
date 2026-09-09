import math

import pytest

from bjtoolkit.ramp import kelly_ramp, spread_ramp
from bjtoolkit.risk import (
    bankroll_for_ror,
    evaluate,
    kelly_for_ror,
    risk_of_ruin,
    ror_for_kelly,
)
from bjtoolkit.rules import get_preset


def test_full_kelly_ruin_is_the_textbook_value():
    """RoR = e^-2 at full Kelly, e^-4 at half. If these drift, the model is wrong."""
    assert ror_for_kelly(1.0) == pytest.approx(math.exp(-2), rel=1e-9)
    assert ror_for_kelly(0.5) == pytest.approx(math.exp(-4), rel=1e-9)
    assert ror_for_kelly(1.0) == pytest.approx(0.1353, abs=1e-4)


def test_kelly_for_ror_inverts_ror_for_kelly():
    for target in (0.01, 0.05, 0.10, 0.25):
        assert ror_for_kelly(kelly_for_ror(target)) == pytest.approx(target, rel=1e-9)


def test_betting_less_reduces_ruin():
    fractions = [0.2, 0.4, 0.6, 0.8, 1.0]
    rors = [ror_for_kelly(f) for f in fractions]
    assert rors == sorted(rors)


def test_kelly_for_ror_rejects_impossible_targets():
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            kelly_for_ror(bad)


def test_ruin_is_certain_without_an_edge():
    assert risk_of_ruin(0.0, 1000.0, 100_000) == 1.0
    assert risk_of_ruin(-5.0, 1000.0, 100_000) == 1.0


def test_ruin_falls_as_the_bankroll_grows_for_a_fixed_ramp():
    rors = [risk_of_ruin(5.0, 1500.0, b) for b in (100_000, 200_000, 400_000)]
    assert rors == sorted(rors, reverse=True)


def test_bankroll_solver_round_trips_against_a_fixed_ramp():
    wr, var = 5.68, 1_600_000.0
    for target in (0.01, 0.05, 0.20):
        need = bankroll_for_ror(target, wr, var)
        assert risk_of_ruin(wr, var, need) == pytest.approx(target, rel=1e-9)


def test_bankroll_solver_is_infinite_without_an_edge():
    assert bankroll_for_ror(0.05, -1.0, 1000.0) == math.inf


def test_bankroll_solver_is_not_circular_under_a_fixed_ramp(rules, dist):
    """Regression test for the flaw in the original spec.

    A ramp fixed in currency gives one answer no matter what bankroll you were
    thinking of when you built it. The Kelly ramp does not have this property,
    which is exactly why the solver takes a spread ramp instead.
    """
    ramp = spread_ramp(rules, dist, max_spread=12, unit=200)
    rep = evaluate(rules, dist, ramp)
    answers = {
        round(bankroll_for_ror(0.05, rep.win_rate_per_round, rep.variance_per_round))
        for _ in range(3)
    }
    assert len(answers) == 1
    need = answers.pop()
    # And the answer it gives really does deliver the target ruin probability.
    check = evaluate(rules, dist, ramp, bankroll=need)
    # `need` was rounded to whole currency above; ruin is exponential in the
    # bankroll, so that rounding shows up magnified by the ruin exponent (~3).
    assert check.risk_of_ruin == pytest.approx(0.05, rel=1e-5)


def test_kelly_ramp_ruin_is_roughly_bankroll_invariant(rules, dist):
    """The property that made the spec's solver meaningless, stated positively.

    With proportional betting and no table constraints, ruin barely moves as the
    bankroll changes -- so 'what bankroll do I need for 5% ruin' has no answer.
    Use kelly_for_ror instead.
    """
    r = rules.model_copy(deep=True)
    r.table_min, r.table_max = 1.0, 1e12  # remove the clamps that break scaling
    rors = []
    for b in (1_000_000, 2_000_000, 4_000_000):
        ramp = kelly_ramp(r, dist, bankroll=b, kelly_fraction=0.4, rounding_unit=0.01)
        rep = evaluate(r, dist, ramp, bankroll=b)
        rors.append(rep.risk_of_ruin)
    assert max(rors) - min(rors) < 0.01


def test_evaluate_flags_an_ev_negative_configuration(rules, dist):
    ramp = spread_ramp(rules, dist, max_spread=1, unit=200)  # flat betting
    rep = evaluate(rules, dist, ramp)
    assert rep.win_rate_per_round < 0
    assert any("EV-NEGATIVE" in w for w in rep.warnings)
    assert rep.n0_rounds == math.inf


def test_flat_betting_loses_the_house_edge(rules, dist):
    """Sanity anchor: flat-betting 200 should lose about 0.45% of 200 per hand."""
    ramp = spread_ramp(rules, dist, max_spread=1, unit=200)
    rep = evaluate(rules, dist, ramp)
    assert rep.win_rate_per_round == pytest.approx(200 * -0.0045, abs=0.15)


def test_wonging_raises_win_rate_per_hand_and_cuts_hands_played(rules, dist):
    plain = evaluate(rules, dist, spread_ramp(rules, dist, max_spread=12, unit=200))
    wonged = evaluate(
        rules, dist,
        spread_ramp(rules, dist, max_spread=12, unit=200, wong_out_below=1),
    )
    assert wonged.fraction_of_rounds_played < plain.fraction_of_rounds_played
    assert wonged.win_rate_per_played_hand > plain.win_rate_per_played_hand
    assert wonged.win_rate_per_hour > plain.win_rate_per_hour


def test_per_hour_figures_scale_correctly(rules, dist):
    ramp = spread_ramp(rules, dist, max_spread=12, unit=200)
    rep = evaluate(rules, dist, ramp, rounds_per_hour=100)
    assert rep.win_rate_per_hour == pytest.approx(rep.win_rate_per_round * 100)
    # Standard deviation grows with the square root of the hands, not linearly.
    assert rep.sd_per_hour == pytest.approx(rep.sd_per_round * math.sqrt(100))


def test_n0_is_where_expectation_equals_one_sd(rules, dist):
    ramp = spread_ramp(rules, dist, max_spread=12, unit=200)
    rep = evaluate(rules, dist, ramp)
    n = rep.n0_rounds
    assert rep.win_rate_per_round * n == pytest.approx(
        math.sqrt(rep.variance_per_round * n), rel=1e-6
    )


def test_probability_of_profit_rises_with_hours_played(rules, dist):
    ramp = spread_ramp(rules, dist, max_spread=16, unit=200)
    probs = [
        evaluate(rules, dist, ramp, hours_planned=h).prob_of_profit
        for h in (10, 100, 1000, 10_000)
    ]
    assert probs == sorted(probs)
    assert probs[0] < 0.6 < probs[-1]


def test_six_five_cannot_be_beaten_with_a_normal_spread():
    from bjtoolkit.frequency import simulate_tc_distribution
    r = get_preset("six-five")
    d = simulate_tc_distribution(r, n_shoes=3000, seed=5)
    rep = evaluate(r, d, spread_ramp(r, d, max_spread=12, unit=r.table_min))
    assert rep.win_rate_per_round < 0
