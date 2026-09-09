"""The exact edge of a game, computed by enumeration rather than simulated.

This closes the last unvalidated layer. Phase 1's bankroll figures rest on
`constants.py` -- rule-effect numbers reconstructed from published tables and
never independently checked -- and on the assumption that EV is linear in the
true count at 0.005 per count. Phase 1.5's Monte Carlo could not test either,
because it draws hand results whose moments come from those very constants.

The spec proposed a full-hand simulator for this. It will not work. The house
edge is about 0.45% against a per-hand standard deviation near 1.15, so
resolving it to a hundredth of a percent needs a standard error of 1e-4, which
is roughly 130 million hands. No Python simulation gets there, and a noisy
answer validates nothing.

Enumeration does get there, exactly. There are only 55 unordered two-card player
hands and 10 upcards, and the analyzer already returns the exact EV of every
action. Weighting each deal by its probability and summing gives the true edge
with no sampling error at all -- and evaluating it at a series of true counts
gives the real EV curve, which is what the linear model is meant to approximate.

What this still does not cover: the analyzer's own approximations (dealer
probabilities are not recomputed as the player draws; splits use a single
resplit). Those are documented at their call sites and are worth a hundredth of
a percent or so, which is the resolution this module claims.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analyzer import Action, action_evs, prob_dealer_blackjack
from .cards import (
    ACE,
    RANKS,
    TEN,
    deck_for_true_count,
    fresh_deck,
    remove_many,
)
from .rules import HoleCard, RuleSet


def _initial_deals(deck) -> list[tuple[tuple[int, int], int, float]]:
    """Every (player pair, upcard) with its probability. Weights sum to 1."""
    out: list[tuple[tuple[int, int], int, float]] = []
    total_weight = 0.0
    for a in RANKS:
        for b in RANKS:
            if b < a:
                continue
            if a == b:
                ways = deck[a] * (deck[a] - 1) / 2.0
            else:
                ways = deck[a] * deck[b]
            if ways <= 0:
                continue
            after = remove_many(deck, a, b)
            for up in RANKS:
                if after[up] <= 0:
                    continue
                w = ways * after[up]
                out.append(((a, b), up, w))
                total_weight += w
    # Normalise: the denominator is the same for every term, so this is exact.
    return [(cards, up, w / total_weight) for cards, up, w in out]


@dataclass
class EdgeBreakdown:
    """Where a game's edge comes from, computed rather than assumed."""

    edge: float
    """Player edge per unit wagered, playing the best action every time."""

    blackjack_share: float
    """Contribution of player naturals."""

    surrender_share: float
    doubled_share: float
    split_share: float
    frequency_of: dict[str, float]
    """How often each action is correct, by probability of the deal."""


def exact_edge(
    rules: RuleSet,
    *,
    tc: float | None = None,
    deck=None,
    breakdown: bool = False,
) -> float | EdgeBreakdown:
    """Exact expected value of one round, playing optimally.

    Pass `tc` to evaluate against a shoe of that Hi-Lo true count, or `deck` to
    supply a composition directly. With neither, a full fresh shoe is used.
    """
    if deck is None:
        deck = (
            fresh_deck(rules.decks) if tc is None
            else deck_for_true_count(tc, rules.decks)
        )

    peek_style = rules.hole_card in (
        HoleCard.PEEK, HoleCard.ENHC_ORIGINAL_ONLY
    )

    total = 0.0
    bj_share = 0.0
    sur_share = 0.0
    dbl_share = 0.0
    split_share = 0.0
    freq: dict[str, float] = {}

    for cards, up, p in _initial_deals(deck):
        rest = remove_many(deck, *cards, up)
        player_bj = set(cards) == {TEN, ACE}
        p_bj = prob_dealer_blackjack(up, rest)

        if player_bj:
            # A natural is settled immediately: paid unless the dealer has one
            # too, in which case it pushes. True under every settlement style.
            ev = (1.0 - p_bj) * rules.blackjack_payout
            total += p * ev
            bj_share += p * ev
            freq["blackjack"] = freq.get("blackjack", 0.0) + p
            continue

        evs = action_evs(cards, up, rest, rules)
        action = max(evs, key=lambda a: evs[a])
        ev = evs[action]

        if peek_style:
            # `action_evs` folds in the dealer-natural branch only for full
            # ENHC; under a peek or original-bet-only game it returns the value
            # given no natural, so the branch is added here instead.
            ev = (1.0 - p_bj) * ev + p_bj * -1.0

        total += p * ev
        freq[action.value] = freq.get(action.value, 0.0) + p
        if action is Action.SURRENDER:
            sur_share += p * ev
        elif action is Action.DOUBLE:
            dbl_share += p * ev
        elif action is Action.SPLIT:
            split_share += p * ev

    if not breakdown:
        return total
    return EdgeBreakdown(
        edge=total,
        blackjack_share=bj_share,
        surrender_share=sur_share,
        doubled_share=dbl_share,
        split_share=split_share,
        frequency_of=freq,
    )


def ev_curve(
    rules: RuleSet,
    counts: tuple[float, ...] = tuple(range(-6, 11)),
    *,
    cards_remaining: int | None = None,
) -> dict[float, float]:
    """The real EV(true count) curve, which the linear model approximates.

    Evaluated against a shoe with `cards_remaining` cards left (half the shoe by
    default). Note that the TC-0 point of this curve is NOT the game's
    off-the-top edge: a partly dealt shoe plays slightly better for the player
    for the same reason a 4-deck game beats an 8-deck one. Compare the curve's
    *slope* against HILO_SLOPE, and `exact_edge` on a full shoe against
    `base_edge`.
    """
    return {
        tc: exact_edge(
            rules,
            deck=deck_for_true_count(
                float(tc), rules.decks, cards_remaining=cards_remaining
            ),
        )
        for tc in counts
    }


def fit_linear(curve: dict[float, float]) -> tuple[float, float, float]:
    """Least-squares fit of the EV curve, returning (intercept, slope, max error).

    The intercept is what `constants.base_edge` should equal; the slope is what
    `HILO_SLOPE` should equal. The maximum absolute residual says how much the
    linear model gives up by being a straight line.
    """
    xs = list(curve)
    ys = [curve[x] for x in xs]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = my - slope * mx
    worst = max(abs(y - (intercept + slope * x)) for x, y in zip(xs, ys, strict=True))
    return intercept, slope, worst
