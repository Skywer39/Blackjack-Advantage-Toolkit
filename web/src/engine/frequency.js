// True-count frequency distribution, simulated for a given penetration.
// Mirrors src/bjtoolkit/frequency.py.
//
// This is what makes penetration a real variable rather than a lookup: the
// distribution of true counts is entirely determined by how deep the dealer
// cuts, and the tail is where all the money is.

import { HILO_TAGS, PER_DECK } from "./cards.js";
import { CARDS_PER_HAND } from "./constants.js";

export const cardsPerRound = (rules) =>
  CARDS_PER_HAND.value * (rules.playersAtTable + 1);

function shoeTags(decks) {
  const out = [];
  for (let rank = 0; rank < 10; rank++) {
    const n = PER_DECK[rank] * decks;
    for (let i = 0; i < n; i++) out.push(HILO_TAGS[rank]);
  }
  return Int8Array.from(out);
}

// Deterministic PRNG so a given configuration always produces the same table --
// a bet ramp that shifts each time you open the app is not a bet ramp.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function simulateTcDistribution(rules, opts = {}) {
  const { nShoes = 20000, seed = 12345, tcClip = 12, estimateToHalfDeck = false } = opts;
  const rng = mulberry32(seed);
  const tags = shoeTags(rules.decks);
  const totalCards = tags.length;
  const perRound = cardsPerRound(rules);
  const penCards = rules.penetrationDecksDealt * 52;

  const nRounds = Math.max(1, Math.floor(penCards / perRound));
  const dealt = new Int32Array(nRounds);
  const decksRemaining = new Float64Array(nRounds);
  for (let i = 0; i < nRounds; i++) {
    dealt[i] = Math.floor(i * perRound);
    let dr = (totalCards - dealt[i]) / 52;
    if (estimateToHalfDeck) dr = Math.max(0.5, Math.round(dr * 2) / 2);
    decksRemaining[i] = dr;
  }

  const hist = new Float64Array(2 * tcClip + 1);
  const shoe = Int8Array.from(tags);
  let samples = 0;

  for (let s = 0; s < nShoes; s++) {
    // Fisher-Yates, in place.
    for (let i = totalCards - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      const tmp = shoe[i];
      shoe[i] = shoe[j];
      shoe[j] = tmp;
    }
    let rc = 0;
    let cursor = 0;
    for (let i = 0; i < nRounds; i++) {
      while (cursor < dealt[i]) rc += shoe[cursor++];
      const tc = rc / decksRemaining[i];
      let bucket = Math.trunc(tc);
      if (bucket < -tcClip) bucket = -tcClip;
      if (bucket > tcClip) bucket = tcClip;
      hist[bucket + tcClip] += 1;
      samples++;
    }
  }

  const probs = {};
  for (let i = 0; i < hist.length; i++) {
    if (hist[i] > 0) probs[i - tcClip] = hist[i] / samples;
  }
  return {
    probs,
    decks: rules.decks,
    penetrationDecksDealt: rules.penetrationDecksDealt,
    cardsPerRound: perRound,
    roundsPerShoe: nRounds,
    nRoundsSimulated: samples,
  };
}

export const counts = (dist) =>
  Object.keys(dist.probs).map(Number).sort((a, b) => a - b);
export const probAt = (dist, tc) => dist.probs[tc] || 0;
export const probAtOrAbove = (dist, tc) =>
  counts(dist).filter((t) => t >= tc).reduce((a, t) => a + dist.probs[t], 0);
