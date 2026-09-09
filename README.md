# Blackjack Advantage Toolkit

Bankroll sizing, bet ramps and risk analysis for card counting — for **any** set
of table rules, not one casino. Give it a game and a bankroll; it tells you
whether the game is beatable, what spread it needs, and what that spread costs.

The engine is pure functions over typed config, so the CLI and any future web UI
read the same numbers. Every command takes `--json`.

## Install

```bash
pip install -e .
```

## Start here

The first question is not "what should I bet" but "is this worth playing":

```bash
bj viability --preset ambassador --bankroll 100000
```

```
Off the top: -0.45% (-0.52% .. -0.39%)   Break-even TC: +0.90
You hold an advantage on 27% of rounds

 spread   top bet  bankroll needed  win/hour  N0 hours
     8x  CZK 1,600            -      CZK -11         -   EV-negative
    12x  CZK 2,400  CZK 1,067,398     CZK 15    47,920   unaffordable
    20x  CZK 4,000    CZK 428,386     CZK 86     3,342   unaffordable

NOT VIABLE at CZK 100,000. The smallest spread that beats this game
needs about CZK 428,386 for 5% risk of ruin.
```

That is a real answer, not a failure. A CZK 200 table minimum is a high floor:
you pay the house edge on every low count, and 64% of rounds are low counts.

Now sit out the bad ones:

```bash
bj viability --preset ambassador --bankroll 100000 --wong-out-below 1
```

```
     8x  CZK 1,600     CZK 94,158     CZK 77       821   ok

VIABLE at up to 8x spread: about CZK 77/hour, needing CZK 94,158
bankroll for 5% risk of ruin.
```

Same game, same bankroll, opposite verdict. Back-counting and only playing
positive counts is what makes a high minimum survivable.

## Commands

| Command | Question it answers |
|---|---|
| `bj viability` | Should I play this game at all, and at what spread? |
| `bj sim` | Monte Carlo the bankroll; check the analytic ruin figure against it |
| `bj validate` | How does simulated ruin converge on the analytic figure? |
| `bj bankroll` | How much bankroll does a 1-12 spread need here? |
| `bj ramp` | I have this bankroll — what do I bet at each count? |
| `bj risk` | Win rate, SD, N0, risk of ruin, probability of profit |
| `bj freq` | What does the true-count distribution look like at this penetration? |
| `bj pen-sweep` | What is the dealer's cut card worth to me? |
| `bj rules` | Where does this game's house edge come from? |
| `bj sensitivity` | Which uncertain inputs actually move my conclusions? |
| `bj presets` | What games are built in? |

Any preset can be overridden inline, so you do not need a config file to price a
game you just walked up to:

```bash
bj viability -p vegas-strip -b 20000 --decks 8 --pen 5.5 --h17 --table-min 25
```

For anything more involved, write a `RuleSet` as JSON and pass `--config`.

## Presets

`ambassador` (Czech 6-deck ENHC), `vegas-strip`, `vegas-h17`, `vegas-8d`,
`single-deck`, `double-deck`, `uk-enhc`, `six-five`.

## Penetration is the variable that matters

Penetration is an input everywhere, and the true-count distribution is
**simulated for it** rather than looked up from a fixed table. It is usually
worth more than any rule on the felt:

```bash
bj pen-sweep --preset ambassador --spread 12 --wong-out-below 1
```

| decks dealt | % of shoe | P(TC≥2) | P(TC≥4) | win/hour | bankroll needed |
|---|---|---|---|---|---|
| 3.0 | 50% | 0.084 | 0.011 | CZK 42 | CZK 188,392 |
| 4.0 | 67% | 0.128 | 0.031 | CZK 69 | CZK 122,310 |
| 5.0 | 83% | 0.169 | 0.063 | CZK 154 | CZK 110,981 |

Same rules, same spread, same play. Deep penetration is worth 3.7x the win rate
of shallow, and needs 40% less bankroll to sustain — decided entirely by where
the dealer puts the cut card. Counts of +4 and up, where most of the money is,
occur five times as often.

## The risk numbers are checked, not asserted

`bj validate` plays the recommended configuration out hand by hand and compares
the result with the closed form Phase 1 quotes:

| rounds played | simulated RoR | analytic RoR | gap |
|---|---|---|---|
| 20,000 | 0.13% | 5.00% | −4.87 pts |
| 50,000 | 1.62% | 5.00% | −3.38 pts |
| 100,000 | 3.47% | 5.00% | −1.53 pts |
| 200,000 | 4.63% | 5.00% | −0.37 pts |

The closed form is sound and slightly conservative. It is also an *infinite*
horizon figure — over a first season of a few hundred hours your real risk is a
small fraction of the quoted 5%.

The most useful thing the simulator turned up: **resizing your unit as the
bankroll moves cuts risk of ruin from 4.25% to 0.47%**, at a cost of about 4% of
the median outcome. Full results and caveats in `docs/validation.md`.

## What this gets right that simple tools get wrong

**The bankroll solve is not circular.** If your bets scale with your bankroll,
risk of ruin does not depend on the bankroll at all — win rate grows like `B`,
variance like `B²`, and the ruin exponent is scale-invariant. "What bankroll
gives 5% ruin?" has no answer for Kelly-sized bets. So there are two solvers:
`bankroll_for_ror` for a ramp fixed in currency, and `kelly_for_ror` for
proportional betting (5% ruin ⇒ 0.67 Kelly, at any bankroll).

**Wonging changes the units.** Sitting out is a bet of zero, and everything is
reported per round *observed at the table*, so the win rate reflects the hours
you spend not betting rather than quietly assuming them away.

**Variance rises with the count.** You double and split more at high counts,
which is exactly where your bets are biggest. A constant understates ruin.

**Every constant is sourced and has a range.** `constants.py` holds every
empirical number with a citation and a plausible interval; `bj sensitivity`
re-runs the model at the endpoints so you can see what your conclusions actually
rest on.

## Honest limits

Read `docs/open-questions.md` before betting real money. In short: the EV model
is linear and approximate; the rule-effect constants are reconstructed from
published tables rather than recomputed; **nothing here models heat**, so every
win rate is an upper bound; and the vs-Ace doubling indices on the companion
chart look wrong for a full-ENHC game and are flagged as unresolved.

N0 is the number that deserves the most attention. At most realistic bankrolls
it is several hundred hours — the point at which your expected win merely equals
one standard deviation. Short-term results tell you close to nothing.

## Status

Phase 1 complete: rules engine, true-count simulation, ramps, risk, viability,
CLI, 113 tests.

Not built yet: Monte Carlo validation of the analytic risk of ruin (Phase 1.5),
and the strategy/deviation engine and trainer (Phase 2). Phase 2 should compute
deviation indices for the configured rule set rather than adjusting a published
list — see open question 3.

Card counting is legal. Casinos are private property and may refuse service.
This is an educational modelling tool, not financial advice.
