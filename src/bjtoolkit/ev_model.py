"""Player edge as a function of true count.

The model is linear: EV(tc) = base_edge(rules) + slope * tc. This is the
standard approximation behind every simple betting tool, and it is good to
roughly a hundredth of a percent over the true-count range you actually bet in.

It is NOT good enough to claim an exact edge, and it degrades at extreme counts
where the real curve flattens. For exact figures you need a combinatorial
analyzer (CVData/CVCX) or full-hand simulation. See docs/open-questions.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import constants as C
from .rules import RuleSet, base_edge, base_edge_range


def ev_at_tc(tc: float, rules: RuleSet, *, slope: float | None = None) -> float:
    """Player edge (decimal, positive = player advantage) at a true count."""
    return base_edge(rules) + (C.HILO_SLOPE.value if slope is None else slope) * tc


def variance_at_tc(tc: float, *, tc_dependent: bool = True) -> float:
    """Variance per unit wagered.

    Rises with the count: at high counts you double and split more, so more of
    your money is on the table per round. Ignoring this understates risk of ruin
    precisely where your bets are biggest.
    """
    if not tc_dependent:
        return C.HAND_VARIANCE.value
    return C.HAND_VARIANCE.value + C.HAND_VARIANCE_TC_SLOPE.value * max(0.0, tc)


def breakeven_tc(rules: RuleSet, *, slope: float | None = None) -> float:
    """The true count at which you stop losing money. Your wong-in point."""
    s = C.HILO_SLOPE.value if slope is None else slope
    return -base_edge(rules) / s


@dataclass
class Sensitivity:
    """How much a conclusion moves when the inputs move within their range."""

    label: str
    low: float
    point: float
    high: float

    @property
    def swing(self) -> float:
        return self.high - self.low


def ev_sensitivity(tc: float, rules: RuleSet) -> list[Sensitivity]:
    """Edge at a true count under the pessimistic, point and optimistic inputs."""
    edge_lo, edge_hi = base_edge_range(rules)
    point = ev_at_tc(tc, rules)
    return [
        Sensitivity(
            "rule edge uncertainty",
            edge_lo + C.HILO_SLOPE.value * tc,
            point,
            edge_hi + C.HILO_SLOPE.value * tc,
        ),
        Sensitivity(
            "Hi-Lo slope uncertainty",
            base_edge(rules) + C.HILO_SLOPE.low * tc,
            point,
            base_edge(rules) + C.HILO_SLOPE.high * tc,
        ),
        Sensitivity(
            "both, worst and best case",
            edge_lo + C.HILO_SLOPE.low * tc,
            point,
            edge_hi + C.HILO_SLOPE.high * tc,
        ),
    ]
