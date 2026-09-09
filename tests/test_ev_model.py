import pytest

from bjtoolkit import constants as C
from bjtoolkit.ev_model import breakeven_tc, ev_at_tc, ev_sensitivity, variance_at_tc
from bjtoolkit.rules import get_preset


def test_linear_in_true_count():
    r = get_preset("ambassador")
    base = ev_at_tc(0, r)
    for tc in range(-5, 11):
        assert ev_at_tc(tc, r) == pytest.approx(base + C.HILO_SLOPE.value * tc)


def test_monotonic_increasing():
    r = get_preset("ambassador")
    evs = [ev_at_tc(tc, r) for tc in range(-6, 12)]
    assert evs == sorted(evs)


def test_slope_matches_the_measured_constant():
    """The rule of thumb is half a percent per true count. Measured with the
    exact analyzer over the counts you actually bet in it is 0.535%, which is
    what the constant now carries -- see docs/validation.md section 8."""
    r = get_preset("ambassador")
    step = ev_at_tc(1, r) - ev_at_tc(0, r)
    assert step == pytest.approx(C.HILO_SLOPE.value, abs=1e-9)
    assert step == pytest.approx(0.00535, abs=1e-5)


def test_ev_at_zero_is_the_base_edge():
    from bjtoolkit.rules import base_edge
    r = get_preset("vegas-strip")
    assert ev_at_tc(0, r) == pytest.approx(base_edge(r))


def test_breakeven_tc_is_where_ev_crosses_zero():
    for name in ("ambassador", "vegas-strip", "vegas-8d", "six-five"):
        r = get_preset(name)
        assert ev_at_tc(breakeven_tc(r), r) == pytest.approx(0.0, abs=1e-12)


def test_worse_rules_need_a_higher_count_to_break_even():
    assert breakeven_tc(get_preset("vegas-strip")) < breakeven_tc(get_preset("vegas-8d"))
    assert breakeven_tc(get_preset("vegas-8d")) < breakeven_tc(get_preset("six-five"))


def test_six_five_needs_an_absurd_count():
    """The point of the 6:5 warning: you would need TC +4 just to break even."""
    assert breakeven_tc(get_preset("six-five")) > 3.5


def test_variance_rises_with_the_count():
    assert variance_at_tc(0) == pytest.approx(C.HAND_VARIANCE.value)
    assert variance_at_tc(5) > variance_at_tc(0)
    assert variance_at_tc(5) == pytest.approx(1.42, abs=0.02)


def test_variance_does_not_fall_below_baseline_at_negative_counts():
    assert variance_at_tc(-5) == pytest.approx(C.HAND_VARIANCE.value)


def test_variance_can_be_held_constant():
    assert variance_at_tc(8, tc_dependent=False) == C.HAND_VARIANCE.value


def test_sensitivity_brackets_the_point_estimate():
    r = get_preset("ambassador")
    for s in ev_sensitivity(3.0, r):
        assert s.low < s.point < s.high
        assert s.swing > 0


def test_combined_sensitivity_is_widest():
    r = get_preset("ambassador")
    rows = ev_sensitivity(4.0, r)
    assert rows[-1].swing >= max(s.swing for s in rows[:-1])


def test_slope_uncertainty_grows_with_the_count():
    """At high counts the slope matters more than the rules do."""
    r = get_preset("ambassador")
    low_tc = ev_sensitivity(1.0, r)[1].swing
    high_tc = ev_sensitivity(6.0, r)[1].swing
    assert high_tc > low_tc * 4


def test_every_constant_declares_a_range():
    for name, est in C.ALL_ESTIMATES.items():
        assert est.low <= est.value <= est.high, name
        assert est.source, name


def test_estimate_rejects_a_value_outside_its_range():
    with pytest.raises(ValueError):
        C.Estimate(value=1.0, low=2.0, high=3.0, source="nonsense")
