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

All figures below: Ambassador rules, CZK 93,136 bankroll, 8x spread off a CZK 200
unit, wonging out below TC +1. That is the configuration `bj viability` calls
viable at 5% risk of ruin, so it is the claim worth auditing.

## 1. The closed form is right, and errs on the safe side

Risk of ruin is an *infinite-horizon* quantity. A player with a finite number of
hands left faces less of it, so the two only meet once the horizon is long
compared with the time the edge needs to carry the bankroll clear:

| rounds played | simulated RoR | analytic RoR | gap | ended profitable |
|---|---|---|---|---|
| 20,000 | 0.33% | 5.00% | −4.67 pts | 73.1% |
| 50,000 | 2.08% | 5.00% | −2.92 pts | 84.3% |
| 100,000 | 3.55% | 5.00% | −1.45 pts | 91.5% |
| 200,000 | 4.63% | 5.00% | −0.37 pts | 94.5% |

Converging cleanly from below, and settling just under the analytic figure. The
closed form is sound and slightly conservative — the right direction for a
number you size a bankroll from.

**The practical reading:** 5% is a lifetime figure. Over a first season of a few
hundred hours, your real risk of losing the bankroll is a fraction of that.

## 2. The lumpiness of blackjack payoffs does not matter for ruin

| outcome model | RoR | median final bankroll |
|---|---|---|
| discrete (pushes, 3:2 blackjacks, doubles, splits) | 4.23% | CZK 287,759 |
| normal (same mean and variance) | 4.52% | CZK 290,592 |

Within noise of each other. Ruin is a drift-and-diffusion phenomenon; once the
mean and variance match, the shape of a single hand's payoff washes out. This is
why the moment-matched simulator is a legitimate test of the risk arithmetic
even though it never deals a card.

It is *not* a test of the EV model. If `ev_at_tc` is wrong, the simulator is
wrong in exactly the same way and will cheerfully agree with the closed form.
Checking that needs the Phase 2 strategy engine and real dealt hands.

## 3. Resizing your unit cuts ruin by a factor of twelve

The single most actionable result here.

| betting | RoR | median final | 5th percentile |
|---|---|---|---|
| ramp fixed in CZK | 4.23% | CZK 287,759 | CZK 65,543 |
| resized to current bankroll | **0.35%** | CZK 291,243 | CZK 77,246 |

Recomputing your unit as the bankroll moves — betting less after a bad run,
more after a good one — drops ruin from 4.23% to 0.35%. It costs nothing at the
median and *improves* the fifth percentile by CZK 11,700.

The closed form assumes a fixed ramp, so it overstates the risk faced by anyone
who actually resizes. If you re-derive your unit every few sessions rather than
grinding a fixed ramp into the ground, treat the quoted RoR as a ceiling.

## 4. The ruin barrier barely matters

| ruin declared at | RoR |
|---|---|
| CZK 0 (the analytic barrier) | 4.23% |
| CZK 1,600 (cannot cover the top bet) | 4.70% |

Quitting when you can no longer place your top bet is only marginally worse than
playing to zero. By the time a bankroll is that far down it is almost certainly
going the rest of the way.

## 5. What the distribution of outcomes actually looks like

After 150,000 rounds — roughly 2,100 hours, or several years of weekend play —
starting from CZK 93,136:

| percentile | final bankroll |
|---|---|
| P5 | CZK 65,543 |
| P25 | CZK 211,929 |
| P50 | CZK 287,759 |
| P75 | CZK 362,305 |
| P95 | CZK 473,785 |

93.6% of paths end ahead. Mean profit CZK 190,771 against an analytic
expectation of CZK 198,310 — the gap is the ruined paths, which stop earning.

Note the spread. The 5th and 95th percentiles differ by a factor of eight after
two thousand hours of correct play. That is what an N0 of roughly 670 hours
means in practice, and it is the honest reason not to judge your play by
results.

---

# Part 2: does the EV model itself tell the truth?

Everything above validates the *risk arithmetic*. It cannot test the EV model,
because the simulator draws hand results whose moments come from that model —
a wrong edge produces a simulation that agrees with the wrong closed form
perfectly.

The spec proposed a full-hand simulator for this. It will not work. A 0.45% edge
against a per-hand standard deviation near 1.15 needs a standard error of 1e-4
to resolve to a hundredth of a percent, which is roughly **130 million hands**.
No Python simulation reaches that, and a noisy answer validates nothing.

Enumeration does reach it, exactly. There are only 55 unordered two-card player
hands and 10 upcards, and the Phase 2 analyzer returns the exact EV of every
action. Weighting each deal by its probability gives the true edge with no
sampling error. `bj verify` does this.

## 6. The rule-effect constants hold up

| preset | model | exact | error |
|---|---|---|---|
| vegas-strip | −0.3300% | −0.3337% | −0.0037% |
| vegas-8d | −0.6500% | −0.6469% | +0.0031% |
| ambassador | −0.4500% | −0.4452% | +0.0048% |
| uk-enhc | −0.5200% | −0.5178% | +0.0022% |
| vegas-h17 | −0.5500% | −0.5317% | +0.0183% |
| six-five | −2.0200% | −1.9784% | +0.0416% |

Well under a basis point for most games. H17 and 6:5 are the two loosest, at
about two and four basis points — worth knowing, not worth acting on.

## 7. It found a real bug, not just a discrepancy

The first run of this comparison was off by a consistent −0.05% across every
preset. Systematic, not noise, and too large to shrug at.

The dealer-distribution approximation was the obvious suspect and turned out to
be innocent: measured directly it is worth +0.0003 units, and in the opposite
direction.

The actual cause was in `ev_split`, which modelled splitting into exactly two
hands and never resplitting. Drawing a third card of the split rank happens on
roughly one split hand in thirteen, and playing that as a hard total instead of
splitting again is expensive. Modelling resplits properly closed the gap from
0.05% to under 0.005%. The published chart still reproduces exactly, so the fix
changed the *value* of splitting without disturbing the decisions.

This is the case for enumeration over simulation in one paragraph: a Monte Carlo
with a realistic sample size could never have seen a 0.05% error.

## 8. The Hi-Lo slope was too low

The usual rule of thumb is 0.5% of edge per true count. Measured over true
counts −3 to +6 — the range you actually bet in — it is **0.535%**, and it is
stable across shoe depths from 1.5 to 4 decks remaining:

| decks left | slope, TC −3..+6 | slope, TC +6..+10 |
|---|---|---|
| 1.5 | 0.533% | 0.689% |
| 2.0 | 0.538% | 0.697% |
| 3.0 | 0.542% | 0.706% |
| 4.0 | 0.544% | 0.710% |

That stability is itself worth noting: true count is supposed to normalise for
how much shoe is left, and it does.

Two consequences. The constant is now 0.00535, derived from this computation
rather than from the rule of thumb — it was inside the uncertainty range the
constant already declared, which is some vindication of declaring one. And the
**curve is convex**: above +6 the local slope climbs toward 0.71%, so a straight
line increasingly understates the edge at high counts. That is the conservative
direction, since high counts are where the bets are large.

Correcting the slope moved the Ambassador win rate from CZK 77/hour to CZK 93
and N0 from 821 hours to 672. The tool had been understating its own edge by
about 20%. Required bankroll barely moved, because both win rate and variance
scale together.

One thing not to misread: the TC-0 point of the EV curve is **not** the game's
off-the-top edge. The curve is evaluated against a half-dealt shoe, which plays
slightly better for the player for the same reason a 4-deck game beats an
8-deck one.

## What is still not validated

* **The analyzer's own approximations.** Dealer probabilities are not recomputed
  as the player draws (measured at +0.0003 units, above), and split hands are
  treated as drawing independently from the same shoe. Both are documented at
  their call sites and are worth well under a basis point.
* **Heat.** No backoffs, no shuffle-ups, no barring. Every figure is an upper
  bound on what you would actually earn.
* **Execution.** The simulated player never miscounts, never misplays an index,
  and never tips a dealer.
