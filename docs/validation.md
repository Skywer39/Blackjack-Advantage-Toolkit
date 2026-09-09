# Does the analytic risk model tell the truth?

Phase 1 sizes your bankroll from a closed form:

```
RoR = exp(-2 * win_rate * bankroll / variance)
```

That formula assumes a continuous bankroll, normally distributed increments, an
infinite playing horizon, and a bet that stays fixed relative to the bankroll. A
real bet ramp breaks most of those. Phase 1.5 plays the game out hand by hand to
find out how much it matters.

Reproduce any of this with `bj sim` and `bj validate`.

All figures below: Ambassador rules, CZK 94,158 bankroll, 8x spread off a CZK 200
unit, wonging out below TC +1. That is the configuration `bj viability` calls
viable at 5% risk of ruin, so it is the claim worth auditing.

## 1. The closed form is right, and errs on the safe side

Risk of ruin is an *infinite-horizon* quantity. A player with a finite number of
hands left faces less of it, so the two only meet once the horizon is long
compared with the time the edge needs to carry the bankroll clear:

| rounds played | simulated RoR | analytic RoR | gap | ended profitable |
|---|---|---|---|---|
| 20,000 | 0.13% | 5.00% | −4.87 pts | 71.9% |
| 50,000 | 1.62% | 5.00% | −3.38 pts | 82.1% |
| 100,000 | 3.47% | 5.00% | −1.53 pts | 89.9% |
| 200,000 | 4.63% | 5.00% | −0.37 pts | 94.0% |

Converging cleanly from below, and settling just under the analytic figure. The
closed form is sound and slightly conservative — the right direction for a
number you size a bankroll from.

**The practical reading:** 5% is a lifetime figure. Over a first season of a few
hundred hours, your real risk of losing the bankroll is a fraction of that.

## 2. The lumpiness of blackjack payoffs does not matter for ruin

| outcome model | RoR | median final bankroll |
|---|---|---|
| discrete (pushes, 3:2 blackjacks, doubles, splits) | 4.25% | CZK 255,212 |
| normal (same mean and variance) | 4.08% | CZK 258,570 |

Within noise of each other. Ruin is a drift-and-diffusion phenomenon; once the
mean and variance match, the shape of a single hand's payoff washes out. This is
why the moment-matched simulator is a legitimate test of the risk arithmetic
even though it never deals a card.

It is *not* a test of the EV model. If `ev_at_tc` is wrong, the simulator is
wrong in exactly the same way and will cheerfully agree with the closed form.
Checking that needs the Phase 2 strategy engine and real dealt hands.

## 3. Resizing your unit cuts ruin by a factor of nine

The single most actionable result here.

| betting | RoR | median final | 5th percentile |
|---|---|---|---|
| ramp fixed in CZK | 4.25% | CZK 255,212 | CZK 53,618 |
| resized to current bankroll | **0.47%** | CZK 245,784 | CZK 69,787 |

Recomputing your unit as the bankroll moves — betting less after a bad run,
more after a good one — drops ruin from 4.25% to 0.47% while giving up about 4%
of the median outcome. The fifth percentile *improves* by CZK 16,000.

The closed form assumes a fixed ramp, so it overstates the risk faced by anyone
who actually resizes. If you re-derive your unit every few sessions rather than
grinding a fixed ramp into the ground, treat the quoted RoR as a ceiling.

## 4. The ruin barrier barely matters

| ruin declared at | RoR |
|---|---|
| CZK 0 (the analytic barrier) | 4.25% |
| CZK 1,600 (cannot cover the top bet) | 4.43% |

Quitting when you can no longer place your top bet is only marginally worse than
playing to zero. By the time a bankroll is that far down it is almost certainly
going the rest of the way.

## 5. What the distribution of outcomes actually looks like

After 150,000 rounds — roughly 2,100 hours, or several years of weekend play —
starting from CZK 94,158:

| percentile | final bankroll |
|---|---|
| P5 | CZK 53,618 |
| P25 | CZK 186,054 |
| P50 | CZK 255,212 |
| P75 | CZK 323,408 |
| P95 | CZK 425,274 |

92.5% of paths end ahead. Mean profit CZK 158,296 against an analytic
expectation of CZK 164,167 — the gap is the ruined paths, which stop earning.

Note the spread. The 5th and 95th percentiles differ by a factor of eight after
two thousand hours of correct play. That is what an N0 of roughly 800 hours
means in practice, and it is the honest reason not to judge your play by
results.

## What this does not validate

* **The EV model.** See section 2. Moment matching cannot detect a wrong edge.
* **Heat.** No backoffs, no shuffle-ups, no barring. Every figure is an upper
  bound on what you would actually earn.
* **Execution.** The simulated player never miscounts, never misplays an index,
  and never tips a dealer.
