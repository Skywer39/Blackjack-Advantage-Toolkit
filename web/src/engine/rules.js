// Rule sets and the player edge they imply. Mirrors src/bjtoolkit/rules.py.

import {
  BASELINE_8D,
  HITS_SOFT_17,
  DOUBLE_9_TO_11,
  DOUBLE_10_11,
  NO_DAS,
  RESPLIT_ACES,
  SPLIT_TO_2_HANDS,
  SPLIT_TO_3_HANDS,
  LATE_SURRENDER_VS_10,
  LATE_SURRENDER_VS_9_10,
  LATE_SURRENDER_ALL,
  EARLY_SURRENDER_VS_10,
  EARLY_SURRENDER_ALL,
  BJ_PAYS_6_5,
  BJ_PAYS_7_5,
  BJ_PAYS_1_1,
  ENHC_ORIGINAL_BET_ONLY,
  ENHC_ALL_BETS_LOST,
  DECK_EFFECT,
} from "./constants.js";

export const Surrender = {
  NONE: "none",
  LATE_VS_10: "late_vs_10",
  LATE_VS_9_10: "late_vs_9_10",
  LATE_ALL: "late_all",
  EARLY_VS_10: "early_vs_10",
  EARLY_ALL: "early_all",
};

export const HoleCard = {
  PEEK: "peek",
  ENHC_ORIGINAL_ONLY: "enhc_original_only",
  ENHC_ALL_BETS: "enhc_all_bets",
};

export const DoubleRule = {
  ANY_TWO: "any_two",
  NINE_TO_ELEVEN: "9_to_11",
  TEN_ELEVEN: "10_11",
};

export const isEarlySurrender = (s) =>
  s === Surrender.EARLY_VS_10 || s === Surrender.EARLY_ALL;

export const DEFAULTS = {
  name: "custom",
  decks: 6,
  dealerHitsSoft17: false,
  doubleRule: DoubleRule.ANY_TWO,
  doubleAfterSplit: true,
  resplitAces: false,
  maxSplitHands: 4,
  surrender: Surrender.NONE,
  holeCard: HoleCard.PEEK,
  blackjackPayout: 1.5,
  penetrationDecksDealt: 4.5,
  playersAtTable: 1,
  tableMin: 200,
  tableMax: 5000,
  currency: "CZK",
};

export function makeRules(overrides = {}) {
  const r = { ...DEFAULTS, ...overrides };
  if (r.penetrationDecksDealt >= r.decks) {
    r.penetrationDecksDealt = Math.max(0.5, r.decks - 0.5);
  }
  if (r.tableMax <= r.tableMin) r.tableMax = r.tableMin * 2;
  return r;
}

export const penetrationFraction = (r) => r.penetrationDecksDealt / r.decks;
export const maxTableSpread = (r) => r.tableMax / r.tableMin;

function deckEffect(decks) {
  const known = Object.keys(DECK_EFFECT).map(Number).sort((a, b) => a - b);
  if (DECK_EFFECT[decks]) return DECK_EFFECT[decks];
  const lo = Math.max(...known.filter((d) => d < decks));
  const hi = Math.min(...known.filter((d) => d > decks));
  const t = (decks - lo) / (hi - lo);
  const a = DECK_EFFECT[lo];
  const b = DECK_EFFECT[hi];
  return {
    value: a.value + t * (b.value - a.value),
    low: a.low + t * (b.low - a.low),
    high: a.high + t * (b.high - a.high),
    source: `interpolated between ${lo} and ${hi} decks`,
  };
}

export function edgeComponents(r) {
  const parts = [["baseline (8D, S17, DAS, 3:2, peek)", BASELINE_8D]];

  if (r.decks !== 8) parts.push([`${r.decks} decks instead of 8`, deckEffect(r.decks)]);
  if (r.dealerHitsSoft17) parts.push(["dealer hits soft 17", HITS_SOFT_17]);

  if (r.doubleRule === DoubleRule.NINE_TO_ELEVEN)
    parts.push(["double 9-11 only", DOUBLE_9_TO_11]);
  else if (r.doubleRule === DoubleRule.TEN_ELEVEN)
    parts.push(["double 10-11 only", DOUBLE_10_11]);

  if (!r.doubleAfterSplit) parts.push(["no double after split", NO_DAS]);
  if (r.resplitAces) parts.push(["resplit aces", RESPLIT_ACES]);
  if (r.maxSplitHands === 2) parts.push(["split to 2 hands only", SPLIT_TO_2_HANDS]);
  else if (r.maxSplitHands === 3) parts.push(["split to 3 hands only", SPLIT_TO_3_HANDS]);

  const surrenderEffect = {
    [Surrender.NONE]: null,
    [Surrender.LATE_VS_10]: ["late surrender vs 10", LATE_SURRENDER_VS_10],
    [Surrender.LATE_VS_9_10]: ["late surrender vs 9-10", LATE_SURRENDER_VS_9_10],
    [Surrender.LATE_ALL]: ["late surrender", LATE_SURRENDER_ALL],
    [Surrender.EARLY_VS_10]: ["early surrender vs 10", EARLY_SURRENDER_VS_10],
    [Surrender.EARLY_ALL]: ["early surrender", EARLY_SURRENDER_ALL],
  }[r.surrender];
  if (surrenderEffect) parts.push(surrenderEffect);

  if (r.holeCard === HoleCard.ENHC_ORIGINAL_ONLY)
    parts.push(["no hole card, original bet only", ENHC_ORIGINAL_BET_ONLY]);
  else if (r.holeCard === HoleCard.ENHC_ALL_BETS)
    parts.push(["no hole card, all bets lost", ENHC_ALL_BETS_LOST]);

  const payout = Math.round(r.blackjackPayout * 10000) / 10000;
  if (payout !== 1.5) {
    const known = { 1.2: BJ_PAYS_6_5, 1.4: BJ_PAYS_7_5, 1.0: BJ_PAYS_1_1 };
    if (known[payout]) parts.push([`blackjack pays ${payout}:1`, known[payout]]);
    else {
      const scaled = (BJ_PAYS_6_5.value * (1.5 - payout)) / 0.3;
      parts.push([`blackjack pays ${payout}:1`, {
        value: scaled, low: scaled * 1.1, high: scaled * 0.9,
        source: "scaled linearly from the 6:5 figure",
      }]);
    }
  }
  return parts;
}

export const baseEdge = (r) =>
  edgeComponents(r).reduce((acc, [, e]) => acc + e.value, 0);

export function baseEdgeRange(r) {
  const parts = edgeComponents(r);
  return [
    parts.reduce((a, [, e]) => a + e.low, 0),
    parts.reduce((a, [, e]) => a + e.high, 0),
  ];
}

export const PRESETS = {
  ambassador: makeRules({
    name: "Casino Ambassador (Prague)", decks: 6, dealerHitsSoft17: false,
    surrender: Surrender.LATE_VS_9_10, holeCard: HoleCard.ENHC_ALL_BETS,
    penetrationDecksDealt: 4.5, tableMin: 200, tableMax: 5000, currency: "CZK",
  }),
  "vegas-strip": makeRules({
    name: "Vegas Strip 6-deck (S17, DAS, LS)", decks: 6,
    surrender: Surrender.LATE_ALL, tableMin: 25, tableMax: 2000, currency: "USD",
  }),
  "vegas-h17": makeRules({
    name: "Vegas 6-deck H17", decks: 6, dealerHitsSoft17: true,
    surrender: Surrender.LATE_ALL, tableMin: 15, tableMax: 1000, currency: "USD",
  }),
  "vegas-8d": makeRules({
    name: "Vegas 8-deck H17, no surrender", decks: 8, dealerHitsSoft17: true,
    penetrationDecksDealt: 6, tableMin: 10, tableMax: 1000, currency: "USD",
  }),
  "single-deck": makeRules({
    name: "Single deck S17, double 10-11 only", decks: 1,
    doubleRule: DoubleRule.TEN_ELEVEN, doubleAfterSplit: false, maxSplitHands: 2,
    penetrationDecksDealt: 0.65, tableMin: 25, tableMax: 500, currency: "USD",
  }),
  "double-deck": makeRules({
    name: "Double deck H17, DAS", decks: 2, dealerHitsSoft17: true,
    penetrationDecksDealt: 1.5, tableMin: 25, tableMax: 1000, currency: "USD",
  }),
  "six-five": makeRules({
    name: "6:5 tourist table -- do not play this", decks: 6,
    dealerHitsSoft17: true, blackjackPayout: 1.2, penetrationDecksDealt: 4,
    tableMin: 10, tableMax: 500, currency: "USD",
  }),
  "uk-enhc": makeRules({
    name: "UK/European 6-deck ENHC, S17", decks: 6,
    holeCard: HoleCard.ENHC_ALL_BETS, penetrationDecksDealt: 4.5,
    tableMin: 10, tableMax: 500, currency: "GBP",
  }),
};
