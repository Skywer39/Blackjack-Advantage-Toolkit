# Open questions and disputed numbers

Things this toolkit is not sure about, so they are not silently buried in the
code. Roughly in order of how much money they are worth.

## 1. Is the Ambassador game really S17?

The preset assumes the dealer stands on soft 17. If the dealer hits, the game is
0.22% worse and the accompanying strategy chart is wrong in several cells.

Check with `--h17` to see the cost. This is a one-minute question at the table
and it is worth more than any modelling improvement in this repo.

## 2. How does surrender settle in a no-hole-card game?

This is the biggest unresolved item and the toolkit currently guesses.

With no hole card there is nothing to peek at, so "late" surrender is not
really late. Three possibilities, worth very different amounts:

| Settlement | Effect | Modelled as |
|---|---|---|
| Surrender resolves immediately; you keep half even when the dealer later draws a blackjack | **+0.24%** | `Surrender.EARLY_VS_10` |
| Surrender resolves after the dealer's draw; a dealer blackjack takes the whole bet | +0.07% | `Surrender.LATE_VS_9_10` (current default) |
| Surrender not honoured against a ten at all | 0.00% | `Surrender.NONE` |

The spread between the top and bottom row is larger than the entire ENHC
penalty. Ask the pit how a surrender against a ten is settled when the dealer
draws a blackjack.

## 3. RESOLVED: the vs-Ace doubling indices were wrong

Settled by the Phase 2 analyzer. Doubling 11 or 10 into an ace is never correct
in a full-ENHC game at any true count, so the chart's `+1` and `+4` indices
should not be used. The engine also found a fifth basic-strategy correction the
chart is missing -- `11 vs 10 -> hit` -- and confirmed the four it does list.

Full working in `docs/chart-review.md`.

## 4. RESOLVED: the EV model has been checked against exact enumeration

Both halves of the model are now verified by `bj verify`, which enumerates every
initial deal rather than sampling. Full working in `docs/validation.md`.

* The rule-effect constants hold to well under a basis point for most games;
  H17 and 6:5 are the loosest at about two and four basis points.
* The Hi-Lo slope was too low. The usual 0.5%-per-true-count rule of thumb
  measures **0.535%** over the counts you actually bet in, stable across shoe
  depths, and the constant now carries that. The tool had been understating its
  own edge by roughly 20%.
* The real curve is **convex**: above +6 the local slope climbs toward 0.71%, so
  a straight line increasingly understates the edge where the bets are biggest.
  That is the conservative direction, and it remains an approximation.

What is still unverified is the analyzer's own approximations -- dealer
probabilities are not recomputed as the player draws (measured at +0.0003 units,
so negligible), and split hands are treated as drawing independently from the
same shoe. Both are documented at their call sites.

## 5. Nothing here models heat

The optimizer will happily recommend a 20x spread. No real casino will let you
keep one. Backoffs, shuffle-ups and barring are not in the model at all, so
every win-rate figure is an upper bound on what you would actually earn.

Use `--max-spread` to constrain the ramp to something you could plausibly get
away with, and read the difference as the cost of cover.

## 6. RESOLVED: the rule-effect constants are no longer just reconstructed

`constants.py` still cites published rule-variation tables as its source, but
every value is now checked against this project's own exact enumeration
(`bj verify`), and `HILO_SLOPE` is derived from it outright. Agreement is well
under a basis point for most games.

`bj sensitivity` still shows which conclusions actually depend on which
constants; for most bankroll questions the answer remains "none of them, the
penetration matters more."
