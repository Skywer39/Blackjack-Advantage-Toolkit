"""Command line interface.

Every command takes --json, which emits the same data as machine-readable
output. That is the contract a web UI would consume later.
"""

from __future__ import annotations

import dataclasses
import json as jsonlib
import math
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import constants as C
from .analyzer import Action
from .cards import RANK_NAMES
from .counting import SYSTEMS
from .ev_model import breakeven_tc, ev_at_tc, ev_sensitivity
from .exact import ev_curve, exact_edge, fit_linear
from .frequency import load_or_simulate
from .ramp import kelly_ramp, spread_ramp
from .risk import (
    bankroll_for_ror,
    evaluate,
    kelly_for_ror,
    ror_for_kelly,
)
from .rules import (
    PRESETS,
    RuleSet,
    base_edge,
    base_edge_range,
    edge_components,
    get_preset,
)
from .simulate import ruin_convergence, simulate
from .strategy import (
    UPCARDS,
    all_deviations,
    basic_strategy,
    decide,
    insurance_index,
    rank_deviations,
)
from .viability import assess, penetration_sweep

app = typer.Typer(
    add_completion=False,
    help="Blackjack advantage toolkit: rules in, bankroll and bet ramp out.",
)
console = Console()


def _load_rules(
    preset: str,
    config: Path | None,
    decks: int | None,
    pen: float | None,
    table_min: float | None,
    table_max: float | None,
    h17: bool | None,
    players: int | None,
) -> RuleSet:
    if config is not None:
        rules = RuleSet.model_validate_json(config.read_text())
    else:
        try:
            rules = get_preset(preset)
        except KeyError as exc:
            raise typer.BadParameter(str(exc)) from None
    for field, value in (
        ("decks", decks),
        ("penetration_decks_dealt", pen),
        ("table_min", table_min),
        ("table_max", table_max),
        ("dealer_hits_soft_17", h17),
        ("players_at_table", players),
    ):
        if value is not None:
            setattr(rules, field, value)
    return RuleSet.model_validate(rules.model_dump())


# Shared options
P_PRESET = typer.Option("ambassador", "--preset", "-p", help="Named rule set.")
P_CONFIG = typer.Option(None, "--config", help="JSON file with a custom RuleSet.")
P_DECKS = typer.Option(None, "--decks", help="Override deck count.")
P_PEN = typer.Option(None, "--pen", help="Override penetration, in decks dealt.")
P_MIN = typer.Option(None, "--table-min", help="Override table minimum.")
P_MAX = typer.Option(None, "--table-max", help="Override table maximum.")
P_H17 = typer.Option(None, "--h17/--s17", help="Dealer hits or stands on soft 17.")
P_PLAYERS = typer.Option(None, "--players", help="Players at the table, including you.")
P_JSON = typer.Option(False, "--json", help="Emit machine-readable JSON.")


def _money(x: float, cur: str) -> str:
    return f"{cur} {x:,.0f}"


def _dump(obj) -> str:
    def default(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, RuleSet):
            return o.model_dump(mode="json")
        if isinstance(o, set):
            return sorted(o)
        if isinstance(o, float) and not math.isfinite(o):
            return None
        return str(o)

    return jsonlib.dumps(obj, indent=2, default=default)


@app.command()
def presets(json: bool = P_JSON) -> None:
    """List the built-in rule sets."""
    if json:
        typer.echo(_dump([
            {"key": key, "rules": r, "base_edge": base_edge(r),
             "breakeven_tc": breakeven_tc(r)}
            for key, r in PRESETS.items()
        ]))
        return
    t = Table(title="Presets")
    for c in ("key", "game", "decks", "pen", "edge", "table"):
        t.add_column(c)
    for key, r in PRESETS.items():
        t.add_row(
            key,
            r.name,
            str(r.decks),
            f"{r.penetration_fraction:.0%}",
            f"{base_edge(r) * 100:+.2f}%",
            f"{r.currency} {r.table_min:,.0f}-{r.table_max:,.0f}",
        )
    console.print(t)


@app.command()
def rules(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    json: bool = P_JSON,
) -> None:
    """Show a rule set and where its house edge comes from."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    parts = edge_components(r)
    lo, hi = base_edge_range(r)
    if json:
        typer.echo(_dump({
            "rules": r,
            "base_edge": base_edge(r),
            "base_edge_low": lo,
            "base_edge_high": hi,
            "breakeven_tc": breakeven_tc(r),
            "components": [
                {"name": n, "delta": e.value, "low": e.low, "high": e.high,
                 "source": e.source}
                for n, e in parts
            ],
        }))
        return

    console.print(f"\n[bold]{r.name}[/bold]")
    t = Table(show_header=True)
    t.add_column("component")
    t.add_column("edge", justify="right")
    t.add_column("range", justify="right")
    for name, e in parts:
        t.add_row(name, f"{e.value * 100:+.3f}%",
                  f"{e.low * 100:+.3f}% .. {e.high * 100:+.3f}%")
    t.add_row("[bold]off the top[/bold]", f"[bold]{base_edge(r) * 100:+.3f}%[/bold]",
              f"[bold]{lo * 100:+.3f}% .. {hi * 100:+.3f}%[/bold]")
    console.print(t)
    console.print(
        f"Break-even true count: [bold]{breakeven_tc(r):+.2f}[/bold]  "
        f"(you have an advantage above this)"
    )
    console.print(
        f"Penetration: {r.penetration_decks_dealt:g} of {r.decks} decks "
        f"({r.penetration_fraction:.0%})   Table: "
        f"{r.currency} {r.table_min:,.0f}-{r.table_max:,.0f} "
        f"({r.max_table_spread:.0f}x)\n"
    )


@app.command()
def freq(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    system: str = typer.Option("hi-lo", "--system", help="Counting system."),
    regen: bool = typer.Option(False, "--regen", help="Force re-simulation."),
    shoes: int = typer.Option(40_000, "--shoes", help="Shoes to simulate."),
    half_deck: bool = typer.Option(
        False, "--half-deck", help="Model estimating decks remaining to the nearest half."
    ),
    json: bool = P_JSON,
) -> None:
    """Simulate the true-count distribution for this penetration."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    sys_ = SYSTEMS.get(system)
    if sys_ is None:
        raise typer.BadParameter(f"unknown system; try: {', '.join(SYSTEMS)}")
    d = load_or_simulate(r, system=sys_, regenerate=regen, n_shoes=shoes,
                         estimate_to_half_deck=half_deck)
    if json:
        typer.echo(_dump(d.to_dict()))
        return
    t = Table(title=f"True-count distribution ({d.system}, {r.decks}D, "
                    f"{r.penetration_decks_dealt:g} decks dealt, "
                    f"{d.rounds_per_shoe:.0f} rounds/shoe)")
    t.add_column("TC")
    t.add_column("P", justify="right")
    t.add_column("cumulative >=", justify="right")
    t.add_column("edge", justify="right")
    for tc in d.counts():
        if d.p(tc) < 5e-4:
            continue
        e = ev_at_tc(tc, r)
        t.add_row(f"{tc:+d}", f"{d.p(tc):.4f}", f"{d.prob_at_or_above(tc):.4f}",
                  f"[{'green' if e > 0 else 'red'}]{e * 100:+.2f}%[/]")
    console.print(t)
    console.print(f"Simulated {d.n_rounds_simulated:,} rounds.\n")


@app.command()
def ramp(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    bankroll: float = typer.Option(..., "--bankroll", "-b"),
    kelly: float = typer.Option(0.40, "--kelly", help="Fraction of full Kelly."),
    max_spread: float | None = typer.Option(
        None, "--max-spread", help="Cover limit on your top bet, as a multiple of the minimum."
    ),
    wong: int | None = typer.Option(
        None, "--wong-out-below", help="Sit out rounds below this true count."
    ),
    json: bool = P_JSON,
) -> None:
    """Build a Kelly bet ramp for a known bankroll."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    d = load_or_simulate(r)
    ramp_ = kelly_ramp(r, d, bankroll=bankroll, kelly_fraction=kelly,
                       max_spread=max_spread, wong_out_below=wong)
    rep = evaluate(r, d, ramp_, bankroll=bankroll)
    if json:
        typer.echo(_dump({
            "rules": r, "bankroll": bankroll, "kelly_fraction": kelly,
            "bets": ramp_.bets, "sat_out": ramp_.sat_out, "spread": ramp_.spread,
            "report": rep.to_dict(),
        }))
        return

    t = Table(title=f"Bet ramp -- {r.currency} {bankroll:,.0f} bankroll at "
                    f"{kelly:g} Kelly")
    for c, j in (("TC", "left"), ("P", "right"), ("edge", "right"),
                 ("bet", "right"), ("share of EV", "right")):
        t.add_column(c, justify=j)
    total_ev = sum(d.p(tc) * ramp_.bet(tc) * ev_at_tc(tc, r) for tc in d.counts())
    for tc in d.counts():
        if d.p(tc) < 5e-4:
            continue
        e = ev_at_tc(tc, r)
        bet = ramp_.bet(tc)
        contrib = d.p(tc) * bet * e
        t.add_row(
            f"{tc:+d}", f"{d.p(tc):.3f}", f"{e * 100:+.2f}%",
            "[dim]sit out[/dim]" if bet == 0 else _money(bet, r.currency),
            "" if total_ev == 0 or bet == 0 else f"{contrib / total_ev:+.0%}",
        )
    console.print(t)
    _print_report(rep, r, ramp_.spread)


def _print_report(rep, r: RuleSet, spread: float) -> None:
    console.print(f"Realised spread     [bold]{spread:.1f}x[/bold]")
    console.print(f"Rounds played       {rep.fraction_of_rounds_played:.0%} of those dealt")
    colour = "green" if rep.win_rate_per_hour > 0 else "red"
    console.print(
        f"Win rate            [{colour}]{_money(rep.win_rate_per_hour, r.currency)}"
        f"/hour[/{colour}]  (+/- {_money(rep.sd_per_hour, r.currency)} SD)"
    )
    if math.isfinite(rep.n0_hours):
        console.print(
            f"N0                  {rep.n0_hours:,.0f} hours until expected win "
            f"= 1 SD"
        )
    if rep.risk_of_ruin is not None:
        console.print(f"Risk of ruin        {rep.risk_of_ruin:.1%}")
    console.print(
        f"After {rep.hours_planned:g}h         "
        f"{_money(rep.expected_profit, r.currency)} expected, "
        f"{rep.prob_of_profit:.0%} chance of being ahead"
    )
    for w in rep.warnings:
        console.print(f"\n[yellow]! {w}[/yellow]")
    console.print()


@app.command()
def risk(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    bankroll: float = typer.Option(..., "--bankroll", "-b"),
    kelly: float = typer.Option(0.40, "--kelly"),
    hours: float = typer.Option(100.0, "--hours"),
    rounds_per_hour: int = typer.Option(70, "--rounds-per-hour"),
    max_spread: float | None = typer.Option(None, "--max-spread"),
    wong: int | None = typer.Option(None, "--wong-out-below"),
    json: bool = P_JSON,
) -> None:
    """Full risk report for a bankroll and ramp."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    d = load_or_simulate(r)
    ramp_ = kelly_ramp(r, d, bankroll=bankroll, kelly_fraction=kelly,
                       max_spread=max_spread, wong_out_below=wong)
    rep = evaluate(r, d, ramp_, bankroll=bankroll, hours_planned=hours,
                   rounds_per_hour=rounds_per_hour)
    if json:
        typer.echo(_dump({"rules": r, "report": rep.to_dict(),
                          "bets": ramp_.bets, "spread": ramp_.spread}))
        return
    console.print(f"\n[bold]{r.name}[/bold]  --  {r.currency} {bankroll:,.0f} at "
                  f"{kelly:g} Kelly\n")
    _print_report(rep, r, ramp_.spread)
    console.print(
        f"[dim]Proportional betting at {kelly:g} Kelly implies a long-run ruin "
        f"probability of {ror_for_kelly(kelly):.1%} regardless of bankroll size; "
        f"the figure above is for this ramp held fixed.[/dim]\n"
    )


@app.command()
def bankroll(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    target_ror: float = typer.Option(0.05, "--target-ror"),
    spread: float = typer.Option(12, "--spread", help="Bet spread you intend to use."),
    unit: float | None = typer.Option(None, "--unit", help="Bottom bet. Defaults to the table minimum."),
    wong: int | None = typer.Option(None, "--wong-out-below"),
    json: bool = P_JSON,
) -> None:
    """How much bankroll a given spread needs. The non-circular solve."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    d = load_or_simulate(r)
    u = unit if unit is not None else r.table_min
    ramp_ = spread_ramp(r, d, max_spread=spread, unit=u, wong_out_below=wong)
    rep = evaluate(r, d, ramp_)
    need = bankroll_for_ror(target_ror, rep.win_rate_per_round, rep.variance_per_round)
    kelly_eq = kelly_for_ror(target_ror)
    if json:
        typer.echo(_dump({
            "rules": r, "spread": spread, "unit": u, "target_ror": target_ror,
            "required_bankroll": need if math.isfinite(need) else None,
            "equivalent_kelly_fraction": kelly_eq,
            "bets": ramp_.bets, "report": rep.to_dict(),
        }))
        return
    console.print(f"\n[bold]{r.name}[/bold]")
    console.print(f"Spreading {u:,.0f}-{u * spread:,.0f} {r.currency} ({spread:g}x)\n")
    if math.isfinite(need):
        console.print(f"Bankroll for {target_ror:.0%} risk of ruin: "
                      f"[bold]{_money(need, r.currency)}[/bold]")
    else:
        console.print("[red]No bankroll makes this viable -- the ramp is EV-negative.[/red]")
    console.print(f"Win rate: {_money(rep.win_rate_per_hour, r.currency)}/hour")
    if math.isfinite(rep.n0_hours):
        console.print(f"N0: {rep.n0_hours:,.0f} hours")
    console.print(
        f"\n[dim]Equivalently: proportional betting at {kelly_eq:.2f} Kelly gives "
        f"{target_ror:.0%} ruin at any bankroll size.[/dim]"
    )
    for w in ramp_.warnings + rep.warnings:
        console.print(f"[yellow]! {w}[/yellow]")
    console.print()


@app.command()
def viability(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    bankroll: float | None = typer.Option(None, "--bankroll", "-b"),
    target_ror: float = typer.Option(0.05, "--target-ror"),
    unit: float | None = typer.Option(None, "--unit"),
    wong: int | None = typer.Option(None, "--wong-out-below"),
    json: bool = P_JSON,
) -> None:
    """Should you play this game at all? Start here."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    rep = assess(r, bankroll=bankroll, target_ror=target_ror, unit=unit,
                 wong_out_below=wong)
    if json:
        typer.echo(_dump(rep))
        return

    console.print(f"\n[bold]{r.name}[/bold]")
    console.print(
        f"Off the top: [bold]{rep.base_edge * 100:+.2f}%[/bold] "
        f"({rep.base_edge_range[0] * 100:+.2f}% .. {rep.base_edge_range[1] * 100:+.2f}%)"
        f"   Break-even TC: [bold]{rep.breakeven_tc:+.2f}[/bold]"
        f"   You hold an advantage on {rep.prob_advantage:.0%} of rounds\n"
    )

    t = Table(title=f"Spread options (unit {r.currency} "
                    f"{(unit or r.table_min):,.0f}, {target_ror:.0%} risk of ruin)")
    for c in ("spread", "top bet", "bankroll needed", "win/hour", "N0 hours", ""):
        t.add_column(c, justify="right" if c != "" else "left")
    for o in rep.options:
        # Check EV before affordability: an EV-negative option needs an infinite
        # bankroll, and reporting that as merely "unaffordable" hides the reason.
        if o.win_rate_per_hour <= 0:
            flag, style = "EV-negative", "red"
        elif not o.fits_table:
            flag, style = "over table max", "red"
        elif not o.affordable:
            flag, style = "unaffordable", "red"
        else:
            flag, style = "ok", "green"
        t.add_row(
            f"{o.max_spread:g}x", _money(o.top_bet, r.currency),
            _money(o.required_bankroll, r.currency) if math.isfinite(o.required_bankroll) else "-",
            _money(o.win_rate_per_hour, r.currency),
            f"{o.n0_hours:,.0f}" if math.isfinite(o.n0_hours) else "-",
            f"[{style}]{flag}[/{style}]",
        )
    console.print(t)

    style = "green" if rep.verdict.startswith("VIABLE") else "red"
    console.print(f"\n[bold {style}]{rep.verdict}[/bold {style}]")
    for n in rep.notes:
        console.print(f"[yellow]! {n}[/yellow]")
    console.print()


@app.command("pen-sweep")
def pen_sweep(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, table_min: float | None = P_MIN,
    table_max: float | None = P_MAX, h17: bool | None = P_H17,
    players: int | None = P_PLAYERS,
    spread: float = typer.Option(12, "--spread"),
    target_ror: float = typer.Option(0.05, "--target-ror"),
    unit: float | None = typer.Option(None, "--unit"),
    wong: int | None = typer.Option(None, "--wong-out-below"),
    json: bool = P_JSON,
) -> None:
    """How much the dealer's cut card is worth to you."""
    r = _load_rules(preset, config, decks, None, table_min, table_max, h17, players)
    rows = penetration_sweep(r, max_spread=spread, target_ror=target_ror, unit=unit,
                             wong_out_below=wong)
    if json:
        typer.echo(_dump(rows))
        return
    t = Table(title=f"Penetration sweep -- {r.decks} decks, {spread:g}x spread")
    for c in ("decks dealt", "% of shoe", "rounds/shoe", "P(TC>=2)", "P(TC>=4)",
              "win/hour", "N0 hours", "bankroll needed"):
        t.add_column(c, justify="right")
    for row in rows:
        t.add_row(
            f"{row['penetration_decks']:g}", f"{row['penetration_pct']:.0%}",
            f"{row['rounds_per_shoe']:.0f}", f"{row['prob_tc_ge_2']:.3f}",
            f"{row['prob_tc_ge_4']:.3f}",
            _money(row["win_rate_per_hour"], r.currency),
            f"{row['n0_hours']:,.0f}" if math.isfinite(row["n0_hours"]) else "-",
            _money(row["required_bankroll"], r.currency)
            if math.isfinite(row["required_bankroll"]) else "-",
        )
    console.print(t)
    console.print()


def _sim_ramp(r, d, bankroll, spread, kelly, unit, wong):
    """Pick the ramp the simulator should play: fixed-spread by default, Kelly
    only if the caller asked for it explicitly."""
    if kelly is not None:
        return kelly_ramp(r, d, bankroll=bankroll, kelly_fraction=kelly,
                          wong_out_below=wong), f"{kelly:g} Kelly"
    return (
        spread_ramp(r, d, max_spread=spread, unit=unit or r.table_min,
                    wong_out_below=wong),
        f"fixed {spread:g}x spread",
    )


@app.command()
def sim(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    bankroll: float = typer.Option(..., "--bankroll", "-b"),
    spread: float = typer.Option(8, "--spread", help="Fixed spread to play."),
    kelly: float | None = typer.Option(
        None, "--kelly", help="Play a Kelly ramp instead of a fixed spread."
    ),
    unit: float | None = typer.Option(None, "--unit"),
    wong: int | None = typer.Option(None, "--wong-out-below"),
    paths: int = typer.Option(10_000, "--paths", help="Bankrolls to simulate."),
    hands: int = typer.Option(100_000, "--hands", help="Rounds per path."),
    ruin_at: float = typer.Option(
        0.0, "--ruin-at",
        help="Bankroll level counted as ruin. 0 matches the analytic barrier; "
             "pass the table minimum for the practical answer.",
    ),
    outcome_model: str = typer.Option(
        "discrete", "--outcome-model", help="'discrete' (lumpy) or 'normal'."
    ),
    resize: bool = typer.Option(
        False, "--resize", help="Resize bets to the current bankroll each round."
    ),
    seed: int = typer.Option(1234, "--seed"),
    json: bool = P_JSON,
) -> None:
    """Monte Carlo the bankroll, and check the analytic risk of ruin against it."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    d = load_or_simulate(r)
    ramp_, label = _sim_ramp(r, d, bankroll, spread, kelly, unit, wong)
    res = simulate(r, d, ramp_, bankroll=bankroll, n_paths=paths, n_hands=hands,
                   ruin_at=ruin_at, outcome_model=outcome_model, resize=resize,
                   seed=seed)
    if json:
        typer.echo(_dump(res.to_dict()))
        return

    console.print(f"\n[bold]{r.name}[/bold]")
    console.print(
        f"{paths:,} bankrolls of {_money(bankroll, r.currency)}, "
        f"{hands:,} rounds each, {label}, "
        f"{'resized each round' if resize else 'ramp fixed'}\n"
    )
    t = Table(title="Risk of ruin")
    t.add_column("source")
    t.add_column("value", justify="right")
    t.add_row("analytic (closed form, infinite horizon)", f"{res.analytic_ror:.2%}")
    t.add_row(f"simulated over {hands:,} rounds", f"{res.empirical_ror:.2%}")
    t.add_row("difference", f"{res.ror_gap_points:+.2f} points")
    console.print(t)

    t2 = Table(title=f"Final bankroll after {hands:,} rounds")
    t2.add_column("percentile")
    t2.add_column("bankroll", justify="right")
    for k, v in res.final_percentiles.items():
        t2.add_row(k.upper(), _money(v, r.currency))
    console.print(t2)
    console.print(
        f"Ended profitable    {res.fraction_profitable:.1%} of paths\n"
        f"Mean profit         {_money(res.empirical_mean_profit, r.currency)} "
        f"(analytic {_money(res.analytic_expected_profit, r.currency)})"
    )
    for w in res.warnings:
        console.print(f"[yellow]! {w}[/yellow]")
    console.print()


@app.command()
def validate(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    bankroll: float = typer.Option(..., "--bankroll", "-b"),
    spread: float = typer.Option(8, "--spread"),
    unit: float | None = typer.Option(None, "--unit"),
    wong: int | None = typer.Option(None, "--wong-out-below"),
    paths: int = typer.Option(5_000, "--paths"),
    seed: int = typer.Option(1234, "--seed"),
    json: bool = P_JSON,
) -> None:
    """Show how simulated ruin converges toward the analytic figure."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    d = load_or_simulate(r)
    ramp_ = spread_ramp(r, d, max_spread=spread, unit=unit or r.table_min,
                        wong_out_below=wong)
    rows = ruin_convergence(r, d, ramp_, bankroll=bankroll, n_paths=paths, seed=seed)
    if json:
        typer.echo(_dump(rows))
        return
    t = Table(title=f"Ruin convergence -- {_money(bankroll, r.currency)}, "
                    f"{spread:g}x spread, {paths:,} paths")
    for c in ("rounds", "simulated RoR", "analytic RoR", "gap", "% profitable"):
        t.add_column(c, justify="right")
    for row in rows:
        t.add_row(f"{row['n_hands']:,}", f"{row['empirical_ror']:.2%}",
                  f"{row['analytic_ror']:.2%}", f"{row['gap_points']:+.2f} pts",
                  f"{row['fraction_profitable']:.1%}")
    console.print(t)
    console.print(
        "\n[dim]The closed form is an infinite-horizon probability. A finite "
        "playing career carries less ruin risk than it quotes; the two converge "
        "only once the horizon is long compared with the time the edge needs to "
        "carry the bankroll clear.[/dim]\n"
    )


_SYMBOL = {
    Action.HIT: "H", Action.STAND: "S", Action.DOUBLE: "D",
    Action.SPLIT: "P", Action.SURRENDER: "R",
}
_COLOUR = {
    Action.HIT: "white", Action.STAND: "yellow", Action.DOUBLE: "green",
    Action.SPLIT: "cyan", Action.SURRENDER: "magenta",
}


@app.command()
def chart(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    tc: float = typer.Option(0.0, "--tc", help="True count to compute the chart at."),
    mark_close: bool = typer.Option(
        True, "--mark-close/--no-mark-close",
        help="Flag cells decided by less than 0.01 in EV.",
    ),
    json: bool = P_JSON,
) -> None:
    """Compute basic strategy for these exact rules, cell by cell."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    cells = basic_strategy(r, tc)
    if json:
        typer.echo(_dump([
            {"category": c.category, "label": c.label,
             "upcard": RANK_NAMES[c.upcard], "action": c.action.value,
             "ev": c.ev, "margin": c.margin, "close": c.close}
            for c in cells
        ]))
        return

    by: dict[tuple[str, str], dict[int, object]] = {}
    for c in cells:
        by.setdefault((c.category, c.label), {})[c.upcard] = c

    console.print(f"\n[bold]{r.name}[/bold]  (true count {tc:+g})")
    for category, title in (("hard", "Hard totals"), ("soft", "Soft totals"),
                            ("pair", "Pairs")):
        t = Table(title=title)
        t.add_column("")
        for u in UPCARDS:
            t.add_column(RANK_NAMES[u], justify="center")
        for (cat, label), row in by.items():
            if cat != category:
                continue
            cellz = []
            for u in UPCARDS:
                c = row[u]
                sym = _SYMBOL[c.action]
                if mark_close and c.close:
                    sym += "*"
                cellz.append(f"[{_COLOUR[c.action]}]{sym}[/]")
            t.add_row(label, *cellz)
        console.print(t)
    console.print(
        "H hit  S stand  D double  P split  R surrender"
        + ("   * decided by less than 0.01 in EV" if mark_close else "")
    )
    console.print(
        f"Insurance becomes profitable at true count "
        f"[bold]{insurance_index(r):+.2f}[/bold]\n"
    )


@app.command()
def deviations(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    top: int = typer.Option(18, "--top", help="How many to show. 0 for all."),
    lo: int = typer.Option(-6, "--min-tc"),
    hi: int = typer.Option(8, "--max-tc"),
    json: bool = P_JSON,
) -> None:
    """Deviation indices for these rules, ranked by what each is actually worth."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    dist = load_or_simulate(r)
    devs = all_deviations(r, tc_range=(lo, hi))
    ranked = rank_deviations(
        r, {t: dist.p(t) for t in dist.counts()}, deviations=devs
    )
    shown = ranked if top <= 0 else ranked[:top]
    if json:
        typer.echo(_dump([
            {"category": x.deviation.category, "label": x.deviation.label,
             "upcard": RANK_NAMES[x.deviation.upcard],
             "basic": x.deviation.basic.value,
             "switch_to": x.deviation.switch_to.value,
             "index": x.deviation.index, "direction": x.deviation.direction,
             "value_bp_per_round": x.value_per_hand * 10000,
             "frequency": x.frequency}
            for x in shown
        ]))
        return

    console.print(f"\n[bold]{r.name}[/bold]")
    console.print(
        f"Insurance at true count [bold]{insurance_index(r):+.2f}[/bold] "
        f"-- worth more than every play deviation below combined.\n"
    )
    t = Table(title=f"Top {len(shown)} of {len(ranked)} deviations, by value at "
                    f"{r.penetration_fraction:.0%} penetration")
    for c in ("#", "hand", "vs", "basic", "becomes", "index", "gain"):
        t.add_column(c, justify="right" if c in ("#", "index", "gain") else "left")
    for i, x in enumerate(shown, 1):
        d = x.deviation
        t.add_row(str(i), d.label, RANK_NAMES[d.upcard], d.basic.value,
                  d.switch_to.value, f"{d.index:+d}{d.direction}",
                  f"{x.value_per_hand * 10000:.2f} bp")
    console.print(t)
    console.print(
        "\n[dim]Gain is basis points of a bet per round played, at your "
        "penetration. Learn them in this order; the tail is worth nothing.[/dim]\n"
    )


@app.command()
def play(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    hand: str = typer.Argument(..., help="Your cards, e.g. 'A,7' or 'T,6' or '5,6'."),
    upcard: str = typer.Argument(..., help="Dealer upcard, e.g. 'T' or '9'."),
    tc: float = typer.Option(0.0, "--tc", help="Current true count."),
    json: bool = P_JSON,
) -> None:
    """What is the correct play for one hand, right now?"""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)

    def parse(token: str) -> int:
        token = token.strip().upper()
        if token in ("10", "J", "Q", "K"):
            token = "T"
        if token not in RANK_NAMES:
            raise typer.BadParameter(f"unknown card {token!r}")
        return RANK_NAMES.index(token)

    cards = tuple(parse(c) for c in hand.split(","))
    up = parse(upcard)
    if len(cards) < 2:
        raise typer.BadParameter("give at least two cards, e.g. 'T,6'")

    from .analyzer import action_evs
    from .cards import deck_for_true_count, remove_many
    deck = remove_many(deck_for_true_count(tc, r.decks), *cards, up)
    evs = action_evs(cards, up, deck, r,
                     allow_split=(len(cards) == 2 and cards[0] == cards[1]))
    action = decide(cards, up, tc, r)
    if json:
        typer.echo(_dump({"action": action.value,
                          "evs": {a.value: v for a, v in evs.items()}}))
        return
    console.print(f"\n[bold]{hand.upper()} vs {RANK_NAMES[up]}[/bold] at true "
                  f"count {tc:+g}  ->  [bold green]{action.value.upper()}[/bold green]")
    t = Table()
    t.add_column("action")
    t.add_column("EV", justify="right")
    for a, v in sorted(evs.items(), key=lambda kv: -kv[1]):
        t.add_row(a.value, f"{v:+.4f}")
    console.print(t)
    console.print()


@app.command()
def verify(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    lo: int = typer.Option(-3, "--min-tc", help="Low end of the fitted range."),
    hi: int = typer.Option(6, "--max-tc", help="High end of the fitted range."),
    json: bool = P_JSON,
) -> None:
    """Check the model's constants against an exact enumeration of the game."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    measured = exact_edge(r)
    modelled = base_edge(r)
    curve = ev_curve(r, tuple(range(lo, hi + 1)))
    _, slope, worst = fit_linear(curve)

    if json:
        typer.echo(_dump({
            "rules": r,
            "base_edge_model": modelled,
            "base_edge_exact": measured,
            "base_edge_error": measured - modelled,
            "slope_model": C.HILO_SLOPE.value,
            "slope_exact": slope,
            "slope_error": slope - C.HILO_SLOPE.value,
            "worst_linear_residual": worst,
            "curve": {str(k): v for k, v in curve.items()},
        }))
        return

    console.print(f"\n[bold]{r.name}[/bold]\n")
    t = Table(title="Model constants against exact enumeration")
    for c in ("quantity", "model", "exact", "error"):
        t.add_column(c, justify="right" if c != "quantity" else "left")
    t.add_row("off-the-top edge", f"{modelled * 100:+.4f}%",
              f"{measured * 100:+.4f}%", f"{(measured - modelled) * 100:+.4f}%")
    t.add_row(f"slope over TC {lo:+d}..{hi:+d}", f"{C.HILO_SLOPE.value * 100:.4f}%",
              f"{slope * 100:.4f}%", f"{(slope - C.HILO_SLOPE.value) * 100:+.4f}%")
    console.print(t)

    t2 = Table(title="Exact EV by true count")
    for c in ("TC", "exact", "linear model", "error"):
        t2.add_column(c, justify="right")
    for tc, v in curve.items():
        m = ev_at_tc(tc, r)
        t2.add_row(f"{tc:+.0f}", f"{v * 100:+.4f}%", f"{m * 100:+.4f}%",
                   f"{(v - m) * 100:+.4f}%")
    console.print(t2)
    console.print(
        f"\n[dim]Worst departure from a straight line over this range: "
        f"{worst * 100:.4f}%. The curve is convex, so a linear model understates "
        f"the edge at high counts -- the conservative direction, since that is "
        f"where the bets are big.\n"
        f"The TC-0 point is not the off-the-top edge: this curve is evaluated "
        f"against a half-dealt shoe, which plays slightly better for the "
        f"player.[/dim]\n"
    )


@app.command()
def sensitivity(
    preset: str = P_PRESET, config: Path | None = P_CONFIG,
    decks: int | None = P_DECKS, pen: float | None = P_PEN,
    table_min: float | None = P_MIN, table_max: float | None = P_MAX,
    h17: bool | None = P_H17, players: int | None = P_PLAYERS,
    tc: float = typer.Option(3.0, "--tc", help="True count to evaluate at."),
    json: bool = P_JSON,
) -> None:
    """Which uncertain constants actually move your conclusions."""
    r = _load_rules(preset, config, decks, pen, table_min, table_max, h17, players)
    rows = ev_sensitivity(tc, r)
    if json:
        typer.echo(_dump([dataclasses.asdict(s) for s in rows]))
        return
    t = Table(title=f"Edge at TC {tc:+g}, under input uncertainty")
    for c in ("source of uncertainty", "pessimistic", "point", "optimistic", "swing"):
        t.add_column(c, justify="right")
    for s in rows:
        t.add_row(s.label, f"{s.low * 100:+.3f}%", f"{s.point * 100:+.3f}%",
                  f"{s.high * 100:+.3f}%", f"{s.swing * 100:.3f}%")
    console.print(t)
    console.print(
        "\n[dim]If the swing is comparable to your edge, the model is not precise "
        "enough to justify the decision you are about to make with it.[/dim]\n"
    )


if __name__ == "__main__":
    app()
