"""The analyzer is checked against published dealer probabilities and against
arithmetic identities that must hold whatever the rules are."""

import pytest

from bjtoolkit.analyzer import (
    ACE, Action, action_evs, dealer_outcomes, ev_stand, prob_dealer_blackjack,
)
from bjtoolkit.cards import TEN, fresh_deck, hand_from, remove_many
from bjtoolkit.rules import HoleCard, RuleSet, Surrender, get_preset


@pytest.fixture(scope="module")
def deck6():
    return fresh_deck(6)


def dist(upcard, deck6, h17=False, exclude_bj=True):
    return dealer_outcomes(upcard, remove_many(deck6, upcard), h17, exclude_bj)


# --- dealer ---------------------------------------------------------------

@pytest.mark.parametrize("upcard,expected_bust", [
    (0, 0.353), (1, 0.375), (2, 0.394), (3, 0.416), (4, 0.423),
    (5, 0.262), (6, 0.245), (7, 0.231),
])
def test_dealer_bust_rates_match_published_tables(upcard, expected_bust, deck6):
    """Standard 6-deck S17 dealer bust probabilities, to a tenth of a point."""
    assert dist(upcard, deck6)[5] == pytest.approx(expected_bust, abs=0.004)


def test_dealer_outcome_distributions_are_normalised(deck6):
    for up in range(10):
        for h17 in (False, True):
            assert sum(dist(up, deck6, h17)) == pytest.approx(1.0)


def test_ten_up_bust_rate_reflects_the_no_blackjack_conditioning(deck6):
    """Excluding naturals removes the automatic 21s, so the surviving hands bust
    more often. 21.2% unconditional becomes 21.2/(1-0.077) = 23.0%."""
    assert dist(TEN, deck6)[5] == pytest.approx(0.230, abs=0.004)


def test_hitting_soft_17_reduces_dealer_bust_on_an_ace(deck6):
    s17 = dist(ACE, deck6, h17=False)
    h17 = dist(ACE, deck6, h17=True)
    assert h17[5] > s17[5]        # hitting soft 17 busts more often
    assert h17[0] < s17[0]        # and finishes on 17 less often


def test_dealer_blackjack_probabilities(deck6):
    assert prob_dealer_blackjack(ACE, remove_many(deck6, ACE)) == pytest.approx(
        96 / 311, abs=1e-6
    )
    assert prob_dealer_blackjack(TEN, remove_many(deck6, TEN)) == pytest.approx(
        24 / 311, abs=1e-6
    )
    assert prob_dealer_blackjack(4, deck6) == 0.0


# --- player ---------------------------------------------------------------

def test_standing_on_a_bust_always_loses(deck6):
    assert ev_stand(22, dist(0, deck6)) == -1.0


def test_standing_on_21_beats_standing_on_20(deck6):
    d = dist(5, deck6)
    assert ev_stand(21, d) > ev_stand(20, d) > ev_stand(19, d)


def test_the_best_upcard_to_stand_against_depends_on_your_total(deck6):
    """Standing on a stiff, you want the upcard that busts most often -- a six.
    Standing on 18 you want a seven, because the dealer's likeliest total is 17,
    which you already beat."""
    stiff = {up: ev_stand(13, dist(up, deck6)) for up in range(10)}
    assert max(stiff, key=lambda u: stiff[u]) == 4      # a six busts most
    strong = {up: ev_stand(18, dist(up, deck6)) for up in range(10)}
    assert max(strong, key=lambda u: strong[u]) == 5    # a seven makes 17
    assert min(stiff, key=lambda u: stiff[u]) == ACE
    # The worst upcard for an 18 is a nine, not an ace: a nine makes 19 often,
    # while an ace that is already known not to be a natural makes a lot of 17s.
    assert min(strong, key=lambda u: strong[u]) == 7


# --- the dealer-blackjack branch, which is the point of the module ---------

def test_peek_and_original_bet_only_are_identical(deck6):
    """OBO gives back exactly what a peek would have, so play must not differ."""
    peek = RuleSet(decks=6, hole_card=HoleCard.PEEK)
    obo = RuleSet(decks=6, hole_card=HoleCard.ENHC_ORIGINAL_ONLY)
    cards = (3, 4)  # 5 + 6 = 11
    deck = remove_many(deck6, *cards, ACE)
    a = action_evs(cards, ACE, deck, peek)
    b = action_evs(cards, ACE, deck, obo)
    for action in a:
        assert a[action] == pytest.approx(b[action])


def test_full_enhc_penalises_doubling_but_not_hitting(deck6):
    """The asymmetry that forces an ENHC-specific chart."""
    peek = RuleSet(decks=6, hole_card=HoleCard.PEEK)
    enhc = RuleSet(decks=6, hole_card=HoleCard.ENHC_ALL_BETS)
    cards = (3, 4)
    deck = remove_many(deck6, *cards, ACE)
    p = action_evs(cards, ACE, deck, peek)
    e = action_evs(cards, ACE, deck, enhc)
    p_bj = prob_dealer_blackjack(ACE, deck)
    # Hitting risks one unit either way, so it loses exactly the blackjack term.
    assert e[Action.HIT] == pytest.approx(
        (1 - p_bj) * p[Action.HIT] - p_bj, abs=1e-9
    )
    # Doubling risks two, so it loses twice as much.
    assert e[Action.DOUBLE] == pytest.approx(
        (1 - p_bj) * p[Action.DOUBLE] - 2 * p_bj, abs=1e-9
    )


def test_doubling_eleven_into_an_ace_is_never_right_under_full_enhc(deck6):
    """A ~31% chance of losing a doubled bet swamps any doubling gain, and it
    gets worse with the count because tens get richer. Contradicts the standard
    Illustrious 18 index of +1, which assumes a peek game."""
    from bjtoolkit.cards import deck_for_true_count
    enhc = get_preset("ambassador")
    for tc in (0, 1, 2, 4, 8, 12):
        deck = remove_many(deck_for_true_count(tc, 6), 3, 4, ACE)
        evs = action_evs((3, 4), ACE, deck, enhc)
        assert evs[Action.DOUBLE] < evs[Action.HIT], f"flipped at TC {tc}"


def test_the_same_hand_does_double_in_a_peek_game(deck6):
    """The mirror of the test above: the engine reproduces the published +1
    index when the dealer peeks, so the ENHC result is not a bug."""
    from bjtoolkit.cards import deck_for_true_count
    peek = get_preset("vegas-strip")
    at0 = action_evs((3, 4), ACE, remove_many(deck_for_true_count(0, 6), 3, 4, ACE), peek)
    at1 = action_evs((3, 4), ACE, remove_many(deck_for_true_count(1, 6), 3, 4, ACE), peek)
    assert at0[Action.HIT] > at0[Action.DOUBLE]
    assert at1[Action.DOUBLE] > at1[Action.HIT]


def test_early_surrender_is_a_flat_half_unit(deck6):
    r = RuleSet(decks=6, surrender=Surrender.EARLY_ALL,
                hole_card=HoleCard.ENHC_ALL_BETS)
    evs = action_evs((8, 4), ACE, remove_many(deck6, 8, 4, ACE), r)
    assert evs[Action.SURRENDER] == -0.5


def test_late_surrender_is_worse_than_early_under_enhc(deck6):
    """Late surrender loses the whole bet to a dealer natural, early does not.
    This is the settlement question in docs/open-questions.md, made concrete."""
    late = RuleSet(decks=6, surrender=Surrender.LATE_ALL,
                   hole_card=HoleCard.ENHC_ALL_BETS)
    early = RuleSet(decks=6, surrender=Surrender.EARLY_ALL,
                    hole_card=HoleCard.ENHC_ALL_BETS)
    deck = remove_many(deck6, 8, 4, ACE)
    a = action_evs((8, 4), ACE, deck, late)[Action.SURRENDER]
    b = action_evs((8, 4), ACE, deck, early)[Action.SURRENDER]
    assert b > a


def test_surrender_is_only_offered_where_the_rules_allow_it(deck6):
    for surrender, upcards_with in (
        (Surrender.NONE, set()),
        (Surrender.LATE_VS_10, {TEN}),
        (Surrender.LATE_VS_9_10, {7, TEN}),
        (Surrender.LATE_ALL, set(range(10))),
    ):
        r = RuleSet(decks=6, surrender=surrender)
        for up in range(10):
            evs = action_evs((8, 4), up, remove_many(deck6, 8, 4, up), r)
            has = Action.SURRENDER in evs
            assert has == (up in upcards_with), (surrender, up)


def test_splitting_is_only_offered_on_a_pair(deck6):
    r = RuleSet(decks=6)
    assert Action.SPLIT in action_evs((6, 6), 4, remove_many(deck6, 6, 6, 4), r)
    assert Action.SPLIT not in action_evs((6, 5), 4, remove_many(deck6, 6, 5, 4), r)


def test_doubling_restrictions_are_honoured(deck6):
    from bjtoolkit.rules import DoubleRule
    tight = RuleSet(decks=6, double_rule=DoubleRule.TEN_ELEVEN)
    # 5+6 = 11 may double; 3+4 = 7 may not.
    assert Action.DOUBLE in action_evs((3, 4), 4, remove_many(deck6, 3, 4, 4), tight)
    assert Action.DOUBLE not in action_evs((1, 2), 4, remove_many(deck6, 1, 2, 4), tight)


def test_das_makes_splitting_worth_more(deck6):
    with_das = RuleSet(decks=6, double_after_split=True)
    without = RuleSet(decks=6, double_after_split=False)
    deck = remove_many(deck6, 4, 4, 3)
    a = action_evs((4, 4), 3, deck, with_das)[Action.SPLIT]
    b = action_evs((4, 4), 3, deck, without)[Action.SPLIT]
    assert a > b


def test_every_ev_is_within_the_possible_range(deck6):
    r = get_preset("ambassador")
    for up in range(10):
        evs = action_evs((7, 7), up, remove_many(deck6, 7, 7, up), r)
        for action, v in evs.items():
            assert -2.5 <= v <= 2.5, (up, action, v)
