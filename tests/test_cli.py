"""The --json contract is what a future web UI consumes, so it is tested."""

import json

import pytest
from typer.testing import CliRunner

from bjtoolkit.cli import app

runner = CliRunner()


def run(*args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def run_json(*args):
    return json.loads(run(*args, "--json"))


def test_presets_lists_every_game():
    out = run("presets")
    for key in ("ambassador", "vegas-strip", "six-five", "single-deck"):
        assert key in out


def test_rules_json_exposes_the_component_breakdown():
    d = run_json("rules", "-p", "ambassador")
    assert d["base_edge"] < 0
    assert d["base_edge_low"] < d["base_edge"] < d["base_edge_high"]
    assert len(d["components"]) >= 4
    assert all(c["source"] for c in d["components"])


def test_rules_overrides_apply():
    s17 = run_json("rules", "-p", "vegas-strip", "--s17")
    h17 = run_json("rules", "-p", "vegas-strip", "--h17")
    assert s17["base_edge"] > h17["base_edge"]


def test_deck_and_penetration_overrides_apply():
    d = run_json("rules", "-p", "ambassador", "--decks", "8", "--pen", "6")
    assert d["rules"]["decks"] == 8
    assert d["rules"]["penetration_decks_dealt"] == 6


def test_freq_json_sums_to_one():
    d = run_json("freq", "-p", "ambassador", "--shoes", "800", "--regen")
    assert sum(float(v) for v in d["probs"].values()) == pytest.approx(1.0)


def test_ramp_json_has_a_bet_for_every_count():
    d = run_json("ramp", "-p", "ambassador", "-b", "600000")
    assert d["spread"] > 1
    assert all(float(v) > 0 for v in d["bets"].values())


def test_ramp_reports_warnings_for_a_tiny_bankroll():
    out = run("ramp", "-p", "ambassador", "-b", "40000")
    assert "bankroll too small" in out


def test_risk_json_has_the_headline_metrics():
    d = run_json("risk", "-p", "ambassador", "-b", "800000", "--hours", "100")
    rep = d["report"]
    for key in ("win_rate_per_hour", "sd_per_hour", "n0_hours", "risk_of_ruin",
                "prob_of_profit"):
        assert key in rep
    assert 0.0 <= rep["risk_of_ruin"] <= 1.0
    assert 0.0 <= rep["prob_of_profit"] <= 1.0


def test_bankroll_command_solves_for_a_spread():
    d = run_json("bankroll", "-p", "ambassador", "--spread", "16",
                 "--target-ror", "0.05")
    assert d["required_bankroll"] > 0
    assert d["equivalent_kelly_fraction"] == pytest.approx(0.668, abs=0.01)


def test_bankroll_needed_grows_as_target_ruin_falls():
    lo = run_json("bankroll", "-p", "ambassador", "--spread", "16",
                  "--target-ror", "0.01")["required_bankroll"]
    hi = run_json("bankroll", "-p", "ambassador", "--spread", "16",
                  "--target-ror", "0.20")["required_bankroll"]
    assert lo > hi


def test_viability_json_ranks_spread_options():
    d = run_json("viability", "-p", "ambassador", "-b", "100000")
    assert "verdict" in d
    assert len(d["options"]) >= 5


def test_viability_verdict_flips_with_wonging():
    plain = run_json("viability", "-p", "ambassador", "-b", "100000")
    wong = run_json("viability", "-p", "ambassador", "-b", "100000",
                    "--wong-out-below", "1")
    assert plain["verdict"].startswith("NOT VIABLE")
    assert wong["verdict"].startswith("VIABLE")


def test_pen_sweep_json():
    rows = run_json("pen-sweep", "-p", "ambassador", "--spread", "12")
    assert len(rows) >= 4
    assert [r["prob_tc_ge_4"] for r in rows] == sorted(
        r["prob_tc_ge_4"] for r in rows
    )


def test_sensitivity_json():
    rows = run_json("sensitivity", "-p", "ambassador", "--tc", "3")
    assert all(r["low"] < r["point"] < r["high"] for r in rows)


def test_unknown_preset_is_a_clean_error():
    result = runner.invoke(app, ["rules", "-p", "atlantis"])
    assert result.exit_code != 0
    assert "atlantis" in result.output or "Invalid value" in result.output


def test_works_for_a_us_game_in_dollars():
    d = run_json("viability", "-p", "vegas-strip", "-b", "20000")
    assert d["rules"]["currency"] == "USD"
    assert "USD" in d["verdict"]


def test_ev_negative_spreads_are_labelled_as_such_not_merely_unaffordable():
    """An EV-negative option needs an infinite bankroll; saying 'unaffordable'
    would imply that more money would fix it."""
    out = run("viability", "-p", "ambassador", "-b", "100000")
    assert "EV-negative" in out
