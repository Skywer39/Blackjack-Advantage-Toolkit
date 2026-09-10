// Asserts the browser engine agrees with the Python engine.
//
// Fixtures come from tools/export_fixtures.py. Deterministic quantities must
// match to 1e-9; there is no reason for two implementations of the same
// arithmetic to differ at all. Run via `node web/tests/conformance.test.mjs`,
// or through pytest, which does it for you.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { ACE, RANK_NAMES, TEN, freshDeck, removeMany } from "../src/engine/cards.js";
import { actionEvs, dealerOutcomes, probDealerBlackjack } from "../src/engine/analyzer.js";
import { PRESETS, baseEdge, baseEdgeRange } from "../src/engine/rules.js";
import { basicStrategy, chartLookup, insuranceIndex } from "../src/engine/strategy.js";
import {
  bankrollForRor, evaluate, kellyForRor, rorForKelly, spreadRamp,
} from "../src/engine/risk.js";
import { Progress } from "../src/engine/trainer.js";

const here = dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "fixtures", "conformance.json"), "utf8"),
);

const EPS = 1e-9;
let checks = 0;
const failures = [];

function close(actual, expected, label, eps = EPS) {
  checks++;
  if (expected === null && actual === null) return;
  if (!Number.isFinite(expected)) {
    if (Number.isFinite(actual)) failures.push(`${label}: expected ${expected}, got ${actual}`);
    return;
  }
  if (Math.abs(actual - expected) > eps) {
    failures.push(`${label}: expected ${expected}, got ${actual} (diff ${Math.abs(actual - expected).toExponential(2)})`);
  }
}

function same(actual, expected, label) {
  checks++;
  if (actual !== expected) failures.push(`${label}: expected ${expected}, got ${actual}`);
}

// --- rule edges -----------------------------------------------------------
for (const [name, want] of Object.entries(fx.edges)) {
  const r = PRESETS[name];
  if (!r) { failures.push(`missing preset ${name}`); continue; }
  close(baseEdge(r), want.edge, `edge/${name}`);
  const [lo, hi] = baseEdgeRange(r);
  close(lo, want.low, `edgeLow/${name}`);
  close(hi, want.high, `edgeHigh/${name}`);
}

// --- dealer distributions -------------------------------------------------
for (const [key, want] of Object.entries(fx.dealer)) {
  const [decks, h17, up] = key.split("|").map(Number);
  const got = dealerOutcomes(up, removeMany(freshDeck(decks), up), Boolean(h17), true);
  for (let i = 0; i < 6; i++) close(got[i], want[i], `dealer/${key}[${i}]`);
}

// --- exact action EVs -----------------------------------------------------
for (const probe of fx.actionEvs) {
  const r = PRESETS[probe.preset];
  const deck = removeMany(freshDeck(r.decks), ...probe.cards, probe.upcard);
  close(probDealerBlackjack(probe.upcard, deck), probe.pBlackjack,
    `pBJ/${probe.preset}/${probe.cards}/${probe.upcard}`);
  const evs = actionEvs(probe.cards, probe.upcard, deck, r);
  const gotKeys = Object.keys(evs).sort().join(",");
  const wantKeys = Object.keys(probe.evs).sort().join(",");
  same(gotKeys, wantKeys, `legalActions/${probe.preset}/${probe.cards}/${probe.upcard}`);
  for (const [action, value] of Object.entries(probe.evs)) {
    close(evs[action], value, `ev/${probe.preset}/${probe.cards}/${probe.upcard}/${action}`);
  }
}

// --- whole charts ---------------------------------------------------------
for (const [name, want] of Object.entries(fx.charts)) {
  const map = chartLookup(basicStrategy(PRESETS[name]));
  same(Object.keys(map).length, Object.keys(want).length, `chartSize/${name}`);
  for (const [cell, action] of Object.entries(want)) {
    same(map[cell] ? map[cell].action : "MISSING", action, `chart/${name}/${cell}`);
  }
}

// --- insurance ------------------------------------------------------------
for (const [name, want] of Object.entries(fx.insurance)) {
  close(insuranceIndex(PRESETS[name]), want, `insurance/${name}`, 0.011);
}

// --- risk arithmetic against a fixed frequency table -----------------------
const freq = {};
for (const [k, v] of Object.entries(fx.risk.freq)) freq[Number(k)] = v;
const dist = { probs: freq };

for (const c of fx.risk.cases) {
  const r = PRESETS[c.preset];
  const ramp = spreadRamp(r, dist, {
    maxSpread: c.spread, unit: r.tableMin, wongOutBelow: c.wong,
  });
  for (const [tc, bet] of Object.entries(c.bets)) {
    close(ramp.bets[tc], bet, `bet/${c.preset}/${c.spread}/${c.wong}/${tc}`);
  }
  const rep = evaluate(r, dist, ramp, { bankroll: 100000 });
  const tag = `${c.preset}/${c.spread}/wong=${c.wong}`;
  close(rep.winRatePerRound, c.winRatePerRound, `winRate/${tag}`);
  close(rep.variancePerRound, c.variancePerRound, `variance/${tag}`);
  close(rep.n0Rounds, c.n0Rounds, `n0/${tag}`, 1e-6);
  close(rep.riskOfRuin, c.riskOfRuin, `ror/${tag}`);
  close(rep.probOfProfit, c.probOfProfit, `pProfit/${tag}`, 1e-7);
  close(bankrollForRor(0.05, rep.winRatePerRound, rep.variancePerRound),
    c.requiredBankroll, `bankroll/${tag}`, 1e-6);
}

for (const [t, want] of Object.entries(fx.risk.kellyForRor)) {
  close(kellyForRor(Number(t)), want, `kellyForRor/${t}`);
}
for (const [f, want] of Object.entries(fx.risk.rorForKelly)) {
  close(rorForKelly(Number(f)), want, `rorForKelly/${f}`);
}

// --- trainer weighting ----------------------------------------------------
for (const [name, want] of Object.entries(fx.trainer.weights)) {
  const p = new Progress();
  for (const [correct, seconds] of want.events) p.record(name, correct, seconds * 1000);
  close(p.weight(name), want.weight, `trainerWeight/${name}`);
  if (want.events.length) {
    close(p.accuracy(name), want.accuracy, `trainerAccuracy/${name}`);
    close(p.meanSeconds(name), want.meanSeconds, `trainerMeanSeconds/${name}`);
  }
}

// --- report ---------------------------------------------------------------
if (failures.length) {
  console.error(`FAILED ${failures.length} of ${checks} checks:\n`);
  for (const f of failures.slice(0, 25)) console.error("  " + f);
  if (failures.length > 25) console.error(`  ... and ${failures.length - 25} more`);
  process.exit(1);
}
console.log(`browser engine matches the Python engine on all ${checks} checks`);
