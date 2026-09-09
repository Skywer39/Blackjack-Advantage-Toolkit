"""The simulator's job is to check the analytic risk model, so most of these
tests are about the two agreeing -- and about the places they should not."""

import numpy as np
import pytest

from bjtoolkit.ramp import kelly_ramp, spread_ramp
from bjtoolkit.risk import evaluate
from bjtoolkit.rules import get_preset
from bjtoolkit.simulate import (
    BASE_OUTCOMES, _base_arrays, collapse_to_atoms, ruin_convergence, simulate,
)


@pytest.fixture(scope="module")
def setup(rules, dist):
    ramp = spread_ramp(rules, dist, max_spread=8, unit=200, wong_out_below=1)
    return rules, dist, ramp


# --- the outcome table ----------------------------------------------------

def test_outcome_probabilities_sum_to_one():
    assert sum(p for _, p in BASE_OUTCOMES) == pytest.approx(1.0)


def test_outcome_table_reproduces_the_published_variance():
    """Independent check: a realistic table of blackjack results should land near
    the 1.32 per-unit variance quoted in the literature, without being fitted."""
    _, _, mean, var = _base_arrays()
    assert var == pytest.approx(1.32, abs=0.05)
    assert mean == pytest.approx(-0.015, abs=0.01)


def test_outcome_table_contains_the_hands_that_matter():
    values = {x for x, _ in BASE_OUTCOMES}
    assert 1.5 in values   # blackjack at 3:2
    assert 2.0 in values   # doubles
    assert 0.0 in values   # pushes
    assert -0.5 in values  # surrender


# --- the collapsed sampler ------------------------------------------------

def test_collapsed_atoms_form_a_distribution(setup):
    rules, dist, ramp = setup
    values, probs = collapse_to_atoms(rules, dist, ramp)
    assert probs.sum() == pytest.approx(1.0)
    assert np.all(probs >= 0)
    assert values.size == len(dist.counts()) * len(BASE_OUTCOMES)


def test_collapsed_atoms_match_the_analytic_moments(setup):
    """The whole point of the collapse: one categorical draw per hand that still
    carries exactly the win rate and variance the risk module integrates."""
    rules, dist, ramp = setup
    values, probs = collapse_to_atoms(rules, dist, ramp)
    rep = evaluate(rules, dist, ramp)
    mean = float((values * probs).sum())
    var = float((values**2 * probs).sum() - mean**2)
    assert mean == pytest.approx(rep.win_rate_per_round, rel=1e-9)
    # Variance differs by the between-count term, which the risk module drops as
    # negligible; confirm it really is.
    assert var == pytest.approx(rep.variance_per_round, rel=1e-3)


def test_sat_out_counts_contribute_no_money(setup):
    rules, dist, ramp = setup
    values, probs = collapse_to_atoms(rules, dist, ramp)
    # Every sat-out count contributes only zero-valued atoms.
    n_out = len(BASE_OUTCOMES)
    for i, tc in enumerate(dist.counts()):
        if tc in ramp.sat_out:
            assert np.allclose(values[i * n_out:(i + 1) * n_out], 0.0)


# --- agreement with the closed form ---------------------------------------

@pytest.mark.slow
def test_simulated_ruin_agrees_with_the_closed_form(setup):
    """The Phase 1.5 deliverable.

    Two claims in one simulation: the closed form Phase 1 quotes is close to the
    truth, and it errs by overstating ruin rather than understating it -- the
    safe direction for a number you size a bankroll from.
    """
    rules, dist, ramp = setup
    res = simulate(rules, dist, ramp, bankroll=94_158, n_paths=8000,
                   n_hands=200_000, seed=7)
    assert abs(res.ror_gap_points) < 3.0
    assert res.empirical_ror <= res.analytic_ror + 0.005


@pytest.mark.slow
def test_a_short_horizon_understates_infinite_horizon_ruin(setup):
    """A finite playing career is safer than the closed form implies."""
    rules, dist, ramp = setup
    short = simulate(rules, dist, ramp, bankroll=94_158, n_paths=3000,
                     n_hands=20_000, seed=7)
    long = simulate(rules, dist, ramp, bankroll=94_158, n_paths=3000,
                    n_hands=200_000, seed=7)
    assert short.empirical_ror < long.empirical_ror
    assert any("short relative to N0" in w for w in short.warnings)


@pytest.mark.slow
def test_the_shape_of_a_hand_result_barely_matters_for_ruin(setup):
    """Ruin is drift and diffusion; the lumpiness of blackjack payoffs washes out.
    If this ever fails, the moment matching has broken."""
    rules, dist, ramp = setup
    a = simulate(rules, dist, ramp, bankroll=94_158, n_paths=4000,
                 n_hands=100_000, outcome_model="discrete", seed=3)
    b = simulate(rules, dist, ramp, bankroll=94_158, n_paths=4000,
                 n_hands=100_000, outcome_model="normal", seed=3)
    assert abs(a.empirical_ror - b.empirical_ror) < 0.02


def test_a_bigger_bankroll_ruins_less_often(setup):
    rules, dist, ramp = setup
    # Small bankrolls so ruin is common and the ordering is clear at a short
    # horizon; the claim is monotonicity, not a calibrated ruin figure.
    rors = [
        simulate(rules, dist, ramp, bankroll=b, n_paths=2000, n_hands=20_000,
                 seed=5).empirical_ror
        for b in (15_000, 40_000, 100_000)
    ]
    assert rors == sorted(rors, reverse=True)


@pytest.mark.slow
def test_an_ev_negative_ramp_ruins_almost_everyone(rules, dist):
    flat = spread_ramp(rules, dist, max_spread=1, unit=200)
    res = simulate(rules, dist, flat, bankroll=20_000, n_paths=1500,
                   n_hands=100_000, seed=2)
    assert res.empirical_ror > 0.9
    assert res.analytic_ror == 1.0


# --- behaviour ------------------------------------------------------------

def test_a_higher_ruin_barrier_ruins_more_paths(setup):
    """Quitting when you cannot cover a bet is stricter than going to zero."""
    rules, dist, ramp = setup
    low = simulate(rules, dist, ramp, bankroll=20_000, n_paths=2000,
                   n_hands=20_000, ruin_at=0.0, seed=4)
    high = simulate(rules, dist, ramp, bankroll=20_000, n_paths=2000,
                    n_hands=20_000, ruin_at=1600.0, seed=4)
    assert high.empirical_ror >= low.empirical_ror


@pytest.mark.slow
def test_resizing_bets_to_the_bankroll_reduces_ruin(setup):
    """Betting proportionally means never betting a fixed sum you can no longer
    afford, so the barrier is approached asymptotically rather than crossed."""
    rules, dist, ramp = setup
    fixed = simulate(rules, dist, ramp, bankroll=94_158, n_paths=3000,
                     n_hands=100_000, resize=False, seed=6)
    sized = simulate(rules, dist, ramp, bankroll=94_158, n_paths=3000,
                     n_hands=100_000, resize=True, seed=6)
    assert sized.empirical_ror < fixed.empirical_ror


def test_percentiles_are_ordered(setup):
    rules, dist, ramp = setup
    res = simulate(rules, dist, ramp, bankroll=94_158, n_paths=2000,
                   n_hands=15_000, seed=1)
    p = res.final_percentiles
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]


def test_ruined_paths_stop_playing(setup):
    """A ruined bankroll must not keep betting and climb back out."""
    rules, dist, ramp = setup
    res = simulate(rules, dist, ramp, bankroll=3000, n_paths=2000,
                   n_hands=15_000, seed=8)
    assert res.empirical_ror > 0.3
    assert res.final_percentiles["p5"] == pytest.approx(0.0)


def test_results_are_reproducible(setup):
    rules, dist, ramp = setup
    kw = dict(bankroll=94_158, n_paths=1000, n_hands=10_000, seed=42)
    assert (simulate(rules, dist, ramp, **kw).empirical_ror
            == simulate(rules, dist, ramp, **kw).empirical_ror)


def test_different_seeds_give_different_paths(setup):
    rules, dist, ramp = setup
    kw = dict(bankroll=94_158, n_paths=1000, n_hands=10_000)
    a = simulate(rules, dist, ramp, seed=1, **kw).median_final
    b = simulate(rules, dist, ramp, seed=2, **kw).median_final
    assert a != b


def test_block_size_does_not_change_the_answer(setup):
    """Blocking is an implementation detail; first-passage detection must not
    depend on where the block boundaries fall."""
    rules, dist, ramp = setup
    kw = dict(bankroll=20_000, n_paths=2000, n_hands=20_000, seed=11)
    a = simulate(rules, dist, ramp, block=100, **kw).empirical_ror
    b = simulate(rules, dist, ramp, block=1000, **kw).empirical_ror
    assert abs(a - b) < 0.02


def test_kelly_ramp_can_also_be_simulated(rules, dist):
    ramp = kelly_ramp(rules, dist, bankroll=600_000, wong_out_below=1)
    res = simulate(rules, dist, ramp, bankroll=600_000, n_paths=1000,
                   n_hands=15_000, seed=9)
    assert 0.0 <= res.empirical_ror <= 1.0


def test_rejects_a_bad_outcome_model(setup):
    rules, dist, ramp = setup
    with pytest.raises(ValueError, match="outcome_model"):
        simulate(rules, dist, ramp, bankroll=1000, outcome_model="lognormal")


def test_rejects_nonsense_sizes(setup):
    rules, dist, ramp = setup
    for kw in ({"n_paths": 0}, {"n_hands": -5}):
        with pytest.raises(ValueError):
            simulate(rules, dist, ramp, bankroll=1000, **kw)


@pytest.mark.slow
def test_convergence_helper_returns_increasing_ruin(setup):
    rules, dist, ramp = setup
    rows = ruin_convergence(rules, dist, ramp, bankroll=94_158, n_paths=1500,
                            horizons=(10_000, 40_000, 160_000), seed=3)
    assert [r["empirical_ror"] for r in rows] == sorted(
        r["empirical_ror"] for r in rows
    )
    assert all(r["analytic_ror"] == rows[0]["analytic_ror"] for r in rows)
