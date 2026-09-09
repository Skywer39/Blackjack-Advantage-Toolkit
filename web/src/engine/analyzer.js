// Exact expected value for a blackjack decision, given a deck composition.
// Mirrors src/bjtoolkit/analyzer.py -- see that file for the reasoning; this is
// a port, not a redesign.
//
// The one thing worth repeating here: under full ENHC (no hole card, all bets
// lost to a dealer natural) the blackjack branch does NOT cancel out of the
// action comparison, because doubling and splitting put a second unit at risk.
// That is why an ENHC game needs its own chart rather than the US chart with a
// few cells patched.

import {
  ACE, RANKS, TEN, addCard, drawProbs, remove,
} from "./cards.js";
import { DoubleRule, HoleCard, Surrender, isEarlySurrender } from "./rules.js";

export const Action = {
  STAND: "stand",
  HIT: "hit",
  DOUBLE: "double",
  SPLIT: "split",
  SURRENDER: "surrender",
};

// Memo tables. Bounded for the same reason the Python ones are: every true
// count generates a fresh family of deck compositions that will never be looked
// up again, so an unbounded cache is a slow leak.
const MEMO_LIMIT = 200000;
const playOutMemo = new Map();
const dealerMemo = new Map();
const hitMemo = new Map();

function capped(map) {
  if (map.size > MEMO_LIMIT) map.clear();
}

export function clearCaches() {
  playOutMemo.clear();
  dealerMemo.clear();
  hitMemo.clear();
}

const deckKey = (deck) => deck.join(",");

function playOut(total, soft, deck, h17) {
  if (total > 21) return [0, 0, 0, 0, 0, 1];
  const stands = total >= 18 || (total === 17 && !(soft && h17));
  if (stands && total >= 17) {
    const out = [0, 0, 0, 0, 0, 0];
    out[total - 17] = 1;
    return out;
  }
  const key = `${total}|${soft ? 1 : 0}|${h17 ? 1 : 0}|${deckKey(deck)}`;
  const hit = playOutMemo.get(key);
  if (hit) return hit;

  const probs = drawProbs(deck);
  const acc = [0, 0, 0, 0, 0, 0];
  for (const rank of RANKS) {
    const p = probs[rank];
    if (p <= 0) continue;
    const next = addCard(total, soft, rank);
    const sub = playOut(next.total, next.soft, remove(deck, rank), h17);
    for (let i = 0; i < 6; i++) acc[i] += p * sub[i];
  }
  capped(playOutMemo);
  playOutMemo.set(key, acc);
  return acc;
}

export function dealerOutcomes(upcard, deck, h17, excludeBlackjack) {
  const key = `${upcard}|${h17 ? 1 : 0}|${excludeBlackjack ? 1 : 0}|${deckKey(deck)}`;
  const hit = dealerMemo.get(key);
  if (hit) return hit;

  const start = addCard(0, false, upcard);
  let forbidden = null;
  if (excludeBlackjack) {
    if (upcard === ACE) forbidden = TEN;
    else if (upcard === TEN) forbidden = ACE;
  }

  let result;
  if (forbidden === null) {
    result = playOut(start.total, start.soft, deck, h17);
  } else {
    const probs = drawProbs(deck);
    const denom = 1 - probs[forbidden];
    if (denom <= 0) {
      result = playOut(start.total, start.soft, deck, h17);
    } else {
      const acc = [0, 0, 0, 0, 0, 0];
      for (const rank of RANKS) {
        if (rank === forbidden) continue;
        const p = probs[rank] / denom;
        if (p <= 0) continue;
        const next = addCard(start.total, start.soft, rank);
        const sub = playOut(next.total, next.soft, remove(deck, rank), h17);
        for (let i = 0; i < 6; i++) acc[i] += p * sub[i];
      }
      result = acc;
    }
  }
  capped(dealerMemo);
  dealerMemo.set(key, result);
  return result;
}

export function probDealerBlackjack(upcard, deck) {
  if (upcard === ACE) return drawProbs(deck)[TEN];
  if (upcard === TEN) return drawProbs(deck)[ACE];
  return 0;
}

export function evStand(total, dealer) {
  if (total > 21) return -1;
  let win = dealer[5];
  let lose = 0;
  for (let i = 0; i < 5; i++) {
    const dealerTotal = 17 + i;
    if (dealerTotal < total) win += dealer[i];
    else if (dealerTotal > total) lose += dealer[i];
  }
  return win - lose;
}

export function evHit(total, soft, deck, dealer) {
  if (total > 21) return -1;
  const key = `${total}|${soft ? 1 : 0}|${deckKey(deck)}|${dealer[0]}|${dealer[5]}`;
  const cached = hitMemo.get(key);
  if (cached !== undefined) return cached;

  const probs = drawProbs(deck);
  let acc = 0;
  for (const rank of RANKS) {
    const p = probs[rank];
    if (p <= 0) continue;
    const next = addCard(total, soft, rank);
    if (next.total > 21) {
      acc += p * -1;
      continue;
    }
    const sub = remove(deck, rank);
    acc += p * Math.max(evStand(next.total, dealer), evHit(next.total, next.soft, sub, dealer));
  }
  capped(hitMemo);
  hitMemo.set(key, acc);
  return acc;
}

export function evDouble(total, soft, deck, dealer) {
  const probs = drawProbs(deck);
  let acc = 0;
  for (const rank of RANKS) {
    const p = probs[rank];
    if (p <= 0) continue;
    acc += p * evStand(addCard(total, soft, rank).total, dealer);
  }
  return 2 * acc;
}

export function mayDouble(total, soft, rules) {
  if (rules.doubleRule === DoubleRule.ANY_TWO) return true;
  const hard = soft ? total - 10 : total;
  if (rules.doubleRule === DoubleRule.NINE_TO_ELEVEN)
    return hard >= 9 && hard <= 11 && !soft;
  return hard >= 10 && hard <= 11 && !soft;
}

// EV of ONE hand produced by a split, in units of the bet on that hand.
// Resplitting matters more than it sounds: a third card of the split rank turns
// up on roughly one split hand in thirteen, and playing it as a hard total
// instead of splitting again cost the Python engine 0.05% before it was fixed.
function splitHandEv(rank, deck, dealer, rules, splitsLeft) {
  const probs = drawProbs(deck);
  const aces = rank === ACE;
  let acc = 0;
  for (const draw of RANKS) {
    const p = probs[draw];
    if (p <= 0) continue;
    const sub = remove(deck, draw);

    const mayResplit = draw === rank && splitsLeft > 0 && (!aces || rules.resplitAces);
    if (mayResplit) {
      acc += p * 2 * splitHandEv(rank, sub, dealer, rules, splitsLeft - 1);
      continue;
    }

    const first = addCard(0, false, rank);
    const hand = addCard(first.total, first.soft, draw);
    if (aces) {
      acc += p * evStand(hand.total, dealer);
      continue;
    }
    let best = Math.max(
      evStand(hand.total, dealer),
      evHit(hand.total, hand.soft, sub, dealer),
    );
    if (rules.doubleAfterSplit && mayDouble(hand.total, hand.soft, rules)) {
      best = Math.max(best, evDouble(hand.total, hand.soft, sub, dealer));
    }
    acc += p * best;
  }
  return acc;
}

export function evSplit(rank, deck, dealer, rules) {
  const extra = Math.max(0, rules.maxSplitHands - 2);
  return 2 * splitHandEv(rank, deck, dealer, rules, extra);
}

export function surrenderAllowed(upcard, rules) {
  const s = rules.surrender;
  if (s === Surrender.NONE) return false;
  if (s === Surrender.LATE_VS_10 || s === Surrender.EARLY_VS_10) return upcard === TEN;
  if (s === Surrender.LATE_VS_9_10) return upcard === 7 || upcard === TEN;
  return true;
}

export function actionEvs(cards, upcard, deck, rules, opts = {}) {
  const {
    allowDouble = true, allowSplit = true, allowSurrender = true,
  } = opts;

  let total = 0;
  let soft = false;
  for (const c of cards) ({ total, soft } = addCard(total, soft, c));

  const h17 = rules.dealerHitsSoft17;
  const dealer = dealerOutcomes(upcard, deck, h17, true);

  let pBj = 0;
  let allBets = false;
  if (rules.holeCard === HoleCard.ENHC_ALL_BETS) {
    pBj = probDealerBlackjack(upcard, deck);
    allBets = true;
  }
  const live = 1 - pBj;

  const wrap = (evNoBj, wager) => {
    if (pBj <= 0) return evNoBj;
    const lost = allBets ? wager : 1;
    return live * evNoBj + pBj * -lost;
  };

  const out = {
    [Action.STAND]: wrap(evStand(total, dealer), 1),
    [Action.HIT]: wrap(evHit(total, soft, deck, dealer), 1),
  };

  if (allowDouble && cards.length === 2 && mayDouble(total, soft, rules)) {
    out[Action.DOUBLE] = wrap(evDouble(total, soft, deck, dealer), 2);
  }
  if (allowSplit && cards.length === 2 && cards[0] === cards[1] && rules.maxSplitHands >= 2) {
    out[Action.SPLIT] = wrap(evSplit(cards[0], deck, dealer, rules), 2);
  }
  if (allowSurrender && cards.length === 2 && surrenderAllowed(upcard, rules)) {
    out[Action.SURRENDER] = isEarlySurrender(rules.surrender) ? -0.5 : wrap(-0.5, 1);
  }
  return out;
}

export function bestAction(cards, upcard, deck, rules, opts = {}) {
  const evs = actionEvs(cards, upcard, deck, rules, opts);
  let best = null;
  let bestEv = -Infinity;
  for (const [a, v] of Object.entries(evs)) {
    if (v > bestEv) { best = a; bestEv = v; }
  }
  return { action: best, ev: bestEv, evs };
}
