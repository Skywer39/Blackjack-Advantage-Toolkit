"""Is this game worth playing, and what would it take?

This is the question the toolkit exists to answer. A bet ramp is only useful
once you know the game supports one; most real tables, for most real bankrolls,
do not. Answering "no, and here is what would change that" is a first-class
result here, not an error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .ev_model import breakeven_tc, ev_at_tc
from .frequency import TCDistribution, load_or_simulate
from .ramp import spread_ramp
from .risk import bankroll_for_ror, evaluate, risk_of_ruin
from .rules import RuleSet, base_edge, base_edge_range


@dataclass
class SpreadOption:
    """One candidate spread, costed out."""

    max_spread: float
    unit: float
    top_bet: float
    required_bankroll: float
    win_rate_per_hour: float
    sd_per_hour: float
    n0_hours: float
    fits_table: bool
    affordable: bool
    ror_at_bankroll: float | None = None

    @property
    def viable(self) -> bool:
        return (
            self.fits_table
            and self.affordable
            and self.win_rate_per_hour > 0
            and math.isfinite(self.required_bankroll)
        )


@dataclass
class ViabilityReport:
    rules: RuleSet
    base_edge: float
    base_edge_range: tuple[float, float]
    breakeven_tc: float
    prob_advantage: float
    rounds_per_shoe: float
    options: list[SpreadOption]
    bankroll: float | None
    target_ror: float
    verdict: str
    notes: list[str]


def assess(
    rules: RuleSet,
    *,
    bankroll: float | None = None,
    target_ror: float = 0.05,
    spreads: tuple[float, ...] = (2, 4, 6, 8, 12, 16, 20),
    unit: float | None = None,
    wong_out_below: int | None = None,
    rounds_per_hour: int = 70,
    dist: TCDistribution | None = None,
) -> ViabilityReport:
    dist = dist or load_or_simulate(rules)
    unit = unit if unit is not None else rules.table_min
    edge = base_edge(rules)
    be_tc = breakeven_tc(rules)
    prob_adv = sum(
        dist.p(t) for t in dist.counts() if ev_at_tc(t, rules) > 0
    )

    options: list[SpreadOption] = []
    for spread in spreads:
        ramp = spread_ramp(
            rules, dist, max_spread=spread, unit=unit,
            wong_out_below=wong_out_below,
        )
        rep = evaluate(rules, dist, ramp, rounds_per_hour=rounds_per_hour)
        required = bankroll_for_ror(
            target_ror, rep.win_rate_per_round, rep.variance_per_round
        )
        top = unit * spread
        options.append(
            SpreadOption(
                max_spread=spread,
                unit=unit,
                top_bet=top,
                required_bankroll=required,
                win_rate_per_hour=rep.win_rate_per_hour,
                sd_per_hour=rep.sd_per_hour,
                n0_hours=rep.n0_hours,
                fits_table=top <= rules.table_max,
                affordable=bankroll is None or required <= bankroll,
                ror_at_bankroll=(
                    None
                    if bankroll is None
                    else risk_of_ruin(
                        rep.win_rate_per_round, rep.variance_per_round, bankroll
                    )
                ),
            )
        )

    notes: list[str] = []
    viable = [o for o in options if o.viable]

    if rules.blackjack_payout < 1.5:
        notes.append(
            f"blackjack pays {rules.blackjack_payout}:1, not 3:2. This costs about "
            f"{abs(rules.blackjack_payout - 1.5) / 0.3 * 1.39:.1f}% and is close to "
            f"unbeatable by counting. Walk away from this table."
        )
    if rules.penetration_fraction < 0.6:
        notes.append(
            f"penetration is only {rules.penetration_fraction:.0%} of the shoe. "
            f"High counts barely occur; this is usually what kills a game."
        )
    if rules.max_table_spread < 8:
        notes.append(
            f"the table's own min/max only allows a {rules.max_table_spread:.0f}x "
            f"spread, before any consideration of heat."
        )

    if not viable:
        blocked_by_table = [o for o in options if not o.fits_table and o.affordable]
        if bankroll is not None and all(not o.affordable for o in options):
            cheapest = min(options, key=lambda o: o.required_bankroll)
            verdict = (
                f"NOT VIABLE at {rules.currency} {bankroll:,.0f}. The smallest "
                f"spread that beats this game needs about {rules.currency} "
                f"{cheapest.required_bankroll:,.0f} for {target_ror:.0%} risk of ruin."
            )
        elif blocked_by_table:
            verdict = (
                "NOT VIABLE: the spread this game needs does not fit between the "
                "table minimum and maximum."
            )
        else:
            verdict = "NOT VIABLE: no spread produces a positive win rate here."
    else:
        best = max(viable, key=lambda o: o.win_rate_per_hour)
        verdict = (
            f"VIABLE at up to {best.max_spread:g}x spread: about {rules.currency} "
            f"{best.win_rate_per_hour:,.0f}/hour, needing {rules.currency} "
            f"{best.required_bankroll:,.0f} bankroll for {target_ror:.0%} risk of ruin."
        )
        if best.n0_hours > 500:
            notes.append(
                f"N0 is {best.n0_hours:,.0f} hours at that spread -- that is how long "
                f"before your expected win equals one standard deviation. Short-term "
                f"results here tell you essentially nothing about whether you are "
                f"playing correctly."
            )

    return ViabilityReport(
        rules=rules,
        base_edge=edge,
        base_edge_range=base_edge_range(rules),
        breakeven_tc=be_tc,
        prob_advantage=prob_adv,
        rounds_per_shoe=dist.rounds_per_shoe,
        options=options,
        bankroll=bankroll,
        target_ror=target_ror,
        verdict=verdict,
        notes=notes,
    )


def penetration_sweep(
    rules: RuleSet,
    *,
    penetrations: tuple[float, ...] | None = None,
    max_spread: float = 12,
    target_ror: float = 0.05,
    unit: float | None = None,
    wong_out_below: int | None = None,
    rounds_per_hour: int = 70,
    n_shoes: int = 20_000,
) -> list[dict]:
    """How the game changes as the dealer cuts deeper. Usually the biggest lever."""
    if penetrations is None:
        penetrations = tuple(
            round(rules.decks * f, 2) for f in (0.5, 0.58, 0.67, 0.75, 0.83, 0.88)
        )
    unit = unit if unit is not None else rules.table_min
    rows = []
    for pen in penetrations:
        if pen >= rules.decks:
            continue
        r = rules.model_copy(deep=True)
        r.penetration_decks_dealt = pen
        dist = load_or_simulate(r, n_shoes=n_shoes)
        ramp = spread_ramp(r, dist, max_spread=max_spread, unit=unit,
                           wong_out_below=wong_out_below)
        rep = evaluate(r, dist, ramp, rounds_per_hour=rounds_per_hour)
        rows.append({
            "penetration_decks": pen,
            "penetration_pct": pen / r.decks,
            "rounds_per_shoe": dist.rounds_per_shoe,
            "prob_tc_ge_2": dist.prob_at_or_above(2),
            "prob_tc_ge_4": dist.prob_at_or_above(4),
            "win_rate_per_hour": rep.win_rate_per_hour,
            "n0_hours": rep.n0_hours,
            "required_bankroll": bankroll_for_ror(
                target_ror, rep.win_rate_per_round, rep.variance_per_round
            ),
        })
    return rows
