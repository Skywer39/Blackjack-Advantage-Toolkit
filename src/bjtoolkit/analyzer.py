"""Exact expected value for a blackjack decision, given a deck composition.

This is the piece everything else in Phase 2 rests on. Give it a hand, an
upcard, a rule set and a shoe composition, and it returns the expected value of
each legal action. Basic strategy is then just the argmax; a deviation index is
just the true count at which the argmax changes.

Deriving both from one engine means the strategy is computed for *your* rules
rather than transcribed from someone else's chart -- which matters most exactly
where published charts are least reliable, in a no-hole-card game.

## How a dealer blackjack is handled

The three settlement styles differ in a way that changes the correct play, not
just the edge:

* **Peek.** The dealer checks before you act, so a dealer blackjack costs you one
  unit whatever you were going to do. That term is identical across every action
  and cancels out of the comparison.
* **ENHC, original bet only.** Same net effect as a peek game.
* **ENHC, all bets lost.** A dealer blackjack takes your doubled or split money
  too. Doubling into a dealer ace therefore risks a second unit roughly 31% of
  the time, and that term does *not* cancel. This is why an ENHC game needs its
  own strategy rather than the US chart with a few cells patched.

## Accuracy

Dealer outcome probabilities are computed from the shoe as it stands when you
act, and are not recomputed as you draw. Removing your own one or two hit cards
shifts the dealer's distribution by far less than the shoe composition already
has, and recomputing at every node makes a full chart minutes rather than
seconds. Split hands use the standard single-resplit approximation, documented
at `ev_split`.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from .cards import (
    ACE, RANKS, TEN, Deck, add_card, draw_probs, remove,
)
from .rules import DoubleRule, HoleCard, RuleSet, Surrender

BUST = 22  # sentinel final total for a busted dealer


class Action(str, Enum):
    STAND = "stand"
    HIT = "hit"
    DOUBLE = "double"
    SPLIT = "split"
    SURRENDER = "surrender"


# --------------------------------------------------------------------------
# Dealer
# --------------------------------------------------------------------------

@lru_cache(maxsize=2_000_000)
def _play_out(total: int, soft: bool, deck: Deck, h17: bool) -> tuple[float, ...]:
    """Distribution over the dealer's final total, as (p17..p21, pBust)."""
    if total > 21:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    stands = total >= 18 or (total == 17 and not (soft and h17))
    if stands and total >= 17:
        out = [0.0] * 6
        out[total - 17] = 1.0
        return tuple(out)

    probs = draw_probs(deck)
    acc = [0.0] * 6
    for rank in RANKS:
        p = probs[rank]
        if p <= 0.0:
            continue
        nt, ns = add_card(total, soft, rank)
        sub = _play_out(nt, ns, remove(deck, rank), h17)
        for i in range(6):
            acc[i] += p * sub[i]
    return tuple(acc)


@lru_cache(maxsize=200_000)
def dealer_outcomes(
    upcard: int, deck: Deck, h17: bool, exclude_blackjack: bool
) -> tuple[float, ...]:
    """Dealer's final total distribution, given the upcard and remaining shoe.

    `exclude_blackjack` conditions on the dealer not having a natural, which is
    the situation whenever you are still making a decision -- either because the
    dealer peeked and did not have one, or because the blackjack branch is being
    accounted for separately in a no-hole-card game.
    """
    total, soft = add_card(0, False, upcard)
    forbidden = None
    if exclude_blackjack:
        forbidden = TEN if upcard == ACE else (ACE if upcard == TEN else None)
    if forbidden is None:
        return _play_out(total, soft, deck, h17)

    probs = draw_probs(deck)
    denom = 1.0 - probs[forbidden]
    if denom <= 0.0:
        return _play_out(total, soft, deck, h17)

    acc = [0.0] * 6
    for rank in RANKS:
        if rank == forbidden:
            continue
        p = probs[rank] / denom
        if p <= 0.0:
            continue
        nt, ns = add_card(total, soft, rank)
        sub = _play_out(nt, ns, remove(deck, rank), h17)
        for i in range(6):
            acc[i] += p * sub[i]
    return tuple(acc)


def prob_dealer_blackjack(upcard: int, deck: Deck) -> float:
    """Chance the dealer's next card completes a natural."""
    if upcard == ACE:
        return draw_probs(deck)[TEN]
    if upcard == TEN:
        return draw_probs(deck)[ACE]
    return 0.0


# --------------------------------------------------------------------------
# Player, conditional on the dealer not having a natural
# --------------------------------------------------------------------------

def ev_stand(total: int, dealer: tuple[float, ...]) -> float:
    """EV of standing, in units of the bet on this hand."""
    if total > 21:
        return -1.0
    win = dealer[5]  # dealer busts
    lose = 0.0
    push = 0.0
    for i in range(5):
        dealer_total = 17 + i
        if dealer_total < total:
            win += dealer[i]
        elif dealer_total > total:
            lose += dealer[i]
        else:
            push += dealer[i]
    return win - lose


@lru_cache(maxsize=2_000_000)
def ev_hit(
    total: int, soft: bool, deck: Deck, dealer: tuple[float, ...]
) -> float:
    """EV of taking at least one more card, playing optimally afterwards."""
    if total > 21:
        return -1.0
    probs = draw_probs(deck)
    acc = 0.0
    for rank in RANKS:
        p = probs[rank]
        if p <= 0.0:
            continue
        nt, ns = add_card(total, soft, rank)
        if nt > 21:
            acc += p * -1.0
            continue
        sub = remove(deck, rank)
        acc += p * max(ev_stand(nt, dealer), ev_hit(nt, ns, sub, dealer))
    return acc


def ev_double(
    total: int, soft: bool, deck: Deck, dealer: tuple[float, ...]
) -> float:
    """EV of doubling: exactly one more card, then forced to stand."""
    probs = draw_probs(deck)
    acc = 0.0
    for rank in RANKS:
        p = probs[rank]
        if p <= 0.0:
            continue
        nt, _ = add_card(total, soft, rank)
        acc += p * ev_stand(nt, dealer)
    return 2.0 * acc


def ev_split(
    rank: int, deck: Deck, dealer: tuple[float, ...], rules: RuleSet
) -> float:
    """EV of splitting a pair, in units of the ORIGINAL bet.

    Uses the standard approximation: value one post-split hand and double it,
    without modelling resplits. Resplitting is a small positive option, so this
    slightly understates the value of splitting -- most in the low pairs against
    weak upcards, where splitting already wins comfortably, and least in the
    marginal cells where a chart could actually flip. Split aces receive one
    card only, which is modelled exactly.
    """
    probs = draw_probs(deck)
    one_hand = 0.0
    aces = rank == ACE
    for draw in RANKS:
        p = probs[draw]
        if p <= 0.0:
            continue
        total, soft = add_card(0, False, rank)
        total, soft = add_card(total, soft, draw)
        sub = remove(deck, draw)
        if aces:
            one_hand += p * ev_stand(total, dealer)
            continue
        best = max(ev_stand(total, dealer), ev_hit(total, soft, sub, dealer))
        if rules.double_after_split and _may_double(total, soft, rules):
            best = max(best, ev_double(total, soft, sub, dealer))
        one_hand += p * best
    return 2.0 * one_hand


def _may_double(total: int, soft: bool, rules: RuleSet) -> bool:
    if rules.double_rule is DoubleRule.ANY_TWO:
        return True
    hard = total if not soft else total - 10
    if rules.double_rule is DoubleRule.NINE_TO_ELEVEN:
        return 9 <= hard <= 11 and not soft
    return 10 <= hard <= 11 and not soft


def _surrender_allowed(upcard: int, rules: RuleSet) -> bool:
    s = rules.surrender
    if s is Surrender.NONE:
        return False
    if s in (Surrender.LATE_VS_10, Surrender.EARLY_VS_10):
        return upcard == TEN
    if s is Surrender.LATE_VS_9_10:
        return upcard in (7, TEN)  # rank index 7 is a nine
    return True


# --------------------------------------------------------------------------
# The full decision, including the dealer-blackjack branch
# --------------------------------------------------------------------------

def action_evs(
    cards: tuple[int, ...],
    upcard: int,
    deck: Deck,
    rules: RuleSet,
    *,
    allow_double: bool = True,
    allow_split: bool = True,
    allow_surrender: bool = True,
) -> dict[Action, float]:
    """Expected value of every legal action, in units of the original bet.

    `deck` must already have the player's cards and the dealer's upcard removed.
    Values include the dealer-blackjack branch, which is what makes doubling and
    splitting look correctly worse in a full no-hole-card game.
    """
    total, soft = 0, False
    for c in cards:
        total, soft = add_card(total, soft, c)

    h17 = rules.dealer_hits_soft_17
    dealer = dealer_outcomes(upcard, deck, h17, True)

    p_bj = 0.0
    all_bets = False
    if rules.hole_card is HoleCard.ENHC_ALL_BETS:
        p_bj = prob_dealer_blackjack(upcard, deck)
        all_bets = True
    live = 1.0 - p_bj

    def wrap(ev_no_bj: float, wager: float) -> float:
        """Fold in the branch where the dealer turns over a natural."""
        if p_bj <= 0.0:
            return ev_no_bj
        lost = wager if all_bets else 1.0
        return live * ev_no_bj + p_bj * -lost

    out: dict[Action, float] = {
        Action.STAND: wrap(ev_stand(total, dealer), 1.0),
        Action.HIT: wrap(ev_hit(total, soft, deck, dealer), 1.0),
    }

    if allow_double and len(cards) == 2 and _may_double(total, soft, rules):
        out[Action.DOUBLE] = wrap(ev_double(total, soft, deck, dealer), 2.0)

    if (
        allow_split
        and len(cards) == 2
        and cards[0] == cards[1]
        and rules.max_split_hands >= 2
    ):
        out[Action.SPLIT] = wrap(ev_split(cards[0], deck, dealer, rules), 2.0)

    if allow_surrender and len(cards) == 2 and _surrender_allowed(upcard, rules):
        if rules.surrender.is_early:
            # Settled before the dealer's natural is known: you always keep half.
            out[Action.SURRENDER] = -0.5
        else:
            # Late: a dealer natural takes the whole bet before you can give up.
            out[Action.SURRENDER] = wrap(-0.5, 1.0)

    return out


def best_action(
    cards: tuple[int, ...], upcard: int, deck: Deck, rules: RuleSet, **kwargs
) -> tuple[Action, float]:
    evs = action_evs(cards, upcard, deck, rules, **kwargs)
    action = max(evs, key=lambda a: evs[a])
    return action, evs[action]


def clear_caches() -> None:
    """Drop memo tables. Worth calling between rule sets in long runs."""
    _play_out.cache_clear()
    dealer_outcomes.cache_clear()
    ev_hit.cache_clear()
    draw_probs.cache_clear()
