"""Deck compositions and hand arithmetic.

Ranks are indexed 0-9 for 2,3,4,5,6,7,8,9,T,A. Tens and all the picture cards
share index 8, so a single deck holds sixteen of them.

A hand is a `(total, soft)` pair, where `soft` means an ace is currently being
counted as eleven and could be dropped to one if the hand would otherwise bust.
"""

from __future__ import annotations

from functools import lru_cache

RANKS = tuple(range(10))
TEN, ACE = 8, 9
RANK_NAMES = ("2", "3", "4", "5", "6", "7", "8", "9", "T", "A")
#: Value of each rank. The ace is 11 here; `add_card` demotes it when needed.
RANK_VALUES = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
#: Cards of each rank in one 52-card deck.
PER_DECK = (4, 4, 4, 4, 4, 4, 4, 4, 16, 4)

#: Hi-Lo tag by rank index: 2-6 are +1, 7-9 are 0, tens and aces are -1.
HILO_TAGS = (1, 1, 1, 1, 1, 0, 0, 0, -1, -1)

Deck = tuple[int, ...]
Hand = tuple[int, bool]


def fresh_deck(decks: int = 6) -> Deck:
    return tuple(c * decks for c in PER_DECK)


def remove(deck: Deck, rank: int) -> Deck:
    """Deck with one card of `rank` taken out. Caller must check it is there."""
    return deck[:rank] + (deck[rank] - 1,) + deck[rank + 1:]


def remove_many(deck: Deck, *ranks: int) -> Deck:
    for r in ranks:
        deck = remove(deck, r)
    return deck


def total_cards(deck: Deck) -> int:
    return sum(deck)


@lru_cache(maxsize=None)
def draw_probs(deck: Deck) -> tuple[float, ...]:
    """P(next card is each rank), given what is left in the shoe."""
    n = sum(deck)
    if n <= 0:
        return (0.0,) * 10
    return tuple(c / n for c in deck)


def add_card(total: int, soft: bool, rank: int) -> Hand:
    """Play one card onto a hand, demoting an ace if that avoids a bust."""
    value = RANK_VALUES[rank]
    if rank == ACE:
        if total + 11 <= 21:
            return total + 11, True
        return total + 1, soft
    new_total = total + value
    if new_total > 21 and soft:
        return new_total - 10, False
    return new_total, soft


def hand_from(*ranks: int) -> Hand:
    total, soft = 0, False
    for r in ranks:
        total, soft = add_card(total, soft, r)
    return total, soft


def is_blackjack(*ranks: int) -> bool:
    return len(ranks) == 2 and {*ranks} == {TEN, ACE}


def running_count(deck: Deck, decks: int) -> int:
    """Hi-Lo running count implied by what has been removed from a full shoe."""
    full = fresh_deck(decks)
    return sum(
        HILO_TAGS[r] * (full[r] - deck[r]) for r in RANKS
    )


def true_count_of(deck: Deck, decks: int) -> float:
    remaining = sum(deck)
    if remaining <= 0:
        return 0.0
    return running_count(deck, decks) / (remaining / 52.0)


def deck_for_true_count(
    tc: float, decks: int = 6, *, cards_remaining: int | None = None
) -> Deck:
    """A deck composition consistent with a given Hi-Lo true count.

    Removes low cards (2-6) and adds back high cards (tens and aces) in the
    proportions Hi-Lo tracks, keeping the ratio of tens to aces at its natural
    4:1 so the composition stays realistic rather than merely arithmetically
    correct. This is the standard way index numbers are generated: evaluate the
    same decision against progressively richer shoes and find where the best
    action changes.
    """
    if cards_remaining is None:
        cards_remaining = int(decks * 52 * 0.5)
    decks_remaining = cards_remaining / 52.0
    target_rc = tc * decks_remaining

    base = fresh_deck(decks)
    scale = cards_remaining / (decks * 52)
    deck = [c * scale for c in base]

    # Move `shift` cards from the low group to the high group. Each moved card
    # changes the running count by 2, so shift = target_rc / 2.
    shift = target_rc / 2.0
    low_total = sum(deck[r] for r in range(0, 5))       # ranks 2-6
    high_total = deck[TEN] + deck[ACE]                  # tens and aces
    if low_total <= 0 or high_total <= 0:
        return tuple(max(0, round(c)) for c in deck)

    for r in range(0, 5):
        deck[r] -= shift * (deck[r] / low_total)
    deck[TEN] += shift * (deck[TEN] / high_total)
    deck[ACE] += shift * (deck[ACE] / high_total)

    return tuple(max(0.0, c) for c in deck)  # type: ignore[return-value]
