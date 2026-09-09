"""Monte Carlo validation of the analytic risk model.

Phase 1 quotes a risk of ruin from a closed form:

    RoR = exp(-2 * win_rate * bankroll / variance)

That formula assumes a continuous bankroll, normally distributed increments, an
infinite playing horizon and a bet that stays fixed relative to the bankroll.
A real bet ramp violates most of that. This module plays the game out hand by
hand so you can see how far the approximation is off, and in which direction.

Two things it deliberately does NOT do:

* It does not play real hands. Each round draws a true count from the frequency
  model and then draws a *result* whose mean and variance match the analytic
  model at that count. That makes it a test of the risk arithmetic, not of the
  EV model -- if `ev_at_tc` is wrong, this simulator is wrong in exactly the same
  way and will happily agree with the closed form. Validating the EV model needs
  the Phase 2 strategy engine and real dealt hands.
* It does not model heat, betting errors, or getting barred.

The per-hand outcome table below is the realistic part: real blackjack results
are lumpy (pushes, blackjacks at 3:2, doubles and splits at 2-3 units), not
Gaussian. The table independently reproduces a variance of 1.338 against the
published 1.32, which is a reasonable check that its atoms are sane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .ev_model import ev_at_tc, variance_at_tc
from .frequency import TCDistribution
from .ramp import Ramp
from .risk import evaluate, risk_of_ruin
from .rules import RuleSet

# (payoff in units of the initial bet, probability) for 6-deck basic strategy.
# Covers pushes, blackjacks at 3:2, doubles at +/-2 and split hands at +/-3.
BASE_OUTCOMES: tuple[tuple[float, float], ...] = (
    (1.5, 0.045),    # blackjack, paid 3:2
    (2.0, 0.041),    # winning double
    (1.0, 0.335),    # ordinary win
    (0.0, 0.087),    # push
    (-1.0, 0.437),   # ordinary loss
    (-2.0, 0.030),   # losing double
    (-0.5, 0.005),   # surrender
    (3.0, 0.010),    # winning split
    (-3.0, 0.010),   # losing split
)


@dataclass
class SimResult:
    """What happened across all simulated paths."""

    n_paths: int
    n_hands: int
    starting_bankroll: float
    currency: str

    empirical_ror: float
    analytic_ror: float
    ruin_at: float

    final_percentiles: dict[str, float]
    fraction_profitable: float
    mean_final: float
    median_final: float

    analytic_expected_profit: float
    empirical_mean_profit: float

    outcome_model: str
    resized: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def ror_gap_points(self) -> float:
        """Empirical minus analytic, in percentage points."""
        return (self.empirical_ror - self.analytic_ror) * 100.0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["ror_gap_points"] = self.ror_gap_points
        return d


def _base_arrays() -> tuple[np.ndarray, np.ndarray, float, float]:
    values = np.array([x for x, _ in BASE_OUTCOMES], dtype=np.float64)
    probs = np.array([p for _, p in BASE_OUTCOMES], dtype=np.float64)
    probs = probs / probs.sum()
    mean = float((values * probs).sum())
    var = float((values**2 * probs).sum() - mean**2)
    return values, probs, mean, var


def collapse_to_atoms(
    rules: RuleSet,
    dist: TCDistribution,
    ramp: Ramp,
    *,
    tc_dependent_variance: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Collapse (true count x hand outcome) into one categorical distribution.

    For a ramp fixed in currency, both the bet and the result depend only on the
    true count, so the change in bankroll from one hand has finite support:
    len(counts) * len(BASE_OUTCOMES) atoms with known probabilities. Sampling
    that directly costs one lookup per hand instead of a true-count draw, three
    gathers and a second outcome draw. That speedup is what makes a horizon long
    enough to actually test ruin affordable.
    """
    counts = dist.counts()
    base_values, base_probs, base_mean, base_var = _base_arrays()
    base_sd = math.sqrt(base_var)
    means, sds = outcome_moments(
        rules, counts, tc_dependent_variance=tc_dependent_variance
    )
    bets = np.array([ramp.bet(t) for t in counts], dtype=np.float64)
    tc_probs = np.array([dist.p(t) for t in counts], dtype=np.float64)
    tc_probs /= tc_probs.sum()

    unit = means[:, None] + (base_values[None, :] - base_mean) * (
        sds[:, None] / base_sd
    )
    values = (bets[:, None] * unit).ravel()
    probs = (tc_probs[:, None] * base_probs[None, :]).ravel()
    return values, probs / probs.sum()


def outcome_moments(
    rules: RuleSet, counts: list[int], *, tc_dependent_variance: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """Target mean and standard deviation per unit bet, at each true count."""
    means = np.array([ev_at_tc(tc, rules) for tc in counts], dtype=np.float64)
    sds = np.array(
        [math.sqrt(variance_at_tc(tc, tc_dependent=tc_dependent_variance))
         for tc in counts],
        dtype=np.float64,
    )
    return means, sds


def simulate(
    rules: RuleSet,
    dist: TCDistribution,
    ramp: Ramp,
    *,
    bankroll: float,
    n_paths: int = 20_000,
    n_hands: int = 100_000,
    ruin_at: float = 0.0,
    outcome_model: str = "discrete",
    resize: bool = False,
    kelly_fraction: float = 0.40,
    tc_dependent_variance: bool = True,
    seed: int | None = 1234,
    block: int = 250,
) -> SimResult:
    """Play `n_paths` bankrolls through `n_hands` rounds each.

    `outcome_model="discrete"` draws from the realistic lumpy outcome table,
    affinely rescaled so its mean and variance match the analytic model at each
    count. `"normal"` draws Gaussian increments with the same moments. Comparing
    the two shows whether the shape of a hand result matters for ruin, which it
    largely does not -- ruin is a drift-and-diffusion phenomenon.

    `ruin_at=0.0` matches the barrier the closed form assumes. Passing the table
    minimum instead gives the practical answer: the point at which you can no
    longer place a bet.
    """
    if outcome_model not in ("discrete", "normal"):
        raise ValueError("outcome_model must be 'discrete' or 'normal'")
    if n_paths <= 0 or n_hands <= 0:
        raise ValueError("n_paths and n_hands must be positive")

    rng = np.random.default_rng(seed)
    counts = dist.counts()
    tc_probs = np.array([dist.p(t) for t in counts], dtype=np.float64)
    tc_probs /= tc_probs.sum()
    tc_cum = np.cumsum(tc_probs)

    bets = np.array([ramp.bet(t) for t in counts], dtype=np.float64)
    means, sds = outcome_moments(
        rules, counts, tc_dependent_variance=tc_dependent_variance
    )

    base_values, base_probs, base_mean, base_var = _base_arrays()
    base_cum = np.cumsum(base_probs)
    base_sd = math.sqrt(base_var)

    # Kelly weight per count, used only when resizing.
    kelly_w = np.array(
        [max(0.0, kelly_fraction * ev_at_tc(t, rules)
             / variance_at_tc(t, tc_dependent=tc_dependent_variance))
         for t in counts],
        dtype=np.float64,
    )
    sat_out = np.array([ramp.bet(t) <= 0 for t in counts], dtype=bool)

    # A fixed ramp with the lumpy outcome model needs only one categorical draw
    # per hand; everything else takes the general path.
    fast = (not resize) and outcome_model == "discrete"
    if fast:
        atom_values, atom_probs = collapse_to_atoms(
            rules, dist, ramp, tc_dependent_variance=tc_dependent_variance
        )
        atom_cum = np.cumsum(atom_probs)
        atom_cum[-1] = 1.0

    balance = np.full(n_paths, float(bankroll), dtype=np.float64)
    ruined = np.zeros(n_paths, dtype=bool)

    remaining = n_hands
    while remaining > 0:
        h = min(block, remaining)
        remaining -= h

        u = rng.random((n_paths, h))
        if fast:
            deltas = atom_values[np.searchsorted(atom_cum, u)]
        else:
            tc_idx = np.searchsorted(tc_cum, u)
            np.clip(tc_idx, 0, len(counts) - 1, out=tc_idx)

            if resize:
                # Bets track the current bankroll, clamped to the table as usual.
                size = balance[:, None] * kelly_w[tc_idx]
                np.clip(size, rules.table_min, rules.table_max, out=size)
                size[sat_out[tc_idx]] = 0.0
                hand_bets = size
            else:
                hand_bets = bets[tc_idx]

            if outcome_model == "normal":
                unit_result = means[tc_idx] + sds[tc_idx] * rng.standard_normal(
                    (n_paths, h)
                )
            else:
                v = rng.random((n_paths, h))
                drawn = base_values[np.searchsorted(base_cum, v)]
                # Affine map onto the target moments: keeps the lumpy shape and
                # matches mean and variance exactly.
                unit_result = means[tc_idx] + (drawn - base_mean) * (
                    sds[tc_idx] / base_sd
                )
            deltas = hand_bets * unit_result

        if ruined.any():
            deltas = np.where(ruined[:, None], 0.0, deltas)

        path = balance[:, None] + np.cumsum(deltas, axis=1)
        # First-passage: a path that dips below the barrier mid-block is ruined
        # even if it climbs back before the block ends.
        newly = (path.min(axis=1) <= ruin_at) & ~ruined
        balance = path[:, -1]
        balance[newly] = ruin_at
        ruined |= newly
        balance[ruined] = ruin_at

        if ruined.all():
            break

    rep = evaluate(rules, dist, ramp, bankroll=bankroll)
    analytic = risk_of_ruin(rep.win_rate_per_round, rep.variance_per_round, bankroll)

    profit = balance - bankroll
    warnings: list[str] = []
    survivors = (~ruined).sum()
    if survivors < 30 and not ruined.all():
        warnings.append(
            f"only {survivors} of {n_paths} paths survived; percentiles are noisy"
        )
    if rep.win_rate_per_round > 0:
        # Ruin is an infinite-horizon quantity. Check the horizon is long enough
        # that it has essentially converged, using N0 as the natural timescale.
        if n_hands < 20 * rep.n0_rounds:
            warnings.append(
                f"horizon of {n_hands:,} hands is short relative to N0 "
                f"({rep.n0_rounds:,.0f} hands); empirical ruin will come in below "
                f"the analytic infinite-horizon figure"
            )

    return SimResult(
        n_paths=n_paths,
        n_hands=n_hands,
        starting_bankroll=float(bankroll),
        currency=rules.currency,
        empirical_ror=float(ruined.mean()),
        analytic_ror=float(analytic),
        ruin_at=float(ruin_at),
        final_percentiles={
            f"p{q}": float(np.percentile(balance, q)) for q in (5, 25, 50, 75, 95)
        },
        fraction_profitable=float((profit > 0).mean()),
        mean_final=float(balance.mean()),
        median_final=float(np.median(balance)),
        analytic_expected_profit=float(rep.win_rate_per_round * n_hands),
        empirical_mean_profit=float(profit.mean()),
        outcome_model=outcome_model,
        resized=resize,
        warnings=warnings,
    )


def ruin_convergence(
    rules: RuleSet,
    dist: TCDistribution,
    ramp: Ramp,
    *,
    bankroll: float,
    horizons: tuple[int, ...] = (25_000, 50_000, 100_000, 200_000, 400_000),
    n_paths: int = 5_000,
    seed: int | None = 1234,
    **kwargs,
) -> list[dict]:
    """Empirical ruin as the horizon lengthens.

    The closed form is an infinite-horizon probability. A player with a finite
    number of hands in them faces less ruin risk than it implies, so the two
    numbers only meet once the horizon is long compared with the time the drift
    needs to carry the bankroll clear. This shows that convergence rather than
    asserting it.
    """
    rows = []
    for h in horizons:
        res = simulate(
            rules, dist, ramp, bankroll=bankroll, n_paths=n_paths,
            n_hands=h, seed=seed, **kwargs,
        )
        rows.append({
            "n_hands": h,
            "empirical_ror": res.empirical_ror,
            "analytic_ror": res.analytic_ror,
            "gap_points": res.ror_gap_points,
            "median_final": res.median_final,
            "fraction_profitable": res.fraction_profitable,
        })
    return rows
