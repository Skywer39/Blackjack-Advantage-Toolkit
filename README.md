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

## On your phone

There is a web app: **[Ramp & Ruin](web/)** — a single self-contained HTML file
that computes everything in the browser. No server, no account, works offline
once loaded, installs to an iPhone home screen from Safari's Share → Add to Home
Screen.

It is not a precomputed bundle. The engine is ported to JavaScript, so it prices
**any** rule set you type in — change the hole-card rule and the whole chart
recomputes. Two implementations of one model would normally drift; here the
constants are generated from `constants.py` and a conformance suite asserts the
JavaScript reproduces the Python's answers to 1e-9 across 2,127 checks,
including four complete 340-cell charts. `pytest` runs it.

Deploy it free from this repo: enable **Settings → Pages → Source → GitHub
Actions** once, and `.github/workflows/pages.yml` verifies and publishes on every
push to `main`.

## Start here

The first question is not "what should I bet" but "is this worth playing":

```bash
bj viability --preset ambassador --bankroll 100000
```

```
Off the top: -0.45% (-0.52% .. -0.39%)   Break-even TC: +0.84
You hold an advantage on 27% of rounds

 spread   top bet  bankroll needed  win/hour  N0 hours
     6x  CZK 1,200            -      CZK -14         -   EV-negative
    12x  CZK 2,400    CZK 616,509     CZK 28    14,823   unaffordable
    20x  CZK 4,000    CZK 370,061    CZK 101     2,442   unaffordable

NOT VIABLE at CZK 100,000. The smallest spread that beats this game
needs about CZK 370,061 for 5% risk of ruin.
```

That is a real answer, not a failure. A CZK 200 table minimum is a high floor:
you pay the house edge on every low count, and 64% of rounds are low counts.

Now sit out the bad ones:

```bash
bj viability --preset ambassador --bankroll 100000 --wong-out-below 1
```

```
     8x  CZK 1,600     CZK 93,136     CZK 93       672   ok

VIABLE at up to 8x spread: about CZK 93/hour, needing CZK 93,136
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
| `bj chart` | Basic strategy computed for these exact rules |
| `bj deviations` | Index numbers, ranked by what each is actually worth |
| `bj play` | The correct play for one hand at one count |
| `bj drill` | Practise counting, strategy and deviations for your rules |
| `bj rules` | Where does this game's house edge come from? |
| `bj verify` | Check the model's constants against an exact enumeration |
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
| 3.0 | 50% | 0.084 | 0.011 | CZK 47 | CZK 168,876 |
| 4.0 | 67% | 0.128 | 0.031 | CZK 79 | CZK 115,801 |
| 5.0 | 83% | 0.169 | 0.063 | CZK 176 | CZK 106,624 |

Same rules, same spread, same play. Deep penetration is worth 3.7x the win rate
of shallow, and needs 37% less bankroll to sustain — decided entirely by where
the dealer puts the cut card. Counts of +4 and up, where most of the money is,
occur five times as often.

## The risk numbers are checked, not asserted

`bj validate` plays the recommended configuration out hand by hand and compares
the result with the closed form Phase 1 quotes:

| rounds played | simulated RoR | analytic RoR | gap |
|---|---|---|---|
| 20,000 | 0.33% | 5.00% | −4.67 pts |
| 50,000 | 2.08% | 5.00% | −2.92 pts |
| 100,000 | 3.55% | 5.00% | −1.45 pts |
| 200,000 | 4.63% | 5.00% | −0.37 pts |

The closed form is sound and slightly conservative. It is also an *infinite*
horizon figure — over a first season of a few hundred hours your real risk is a
small fraction of the quoted 5%.

The most useful thing the simulator turned up: **resizing your unit as the
bankroll moves cuts risk of ruin from 4.23% to 0.35%** — for nothing at the
median, and a better bad tail. Full results and caveats in `docs/validation.md`.

## Practising the right chart

```bash
bj drill --preset ambassador --kinds count,truecount,strategy,deviation -n 20
```

Five drills: running count over a stream of cards, true-count conversion,
basic strategy, index plays, and bet sizing off your own ramp.

Two things make it more than flashcards. The strategy and deviation questions
are **generated from the analyzer**, so you practise the chart for the game you
actually sit at — including the ENHC corrections no printed chart carries.
Drilling a Vegas chart for a Prague table would teach you the wrong answer four
times over.

And repetition is weighted toward what you get wrong. Misses come back most,
then slow answers — knowing it eventually is not the same as knowing it with a
dealer waiting. Progress persists between sessions; `bj drill --stats` shows
your weakest items.

The scenarios are constrained to ones you can actually meet: never a shoe state
past the cut card, and the running count is sampled from its real random-walk
spread, so you will not be asked for the true count at −35 with a full shoe.

## The constants are checked against an exact enumeration

`bj verify` enumerates every initial deal, weights each by its probability and
takes the exact EV of the best action — no sampling error at all. This is what
validates the numbers Phase 1 sizes bankrolls from.

The spec proposed a full-hand simulator for this. It cannot work: a 0.45% edge
against a per-hand standard deviation of 1.15 needs roughly 130 million hands to
resolve to a hundredth of a percent. Enumeration gets there exactly, in seconds.

| preset | model | exact | error |
|---|---|---|---|
| vegas-strip | −0.3300% | −0.3337% | −0.0037% |
| vegas-8d | −0.6500% | −0.6469% | +0.0031% |
| ambassador | −0.4500% | −0.4452% | +0.0048% |
| uk-enhc | −0.5200% | −0.5178% | +0.0022% |

The rule-effect constants hold up to well under a basis point. Two things it did
turn up, in `docs/validation.md`:

* **A real bug in the analyzer.** Splits were modelled without resplitting,
  which cost about 0.05% — five times the error of everything else combined.
  Fixed; the published chart still reproduces exactly.
* **The Hi-Lo slope was too low.** The usual 0.5%-per-true-count rule of thumb
  measures 0.535% over the counts you actually bet in, stable across shoe
  depths. The curve is also convex, reaching 0.70% above +6. Correcting it moved
  the Ambassador win rate from CZK 77/hour to CZK 93 — the tool had been
  understating its own edge by about 20%.

## Strategy is computed, not transcribed

`bj chart` derives basic strategy from an exact EV engine rather than copying a
published chart. Run against a plain US game it reproduces the printed 6-deck
S17 chart **exactly, all 340 cells** — which is what makes it trustworthy on
games no one has printed a chart for.

That turned up three things about the ENHC chart this project started from:

* Its four ENHC corrections are all **correct**.
* It is **missing a fifth**: `11 vs 10 → hit`. A ten upcard makes a natural 7.7%
  of the time, and under all-bets-lost that is enough to flip the cell. Doubling
  only becomes right again at true count +4.
* Its **vs-Ace doubling indices are wrong**. `11 vs A → double at +1` and
  `10 vs A → double at +4` are peek-game numbers. Under full ENHC doubling into
  an ace is never correct at any count — a higher count means more tens, so a
  *higher* chance the dealer holds the natural that takes your second unit. The
  engine independently reproduces the +1 index when the dealer does peek, which
  is how you can tell it is right rather than merely different.

`bj deviations` ranks index numbers by what each is worth at your penetration,
so you learn the ones that pay. Working in `docs/chart-review.md`.

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

Read `docs/open-questions.md` before betting real money. The EV model and its
constants are now verified against exact enumeration, and the chart's vs-Ace
indices are resolved. What remains: the linear EV model is still a straight line
through a convex curve, so it understates the edge above about +6; **nothing
here models heat**, so every win rate is an upper bound; and two rules of your
actual game — whether it is really S17, and how surrender settles with no hole
card — are still unconfirmed and together worth more than any modelling
improvement left in this repo.

N0 is the number that deserves the most attention. At most realistic bankrolls
it is several hundred hours — the point at which your expected win merely equals
one standard deviation. Short-term results tell you close to nothing.

## Status

Everything in the original spec is built except session logging:

| phase | what | state |
|---|---|---|
| 1 | rules engine, true-count simulation, ramps, risk, viability | done |
| 1.5 | Monte Carlo validation of the analytic risk model | done |
| 2 | exact analyzer, computed charts, deviation indices, trainer | done |
| 3 | web app: browser engine, live recompute for any rules | done |
| — | exact-enumeration verification of the EV model itself | done |

287 tests, ruff clean. The default suite runs in about 90 seconds; the
long-running enumerations and Monte Carlo runs are opt-in:

```bash
pytest                      # 272 fast tests
pytest -m slow              # 29 slow ones, about 12 minutes
ruff check src tests
```

The spec's full-hand simulator is deliberately **not** built — it cannot resolve
an edge this small at any reachable sample size. `bj verify` enumerates the game
exactly instead; see the verification section above.


Card counting is legal. Casinos are private property and may refuse service.
This is an educational modelling tool, not financial advice.
