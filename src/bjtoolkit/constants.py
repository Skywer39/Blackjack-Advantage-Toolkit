"""Every empirical number in the toolkit, in one place, with a source and a range.

Nothing else in the package is allowed to hard-code a magic number. If you find
one elsewhere, it is a bug.

Each value is an `Estimate`: a point value plus a plausible range and a citation.
The range is not decoration -- `sensitivity()` in `ev_model.py` re-runs the whole
model at the range endpoints so you can see which assumptions your conclusions
actually depend on.

Provenance: these are the standard published rule-effect figures (Wizard of Odds
rule-variation tables, Griffin's *Theory of Blackjack*, Schlesinger's *Blackjack
Attack*). They are reconstructed here from those references rather than
recomputed from a combinatorial analyzer. Treat them as good to ~0.02% absolute,
which is fine for bankroll and ramp planning and not fine for claiming an exact
edge.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Estimate:
    """A number we do not know exactly."""

    value: float
    low: float
    high: float
    source: str

    def __post_init__(self) -> None:
        if not self.low <= self.value <= self.high:
            raise ValueError(f"{self.value} outside [{self.low}, {self.high}]")

    @property
    def uncertainty(self) -> float:
        return (self.high - self.low) / 2.0


def E(value: float, low: float, high: float, source: str) -> Estimate:
    return Estimate(value, low, high, source)


WOO = "Wizard of Odds, rule variation table"
GRIFFIN = "Griffin, Theory of Blackjack"
SCHLESINGER = "Schlesinger, Blackjack Attack (3rd ed.)"

# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------
# Player edge for the reference game:
#   8 decks, S17, double any two, DAS, split to 4, no resplit aces,
#   no surrender, blackjack 3:2, dealer peeks for blackjack.
# Every other rule in this file is a delta applied on top of this.
BASELINE_8D = E(-0.00430, -0.00460, -0.00400, WOO)

# Effect of deck count, relative to the 8-deck baseline. Fewer decks help the
# player: more favourable composition-dependent plays and richer doubles.
DECK_EFFECT = {
    1: E(0.00480, 0.00450, 0.00510, WOO),
    2: E(0.00190, 0.00170, 0.00210, WOO),
    4: E(0.00060, 0.00050, 0.00070, WOO),
    5: E(0.00030, 0.00020, 0.00040, WOO),
    6: E(0.00020, 0.00015, 0.00025, WOO),
    8: E(0.00000, 0.00000, 0.00000, WOO),
}

# ---------------------------------------------------------------------------
# Dealer rules
# ---------------------------------------------------------------------------
# Applied when the dealer HITS soft 17 (the baseline stands).
HITS_SOFT_17 = E(-0.00220, -0.00230, -0.00200, WOO)

# ---------------------------------------------------------------------------
# Doubling
# ---------------------------------------------------------------------------
DOUBLE_9_TO_11 = E(-0.00090, -0.00100, -0.00080, WOO)
DOUBLE_10_11 = E(-0.00180, -0.00200, -0.00160, WOO)
NO_DAS = E(-0.00140, -0.00150, -0.00130, WOO)

# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------
RESPLIT_ACES = E(0.00080, 0.00060, 0.00090, WOO)
SPLIT_TO_2_HANDS = E(-0.00010, -0.00030, -0.00005, WOO)
SPLIT_TO_3_HANDS = E(-0.00005, -0.00015, 0.00000, WOO)

# ---------------------------------------------------------------------------
# Surrender
# ---------------------------------------------------------------------------
# Late surrender: resolved after the dealer checks for blackjack, so a dealer
# blackjack takes the full bet and the surrender never happens.
LATE_SURRENDER_VS_10 = E(0.00060, 0.00050, 0.00070, WOO)
LATE_SURRENDER_VS_9_10 = E(0.00070, 0.00060, 0.00080, WOO)
LATE_SURRENDER_ALL = E(0.00080, 0.00070, 0.00090, WOO)

# Early surrender: resolved BEFORE the dealer's blackjack is known, so you keep
# half your bet even when the dealer would have had one. Worth far more.
EARLY_SURRENDER_VS_10 = E(0.00240, 0.00210, 0.00270, WOO)
EARLY_SURRENDER_ALL = E(0.00630, 0.00580, 0.00680, WOO)

# ---------------------------------------------------------------------------
# Blackjack payout
# ---------------------------------------------------------------------------
# Relative to 3:2. These are large enough to swamp everything else in this file.
BJ_PAYS_6_5 = E(-0.01390, -0.01450, -0.01350, WOO)
BJ_PAYS_7_5 = E(-0.00450, -0.00480, -0.00430, WOO)
BJ_PAYS_1_1 = E(-0.02270, -0.02350, -0.02200, WOO)

# ---------------------------------------------------------------------------
# Hole card
# ---------------------------------------------------------------------------
# ENHC where only the original bet is lost to a dealer blackjack (OBO) plays
# identically to a US peek game -- the dealer's blackjack costs you exactly what
# it would have cost with a peek.
ENHC_ORIGINAL_BET_ONLY = E(0.00000, 0.00000, 0.00000, GRIFFIN)

# Full ENHC: doubled and split bets are also lost to a dealer blackjack. This
# figure ASSUMES you play the ENHC-corrected basic strategy (no doubling or
# splitting into the exposure). Playing the US chart in an ENHC game costs
# roughly twice this.
ENHC_ALL_BETS_LOST = E(-0.00110, -0.00130, -0.00090, GRIFFIN)

# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------
# Player edge gained per +1 true count, Hi-Lo. Fairly insensitive to rules and
# to deck count; the betting correlation of Hi-Lo (~0.97) is what sets it.
HILO_SLOPE = E(0.00500, 0.00450, 0.00550, SCHLESINGER)

# Variance per unit wagered, flat-betting basic strategy. Rises at high counts
# because you double and split more often -- see HAND_VARIANCE_TC_SLOPE.
HAND_VARIANCE = E(1.32, 1.26, 1.38, SCHLESINGER)

# Additional variance per +1 true count. At TC +5 this takes 1.32 to about 1.42,
# which matches the usual quoted range for a counter's high-count hands.
HAND_VARIANCE_TC_SLOPE = E(0.020, 0.010, 0.030, SCHLESINGER)

# Cards consumed per player-hand per round, including the dealer's hand. Used to
# convert penetration into a number of betting decisions per shoe.
CARDS_PER_HAND = E(2.70, 2.50, 2.90, SCHLESINGER)


ALL_ESTIMATES: dict[str, Estimate] = {
    name: obj
    for name, obj in list(globals().items())
    if isinstance(obj, Estimate)
}
