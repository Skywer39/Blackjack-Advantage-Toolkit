"""The headline test here is that the engine reproduces the published 6-deck
S17 chart cell for cell. Everything else is a consequence of that."""

import pytest

from bjtoolkit.analyzer import Action
from bjtoolkit.cards import ACE, TEN, hand_from
from bjtoolkit.rules import HoleCard, Surrender, get_preset
from bjtoolkit.strategy import (
    UPCARDS, all_deviations, basic_strategy, cards_for_hard, cards_for_pair,
    cards_for_soft, decide, evaluate_cell, find_deviation, hard_compositions,
    insurance_index, rank_deviations,
)

SYM = {Action.HIT: "H", Action.STAND: "S", Action.DOUBLE: "D",
       Action.SPLIT: "P", Action.SURRENDER: "R"}

#: Published basic strategy for 6 decks, S17, DAS, late surrender.
#: Columns are dealer 2,3,4,5,6,7,8,9,T,A.
REFERENCE_S17 = {
    ("hard", "5"): "HHHHHHHHHH", ("hard", "6"): "HHHHHHHHHH",
    ("hard", "7"): "HHHHHHHHHH", ("hard", "8"): "HHHHHHHHHH",
    ("hard", "9"): "HDDDDHHHHH", ("hard", "10"): "DDDDDDDDHH",
    ("hard", "11"): "DDDDDDDDDH", ("hard", "12"): "HHSSSHHHHH",
    ("hard", "13"): "SSSSSHHHHH", ("hard", "14"): "SSSSSHHHHH",
    ("hard", "15"): "SSSSSHHHRH", ("hard", "16"): "SSSSSHHRRR",
    ("hard", "17"): "SSSSSSSSSS", ("hard", "18"): "SSSSSSSSSS",
    ("hard", "19"): "SSSSSSSSSS", ("hard", "20"): "SSSSSSSSSS",
    ("soft", "A,2"): "HHHDDHHHHH", ("soft", "A,3"): "HHHDDHHHHH",
    ("soft", "A,4"): "HHDDDHHHHH", ("soft", "A,5"): "HHDDDHHHHH",
    ("soft", "A,6"): "HDDDDHHHHH", ("soft", "A,7"): "SDDDDSSHHH",
    ("soft", "A,8"): "SSSSSSSSSS", ("soft", "A,9"): "SSSSSSSSSS",
    ("pair", "2,2"): "PPPPPPHHHH", ("pair", "3,3"): "PPPPPPHHHH",
    ("pair", "4,4"): "HHHPPHHHHH", ("pair", "5,5"): "DDDDDDDDHH",
    ("pair", "6,6"): "PPPPPHHHHH", ("pair", "7,7"): "PPPPPPHHHH",
    ("pair", "8,8"): "PPPPPPPPPP", ("pair", "9,9"): "PPPPPSPPSS",
    ("pair", "T,T"): "SSSSSSSSSS", ("pair", "A,A"): "PPPPPPPPPP",
}


@pytest.fixture(scope="module")
def strip_chart():
    cells = basic_strategy(get_preset("vegas-strip"))
    out = {}
    for c in cells:
        out.setdefault((c.category, c.label), {})[c.upcard] = c
    return out


def test_reproduces_the_published_s17_chart_exactly(strip_chart):
    """340 cells, computed from first principles, against the printed chart."""
    wrong = []
    for key, expected in REFERENCE_S17.items():
        got = "".join(SYM[strip_chart[key][u].action] for u in UPCARDS)
        if got != expected:
            wrong.append((key, expected, got))
    assert not wrong, "\n".join(f"{k}: want {e}, got {g}" for k, e, g in wrong)


# --- row construction -----------------------------------------------------

@pytest.mark.parametrize("total", range(5, 21))
def test_hard_rows_really_make_that_hard_total(total):
    assert hand_from(*cards_for_hard(total)) == (total, False)


@pytest.mark.parametrize("total", range(13, 21))
def test_soft_rows_really_make_that_soft_total(total):
    assert hand_from(*cards_for_soft(total)) == (total, True)


def test_hard_compositions_are_a_distribution():
    from bjtoolkit.cards import fresh_deck
    for total in range(5, 21):
        comps = hard_compositions(total, fresh_deck(6))
        assert sum(w for _, w in comps) == pytest.approx(1.0)
        for cards, _ in comps:
            assert hand_from(*cards) == (total, False)


def test_composition_averaging_is_what_matches_the_published_chart():
    """16 vs 9 is hit as T,6 but surrender as 9,7. The published answer is the
    weighted average, which is why chart rows average and `decide` does not."""
    r = get_preset("vegas-strip")
    from bjtoolkit.analyzer import action_evs
    from bjtoolkit.cards import deck_for_true_count, remove_many
    base = deck_for_true_count(0, 6)
    picks = {}
    for cards in ((4, 8), (5, 7)):
        evs = action_evs(cards, 7, remove_many(base, *cards, 7), r,
                         allow_split=False)
        picks[cards] = max(evs, key=lambda a: evs[a])
    assert picks[(4, 8)] != picks[(5, 7)]
    assert evaluate_cell("hard", cards_for_hard(16), "16", 7, r).action \
        is Action.SURRENDER


# --- rules actually change the chart --------------------------------------

def test_h17_moves_the_soft_18_and_eleven_cells():
    s17 = {c.upcard: c for c in basic_strategy(get_preset("vegas-strip"))
           if c.category == "hard" and c.label == "11"}
    h17 = {c.upcard: c for c in basic_strategy(get_preset("vegas-h17"))
           if c.category == "hard" and c.label == "11"}
    # Doubling 11 against an ace is correct only when the dealer hits soft 17.
    assert s17[ACE].action is Action.HIT
    assert h17[ACE].action is Action.DOUBLE


def test_without_surrender_the_chart_has_none():
    cells = basic_strategy(get_preset("vegas-8d"))
    assert all(c.action is not Action.SURRENDER for c in cells)


def test_no_das_reduces_the_number_of_splits():
    from bjtoolkit.rules import RuleSet
    with_das = basic_strategy(RuleSet(decks=6, double_after_split=True))
    without = basic_strategy(RuleSet(decks=6, double_after_split=False))
    assert sum(c.action is Action.SPLIT for c in with_das) > \
        sum(c.action is Action.SPLIT for c in without)


# --- the ENHC corrections -------------------------------------------------

@pytest.fixture(scope="module")
def enhc_chart():
    cells = basic_strategy(get_preset("ambassador"))
    out = {}
    for c in cells:
        out.setdefault((c.category, c.label), {})[c.upcard] = c
    return out


@pytest.mark.parametrize("key,upcard,expected", [
    (("hard", "11"), ACE, Action.HIT),      # never double into a natural
    (("pair", "8,8"), ACE, Action.HIT),     # never split into one either
    (("pair", "A,A"), ACE, Action.HIT),
    (("pair", "8,8"), TEN, Action.SURRENDER),
])
def test_the_known_enhc_corrections_are_confirmed(enhc_chart, key, upcard, expected):
    """These four are the corrections the accompanying chart already lists."""
    assert enhc_chart[key][upcard].action is expected


def test_eleven_versus_ten_is_a_fifth_enhc_correction(enhc_chart):
    """Not on the accompanying chart, but it follows from the same arithmetic:
    a ten upcard makes a natural 7.7% of the time, and that is enough to make
    doubling 11 wrong at a neutral shoe."""
    assert enhc_chart[("hard", "11")][TEN].action is Action.HIT
    assert basic_strategy(get_preset("vegas-strip"))  # sanity: peek game differs
    peek = {c.upcard: c for c in basic_strategy(get_preset("vegas-strip"))
            if c.category == "hard" and c.label == "11"}
    assert peek[TEN].action is Action.DOUBLE


def test_everything_against_a_low_upcard_is_unchanged_by_enhc(enhc_chart,
                                                             strip_chart):
    """A dealer showing 2-9 cannot have a natural, so no ENHC correction can
    apply there. Any difference in those columns would be a bug."""
    for key in REFERENCE_S17:
        for up in range(0, 8):   # ranks 2 through 9
            assert enhc_chart[key][up].action is strip_chart[key][up].action, \
                f"{key} vs {up}"


# --- deviations -----------------------------------------------------------

def test_a_deviation_is_found_where_one_should_be():
    r = get_preset("vegas-strip")
    d = find_deviation("hard", cards_for_hard(16), "16", TEN, r)
    assert d is not None


@pytest.mark.slow
def test_deviation_directions_are_consistent():
    for d in all_deviations(get_preset("ambassador"), tc_range=(-4, 5)):
        assert d.direction in ("+", "-")
        assert (d.index > 0) == (d.direction == "+")
        assert d.basic is not d.switch_to


@pytest.mark.slow
def test_ranking_puts_valuable_deviations_first():
    from bjtoolkit.frequency import simulate_tc_distribution
    r = get_preset("ambassador")
    dist = simulate_tc_distribution(r, n_shoes=1500, seed=4)
    devs = all_deviations(r, tc_range=(-3, 4))
    ranked = rank_deviations(r, {t: dist.p(t) for t in dist.counts()},
                             deviations=devs)
    values = [x.value_per_hand for x in ranked]
    assert values == sorted(values, reverse=True)
    assert all(v >= 0 for v in values)


def test_insurance_sits_just_above_three():
    """The conventional index is +3; the honest number is a shade higher."""
    for preset in ("ambassador", "vegas-strip", "vegas-8d"):
        assert 3.0 <= insurance_index(get_preset(preset)) <= 3.3


def test_insurance_comes_sooner_in_a_single_deck_game():
    assert insurance_index(get_preset("single-deck")) < \
        insurance_index(get_preset("vegas-strip"))


# --- decide ---------------------------------------------------------------

def test_decide_uses_your_actual_cards_not_the_averaged_row():
    """At the table you can see your cards, so composition-specific is correct."""
    r = get_preset("vegas-strip")
    assert decide((4, 8), 7, 0.0, r) is Action.HIT          # T,6 vs 9
    assert decide((5, 7), 7, 0.0, r) is Action.SURRENDER    # 9,7 vs 9


def test_decide_follows_the_count():
    """12 vs 3 is the textbook case: hit at a neutral shoe, stand once the deck
    is rich enough that drawing is likely to bust you."""
    r = get_preset("vegas-strip")
    assert decide(cards_for_hard(12), 1, 0.0, r) is Action.HIT
    assert decide(cards_for_hard(12), 1, 4.0, r) is Action.STAND


def test_sixteen_versus_ten_stands_at_high_counts_when_surrender_is_absent():
    """The most famous index of all. It only shows up in a game without
    surrender -- where surrender is offered it beats standing at every count,
    which is why this engine reports no index for it in the Ambassador game."""
    r = get_preset("vegas-8d")   # no surrender
    assert decide(cards_for_hard(16), TEN, -2.0, r) is Action.HIT
    assert decide(cards_for_hard(16), TEN, 2.0, r) is Action.STAND


def test_decide_never_offers_an_illegal_action():
    r = get_preset("ambassador")
    # Three cards: no double, no split, no surrender.
    assert decide((4, 1, 2), 5, 0.0, r) in (Action.HIT, Action.STAND)
