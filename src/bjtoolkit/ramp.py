"""Bet ramps: how much to bet at each true count.

Two ways to build one, answering two different questions.

`kelly_ramp` answers "I have this bankroll, what should I bet?" It sizes each
bet as a fraction of full Kelly and then clamps to what the table and your cover
allow.

`spread_ramp` answers "I want to spread 1 to N, is that affordable?" It fixes
the shape and lets `risk.bankroll_for_ror` solve for the bankroll. This is the
one you want when the bankroll does not exist yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ev_model import ev_at_tc, variance_at_tc
from .frequency import TCDistribution
from .rules import RuleSet


def round_to_unit(x: float, unit: float) -> float:
    return round(x / unit) * unit if unit > 0 else x


@dataclass
class Ramp:
    """A bet for each true count, plus what got in the way of building it."""

    bets: dict[int, float]
    sat_out: set[int] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    rules: RuleSet | None = None

    def bet(self, tc: int) -> float:
        return 0.0 if tc in self.sat_out else self.bets.get(tc, 0.0)

    @property
    def played(self) -> dict[int, float]:
        return {t: b for t, b in self.bets.items() if t not in self.sat_out and b > 0}

    @property
    def spread(self) -> float:
        live = self.played
        if not live:
            return 0.0
        return max(live.values()) / min(live.values())

    @property
    def top_bet(self) -> float:
        live = self.played
        return max(live.values()) if live else 0.0

    @property
    def bottom_bet(self) -> float:
        live = self.played
        return min(live.values()) if live else 0.0


def _wong_set(
    dist: TCDistribution, wong_out_below: int | None
) -> set[int]:
    if wong_out_below is None:
        return set()
    return {t for t in dist.counts() if t < wong_out_below}


def kelly_ramp(
    rules: RuleSet,
    dist: TCDistribution,
    *,
    bankroll: float,
    kelly_fraction: float = 0.40,
    rounding_unit: float | None = None,
    max_spread: float | None = None,
    wong_out_below: int | None = None,
    tc_dependent_variance: bool = True,
) -> Ramp:
    """Fractional-Kelly bets, clamped to the table and to your cover limit."""
    unit = rounding_unit if rounding_unit is not None else rules.table_min
    sat_out = _wong_set(dist, wong_out_below)
    warnings: list[str] = []

    raw: dict[int, float] = {}
    for tc in dist.counts():
        edge = ev_at_tc(tc, rules)
        var = variance_at_tc(tc, tc_dependent=tc_dependent_variance)
        raw[tc] = max(0.0, kelly_fraction * edge / var * bankroll)

    cap = rules.table_max
    if max_spread is not None:
        cap = min(cap, rules.table_min * max_spread)
        if any(v > rules.table_min * max_spread for v in raw.values()):
            warnings.append(
                f"your cover limit of {max_spread:g}x is capping bets below what "
                f"Kelly wants -- you are deliberately leaving EV on the table"
            )

    if any(v > rules.table_max for v in raw.values()):
        warnings.append(
            f"the {rules.currency} {rules.table_max:,.0f} table maximum is "
            f"suppressing your top bets; a higher-limit table is worth real money"
        )

    bets: dict[int, float] = {}
    for tc in dist.counts():
        bet = min(max(raw[tc], rules.table_min), cap)
        bets[tc] = max(round_to_unit(bet, unit), rules.table_min)

    ramp = Ramp(bets=bets, sat_out=sat_out, warnings=warnings, rules=rules)

    # The bankroll-too-small test that matters: at your first advantage count,
    # does Kelly even want a table-minimum bet? If not, every bet you place at an
    # advantage is an overbet forced on you by the table.
    advantage_counts = [t for t in dist.counts() if ev_at_tc(t, rules) > 0
                        and t not in sat_out]
    if advantage_counts:
        first = min(advantage_counts)
        if raw[first] < rules.table_min:
            needed = (
                rules.table_min
                * variance_at_tc(first, tc_dependent=tc_dependent_variance)
                / (kelly_fraction * ev_at_tc(first, rules))
            )
            warnings.append(
                f"bankroll too small for this table: at TC {first:+d} (your first "
                f"advantage count) Kelly wants {rules.currency} {raw[first]:,.0f} "
                f"but the minimum is {rules.currency} {rules.table_min:,.0f}. "
                f"You would need ~{rules.currency} {needed:,.0f} to bet this table "
                f"properly at {kelly_fraction:g} Kelly."
            )
    if ramp.spread and ramp.spread < 2:
        warnings.append(
            f"realised spread is only {ramp.spread:.1f}x -- too flat to overcome "
            f"the off-the-top house edge"
        )
    return ramp


def spread_ramp(
    rules: RuleSet,
    dist: TCDistribution,
    *,
    max_spread: float,
    unit: float | None = None,
    wong_out_below: int | None = None,
    rounding_unit: float | None = None,
    tc_dependent_variance: bool = True,
) -> Ramp:
    """A Kelly-*shaped* ramp scaled to a chosen spread, independent of bankroll.

    The shape is proportional to edge/variance, exactly as Kelly would be; only
    the scale is set by `max_spread` rather than by a bankroll. This is what lets
    `bankroll_for_ror` be a real solve instead of a fixed-point chase.
    """
    unit = unit if unit is not None else rules.table_min
    rounding = rounding_unit if rounding_unit is not None else unit
    sat_out = _wong_set(dist, wong_out_below)
    warnings: list[str] = []

    shape = {
        tc: max(0.0, ev_at_tc(tc, rules))
        / variance_at_tc(tc, tc_dependent=tc_dependent_variance)
        for tc in dist.counts()
    }
    live = [v for t, v in shape.items() if t not in sat_out]
    peak = max(live) if live else 0.0

    bets: dict[int, float] = {}
    for tc in dist.counts():
        if peak <= 0:
            bets[tc] = unit
            continue
        # Scale so the best count sits at max_spread units, floor at one unit.
        scaled = unit + (max_spread - 1.0) * unit * (shape[tc] / peak)
        bets[tc] = max(round_to_unit(scaled, rounding), unit)

    if unit * max_spread > rules.table_max:
        warnings.append(
            f"a {max_spread:g}x spread off a {rules.currency} {unit:,.0f} unit needs "
            f"a top bet of {rules.currency} {unit * max_spread:,.0f}, above this "
            f"table's maximum of {rules.currency} {rules.table_max:,.0f}"
        )
    if unit < rules.table_min:
        warnings.append(
            f"unit {rules.currency} {unit:,.0f} is below the table minimum of "
            f"{rules.currency} {rules.table_min:,.0f}"
        )
    return Ramp(bets=bets, sat_out=sat_out, warnings=warnings, rules=rules)
