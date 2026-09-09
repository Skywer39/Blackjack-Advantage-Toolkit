"""Rule sets for any blackjack game, and the player edge they imply.

The design goal is that a game anywhere in the world can be described here:
Czech ENHC, Vegas Strip, downtown single deck, a 6:5 tourist trap. `base_edge`
is an additive model over `constants.py`, so every toggle moves the number and
nothing is baked in for one casino.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from . import constants as C
from .constants import Estimate


class Surrender(str, Enum):
    NONE = "none"
    LATE_VS_10 = "late_vs_10"
    LATE_VS_9_10 = "late_vs_9_10"
    LATE_ALL = "late_all"
    EARLY_VS_10 = "early_vs_10"
    EARLY_ALL = "early_all"

    @property
    def is_early(self) -> bool:
        return self in (Surrender.EARLY_VS_10, Surrender.EARLY_ALL)


class HoleCard(str, Enum):
    """How the dealer's second card is handled."""

    PEEK = "peek"
    """US style: dealer takes a hole card and checks it for blackjack."""

    ENHC_ORIGINAL_ONLY = "enhc_original_only"
    """No hole card, but only your original bet is lost to a dealer blackjack."""

    ENHC_ALL_BETS = "enhc_all_bets"
    """No hole card, and doubled/split bets are lost too. Needs strategy changes."""

    @property
    def is_enhc(self) -> bool:
        return self is not HoleCard.PEEK


class DoubleRule(str, Enum):
    ANY_TWO = "any_two"
    NINE_TO_ELEVEN = "9_to_11"
    TEN_ELEVEN = "10_11"


class RuleSet(BaseModel):
    """A complete description of one blackjack game."""

    name: str = "custom"

    decks: int = Field(6, ge=1, le=8)
    dealer_hits_soft_17: bool = False
    double_rule: DoubleRule = DoubleRule.ANY_TWO
    double_after_split: bool = True
    resplit_aces: bool = False
    max_split_hands: int = Field(4, ge=2, le=4)
    surrender: Surrender = Surrender.NONE
    hole_card: HoleCard = HoleCard.PEEK
    blackjack_payout: float = Field(1.5, gt=0)

    penetration_decks_dealt: float = Field(4.5, gt=0)
    """Decks dealt before the shuffle. The single most leveraged rule there is."""

    players_at_table: int = Field(1, ge=1, le=7)
    """Including you. Sets how many cards a round burns, so how many betting
    decisions you get per shoe."""

    table_min: float = 200.0
    table_max: float = 5000.0
    currency: str = "CZK"

    @model_validator(mode="after")
    def _check(self) -> RuleSet:
        if self.penetration_decks_dealt >= self.decks:
            raise ValueError(
                f"penetration_decks_dealt ({self.penetration_decks_dealt}) must be "
                f"less than decks ({self.decks}) -- you cannot deal the whole shoe"
            )
        if self.table_max <= self.table_min:
            raise ValueError("table_max must exceed table_min")
        return self

    @property
    def penetration_fraction(self) -> float:
        return self.penetration_decks_dealt / self.decks

    @property
    def max_table_spread(self) -> float:
        return self.table_max / self.table_min


def _deck_effect(decks: int) -> Estimate:
    """Interpolate the deck-count effect for counts not in the published table."""
    if decks in C.DECK_EFFECT:
        return C.DECK_EFFECT[decks]
    known = sorted(C.DECK_EFFECT)
    lo = max(d for d in known if d < decks)
    hi = min(d for d in known if d > decks)
    t = (decks - lo) / (hi - lo)
    a, b = C.DECK_EFFECT[lo], C.DECK_EFFECT[hi]
    return Estimate(
        a.value + t * (b.value - a.value),
        a.low + t * (b.low - a.low),
        a.high + t * (b.high - a.high),
        f"interpolated between {lo} and {hi} decks",
    )


def edge_components(rules: RuleSet) -> list[tuple[str, Estimate]]:
    """The additive breakdown of the player's off-the-top edge.

    Returned as an ordered list so the CLI can show its work -- the point of the
    tool is that you can see which rule is costing you what.
    """
    parts: list[tuple[str, Estimate]] = [
        ("baseline (8D, S17, DAS, 3:2, peek)", C.BASELINE_8D),
    ]

    if rules.decks != 8:
        parts.append((f"{rules.decks} decks instead of 8", _deck_effect(rules.decks)))

    if rules.dealer_hits_soft_17:
        parts.append(("dealer hits soft 17", C.HITS_SOFT_17))

    if rules.double_rule is DoubleRule.NINE_TO_ELEVEN:
        parts.append(("double 9-11 only", C.DOUBLE_9_TO_11))
    elif rules.double_rule is DoubleRule.TEN_ELEVEN:
        parts.append(("double 10-11 only", C.DOUBLE_10_11))

    if not rules.double_after_split:
        parts.append(("no double after split", C.NO_DAS))

    if rules.resplit_aces:
        parts.append(("resplit aces", C.RESPLIT_ACES))

    if rules.max_split_hands == 2:
        parts.append(("split to 2 hands only", C.SPLIT_TO_2_HANDS))
    elif rules.max_split_hands == 3:
        parts.append(("split to 3 hands only", C.SPLIT_TO_3_HANDS))

    surrender_effect = {
        Surrender.NONE: None,
        Surrender.LATE_VS_10: ("late surrender vs 10", C.LATE_SURRENDER_VS_10),
        Surrender.LATE_VS_9_10: ("late surrender vs 9-10", C.LATE_SURRENDER_VS_9_10),
        Surrender.LATE_ALL: ("late surrender", C.LATE_SURRENDER_ALL),
        Surrender.EARLY_VS_10: ("early surrender vs 10", C.EARLY_SURRENDER_VS_10),
        Surrender.EARLY_ALL: ("early surrender", C.EARLY_SURRENDER_ALL),
    }[rules.surrender]
    if surrender_effect is not None:
        parts.append(surrender_effect)

    if rules.hole_card is HoleCard.ENHC_ORIGINAL_ONLY:
        parts.append(("no hole card, original bet only", C.ENHC_ORIGINAL_BET_ONLY))
    elif rules.hole_card is HoleCard.ENHC_ALL_BETS:
        parts.append(("no hole card, all bets lost", C.ENHC_ALL_BETS_LOST))

    payout = round(rules.blackjack_payout, 4)
    if payout != 1.5:
        known = {1.2: C.BJ_PAYS_6_5, 1.4: C.BJ_PAYS_7_5, 1.0: C.BJ_PAYS_1_1}
        if payout in known:
            parts.append((f"blackjack pays {payout}:1", known[payout]))
        else:
            # Linear in the payout shortfall; a natural occurs ~4.75% of hands.
            scaled = C.BJ_PAYS_6_5.value * (1.5 - payout) / 0.3
            parts.append((
                f"blackjack pays {payout}:1",
                Estimate(scaled, scaled * 1.1, scaled * 0.9,
                         "scaled linearly from the 6:5 figure"),
            ))

    return parts


def base_edge(rules: RuleSet) -> float:
    """Player edge off the top, before counting. Negative means house favoured."""
    return sum(e.value for _, e in edge_components(rules))


def base_edge_range(rules: RuleSet) -> tuple[float, float]:
    """Worst and best case edge, given the uncertainty on each component."""
    parts = edge_components(rules)
    return (sum(e.low for _, e in parts), sum(e.high for _, e in parts))


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, RuleSet] = {
    "ambassador": RuleSet(
        name="Casino Ambassador (Prague) -- UNVERIFIED, see docs/open-questions.md",
        decks=6,
        dealer_hits_soft_17=False,
        double_after_split=True,
        resplit_aces=False,
        max_split_hands=4,
        surrender=Surrender.LATE_VS_9_10,
        hole_card=HoleCard.ENHC_ALL_BETS,
        penetration_decks_dealt=4.5,
        table_min=200.0,
        table_max=5000.0,
        currency="CZK",
    ),
    "vegas-strip": RuleSet(
        name="Vegas Strip 6-deck (S17, DAS, LS)",
        decks=6, dealer_hits_soft_17=False, surrender=Surrender.LATE_ALL,
        penetration_decks_dealt=4.5, table_min=25.0, table_max=2000.0,
        currency="USD",
    ),
    "vegas-h17": RuleSet(
        name="Vegas 6-deck H17 (the common downtown game)",
        decks=6, dealer_hits_soft_17=True, surrender=Surrender.LATE_ALL,
        penetration_decks_dealt=4.5, table_min=15.0, table_max=1000.0,
        currency="USD",
    ),
    "vegas-8d": RuleSet(
        name="Vegas 8-deck H17, no surrender",
        decks=8, dealer_hits_soft_17=True, surrender=Surrender.NONE,
        penetration_decks_dealt=6.0, table_min=10.0, table_max=1000.0,
        currency="USD",
    ),
    "single-deck": RuleSet(
        name="Single deck S17, double 10-11 only",
        decks=1, dealer_hits_soft_17=False, double_rule=DoubleRule.TEN_ELEVEN,
        double_after_split=False, max_split_hands=2,
        penetration_decks_dealt=0.65, table_min=25.0, table_max=500.0,
        currency="USD",
    ),
    "double-deck": RuleSet(
        name="Double deck H17, DAS",
        decks=2, dealer_hits_soft_17=True, penetration_decks_dealt=1.5,
        table_min=25.0, table_max=1000.0, currency="USD",
    ),
    "six-five": RuleSet(
        name="6:5 tourist table -- do not play this",
        decks=6, dealer_hits_soft_17=True, blackjack_payout=1.2,
        penetration_decks_dealt=4.0, table_min=10.0, table_max=500.0,
        currency="USD",
    ),
    "uk-enhc": RuleSet(
        name="UK/European 6-deck ENHC, S17",
        decks=6, dealer_hits_soft_17=False, hole_card=HoleCard.ENHC_ALL_BETS,
        surrender=Surrender.NONE, penetration_decks_dealt=4.5,
        table_min=10.0, table_max=500.0, currency="GBP",
    ),
}


def get_preset(name: str) -> RuleSet:
    try:
        return PRESETS[name].model_copy(deep=True)
    except KeyError:
        raise KeyError(
            f"unknown preset {name!r}; available: {', '.join(sorted(PRESETS))}"
        ) from None
