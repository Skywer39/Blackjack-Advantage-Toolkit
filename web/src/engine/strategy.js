// Basic strategy and deviation indices, computed rather than transcribed.
// Mirrors src/bjtoolkit/strategy.py.

import { Action, actionEvs, bestAction } from "./analyzer.js";
import {
  ACE, RANKS, RANK_NAMES, TEN, deckForTrueCount, removeMany,
} from "./cards.js";

export const UPCARDS = RANKS;

const valueOf = (rank) => (rank === TEN ? 10 : rank + 2);

export function cardsForHard(total) {
  for (let a = 0; a < 9; a++)
    for (let b = a; b < 9; b++)
      if (valueOf(a) + valueOf(b) === total && a !== b) return [a, b];
  for (let a = 0; a < 9; a++) if (2 * valueOf(a) === total) return [a, a];
  throw new Error(`no two cards make hard ${total}`);
}

export const cardsForSoft = (total) => [ACE, total - 13];
export const cardsForPair = (rank) => [rank, rank];

// A chart row is not one hand: hard 16 is 10+6 about half the time and 9+7 or
// 8+8 the rest, and those play differently. Published charts quote the
// composition-averaged answer, which is what you memorise before you look at
// your cards. Averaging here is what makes this agree with them.
export function hardCompositions(total, deck) {
  const out = [];
  for (let a = 0; a < 9; a++) {
    for (let b = a; b < 9; b++) {
      if (valueOf(a) + valueOf(b) !== total) continue;
      const weight = a === b ? (deck[a] * (deck[a] - 1)) / 2 : deck[a] * deck[b];
      if (weight > 0) out.push([[a, b], weight]);
    }
  }
  const nonPairs = out.filter(([c]) => c[0] !== c[1]);
  const chosen = nonPairs.length ? nonPairs : out;
  const total_w = chosen.reduce((a, [, w]) => a + w, 0);
  return chosen.map(([c, w]) => [c, w / total_w]);
}

export function evaluateCell(category, cards, label, upcard, rules, tc = 0) {
  const base = deckForTrueCount(tc, rules.decks);
  const comps = category === "hard"
    ? hardCompositions(parseInt(label, 10), base)
    : [[cards, 1]];

  const totals = {};
  let legal = null;
  for (const [comp, weight] of comps) {
    const deck = removeMany(base, ...comp, upcard);
    const evs = actionEvs(comp, upcard, deck, rules, {
      allowSplit: category === "pair",
    });
    const keys = new Set(Object.keys(evs));
    legal = legal === null ? keys : new Set([...legal].filter((k) => keys.has(k)));
    for (const [action, value] of Object.entries(evs)) {
      totals[action] = (totals[action] || 0) + weight * value;
    }
  }
  const ordered = Object.entries(totals)
    .filter(([a]) => legal.has(a))
    .sort((x, y) => y[1] - x[1]);
  const [best, bestEv] = ordered[0];
  const [runner, runnerEv] = ordered[1] || [null, bestEv];
  return {
    category, label, upcard, action: best, ev: bestEv,
    runnerUp: runner, margin: bestEv - runnerEv,
    close: bestEv - runnerEv < 0.01,
  };
}

export const hardRows = () =>
  Array.from({ length: 16 }, (_, i) => [String(i + 5), cardsForHard(i + 5)]);
export const softRows = () =>
  Array.from({ length: 8 }, (_, i) => [`A,${i + 2}`, cardsForSoft(i + 13)]);
export const pairRows = () =>
  RANKS.map((r) => [r === ACE ? "A,A" : `${RANK_NAMES[r]},${RANK_NAMES[r]}`, cardsForPair(r)]);

export function basicStrategy(rules, tc = 0, onProgress = null) {
  const cells = [];
  const groups = [["hard", hardRows()], ["soft", softRows()], ["pair", pairRows()]];
  let done = 0;
  const total = groups.reduce((a, [, rows]) => a + rows.length, 0) * UPCARDS.length;
  for (const [category, rows] of groups) {
    for (const [label, cards] of rows) {
      for (const up of UPCARDS) {
        cells.push(evaluateCell(category, cards, label, up, rules, tc));
        if (onProgress && ++done % 40 === 0) onProgress(done / total);
      }
    }
  }
  return cells;
}

export function chartLookup(cells) {
  const map = {};
  for (const c of cells) map[`${c.category}|${c.label}|${RANK_NAMES[c.upcard]}`] = c;
  return map;
}

// --- deviations ----------------------------------------------------------

export function findDeviation(category, cards, label, upcard, rules, range = [-6, 8]) {
  const [lo, hi] = range;
  const basic = evaluateCell(category, cards, label, upcard, rules, 0).action;
  for (let tc = 1; tc <= hi; tc++) {
    const a = evaluateCell(category, cards, label, upcard, rules, tc).action;
    if (a !== basic) return { category, label, upcard, basic, switchTo: a, index: tc, direction: "+" };
  }
  for (let tc = -1; tc >= lo; tc--) {
    const a = evaluateCell(category, cards, label, upcard, rules, tc).action;
    if (a !== basic) return { category, label, upcard, basic, switchTo: a, index: tc, direction: "-" };
  }
  return null;
}

export function allDeviations(rules, range = [-6, 8], onProgress = null) {
  const found = [];
  const groups = [["hard", hardRows()], ["soft", softRows()], ["pair", pairRows()]];
  const total = groups.reduce((a, [, rows]) => a + rows.length, 0) * UPCARDS.length;
  let done = 0;
  for (const [category, rows] of groups) {
    for (const [label, cards] of rows) {
      for (const up of UPCARDS) {
        const d = findDeviation(category, cards, label, up, rules, range);
        if (d) found.push(d);
        if (onProgress && ++done % 10 === 0) onProgress(done / total);
      }
    }
  }
  return found;
}

function cardsFor(category, label) {
  if (category === "hard") return cardsForHard(parseInt(label, 10));
  if (category === "soft") return cardsForSoft(11 + parseInt(label.split(",")[1], 10));
  const left = label.split(",")[0];
  return cardsForPair(left === "A" ? ACE : RANK_NAMES.indexOf(left));
}

function handProbability(cards, upcard, deck) {
  const n = deck.reduce((a, b) => a + b, 0);
  if (n < 3) return 0;
  const [a, b] = cards;
  const pHand = a === b
    ? (deck[a] / n) * ((deck[a] - 1) / (n - 1))
    : 2 * (deck[a] / n) * (deck[b] / (n - 1));
  return pHand * (deck[upcard] / n);
}

// A deviation earns its place only if the hand comes up, the count reaches the
// index often enough, and the play gains enough when it does. This is what
// separates an Illustrious 18 from a list of seventy curiosities.
export function rankDeviations(rules, tcProbs, deviations) {
  const rows = deviations.map((d) => {
    const cards = cardsFor(d.category, d.label);
    let gain = 0;
    let freq = 0;
    for (const [tcStr, pTc] of Object.entries(tcProbs)) {
      const tc = Number(tcStr);
      const deviating = d.direction === "+" ? tc >= d.index : tc <= d.index;
      if (!deviating) continue;
      const base = deckForTrueCount(tc, rules.decks);
      const evs = actionEvs(cards, d.upcard, removeMany(base, ...cards, d.upcard), rules, {
        allowSplit: d.category === "pair",
      });
      if (!(d.switchTo in evs) || !(d.basic in evs)) continue;
      const edge = evs[d.switchTo] - evs[d.basic];
      if (edge <= 0) continue;
      const pHand = handProbability(cards, d.upcard, base);
      gain += pTc * pHand * edge;
      freq += pTc * pHand;
    }
    return { deviation: d, value: gain, frequency: freq };
  });
  rows.sort((a, b) => b.value - a.value);
  return rows;
}

export function insuranceIndex(rules, precision = 0.01) {
  const edge = (tc) => {
    const deck = removeMany(deckForTrueCount(tc, rules.decks), ACE);
    const n = deck.reduce((a, b) => a + b, 0);
    return 3 * (deck[TEN] / n) - 1;
  };
  let lo = 0;
  let hi = 20;
  if (edge(hi) <= 0) return Infinity;
  while (hi - lo > precision) {
    const mid = (lo + hi) / 2;
    if (edge(mid) > 0) hi = mid;
    else lo = mid;
  }
  return Math.round(hi * 100) / 100;
}

export function decide(cards, upcard, trueCount, rules) {
  const deck = removeMany(deckForTrueCount(trueCount, rules.decks), ...cards, upcard);
  return bestAction(cards, upcard, deck, rules, {
    allowDouble: cards.length === 2,
    allowSplit: cards.length === 2 && cards[0] === cards[1],
    allowSurrender: cards.length === 2,
  }).action;
}
