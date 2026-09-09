"""Basic strategy and deviation indices, computed rather than transcribed.

Both come from `analyzer.action_evs`. Basic strategy is the best action at a
neutral shoe; a deviation index is the true count at which the best action
changes. Because they share an engine, they cannot disagree with each other, and
both are correct for the rule set you actually hand them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analyzer import Action, action_evs, best_action
from .cards import (
    ACE,
    RANK_NAMES,
    RANKS,
    TEN,
    deck_for_true_count,
    remove_many,
)
from .rules import RuleSet

#: Dealer upcards, in the order charts print them: 2..9, T, A.
UPCARDS = tuple(RANKS)


#: Rank index 8 is the ten group; its value is 10, every other index is +2.
def _value(rank: int) -> int:
    return 10 if rank == TEN else rank + 2


def cards_for_hard(total: int) -> tuple[int, int]:
    """Two aceless cards making a hard total, as a chart row means it.

    Prefers a non-pair composition so the row is not accidentally a split
    decision; hard 20 has no such option and uses T,T, which is fine because
    hard rows are evaluated with splitting disabled.
    """
    if not 5 <= total <= 20:
        raise ValueError(f"hard {total} is not a chart row")
    for a in range(0, 9):
        for b in range(a, 9):
            if _value(a) + _value(b) == total and a != b:
                return (a, b)
    for a in range(0, 9):          # pairs, for totals nothing else reaches
        if 2 * _value(a) == total:
            return (a, a)
    raise ValueError(f"no two cards make hard {total}")


def cards_for_soft(total: int) -> tuple[int, int]:
    """Ace plus one card, for the soft rows: soft 13 is A,2 up to soft 20 A,9."""
    partner = total - 13   # soft 13 -> rank index 0 (a two)
    if not 0 <= partner <= 7:
        raise ValueError(f"no ace-plus-one hand makes soft {total}")
    return (ACE, partner)


def cards_for_pair(rank: int) -> tuple[int, int]:
    return (rank, rank)


@dataclass(frozen=True)
class Cell:
    """One square of a strategy chart."""

    category: str          # "hard" | "soft" | "pair"
    label: str             # "16", "A,7", "8,8"
    upcard: int
    action: Action
    ev: float
    runner_up: Action | None
    margin: float          # how much better the best action is than the next

    @property
    def close(self) -> bool:
        """Marginal cells are where charts disagree and rules matter most."""
        return self.margin < 0.01


def _deck_at(tc: float, rules: RuleSet, cards: tuple[int, ...], upcard: int):
    deck = deck_for_true_count(tc, rules.decks)
    return remove_many(deck, *cards, upcard)


def hard_compositions(total: int, deck) -> list[tuple[tuple[int, int], float]]:
    """Every two-card way to make a hard total, with its relative likelihood.

    A chart row is not one hand. Hard 16 is 10+6 about half the time and 9+7 or
    8+8 the rest, and those play differently: against a nine, 10,6 prefers
    hitting by 0.0001 while 9,7 prefers surrender by 0.0007. Published charts
    quote the composition-*averaged* answer, which is the right thing to
    memorise when you have not yet looked at your cards. Averaging here is what
    makes this engine agree with them.

    Pair compositions are excluded because they have their own chart row, unless
    nothing else makes the total (hard 20 is only T,T).
    """
    out: list[tuple[tuple[int, int], float]] = []
    for a in range(0, 9):
        for b in range(a, 9):
            if _value(a) + _value(b) != total:
                continue
            if a == b:
                weight = deck[a] * (deck[a] - 1) / 2.0
            else:
                weight = deck[a] * deck[b]
            if weight > 0:
                out.append(((a, b), weight))
    non_pairs = [(c, w) for c, w in out if c[0] != c[1]]
    chosen = non_pairs or out
    total_w = sum(w for _, w in chosen)
    return [(c, w / total_w) for c, w in chosen]


def evaluate_cell(
    category: str,
    cards: tuple[int, ...],
    label: str,
    upcard: int,
    rules: RuleSet,
    tc: float = 0.0,
) -> Cell:
    """The best action for a chart row, averaged over its compositions."""
    base = deck_for_true_count(tc, rules.decks)
    if category == "hard":
        comps = hard_compositions(int(label), base)
    else:
        comps = [(cards, 1.0)]

    totals: dict[Action, float] = {}
    seen_all: list[set[Action]] = []
    for comp, weight in comps:
        deck = remove_many(base, *comp, upcard)
        evs = action_evs(
            comp, upcard, deck, rules,
            allow_split=(category == "pair"),
        )
        seen_all.append(set(evs))
        for action, value in evs.items():
            totals[action] = totals.get(action, 0.0) + weight * value

    # Only actions legal for every composition can be recommended for the row.
    legal = set.intersection(*seen_all) if seen_all else set()
    totals = {a: v for a, v in totals.items() if a in legal}

    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    best, best_ev = ordered[0]
    runner, runner_ev = (ordered[1] if len(ordered) > 1 else (None, best_ev))
    return Cell(category, label, upcard, best, best_ev, runner, best_ev - runner_ev)


def hard_rows() -> list[tuple[str, tuple[int, int]]]:
    return [(str(t), cards_for_hard(t)) for t in range(5, 21)]


def soft_rows() -> list[tuple[str, tuple[int, int]]]:
    return [(f"A,{t - 11}", cards_for_soft(t)) for t in range(13, 21)]


def pair_rows() -> list[tuple[str, tuple[int, int]]]:
    out = []
    for r in RANKS:
        name = "A,A" if r == ACE else f"{RANK_NAMES[r]},{RANK_NAMES[r]}"
        out.append((name, cards_for_pair(r)))
    return out


def basic_strategy(rules: RuleSet, tc: float = 0.0) -> list[Cell]:
    """The whole chart for one rule set, computed cell by cell."""
    cells: list[Cell] = []
    for category, rows in (
        ("hard", hard_rows()), ("soft", soft_rows()), ("pair", pair_rows())
    ):
        for label, cards in rows:
            for up in UPCARDS:
                cells.append(
                    evaluate_cell(category, cards, label, up, rules, tc)
                )
    return cells


# --------------------------------------------------------------------------
# Deviation indices
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Deviation:
    category: str
    label: str
    upcard: int
    basic: Action
    switch_to: Action
    index: int
    direction: str   # "+" deviate at this count and above, "-" at and below

    def describe(self) -> str:
        up = RANK_NAMES[self.upcard]
        return (
            f"{self.label} vs {up}: {self.basic.value} -> {self.switch_to.value} "
            f"at TC {self.index:+d}{self.direction}"
        )


def find_deviation(
    category: str,
    cards: tuple[int, ...],
    label: str,
    upcard: int,
    rules: RuleSet,
    *,
    tc_range: tuple[int, int] = (-10, 10),
) -> Deviation | None:
    """Scan the true count for the point where the best action changes.

    Returns the first crossover found moving away from a neutral shoe, which is
    what an index number means. Cells whose best action never changes over the
    range have no index and are simply played by basic strategy.
    """
    lo, hi = tc_range
    basic = evaluate_cell(category, cards, label, upcard, rules, 0.0).action

    for tc in range(1, hi + 1):
        a = evaluate_cell(category, cards, label, upcard, rules, float(tc)).action
        if a != basic:
            return Deviation(category, label, upcard, basic, a, tc, "+")
    for tc in range(-1, lo - 1, -1):
        a = evaluate_cell(category, cards, label, upcard, rules, float(tc)).action
        if a != basic:
            return Deviation(category, label, upcard, basic, a, tc, "-")
    return None


def all_deviations(
    rules: RuleSet, *, tc_range: tuple[int, int] = (-10, 10)
) -> list[Deviation]:
    """Every cell in the chart whose correct play changes with the count."""
    found: list[Deviation] = []
    for category, rows in (
        ("hard", hard_rows()), ("soft", soft_rows()), ("pair", pair_rows())
    ):
        for label, cards in rows:
            for up in UPCARDS:
                d = find_deviation(category, cards, label, up, rules,
                                   tc_range=tc_range)
                if d is not None:
                    found.append(d)
    return found


# --------------------------------------------------------------------------
# Which deviations are actually worth learning
# --------------------------------------------------------------------------

def hand_probability(category: str, cards: tuple[int, ...], upcard: int, deck) -> float:
    """Rough chance of being dealt this hand against this upcard.

    Treats the upcard as independent of the player's two cards, which is close
    enough for ranking purposes and avoids a combinatorial detour.
    """
    n = sum(deck)
    if n < 3:
        return 0.0
    a, b = cards[0], cards[1]
    if a == b:
        p_hand = (deck[a] / n) * ((deck[a] - 1) / (n - 1))
    else:
        p_hand = 2.0 * (deck[a] / n) * (deck[b] / (n - 1))
    return p_hand * (deck[upcard] / n)


@dataclass(frozen=True)
class RankedDeviation:
    deviation: Deviation
    value_per_hand: float
    """Expected gain per round played, in units of the bet."""

    frequency: float
    """Share of rounds where the hand occurs AND the count says to deviate."""

    def describe(self) -> str:
        return (
            f"{self.deviation.describe():<44} "
            f"gain {self.value_per_hand * 10000:6.2f} bp/round"
        )


def rank_deviations(
    rules: RuleSet,
    tc_probs: dict[int, float],
    *,
    tc_range: tuple[int, int] = (-6, 8),
    deviations: list[Deviation] | None = None,
) -> list[RankedDeviation]:
    """Order deviations by how much money each is actually worth.

    A deviation earns its place only if the hand comes up, the count reaches the
    index often enough to matter, and the play gains enough when it does. An
    index of +7 on a hand you see once a session is not worth the memory; this
    is what separates an Illustrious 18 from a list of seventy curiosities.

    `tc_probs` comes from the Phase 1 frequency model, so the ranking reflects
    your actual penetration.
    """
    devs = deviations if deviations is not None else all_deviations(
        rules, tc_range=tc_range
    )
    rows: list[RankedDeviation] = []
    for d in devs:
        cards = _cards_for(d.category, d.label)
        gain = 0.0
        freq = 0.0
        for tc, p_tc in tc_probs.items():
            if not _deviating_at(d, tc):
                continue
            base = deck_for_true_count(float(tc), rules.decks)
            deck = remove_many(base, *cards, d.upcard)
            evs = action_evs(cards, d.upcard, deck, rules,
                             allow_split=(d.category == "pair"))
            if d.switch_to not in evs or d.basic not in evs:
                continue
            edge = evs[d.switch_to] - evs[d.basic]
            if edge <= 0:
                continue
            p_hand = hand_probability(d.category, cards, d.upcard, base)
            gain += p_tc * p_hand * edge
            freq += p_tc * p_hand
        rows.append(RankedDeviation(d, gain, freq))
    rows.sort(key=lambda r: r.value_per_hand, reverse=True)
    return rows


def _deviating_at(d: Deviation, tc: int) -> bool:
    return tc >= d.index if d.direction == "+" else tc <= d.index


def _cards_for(category: str, label: str) -> tuple[int, int]:
    if category == "hard":
        return cards_for_hard(int(label))
    if category == "soft":
        return cards_for_soft(11 + int(label.split(",")[1]))
    left = label.split(",")[0]
    return cards_for_pair(ACE if left == "A" else RANK_NAMES.index(left))


def insurance_index(rules: RuleSet, *, precision: float = 0.01) -> float:
    """The exact true count at which insurance stops being a bad bet.

    Insurance pays 2:1 and wins when the hole card is a ten, so it turns
    profitable once tens pass one third of the remaining shoe.

    Returned as a fraction rather than the conventional integer, because the
    answer genuinely sits just above +3 and moves with what you can see. Counting
    only the dealer's ace as removed it lands near +3.06; if you also hold a ten
    it drifts to about +3.3, and with no removals at all the pure composition
    math gives +3.33. Hi-Lo treats tens and aces alike as high cards while only
    tens pay insurance, which is why the threshold is not a rounder number.

    The conventional index of +3 is therefore a good approximation and very
    slightly aggressive. Round this yourself if you want the convention.
    """
    from .cards import draw_probs

    def edge(tc: float) -> float:
        deck = remove_many(deck_for_true_count(tc, rules.decks), ACE)
        return 3.0 * draw_probs(deck)[TEN] - 1.0

    lo, hi = 0.0, 20.0
    if edge(hi) <= 0:
        return float("inf")
    while hi - lo > precision:
        mid = (lo + hi) / 2.0
        if edge(mid) > 0:
            hi = mid
        else:
            lo = mid
    return round(hi, 2)


# --------------------------------------------------------------------------
# Playing decision
# --------------------------------------------------------------------------

def decide(
    cards: tuple[int, ...],
    upcard: int,
    true_count: float,
    rules: RuleSet,
    *,
    allow_double: bool = True,
    allow_split: bool = True,
    allow_surrender: bool = True,
) -> Action:
    """The correct play for this hand, at this count, under these rules."""
    deck = _deck_at(true_count, rules, cards, upcard)
    action, _ = best_action(
        cards, upcard, deck, rules,
        allow_double=allow_double and len(cards) == 2,
        allow_split=allow_split and len(cards) == 2 and cards[0] == cards[1],
        allow_surrender=allow_surrender and len(cards) == 2,
    )
    return action
