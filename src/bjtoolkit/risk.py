"""Win rate, variance, N0, risk of ruin, and the bankroll solve.

A note on the solve, because the obvious version of it is wrong.

If your bets scale with your bankroll (which is what Kelly means), then
win_rate is proportional to B and variance is proportional to B^2, so the ruin
exponent 2*wr*B/var is scale-invariant: risk of ruin does not depend on your
bankroll at all. It depends only on what fraction of Kelly you bet. Trying to
"solve for the bankroll that gives 5% ruin" against Kelly-sized bets is a
fixed-point chase whose answer just tracks whatever bankroll you fed in.

So there are two honest questions, and this module answers both separately:

  bankroll_for_ror  -- given a FIXED ramp in currency, what bankroll do I need?
  kelly_for_ror     -- given proportional betting, what Kelly fraction may I use?

Wonging is handled by keeping everything per *round observed at the table*
rather than per round played. That way sitting out is just a bet of zero and the
arithmetic stays honest about the hours you spend not betting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .ev_model import ev_at_tc, variance_at_tc
from .frequency import TCDistribution
from .ramp import Ramp
from .rules import RuleSet


def _phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class RiskReport:
    currency: str
    rounds_per_hour: int

    fraction_of_rounds_played: float
    win_rate_per_round: float
    """Per round OBSERVED at the table, counting sat-out rounds as zero."""
    win_rate_per_played_hand: float
    variance_per_round: float
    sd_per_round: float

    win_rate_per_hour: float
    sd_per_hour: float
    hands_played_per_hour: float

    n0_rounds: float
    n0_hours: float

    bankroll: float | None = None
    risk_of_ruin: float | None = None

    hours_planned: float = 0.0
    expected_profit: float = 0.0
    sd_over_planned: float = 0.0
    prob_of_profit: float = 0.0

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items()
        }


def evaluate(
    rules: RuleSet,
    dist: TCDistribution,
    ramp: Ramp,
    *,
    bankroll: float | None = None,
    rounds_per_hour: int = 70,
    hours_planned: float = 100.0,
    tc_dependent_variance: bool = True,
) -> RiskReport:
    """Integrate the ramp against the true-count distribution."""
    wr = 0.0
    var = 0.0
    played_p = 0.0
    for tc in dist.counts():
        p = dist.p(tc)
        bet = ramp.bet(tc)
        if bet <= 0:
            continue
        played_p += p
        wr += p * bet * ev_at_tc(tc, rules)
        var += p * bet**2 * variance_at_tc(tc, tc_dependent=tc_dependent_variance)

    sd = math.sqrt(var) if var > 0 else 0.0
    warnings = list(ramp.warnings)

    if wr <= 0:
        warnings.append(
            "this configuration is EV-NEGATIVE: you would lose money playing it. "
            "The ramp is too flat, the penetration too shallow, or the rules too "
            "poor to beat the house edge you pay on low counts."
        )

    n0_rounds = var / wr**2 if wr > 0 else math.inf
    ror = None
    if bankroll is not None:
        ror = risk_of_ruin(wr, var, bankroll)

    expected = wr * rounds_per_hour * hours_planned
    sd_planned = sd * math.sqrt(rounds_per_hour * hours_planned)
    prob_profit = _phi(expected / sd_planned) if sd_planned > 0 else 0.0

    return RiskReport(
        currency=rules.currency,
        rounds_per_hour=rounds_per_hour,
        fraction_of_rounds_played=played_p,
        win_rate_per_round=wr,
        win_rate_per_played_hand=wr / played_p if played_p > 0 else 0.0,
        variance_per_round=var,
        sd_per_round=sd,
        win_rate_per_hour=wr * rounds_per_hour,
        sd_per_hour=sd * math.sqrt(rounds_per_hour),
        hands_played_per_hour=played_p * rounds_per_hour,
        n0_rounds=n0_rounds,
        n0_hours=n0_rounds / rounds_per_hour if math.isfinite(n0_rounds) else math.inf,
        bankroll=bankroll,
        risk_of_ruin=ror,
        hours_planned=hours_planned,
        expected_profit=expected,
        sd_over_planned=sd_planned,
        prob_of_profit=prob_profit,
        warnings=warnings,
    )


def risk_of_ruin(
    win_rate_per_round: float, variance_per_round: float, bankroll: float
) -> float:
    """Probability of losing the whole bankroll, playing forever.

    The standard exponential approximation. It assumes the ramp stays fixed in
    currency terms as the bankroll moves, which is true for a flat unit and false
    for strict Kelly resizing -- see the module docstring.
    """
    if win_rate_per_round <= 0:
        return 1.0
    if variance_per_round <= 0:
        return 0.0
    return math.exp(-2.0 * win_rate_per_round * bankroll / variance_per_round)


def bankroll_for_ror(
    target_ror: float, win_rate_per_round: float, variance_per_round: float
) -> float:
    """Bankroll needed to hold a FIXED ramp at a target risk of ruin.

    Only meaningful when the ramp is fixed in currency -- build it with
    `ramp.spread_ramp`, not `ramp.kelly_ramp`. Feeding this the output of a
    bankroll-sized ramp is the circularity described in the module docstring.
    """
    if not 0.0 < target_ror < 1.0:
        raise ValueError("target_ror must be strictly between 0 and 1")
    if win_rate_per_round <= 0:
        return math.inf
    return -math.log(target_ror) * variance_per_round / (2.0 * win_rate_per_round)


def kelly_for_ror(target_ror: float) -> float:
    """The Kelly fraction implied by a target risk of ruin.

    From RoR = exp(-2/f) for proportional betting: full Kelly gives ~13.5% ruin,
    half Kelly ~1.8%. This is the correct inverse when your bets scale with your
    bankroll, and it is independent of the bankroll's size.
    """
    if not 0.0 < target_ror < 1.0:
        raise ValueError("target_ror must be strictly between 0 and 1")
    return -2.0 / math.log(target_ror)


def ror_for_kelly(kelly_fraction: float) -> float:
    """Risk of ruin implied by proportional betting at this Kelly fraction."""
    if kelly_fraction <= 0:
        return 0.0
    return math.exp(-2.0 / kelly_fraction)
