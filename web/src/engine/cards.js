// Deck compositions and hand arithmetic. Mirrors src/bjtoolkit/cards.py.
//
// Ranks are 0-9 for 2,3,4,5,6,7,8,9,T,A. Tens and pictures share index 8, so a
// deck holds sixteen of them. A hand is { total, soft }, where soft means an ace
// is currently counted as eleven and can still be dropped to one.

export const RANKS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
export const TEN = 8;
export const ACE = 9;
export const RANK_NAMES = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "A"];
export const RANK_VALUES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
export const PER_DECK = [4, 4, 4, 4, 4, 4, 4, 4, 16, 4];
export const HILO_TAGS = [1, 1, 1, 1, 1, 0, 0, 0, -1, -1];

export function freshDeck(decks = 6) {
  return PER_DECK.map((c) => c * decks);
}

export function remove(deck, rank) {
  const out = deck.slice();
  out[rank] -= 1;
  return out;
}

export function removeMany(deck, ...ranks) {
  const out = deck.slice();
  for (const r of ranks) out[r] -= 1;
  return out;
}

export function totalCards(deck) {
  let n = 0;
  for (let i = 0; i < 10; i++) n += deck[i];
  return n;
}

export function drawProbs(deck) {
  const n = totalCards(deck);
  if (n <= 0) return new Array(10).fill(0);
  return deck.map((c) => c / n);
}

export function addCard(total, soft, rank) {
  if (rank === ACE) {
    if (total + 11 <= 21) return { total: total + 11, soft: true };
    return { total: total + 1, soft };
  }
  const t = total + RANK_VALUES[rank];
  if (t > 21 && soft) return { total: t - 10, soft: false };
  return { total: t, soft };
}

export function handFrom(...ranks) {
  let total = 0;
  let soft = false;
  for (const r of ranks) ({ total, soft } = addCard(total, soft, r));
  return { total, soft };
}

// A deck composition consistent with a given Hi-Lo true count. Low cards are
// moved into the high group in their natural proportions, so the tens-to-aces
// ratio stays realistic rather than merely arithmetically correct.
export function deckForTrueCount(tc, decks = 6, cardsRemaining = null) {
  const remaining = cardsRemaining === null
    ? Math.round(decks * 52 * 0.5)
    : cardsRemaining;
  const decksRemaining = remaining / 52;
  const targetRc = tc * decksRemaining;

  const scale = remaining / (decks * 52);
  const deck = PER_DECK.map((c) => c * decks * scale);

  // Each card moved from the low group to the high group shifts the running
  // count by two, so the number to move is half the target.
  const shift = targetRc / 2;
  let lowTotal = 0;
  for (let r = 0; r < 5; r++) lowTotal += deck[r];
  const highTotal = deck[TEN] + deck[ACE];
  if (lowTotal <= 0 || highTotal <= 0) return deck;

  for (let r = 0; r < 5; r++) deck[r] -= shift * (deck[r] / lowTotal);
  deck[TEN] += shift * (deck[TEN] / highTotal);
  deck[ACE] += shift * (deck[ACE] / highTotal);
  return deck.map((c) => Math.max(0, c));
}

export function runningCount(deck, decks) {
  const full = freshDeck(decks);
  let rc = 0;
  for (const r of RANKS) rc += HILO_TAGS[r] * (full[r] - deck[r]);
  return rc;
}

export function trueCountOf(deck, decks) {
  const remaining = totalCards(deck);
  if (remaining <= 0) return 0;
  return runningCount(deck, decks) / (remaining / 52);
}
