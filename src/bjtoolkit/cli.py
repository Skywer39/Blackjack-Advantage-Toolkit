"""Command line interface.

Every command takes --json, which emits the same data as machine-readable
output. That is the contract a web UI would consume later.
"""

from __future__ import annotations

import dataclasses
import json as jsonlib
import math
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import constants as C
from .counting import SYSTEMS
from .ev_model import breakeven_tc, ev_at_tc, ev_sensitivity
from .frequency import load_or_simulate
from .ramp import kelly_ramp, spread_ramp
from .risk import (
    bankroll_for_ror,
    evaluate,
    kelly_for_ror,
    risk_of_ruin,
    ror_for_kelly,
)
from .rules import PRESETS, RuleSet, base_edge, base_edge_range, edge_components, get_preset
from .viability import assess, penetration_sweep

app = typer.Typer(
    add_completion=False,
    help="Blackjack advantage toolkit: rules in, bankroll and bet ramp out.",
)
console = Console()


def _load_rules(
    preset: str,
    config: Optional[Path],
    decks: Optional[int],
    pen: Optional[float],
    table_min: Optional[float],
    table_max: Optional[float],
    h17: Optional[bool],
    players: Optional[int],
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
def presets() -> None:
    """List the built-in rule sets."""
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
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
    t.add_column("TC"); t.add_column("P", justify="right")
    t.add_column("cumulative >=", justify="right"); t.add_column("edge", justify="right")
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
    bankroll: float = typer.Option(..., "--bankroll", "-b"),
    kelly: float = typer.Option(0.40, "--kelly", help="Fraction of full Kelly."),
    max_spread: Optional[float] = typer.Option(
        None, "--max-spread", help="Cover limit on your top bet, as a multiple of the minimum."
    ),
    wong: Optional[int] = typer.Option(
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
    bankroll: float = typer.Option(..., "--bankroll", "-b"),
    kelly: float = typer.Option(0.40, "--kelly"),
    hours: float = typer.Option(100.0, "--hours"),
    rounds_per_hour: int = typer.Option(70, "--rounds-per-hour"),
    max_spread: Optional[float] = typer.Option(None, "--max-spread"),
    wong: Optional[int] = typer.Option(None, "--wong-out-below"),
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
    target_ror: float = typer.Option(0.05, "--target-ror"),
    spread: float = typer.Option(12, "--spread", help="Bet spread you intend to use."),
    unit: Optional[float] = typer.Option(None, "--unit", help="Bottom bet. Defaults to the table minimum."),
    wong: Optional[int] = typer.Option(None, "--wong-out-below"),
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
    bankroll: Optional[float] = typer.Option(None, "--bankroll", "-b"),
    target_ror: float = typer.Option(0.05, "--target-ror"),
    unit: Optional[float] = typer.Option(None, "--unit"),
    wong: Optional[int] = typer.Option(None, "--wong-out-below"),
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
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, table_min: Optional[float] = P_MIN,
    table_max: Optional[float] = P_MAX, h17: Optional[bool] = P_H17,
    players: Optional[int] = P_PLAYERS,
    spread: float = typer.Option(12, "--spread"),
    target_ror: float = typer.Option(0.05, "--target-ror"),
    unit: Optional[float] = typer.Option(None, "--unit"),
    wong: Optional[int] = typer.Option(None, "--wong-out-below"),
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


@app.command()
def sensitivity(
    preset: str = P_PRESET, config: Optional[Path] = P_CONFIG,
    decks: Optional[int] = P_DECKS, pen: Optional[float] = P_PEN,
    table_min: Optional[float] = P_MIN, table_max: Optional[float] = P_MAX,
    h17: Optional[bool] = P_H17, players: Optional[int] = P_PLAYERS,
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
