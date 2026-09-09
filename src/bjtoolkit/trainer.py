"""Drills for the things you have to do at speed, under a pit boss's gaze.

Five of them, in the order they matter:

* `count`      -- keep a running count over a stream of cards
* `truecount`  -- convert running to true, from the discard tray
* `strategy`   -- the correct play, from the chart computed for YOUR rules
* `deviation`  -- index plays, drawn in the order they are worth learning
* `bet`        -- what to put out at a given count, from your own ramp

Two things make this more than a flashcard loop.

The strategy and deviation drills are generated from the Phase 2 analyzer, so
you are practising the chart for the game you actually sit at -- including the
ENHC corrections that no printed chart carries. Drilling a Vegas chart for a
Prague table would teach you the wrong answer four times over.

And repetition is weighted toward what you get wrong. Items you miss, or answer
slowly, come back more often; items you have never seen jump the queue. That is
the whole difference between practice and revision.

The engine here is pure -- generate a question, check an answer, record the
result -- so the interactive loop in the CLI stays thin and the drills stay
testable.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .analyzer import Action
from .cards import (
    HILO_TAGS,
    RANK_NAMES,
    RANKS,
    fresh_deck,
    remove,
)
from .frequency import data_dir
from .rules import RuleSet

#: How a card is spoken and written at the table.
FACE_NAMES = {8: ("10", "J", "Q", "K")}

ACTION_WORDS: dict[str, Action] = {
    "h": Action.HIT, "hit": Action.HIT,
    "s": Action.STAND, "stand": Action.STAND, "st": Action.STAND,
    "d": Action.DOUBLE, "double": Action.DOUBLE, "dbl": Action.DOUBLE,
    "p": Action.SPLIT, "split": Action.SPLIT, "sp": Action.SPLIT,
    "r": Action.SURRENDER, "surrender": Action.SURRENDER, "sur": Action.SURRENDER,
}

KINDS = ("count", "truecount", "strategy", "deviation", "bet")


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------

@dataclass
class ItemStats:
    seen: int = 0
    correct: int = 0
    total_seconds: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.seen if self.seen else 0.0

    @property
    def mean_seconds(self) -> float:
        return self.total_seconds / self.seen if self.seen else 0.0


@dataclass
class Progress:
    """Per-item history, persisted between sessions."""

    items: dict[str, ItemStats] = field(default_factory=dict)

    def stat(self, key: str) -> ItemStats:
        return self.items.setdefault(key, ItemStats())

    def record(self, key: str, correct: bool, seconds: float) -> None:
        s = self.stat(key)
        s.seen += 1
        s.correct += int(correct)
        s.total_seconds += max(0.0, seconds)

    def weight(self, key: str, *, slow_after: float = 4.0) -> float:
        """Sampling weight: unseen first, then wrong, then slow.

        An item you have never met gets a large weight so the drill explores
        before it exploits. After that the weight rises with your error rate and,
        more gently, with how long you take -- knowing the answer eventually is
        not the same as knowing it at the table.
        """
        s = self.items.get(key)
        if s is None or s.seen == 0:
            return 6.0
        error_rate = 1.0 - s.accuracy
        slowness = max(0.0, s.mean_seconds - slow_after) / slow_after
        return 1.0 + 5.0 * error_rate + 1.5 * min(slowness, 2.0)

    def summary(self) -> dict:
        seen = sum(s.seen for s in self.items.values())
        correct = sum(s.correct for s in self.items.values())
        secs = sum(s.total_seconds for s in self.items.values())
        return {
            "answered": seen,
            "correct": correct,
            "accuracy": correct / seen if seen else 0.0,
            "mean_seconds": secs / seen if seen else 0.0,
            "items_tracked": len(self.items),
        }

    def weakest(self, n: int = 10) -> list[tuple[str, ItemStats]]:
        """The items costing you the most, worst first."""
        tried = [(k, s) for k, s in self.items.items() if s.seen >= 2]
        tried.sort(key=lambda kv: (kv[1].accuracy, -kv[1].mean_seconds))
        return tried[:n]

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return {"items": {k: asdict(v) for k, v in self.items.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> Progress:
        return cls(items={k: ItemStats(**v) for k, v in d.get("items", {}).items()})

    @classmethod
    def load(cls, path: Path | None = None) -> Progress:
        path = path or default_progress_path()
        if not path.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError, KeyError):
            # A corrupt progress file must never stop you drilling.
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or default_progress_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))


def default_progress_path() -> Path:
    """Where drill history lives.

    Follows BJTOOLKIT_CACHE_DIR like the other caches, so you can keep it out of
    a shared checkout. It is git-ignored by default: your misses are yours.
    """
    return data_dir() / "trainer_progress.json"


# --------------------------------------------------------------------------
# Questions
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Question:
    kind: str
    prompt: str
    answer: str
    item_key: str
    explain: str = ""
    tolerance: float = 0.0
    context: dict = field(default_factory=dict)

    def check(self, response: str) -> bool:
        response = response.strip().lower()
        if not response:
            return False
        if self.kind in ("strategy", "deviation"):
            got = ACTION_WORDS.get(response)
            return got is not None and got.value == self.answer
        try:
            value = float(response)
        except ValueError:
            return False
        return abs(value - float(self.answer)) <= self.tolerance + 1e-9


def card_name(rank: int, rng: random.Random) -> str:
    """Print a ten as one of its four faces, so the eye learns all of them."""
    if rank == 8:
        return rng.choice(FACE_NAMES[8])
    return RANK_NAMES[rank]


# --------------------------------------------------------------------------
# Cached strategy material
# --------------------------------------------------------------------------

def _rules_key(rules: RuleSet) -> str:
    parts = [
        f"{rules.decks}d",
        "h17" if rules.dealer_hits_soft_17 else "s17",
        rules.double_rule.value,
        "das" if rules.double_after_split else "nodas",
        "rsa" if rules.resplit_aces else "norsa",
        f"sp{rules.max_split_hands}",
        rules.surrender.value,
        rules.hole_card.value,
        f"bj{rules.blackjack_payout:g}",
    ]
    return "_".join(parts)


def cached_chart(
    rules: RuleSet, *, regenerate: bool = False, cache_dir: Path | None = None
) -> dict[str, str]:
    """The basic strategy chart, keyed "category|label|upcard" -> action.

    Computing a chart takes a couple of seconds, which is fine once and annoying
    every time you sit down to drill.
    """
    from .strategy import basic_strategy

    path = (cache_dir or data_dir()) / f"chart_{_rules_key(rules)}.json"
    if path.exists() and not regenerate:
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    table = {
        f"{c.category}|{c.label}|{RANK_NAMES[c.upcard]}": c.action.value
        for c in basic_strategy(rules)
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=2, sort_keys=True))
    return table


def cached_deviations(
    rules: RuleSet,
    *,
    top: int = 24,
    regenerate: bool = False,
    cache_dir: Path | None = None,
) -> list[dict]:
    """Deviations worth learning, most valuable first.

    Ranked against your own penetration, so the list reflects the counts you
    will actually reach rather than a textbook's.
    """
    from .frequency import load_or_simulate
    from .strategy import all_deviations, rank_deviations

    path = (cache_dir or data_dir()) / f"devs_{_rules_key(rules)}.json"
    if path.exists() and not regenerate:
        try:
            return json.loads(path.read_text())[:top]
        except json.JSONDecodeError:
            pass
    dist = load_or_simulate(rules)
    devs = all_deviations(rules, tc_range=(-6, 8))
    ranked = rank_deviations(rules, {t: dist.p(t) for t in dist.counts()},
                             deviations=devs)
    rows = [
        {
            "category": x.deviation.category,
            "label": x.deviation.label,
            "upcard": RANK_NAMES[x.deviation.upcard],
            "basic": x.deviation.basic.value,
            "switch_to": x.deviation.switch_to.value,
            "index": x.deviation.index,
            "direction": x.deviation.direction,
            "value": x.value_per_hand,
        }
        for x in ranked if x.value_per_hand > 0
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2))
    return rows[:top]


# --------------------------------------------------------------------------
# The drill
# --------------------------------------------------------------------------

class Trainer:
    """Generates questions and remembers how you did on each."""

    def __init__(
        self,
        rules: RuleSet,
        *,
        progress: Progress | None = None,
        kinds: tuple[str, ...] = KINDS,
        seed: int | None = None,
        cards_per_count_question: int = 12,
        ramp: dict[int, float] | None = None,
        deviation_pool: int = 18,
        cache_dir: Path | None = None,
    ) -> None:
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            raise ValueError(f"unknown drill kind(s): {bad}; choose from {KINDS}")
        self.rules = rules
        self.progress = progress if progress is not None else Progress()
        self.kinds = kinds
        self.rng = random.Random(seed)
        self.cards_per_count_question = cards_per_count_question
        self.ramp = ramp
        self._cache_dir = cache_dir
        self._chart: dict[str, str] | None = None
        self._devs: list[dict] | None = None
        self._deviation_pool = deviation_pool

    # -- lazy material -----------------------------------------------------

    @property
    def chart(self) -> dict[str, str]:
        if self._chart is None:
            self._chart = cached_chart(self.rules, cache_dir=self._cache_dir)
        return self._chart

    @property
    def deviations(self) -> list[dict]:
        if self._devs is None:
            self._devs = cached_deviations(
                self.rules, top=self._deviation_pool, cache_dir=self._cache_dir
            )
        return self._devs

    def warm_up(self) -> None:
        """Compute and cache whatever the selected drills need.

        Called before the interactive loop so the first question does not stall
        while a chart is derived.
        """
        if "strategy" in self.kinds or "deviation" in self.kinds:
            _ = self.chart
        if "deviation" in self.kinds:
            _ = self.deviations

    # -- question generation ----------------------------------------------

    def next_question(self) -> Question:
        kind = self._pick_kind()
        return {
            "count": self.count_question,
            "truecount": self.truecount_question,
            "strategy": self.strategy_question,
            "deviation": self.deviation_question,
            "bet": self.bet_question,
        }[kind]()

    def _pick_kind(self) -> str:
        """Choose a drill type, favouring the ones going worst."""
        usable = [k for k in self.kinds if k != "deviation" or self.deviations]
        if not usable:
            usable = [k for k in self.kinds if k != "deviation"] or ["count"]
        weights = [self._kind_weight(k) for k in usable]
        return self.rng.choices(usable, weights=weights, k=1)[0]

    def _kind_weight(self, kind: str) -> float:
        keys = [k for k in self.progress.items if k.startswith(f"{kind}:")]
        if not keys:
            return 3.0
        return sum(self.progress.weight(k) for k in keys) / len(keys)

    def count_question(self) -> Question:
        deck = fresh_deck(self.rules.decks)
        cards: list[int] = []
        rc = 0
        for _ in range(self.cards_per_count_question):
            rank = self._draw(deck)
            deck = remove(deck, rank)
            cards.append(rank)
            rc += HILO_TAGS[rank]
        shown = " ".join(card_name(c, self.rng) for c in cards)
        return Question(
            kind="count",
            prompt=f"Running count after: {shown}",
            answer=str(rc),
            item_key=f"count:{len(cards)}",
            explain=f"tags {' '.join(f'{HILO_TAGS[c]:+d}' for c in cards)} = {rc:+d}",
            context={"cards": cards, "running_count": rc},
        )

    def truecount_question(self) -> Question:
        # Half-deck granularity, because that is what a discard tray gives you,
        # and never deeper than the cut card allows -- drilling "half a deck
        # left" is wasted effort at a table that shuffles with 1.5 remaining.
        min_left = max(0.5, self.rules.decks - self.rules.penetration_decks_dealt)
        lo = max(1, int(round(min_left * 2)))
        hi = self.rules.decks * 2 - 1     # at least half a deck has been dealt
        halves = self.rng.randint(lo, max(lo, hi))
        decks_left = halves / 2.0

        # The running count is not free to be anything. It starts at zero and
        # random-walks as cards come out, so its spread depends on how many have
        # been DEALT: sd = sigma * sqrt(dealt * remaining / (total - 1)), with
        # sigma^2 = 40/52 for Hi-Lo's forty non-zero tags. Sampling uniformly
        # would drill impossible shoes -- a running count of -35 with the whole
        # shoe still in the tray.
        total = self.rules.decks * 52
        remaining = decks_left * 52
        dealt = total - remaining
        sd = math.sqrt(40.0 / 52.0) * math.sqrt(
            max(0.0, dealt * remaining / (total - 1))
        )
        rc = int(round(self.rng.gauss(0.0, sd))) if sd > 0 else 0
        tc = rc / decks_left
        return Question(
            kind="truecount",
            prompt=f"Running count {rc:+d}, about {decks_left:g} decks left. "
                   f"True count?",
            answer=f"{tc:.2f}",
            item_key=f"truecount:{decks_left:g}",
            tolerance=0.5,
            explain=f"{rc:+d} / {decks_left:g} = {tc:+.2f}",
            context={"running_count": rc, "decks_remaining": decks_left},
        )

    def strategy_question(self) -> Question:
        key = self._weighted_choice(
            [k for k in self.chart], lambda k: f"strategy:{k}"
        )
        category, label, upcard = key.split("|")
        action = self.chart[key]
        hand = {"hard": f"hard {label}", "soft": label, "pair": label}[category]
        return Question(
            kind="strategy",
            prompt=f"{hand} vs dealer {upcard} -- hit, stand, double, split "
                   f"or surrender?",
            answer=action,
            item_key=f"strategy:{key}",
            explain=f"basic strategy for these rules says {action}",
            context={"category": category, "label": label, "upcard": upcard},
        )

    def deviation_question(self) -> Question:
        if not self.deviations:
            return self.strategy_question()
        d = self._weighted_choice(
            self.deviations,
            lambda x: f"deviation:{x['category']}|{x['label']}|{x['upcard']}",
        )
        index, direction = d["index"], d["direction"]
        # Ask on both sides of the index, so the drill teaches the boundary
        # rather than one memorised answer.
        deviating = self.rng.random() < 0.5
        if direction == "+":
            tc = index + self.rng.randint(0, 3) if deviating \
                else index - self.rng.randint(1, 3)
        else:
            tc = index - self.rng.randint(0, 3) if deviating \
                else index + self.rng.randint(1, 3)
        acts = d["switch_to"] if deviating else d["basic"]
        hand = {"hard": f"hard {d['label']}", "soft": d["label"],
                "pair": d["label"]}[d["category"]]
        return Question(
            kind="deviation",
            prompt=f"{hand} vs dealer {d['upcard']} at true count {tc:+d}?",
            answer=acts,
            item_key=f"deviation:{d['category']}|{d['label']}|{d['upcard']}",
            explain=f"index is {index:+d}{direction}: "
                    f"{d['switch_to']} at {index:+d}{direction}, "
                    f"otherwise {d['basic']}",
            context={"index": index, "direction": direction, "tc": tc},
        )

    def bet_question(self) -> Question:
        if not self.ramp:
            return self.truecount_question()
        tc = self._weighted_choice(
            sorted(self.ramp), lambda t: f"bet:{t}"
        )
        bet = self.ramp[tc]
        return Question(
            kind="bet",
            prompt=f"True count {tc:+d}. What do you bet, in "
                   f"{self.rules.currency}?",
            answer=f"{bet:g}",
            item_key=f"bet:{tc}",
            tolerance=max(1.0, self.rules.table_min / 2.0),
            explain=f"your ramp says {self.rules.currency} {bet:,.0f}",
            context={"true_count": tc, "bet": bet},
        )

    # -- helpers -----------------------------------------------------------

    def _draw(self, deck) -> int:
        total = sum(deck)
        pick = self.rng.random() * total
        acc = 0.0
        for rank in RANKS:
            acc += deck[rank]
            if pick < acc:
                return rank
        return RANKS[-1]

    def _weighted_choice(self, options, key_of):
        weights = [self.progress.weight(key_of(o)) for o in options]
        return self.rng.choices(list(options), weights=weights, k=1)[0]

    # -- recording ---------------------------------------------------------

    def answer(self, question: Question, response: str, seconds: float) -> bool:
        correct = question.check(response)
        self.progress.record(question.item_key, correct, seconds)
        return correct
