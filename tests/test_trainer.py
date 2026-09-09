"""The trainer engine is pure, so all of it is testable without a terminal."""

import json

import pytest

from bjtoolkit.cards import HILO_TAGS
from bjtoolkit.rules import get_preset
from bjtoolkit.trainer import (
    KINDS,
    ItemStats,
    Progress,
    Question,
    Trainer,
    cached_chart,
    cached_deviations,
)


@pytest.fixture(scope="module")
def rules():
    return get_preset("ambassador")


@pytest.fixture(scope="module")
def shared_cache(tmp_path_factory):
    """One cache for the whole module: a chart costs a couple of seconds to
    compute and nothing to reuse."""
    return tmp_path_factory.mktemp("bjcache")


@pytest.fixture
def trainer(rules, shared_cache):
    return Trainer(rules, kinds=("count", "truecount"), seed=5,
                   cache_dir=shared_cache)


# --- progress and weighting ----------------------------------------------

def test_unseen_items_are_prioritised():
    p = Progress()
    p.record("known", True, 1.0)
    assert p.weight("never-seen") > p.weight("known")


def test_wrong_answers_come_back_more_often():
    p = Progress()
    for _ in range(5):
        p.record("easy", True, 1.0)
        p.record("hard", False, 1.0)
    assert p.weight("hard") > p.weight("easy") * 3


def test_slow_answers_come_back_more_often():
    """Knowing it eventually is not the same as knowing it at the table."""
    p = Progress()
    for _ in range(5):
        p.record("quick", True, 1.0)
        p.record("laboured", True, 12.0)
    assert p.weight("laboured") > p.weight("quick")


def test_weight_is_bounded_so_nothing_starves():
    p = Progress()
    for _ in range(50):
        p.record("awful", False, 60.0)
    assert p.weight("awful") < 15.0


def test_stats_track_accuracy_and_time():
    s = ItemStats()
    assert s.accuracy == 0.0 and s.mean_seconds == 0.0
    p = Progress()
    p.record("k", True, 2.0)
    p.record("k", False, 4.0)
    assert p.stat("k").accuracy == 0.5
    assert p.stat("k").mean_seconds == 3.0


def test_summary_aggregates_everything():
    p = Progress()
    p.record("a", True, 1.0)
    p.record("b", False, 3.0)
    s = p.summary()
    assert s == {"answered": 2, "correct": 1, "accuracy": 0.5,
                 "mean_seconds": 2.0, "items_tracked": 2}


def test_weakest_lists_the_worst_first():
    p = Progress()
    for _ in range(3):
        p.record("good", True, 1.0)
        p.record("bad", False, 1.0)
    worst = p.weakest(2)
    assert worst[0][0] == "bad"


def test_weakest_ignores_items_seen_once():
    """One miss is noise, not a weakness."""
    p = Progress()
    p.record("fluke", False, 1.0)
    assert p.weakest() == []


# --- persistence ----------------------------------------------------------

def test_progress_round_trips_through_disk(tmp_path):
    p = Progress()
    p.record("count:12", True, 2.5)
    p.record("strategy:hard|16|T", False, 5.0)
    path = tmp_path / "prog.json"
    p.save(path)
    back = Progress.load(path)
    assert back.to_dict() == p.to_dict()
    assert back.stat("count:12").mean_seconds == 2.5


def test_missing_progress_file_is_a_fresh_start(tmp_path):
    assert Progress.load(tmp_path / "nope.json").summary()["answered"] == 0


def test_corrupt_progress_file_does_not_stop_you_drilling(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json at all")
    assert Progress.load(path).summary()["answered"] == 0


# --- questions ------------------------------------------------------------

def test_counting_question_answer_matches_the_tags(trainer):
    q = trainer.count_question()
    assert q.answer == str(sum(HILO_TAGS[c] for c in q.context["cards"]))
    assert q.check(q.answer)
    assert not q.check(str(int(q.answer) + 1))


def test_counting_question_shows_the_requested_number_of_cards(rules, tmp_path):
    t = Trainer(rules, kinds=("count",), seed=1, cards_per_count_question=20,
                cache_dir=tmp_path)
    assert len(t.count_question().context["cards"]) == 20


def test_tens_are_shown_as_all_four_faces(rules, tmp_path):
    t = Trainer(rules, kinds=("count",), seed=2, cards_per_count_question=40,
                cache_dir=tmp_path)
    seen = set()
    for _ in range(15):
        seen.update(t.count_question().prompt.split(": ")[1].split())
    assert {"10", "J", "Q", "K"} <= seen


def test_true_count_questions_stay_inside_the_cut_card(rules, tmp_path):
    """Drilling shoe states the dealer would already have shuffled is wasted."""
    t = Trainer(rules, kinds=("truecount",), seed=3, cache_dir=tmp_path)
    floor = rules.decks - rules.penetration_decks_dealt
    for _ in range(60):
        left = t.truecount_question().context["decks_remaining"]
        assert floor - 1e-9 <= left <= rules.decks


def test_a_full_shoe_has_a_zero_running_count(rules, tmp_path):
    """The count starts at zero, so it cannot be -35 with nothing dealt."""
    t = Trainer(rules, kinds=("truecount",), seed=4, cache_dir=tmp_path)
    for _ in range(80):
        q = t.truecount_question()
        left = q.context["decks_remaining"]
        rc = q.context["running_count"]
        dealt = (rules.decks - left) * 52
        # Three standard deviations of a Hi-Lo random walk, plus slack.
        limit = 3.2 * (0.878 * (dealt * left * 52 / (rules.decks * 52)) ** 0.5) + 3
        assert abs(rc) <= limit, (rc, left)


def test_true_count_accepts_a_half_count_of_slack(trainer):
    q = trainer.truecount_question()
    exact = float(q.answer)
    assert q.check(f"{exact + 0.4:.2f}")
    assert not q.check(f"{exact + 0.9:.2f}")


def test_question_rejects_junk(trainer):
    q = trainer.count_question()
    for junk in ("", "   ", "banana", "h"):
        assert not q.check(junk)


# --- strategy and deviation drills ---------------------------------------

def test_strategy_questions_come_from_the_computed_chart(rules, shared_cache):
    t = Trainer(rules, kinds=("strategy",), seed=6, cache_dir=shared_cache)
    chart = t.chart
    for _ in range(20):
        q = t.strategy_question()
        key = "|".join((q.context["category"], q.context["label"],
                        q.context["upcard"]))
        assert q.answer == chart[key]


def test_strategy_drill_teaches_the_enhc_corrections(rules, shared_cache):
    """The whole point of generating from the analyzer: this drill teaches the
    Prague answer, not the Vegas one."""
    chart = cached_chart(rules, cache_dir=shared_cache)
    assert chart["hard|11|A"] == "hit"
    assert chart["hard|11|T"] == "hit"
    assert chart["pair|8,8|A"] == "hit"
    assert chart["pair|8,8|T"] == "surrender"


def test_action_answers_accept_letters_and_words(rules, shared_cache):
    t = Trainer(rules, kinds=("strategy",), seed=7, cache_dir=shared_cache)
    q = t.strategy_question()
    word = q.answer
    letter = {"hit": "h", "stand": "s", "double": "d", "split": "p",
              "surrender": "r"}[word]
    assert q.check(word) and q.check(letter) and q.check(word.upper())
    assert not q.check("z")


@pytest.mark.slow
def test_deviation_questions_ask_both_sides_of_the_index(rules, tmp_path):
    """A drill that only ever asks above the index teaches one answer, not a
    boundary."""
    t = Trainer(rules, kinds=("deviation",), seed=8, cache_dir=tmp_path)
    answers = set()
    for _ in range(60):
        q = t.deviation_question()
        answers.add((q.item_key, q.answer))
    keys = {k for k, _ in answers}
    both = [k for k in keys if len({a for kk, a in answers if kk == k}) > 1]
    assert both, "no cell was ever asked on both sides of its index"


@pytest.mark.slow
def test_deviations_are_cached_and_ranked(rules, tmp_path):
    rows = cached_deviations(rules, top=10, cache_dir=tmp_path)
    assert len(rows) <= 10
    assert [r["value"] for r in rows] == sorted(
        (r["value"] for r in rows), reverse=True
    )
    again = cached_deviations(rules, top=10, cache_dir=tmp_path)
    assert again == rows


def test_deviation_drill_falls_back_when_there_is_nothing_ranked(rules, shared_cache):
    t = Trainer(rules, kinds=("deviation",), seed=9, cache_dir=shared_cache)
    t._devs = []
    assert t.deviation_question().kind == "strategy"


# --- betting drill --------------------------------------------------------

def test_bet_drill_uses_your_own_ramp(rules, tmp_path):
    ramp = {-1: 200.0, 0: 200.0, 2: 800.0, 4: 1600.0}
    t = Trainer(rules, kinds=("bet",), seed=10, ramp=ramp, cache_dir=tmp_path)
    for _ in range(20):
        q = t.bet_question()
        assert float(q.answer) == ramp[q.context["true_count"]]


def test_bet_drill_falls_back_without_a_ramp(rules, tmp_path):
    t = Trainer(rules, kinds=("bet",), seed=11, cache_dir=tmp_path)
    assert t.bet_question().kind == "truecount"


# --- the loop -------------------------------------------------------------

def test_answering_records_progress(trainer):
    q = trainer.count_question()
    assert trainer.answer(q, q.answer, 1.5) is True
    assert trainer.progress.stat(q.item_key).correct == 1
    assert trainer.answer(q, "nonsense", 9.0) is False
    assert trainer.progress.stat(q.item_key).seen == 2


def test_next_question_only_returns_selected_kinds(rules, tmp_path):
    t = Trainer(rules, kinds=("count", "truecount"), seed=12, cache_dir=tmp_path)
    kinds = {t.next_question().kind for _ in range(40)}
    assert kinds <= {"count", "truecount"}


def test_unknown_kind_is_rejected(rules):
    with pytest.raises(ValueError, match="unknown drill kind"):
        Trainer(rules, kinds=("count", "telepathy"))


def test_every_advertised_kind_can_generate_a_question(rules, shared_cache):
    ramp = {0: 200.0, 3: 1000.0}
    # "deviation" needs a full index scan, so it is exercised in the slow suite.
    for kind in [k for k in KINDS if k != "deviation"]:
        t = Trainer(rules, kinds=(kind,), seed=13, ramp=ramp,
                    cache_dir=shared_cache)
        q = t.next_question()
        assert isinstance(q, Question) and q.prompt and q.answer


@pytest.mark.slow
def test_the_deviation_kind_generates_a_question(rules, shared_cache):
    t = Trainer(rules, kinds=("deviation",), seed=13, cache_dir=shared_cache)
    q = t.next_question()
    assert isinstance(q, Question) and q.prompt and q.answer
    assert KINDS == ("count", "truecount", "strategy", "deviation", "bet")


def test_drilling_shifts_toward_what_you_get_wrong(rules, tmp_path):
    """The behaviour that makes this practice rather than revision."""
    t = Trainer(rules, kinds=("truecount",), seed=14, cache_dir=tmp_path)
    seen: dict[str, int] = {}
    for _ in range(30):
        q = t.truecount_question()
        seen[q.item_key] = seen.get(q.item_key, 0) + 1
        # Always wrong on one particular divisor, always right elsewhere.
        wrong = q.context["decks_remaining"] == 2.0
        t.answer(q, "-999" if wrong else q.answer, 1.0)
    after = {k: t.progress.weight(k) for k in t.progress.items}
    bad = [k for k in after if k.endswith(":2")]
    if bad:  # only if that divisor came up at all
        assert after[bad[0]] == max(after.values())


def test_chart_cache_is_written_and_reused(rules, tmp_path):
    a = cached_chart(rules, cache_dir=tmp_path)
    files = list(tmp_path.glob("chart_*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == a
    assert cached_chart(rules, cache_dir=tmp_path) == a


def test_different_rules_get_different_cached_charts(tmp_path):
    a = cached_chart(get_preset("ambassador"), cache_dir=tmp_path)
    b = cached_chart(get_preset("vegas-strip"), cache_dir=tmp_path)
    assert a != b
    assert len(list(tmp_path.glob("chart_*.json"))) == 2


def test_warm_up_populates_only_what_the_drills_need(rules, shared_cache):
    t = Trainer(rules, kinds=("count",), seed=15, cache_dir=shared_cache)
    t.warm_up()
    assert t._chart is None and t._devs is None
    t2 = Trainer(rules, kinds=("strategy",), seed=15, cache_dir=shared_cache)
    t2.warm_up()
    assert t2._chart is not None and t2._devs is None
