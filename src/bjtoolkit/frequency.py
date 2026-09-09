"""True-count frequency distribution, simulated for a given penetration.

This is the module that makes penetration a real variable. The distribution of
true counts is not a fixed table -- it is entirely determined by how deep the
dealer cuts, and the tail is where all the money is. A game cut at 50% and the
same game cut at 85% have the same rules and completely different value.

The approach is a straight shoe simulation: shuffle, deal to the cut card,
record the true count before each betting decision, histogram the result.
Vectorised over many shoes at once, so a million rounds takes a couple of
seconds.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import constants as C
from .counting import HI_LO, CountSystem
from .rules import RuleSet

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def data_dir() -> Path:
    """Where simulated distributions are cached.

    Overridable via BJTOOLKIT_CACHE_DIR so that tests (and anyone running from a
    read-only checkout) do not write into the repository's data directory.
    """
    override = os.environ.get("BJTOOLKIT_CACHE_DIR")
    return Path(override) if override else _DEFAULT_DATA_DIR


@dataclass
class TCDistribution:
    """P(true count) at the moment you size your bet."""

    probs: dict[int, float]
    decks: int
    penetration_decks_dealt: float
    cards_per_round: float
    rounds_per_shoe: float
    system: str = "Hi-Lo"
    estimate_to_half_deck: bool = False
    n_rounds_simulated: int = 0

    def __post_init__(self) -> None:
        total = sum(self.probs.values())
        if total <= 0:
            raise ValueError("empty distribution")
        if abs(total - 1.0) > 1e-9:
            self.probs = {k: v / total for k, v in self.probs.items()}

    def p(self, tc: int) -> float:
        return self.probs.get(tc, 0.0)

    def counts(self) -> list[int]:
        return sorted(self.probs)

    def prob_at_or_above(self, tc: int) -> float:
        return sum(p for t, p in self.probs.items() if t >= tc)

    def to_dict(self) -> dict:
        return {
            "decks": self.decks,
            "penetration_decks_dealt": self.penetration_decks_dealt,
            "cards_per_round": self.cards_per_round,
            "rounds_per_shoe": self.rounds_per_shoe,
            "system": self.system,
            "estimate_to_half_deck": self.estimate_to_half_deck,
            "n_rounds_simulated": self.n_rounds_simulated,
            "probs": {str(k): v for k, v in sorted(self.probs.items())},
        }

    @classmethod
    def from_dict(cls, d: dict) -> TCDistribution:
        return cls(
            probs={int(k): float(v) for k, v in d["probs"].items()},
            decks=d["decks"],
            penetration_decks_dealt=d["penetration_decks_dealt"],
            cards_per_round=d["cards_per_round"],
            rounds_per_shoe=d["rounds_per_shoe"],
            system=d.get("system", "Hi-Lo"),
            estimate_to_half_deck=d.get("estimate_to_half_deck", False),
            n_rounds_simulated=d.get("n_rounds_simulated", 0),
        )


def cards_per_round(rules: RuleSet) -> float:
    """Cards burned per round: every player's hand plus the dealer's."""
    return C.CARDS_PER_HAND.value * (rules.players_at_table + 1)


def simulate_tc_distribution(
    rules: RuleSet,
    *,
    system: CountSystem = HI_LO,
    n_shoes: int = 40_000,
    estimate_to_half_deck: bool = False,
    tc_clip: int = 12,
    seed: int | None = None,
    batch: int = 4_000,
) -> TCDistribution:
    """Simulate the true-count distribution at the point of betting.

    Counts are bucketed by truncation toward zero, which is what a player
    actually does at the table: a true count of +2.7 is played as "+2 and
    change" for betting, and compared exactly against indices for playing.
    """
    rng = np.random.default_rng(seed)
    tags = system.shoe_tags(rules.decks)
    total_cards = tags.size
    per_round = cards_per_round(rules)
    pen_cards = rules.penetration_decks_dealt * 52.0

    # Cards already dealt before each betting decision: 0, per_round, 2*per_round...
    # We bet before a round, so the last decision is the last one that still has
    # a full round of cards available before the cut card.
    offsets = np.arange(0, max(1, int(pen_cards // per_round))) * per_round
    dealt = offsets.astype(np.int64)
    if dealt.size == 0:
        raise ValueError("penetration too shallow for even one round")

    hist = np.zeros(2 * tc_clip + 1, dtype=np.int64)
    remaining = total_cards - dealt
    decks_remaining = remaining / 52.0
    if estimate_to_half_deck:
        decks_remaining = np.maximum(0.5, np.round(decks_remaining * 2) / 2)

    done = 0
    while done < n_shoes:
        n = min(batch, n_shoes - done)
        # A shuffled shoe per row, as count tags.
        order = np.argsort(rng.random((n, total_cards)), axis=1)
        shoes = tags[order]
        running = np.cumsum(shoes, axis=1, dtype=np.int32)
        # Running count after `d` cards; d=0 means a fresh shoe, count 0.
        rc = np.zeros((n, dealt.size), dtype=np.int32)
        nonzero = dealt > 0
        rc[:, nonzero] = running[:, dealt[nonzero] - 1]

        tc = rc / decks_remaining
        bucket = np.clip(np.trunc(tc).astype(np.int64), -tc_clip, tc_clip)
        hist += np.bincount(bucket.ravel() + tc_clip, minlength=hist.size)
        done += n

    total = hist.sum()
    probs = {
        int(i - tc_clip): float(v) / total
        for i, v in enumerate(hist)
        if v > 0
    }
    return TCDistribution(
        probs=probs,
        decks=rules.decks,
        penetration_decks_dealt=rules.penetration_decks_dealt,
        cards_per_round=per_round,
        rounds_per_shoe=float(dealt.size),
        system=system.name,
        estimate_to_half_deck=estimate_to_half_deck,
        n_rounds_simulated=int(total),
    )


def _cache_key(rules: RuleSet, system: CountSystem, half_deck: bool) -> str:
    return (
        f"tc_{system.name.lower().replace(' ', '').replace('-', '')}"
        f"_{rules.decks}d"
        f"_pen{rules.penetration_decks_dealt:g}"
        f"_p{rules.players_at_table}"
        f"{'_halfdeck' if half_deck else ''}.json"
    )


def load_or_simulate(
    rules: RuleSet,
    *,
    system: CountSystem = HI_LO,
    regenerate: bool = False,
    n_shoes: int = 40_000,
    estimate_to_half_deck: bool = False,
    seed: int | None = 12345,
    cache_dir: Path | None = None,
) -> TCDistribution:
    """Cached wrapper around `simulate_tc_distribution`."""
    cache_dir = cache_dir or data_dir()
    path = cache_dir / _cache_key(rules, system, estimate_to_half_deck)
    if path.exists() and not regenerate:
        return TCDistribution.from_dict(json.loads(path.read_text()))
    dist = simulate_tc_distribution(
        rules,
        system=system,
        n_shoes=n_shoes,
        estimate_to_half_deck=estimate_to_half_deck,
        seed=seed,
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dist.to_dict(), indent=2))
    return dist
