# What the engine says about the accompanying chart

`bj chart --preset ambassador` computes basic strategy from scratch for the
Ambassador rules. This is what it found when compared against the ENHC deviation
chart that came with the original spec.

First, the engine's credentials. Run against a plain US game it reproduces the
published 6-deck S17 DAS chart **exactly — all 340 cells**, which is asserted in
`tests/test_strategy.py::test_reproduces_the_published_s17_chart_exactly`. Where
it disagrees with the ENHC chart below, the disagreement is worth taking
seriously.

## Confirmed: the four ENHC corrections the chart lists

All four are correct.

| cell | chart | engine |
|---|---|---|
| 11 vs A | hit | hit |
| 8,8 vs A | hit | hit |
| A,A vs A | hit | hit |
| 8,8 vs 10 | surrender | surrender |

The chart's reasoning is right too: against an ace the dealer completes a
natural about 31% of the time, against a ten only 7.7%, and against 2-9 never.
Every column from 2 to 9 is identical to the standard S17 chart, which the test
suite also asserts.

## Missing: a fifth correction, 11 vs 10

The chart doubles hard 11 against a ten. Under full ENHC that is wrong.

| rules | hit | double | best |
|---|---|---|---|
| peek (US) | +0.1187 | +0.1789 | double |
| ENHC, original bet only | +0.1187 | +0.1789 | double |
| ENHC, all bets lost | +0.0309 | +0.0080 | **hit** |

A ten upcard makes a natural 7.7% of the time, and under all-bets-lost that
takes the doubled portion with it. It is enough to flip the cell. Doubling only
becomes correct again at **true count +4**, as the extra tens start to pay for
the risk.

If the game turns out to be original-bet-only rather than all-bets-lost, this
correction disappears along with the other four.

## Wrong: the vs-Ace doubling indices

The chart carries `11 vs A → double at +1` and `10 vs A → double at +4`, and the
spec encodes the same values. Both are standard Illustrious 18 numbers for a
**peek** game, and they do not survive here.

Hard 11 against an ace, by true count:

| TC | peek: hit | peek: double | ENHC: hit | ENHC: double |
|---|---|---|---|---|
| 0 | +0.1499 | +0.1434 | −0.2109 | −0.5291 |
| +1 | +0.1587 | **+0.1755** | −0.2139 | −0.5241 |
| +4 | +0.1856 | **+0.2701** | −0.2235 | −0.5133 |
| +12 | +0.2707 | **+0.5064** | −0.2475 | −0.5158 |

In the peek game doubling takes over at +1, exactly the published index — good
evidence the engine is right rather than merely different. Under full ENHC the
gap never closes. It cannot: a higher count means more tens, which means a
*higher* chance the dealer has the natural that takes your second unit. The same
argument kills `10 vs A`.

**There is no correct index for doubling into an ace in this game. Never do it.**

## Insurance is a shade above +3

The conventional index is +3. Computed exactly, the break-even sits at **+3.06**
counting only the dealer's ace as seen, drifting to about +3.3 if you also hold
a ten. Hi-Lo counts tens and aces alike as high cards while only tens pay
insurance, which is why the number is not rounder.

Taking insurance at +3 is very slightly aggressive and costs almost nothing.
Keep using +3; just know it is a rounding, not a threshold.

## On the deviation list generally

`bj deviations --preset ambassador` finds 78 cells whose correct play changes
with the count, and ranks them by what each is actually worth at your
penetration. The tail is worthless — a 40th-ranked index on a hand you see twice
a session earns a rounding error. Learn the top of the list and skip the rest.

One structural note: the engine reports **no index for 16 vs 10**, the most
famous index in blackjack. That is correct for this game. The classic "stand at
0 or above" assumes surrender is unavailable; where late surrender is offered it
beats standing at every count, so there is nothing to deviate to. In a
no-surrender game (`--preset vegas-8d`) the engine finds the index as expected.
