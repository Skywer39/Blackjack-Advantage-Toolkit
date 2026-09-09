"""Card counting systems and true-count conversion."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

# Rank 11 is the Ace. Ranks 2-9 are themselves, 10 covers T/J/Q/K.
RANKS = list(range(2, 12))
CARDS_PER_RANK_PER_DECK = {r: 4 for r in range(2, 10)} | {10: 16, 11: 4}


class CountSystem(BaseModel):
    name: str = "Hi-Lo"
    tags: dict[int, int] = Field(
        default_factory=lambda: {
            2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 0, 8: 0, 9: 0, 10: -1, 11: -1
        }
    )
    level: int = 1

    @property
    def balanced(self) -> bool:
        return sum(self.tags[r] * CARDS_PER_RANK_PER_DECK[r] for r in RANKS) == 0

    def shoe_tags(self, decks: int) -> np.ndarray:
        """Every card in a fresh shoe, as its count tag."""
        out: list[int] = []
        for rank in RANKS:
            out.extend([self.tags[rank]] * (CARDS_PER_RANK_PER_DECK[rank] * decks))
        return np.array(out, dtype=np.int8)


HI_LO = CountSystem()

KO = CountSystem(
    name="KO",
    tags={2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 0, 9: 0, 10: -1, 11: -1},
)

HI_OPT_II = CountSystem(
    name="Hi-Opt II",
    tags={2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 0, 9: 0, 10: -2, 11: 0},
    level=2,
)

SYSTEMS = {"hi-lo": HI_LO, "ko": KO, "hi-opt-ii": HI_OPT_II}


def true_count(
    running_count: float,
    cards_remaining: int,
    *,
    estimate_to_half_deck: bool = False,
) -> float:
    """Running count divided by decks remaining.

    At a real table you eyeball the discard tray, so you get the decks remaining
    to maybe the nearest half deck. `estimate_to_half_deck=True` models that,
    which slightly blurs the true-count distribution and is the honest setting
    for planning. Exact division is the theoretical ceiling.
    """
    decks_remaining = cards_remaining / 52.0
    if estimate_to_half_deck:
        decks_remaining = max(0.5, round(decks_remaining * 2) / 2)
    if decks_remaining <= 0:
        return 0.0
    return running_count / decks_remaining
