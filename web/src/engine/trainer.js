// Drills for the things you have to do at speed. Mirrors src/bjtoolkit/trainer.py.
//
// Two things make this more than a flashcard loop, and both are ported intact:
// questions are generated from the chart computed for YOUR rules, and
// repetition is weighted toward what you get wrong. Scenarios are also
// constrained to ones you can actually meet -- never past the cut card, and the
// running count sampled from its real random-walk spread rather than uniformly.

import { HILO_TAGS, PER_DECK, RANK_NAMES } from "./cards.js";

export const KINDS = ["count", "truecount", "strategy", "deviation", "bet"];

export const KIND_LABELS = {
  count: "Running count",
  truecount: "True count",
  strategy: "Basic strategy",
  deviation: "Index plays",
  bet: "Bet sizing",
};

export const ACTION_WORDS = {
  h: "hit", hit: "hit",
  s: "stand", stand: "stand",
  d: "double", double: "double",
  p: "split", split: "split",
  r: "surrender", surrender: "surrender",
};

// --- progress -------------------------------------------------------------

export function emptyStats() {
  return { seen: 0, correct: 0, totalMs: 0 };
}

export class Progress {
  constructor(items = {}) {
    this.items = items;
  }

  stat(key) {
    if (!this.items[key]) this.items[key] = emptyStats();
    return this.items[key];
  }

  record(key, correct, ms) {
    const s = this.stat(key);
    s.seen += 1;
    s.correct += correct ? 1 : 0;
    s.totalMs += Math.max(0, ms);
  }

  accuracy(key) {
    const s = this.items[key];
    return s && s.seen ? s.correct / s.seen : 0;
  }

  meanSeconds(key) {
    const s = this.items[key];
    return s && s.seen ? s.totalMs / s.seen / 1000 : 0;
  }

  // Unseen first, then wrong, then slow -- knowing an index eventually is not
  // the same as knowing it with a dealer waiting. Bounded so nothing starves.
  weight(key, slowAfter = 4) {
    const s = this.items[key];
    if (!s || s.seen === 0) return 6;
    const errorRate = 1 - s.correct / s.seen;
    const mean = s.totalMs / s.seen / 1000;
    const slowness = Math.max(0, mean - slowAfter) / slowAfter;
    return 1 + 5 * errorRate + 1.5 * Math.min(slowness, 2);
  }

  summary() {
    let seen = 0;
    let correct = 0;
    let ms = 0;
    for (const s of Object.values(this.items)) {
      seen += s.seen;
      correct += s.correct;
      ms += s.totalMs;
    }
    return {
      answered: seen,
      correct,
      accuracy: seen ? correct / seen : 0,
      meanSeconds: seen ? ms / seen / 1000 : 0,
      itemsTracked: Object.keys(this.items).length,
    };
  }

  // One miss is noise, not a weakness, so an item needs two attempts to rank.
  weakest(n = 8) {
    return Object.entries(this.items)
      .filter(([, s]) => s.seen >= 2)
      .sort((a, b) => {
        const accA = a[1].correct / a[1].seen;
        const accB = b[1].correct / b[1].seen;
        if (accA !== accB) return accA - accB;
        return b[1].totalMs / b[1].seen - a[1].totalMs / a[1].seen;
      })
      .slice(0, n);
  }

  byKind() {
    const out = {};
    for (const [key, s] of Object.entries(this.items)) {
      const kind = key.split(":")[0];
      if (!out[kind]) out[kind] = { seen: 0, correct: 0, totalMs: 0 };
      out[kind].seen += s.seen;
      out[kind].correct += s.correct;
      out[kind].totalMs += s.totalMs;
    }
    return out;
  }
}

// --- persistence ----------------------------------------------------------
// localStorage is per-viewer and per-artifact, survives a republish, and can
// throw outright in a private window -- so every access is guarded and the app
// works with none of it.

const STORE_KEY = "rr-progress-v1";

export function loadProgress() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return new Progress();
    const parsed = JSON.parse(raw);
    const items = {};
    for (const [k, v] of Object.entries(parsed.items || {})) {
      if (v && typeof v.seen === "number") items[k] = { ...emptyStats(), ...v };
    }
    return new Progress(items);
  } catch {
    return new Progress();
  }
}

export function saveProgress(progress) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({ items: progress.items }));
    return true;
  } catch {
    return false;
  }
}

export function clearProgress() {
  try { localStorage.removeItem(STORE_KEY); } catch { /* nothing to clear */ }
}

// --- shoe ----------------------------------------------------------------

function drawRank(deck, rng) {
  let total = 0;
  for (const c of deck) total += c;
  let pick = rng() * total;
  for (let r = 0; r < 10; r++) {
    pick -= deck[r];
    if (pick < 0) return r;
  }
  return 9;
}

export const FACES = ["10", "J", "Q", "K"];

export function cardFace(rank, rng) {
  return rank === 8 ? FACES[Math.floor(rng() * 4)] : RANK_NAMES[rank];
}

// Box-Muller, for sampling a running count from its real spread.
function gauss(rng, sd) {
  const u = Math.max(1e-12, rng());
  const v = rng();
  return sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

// --- question generation --------------------------------------------------

export function countQuestion(rules, nCards, rng = Math.random) {
  const deck = PER_DECK.map((c) => c * rules.decks);
  const cards = [];
  let rc = 0;
  for (let i = 0; i < nCards; i++) {
    const rank = drawRank(deck, rng);
    deck[rank] -= 1;
    cards.push(rank);
    rc += HILO_TAGS[rank];
  }
  return {
    kind: "count",
    cards,
    faces: cards.map((c) => cardFace(c, rng)),
    answer: rc,
    itemKey: `count:${nCards}`,
    explain: cards.map((c) => (HILO_TAGS[c] >= 0 ? "+" : "") + HILO_TAGS[c]).join(" ")
      + ` = ${rc >= 0 ? "+" : ""}${rc}`,
    tolerance: 0,
  };
}

export function trueCountQuestion(rules, rng = Math.random) {
  // Never past the cut card: drilling a shoe state the dealer would already
  // have shuffled is wasted effort.
  const minLeft = Math.max(0.5, rules.decks - rules.penetrationDecksDealt);
  const lo = Math.max(1, Math.round(minLeft * 2));
  const hi = Math.max(lo, rules.decks * 2 - 1);
  const halves = lo + Math.floor(rng() * (hi - lo + 1));
  const decksLeft = halves / 2;

  // The count starts at zero and random-walks, so its spread depends on cards
  // DEALT: sd = sigma * sqrt(dealt * remaining / (total - 1)), sigma^2 = 40/52.
  const total = rules.decks * 52;
  const remaining = decksLeft * 52;
  const dealt = total - remaining;
  const sd = Math.sqrt(40 / 52) * Math.sqrt(Math.max(0, (dealt * remaining) / (total - 1)));
  const rc = sd > 0 ? Math.round(gauss(rng, sd)) : 0;
  const tc = rc / decksLeft;
  return {
    kind: "truecount",
    runningCount: rc,
    decksRemaining: decksLeft,
    answer: tc,
    itemKey: `truecount:${decksLeft}`,
    explain: `${rc >= 0 ? "+" : ""}${rc} ÷ ${decksLeft} = ${tc >= 0 ? "+" : ""}${tc.toFixed(2)}`,
    tolerance: 0.5,
  };
}

const HAND_LABEL = (category, label) =>
  category === "hard" ? `Hard ${label}` : label;

export function strategyQuestion(chartKeys, chart, progress, rng = Math.random) {
  const key = weightedPick(chartKeys, (k) => progress.weight(`strategy:${k}`), rng);
  const [category, label, upcard] = key.split("|");
  return {
    kind: "strategy",
    hand: HAND_LABEL(category, label),
    upcard,
    answer: chart[key],
    itemKey: `strategy:${key}`,
    explain: `basic strategy for these rules says ${chart[key]}`,
  };
}

export function deviationQuestion(deviations, progress, rng = Math.random) {
  const d = weightedPick(
    deviations,
    (x) => progress.weight(`deviation:${x.category}|${x.label}|${x.upcard}`),
    rng,
  );
  // Ask on both sides of the index: the drill should teach a boundary, not one
  // memorised answer.
  const deviating = rng() < 0.5;
  const off = 1 + Math.floor(rng() * 3);
  let tc;
  if (d.direction === "+") tc = deviating ? d.index + Math.floor(rng() * 3) : d.index - off;
  else tc = deviating ? d.index - Math.floor(rng() * 3) : d.index + off;
  return {
    kind: "deviation",
    hand: HAND_LABEL(d.category, d.label),
    upcard: d.upcard,
    trueCount: tc,
    answer: deviating ? d.switchTo : d.basic,
    itemKey: `deviation:${d.category}|${d.label}|${d.upcard}`,
    explain: `index is ${d.index >= 0 ? "+" : ""}${d.index}${d.direction}: `
      + `${d.switchTo} at ${d.index >= 0 ? "+" : ""}${d.index}${d.direction}, otherwise ${d.basic}`,
  };
}

export function betQuestion(rules, ramp, progress, rng = Math.random) {
  const tcs = Object.keys(ramp).map(Number).sort((a, b) => a - b);
  const tc = weightedPick(tcs, (t) => progress.weight(`bet:${t}`), rng);
  return {
    kind: "bet",
    trueCount: tc,
    answer: ramp[tc],
    itemKey: `bet:${tc}`,
    explain: `your ramp says ${rules.currency} ${ramp[tc].toLocaleString()}`,
    tolerance: Math.max(1, rules.tableMin / 2),
  };
}

function weightedPick(options, weightOf, rng) {
  let total = 0;
  const weights = options.map((o) => {
    const w = Math.max(0.0001, weightOf(o));
    total += w;
    return w;
  });
  let pick = rng() * total;
  for (let i = 0; i < options.length; i++) {
    pick -= weights[i];
    if (pick < 0) return options[i];
  }
  return options[options.length - 1];
}

export function pickKind(kinds, progress, rng = Math.random) {
  return weightedPick(kinds, (k) => {
    const keys = Object.keys(progress.items).filter((x) => x.startsWith(`${k}:`));
    if (!keys.length) return 3;
    return keys.reduce((a, key) => a + progress.weight(key), 0) / keys.length;
  }, rng);
}

export function checkAnswer(question, response) {
  const raw = String(response).trim().toLowerCase();
  if (!raw) return false;
  if (question.kind === "strategy" || question.kind === "deviation") {
    return ACTION_WORDS[raw] === question.answer;
  }
  const value = Number(raw.replace(/[+\s,]/g, ""));
  if (!Number.isFinite(value)) return false;
  return Math.abs(value - question.answer) <= (question.tolerance || 0) + 1e-9;
}
