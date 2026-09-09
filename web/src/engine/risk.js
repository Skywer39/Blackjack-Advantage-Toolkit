// EV model, bet ramps and risk metrics.
// Mirrors src/bjtoolkit/{ev_model,ramp,risk,viability}.py.

import {
  HAND_VARIANCE, HAND_VARIANCE_TC_SLOPE, HILO_SLOPE,
} from "./constants.js";
import { counts, probAt } from "./frequency.js";
import { baseEdge } from "./rules.js";

export const evAtTc = (tc, rules, slope = null) =>
  baseEdge(rules) + (slope === null ? HILO_SLOPE.value : slope) * tc;

export const varianceAtTc = (tc, tcDependent = true) =>
  tcDependent
    ? HAND_VARIANCE.value + HAND_VARIANCE_TC_SLOPE.value * Math.max(0, tc)
    : HAND_VARIANCE.value;

export const breakevenTc = (rules) => -baseEdge(rules) / HILO_SLOPE.value;

const roundToUnit = (x, unit) => (unit > 0 ? Math.round(x / unit) * unit : x);

function rampShell(bets, satOut, warnings) {
  const played = {};
  for (const [t, b] of Object.entries(bets)) {
    if (!satOut.has(Number(t)) && b > 0) played[t] = b;
  }
  const values = Object.values(played);
  return {
    bets, satOut, warnings, played,
    bet: (tc) => (satOut.has(tc) ? 0 : bets[tc] || 0),
    spread: values.length ? Math.max(...values) / Math.min(...values) : 0,
    topBet: values.length ? Math.max(...values) : 0,
    bottomBet: values.length ? Math.min(...values) : 0,
  };
}

const wongSet = (dist, wongOutBelow) =>
  wongOutBelow === null || wongOutBelow === undefined
    ? new Set()
    : new Set(counts(dist).filter((t) => t < wongOutBelow));

export function kellyRamp(rules, dist, opts = {}) {
  const {
    bankroll, kellyFraction = 0.4, roundingUnit = null,
    maxSpread = null, wongOutBelow = null, tcDependentVariance = true,
  } = opts;
  const unit = roundingUnit === null ? rules.tableMin : roundingUnit;
  const satOut = wongSet(dist, wongOutBelow);
  const warnings = [];

  const raw = {};
  for (const tc of counts(dist)) {
    raw[tc] = Math.max(0, (kellyFraction * evAtTc(tc, rules) / varianceAtTc(tc, tcDependentVariance)) * bankroll);
  }

  let cap = rules.tableMax;
  if (maxSpread !== null) {
    cap = Math.min(cap, rules.tableMin * maxSpread);
    if (Object.values(raw).some((v) => v > rules.tableMin * maxSpread)) {
      warnings.push(`your cover limit of ${maxSpread}x is capping bets below what Kelly wants -- you are deliberately leaving EV on the table`);
    }
  }
  if (Object.values(raw).some((v) => v > rules.tableMax)) {
    warnings.push(`the ${rules.currency} ${rules.tableMax.toLocaleString()} table maximum is suppressing your top bets`);
  }

  const bets = {};
  for (const tc of counts(dist)) {
    const bet = Math.min(Math.max(raw[tc], rules.tableMin), cap);
    bets[tc] = Math.max(roundToUnit(bet, unit), rules.tableMin);
  }

  const advantage = counts(dist).filter((t) => evAtTc(t, rules) > 0 && !satOut.has(t));
  if (advantage.length) {
    const first = Math.min(...advantage);
    if (raw[first] < rules.tableMin) {
      const needed = (rules.tableMin * varianceAtTc(first, tcDependentVariance)) / (kellyFraction * evAtTc(first, rules));
      warnings.push(`bankroll too small for this table: at TC ${first >= 0 ? "+" : ""}${first} Kelly wants ${rules.currency} ${Math.round(raw[first]).toLocaleString()} but the minimum is ${rules.currency} ${rules.tableMin.toLocaleString()}. You would need about ${rules.currency} ${Math.round(needed).toLocaleString()} to bet this table properly at ${kellyFraction} Kelly.`);
    }
  }
  const ramp = rampShell(bets, satOut, warnings);
  if (ramp.spread && ramp.spread < 2) {
    warnings.push(`realised spread is only ${ramp.spread.toFixed(1)}x -- too flat to overcome the off-the-top house edge`);
  }
  return ramp;
}

// A Kelly-SHAPED ramp scaled to a chosen spread, independent of bankroll. This
// is what makes bankrollForRor a real solve rather than a fixed-point chase.
export function spreadRamp(rules, dist, opts = {}) {
  const {
    maxSpread, unit = null, wongOutBelow = null,
    roundingUnit = null, tcDependentVariance = true,
  } = opts;
  const u = unit === null ? rules.tableMin : unit;
  const rounding = roundingUnit === null ? u : roundingUnit;
  const satOut = wongSet(dist, wongOutBelow);
  const warnings = [];

  const shape = {};
  for (const tc of counts(dist)) {
    shape[tc] = Math.max(0, evAtTc(tc, rules)) / varianceAtTc(tc, tcDependentVariance);
  }
  const live = counts(dist).filter((t) => !satOut.has(t)).map((t) => shape[t]);
  const peak = live.length ? Math.max(...live) : 0;

  const bets = {};
  for (const tc of counts(dist)) {
    if (peak <= 0) { bets[tc] = u; continue; }
    const scaled = u + (maxSpread - 1) * u * (shape[tc] / peak);
    bets[tc] = Math.max(roundToUnit(scaled, rounding), u);
  }
  if (u * maxSpread > rules.tableMax) {
    warnings.push(`a ${maxSpread}x spread off a ${rules.currency} ${u.toLocaleString()} unit needs a top bet of ${rules.currency} ${(u * maxSpread).toLocaleString()}, above this table's maximum of ${rules.currency} ${rules.tableMax.toLocaleString()}`);
  }
  return rampShell(bets, satOut, warnings);
}

const phi = (x) => 0.5 * (1 + erf(x / Math.SQRT2));

function erf(x) {
  // Abramowitz & Stegun 7.1.26, good to about 1.5e-7 -- far tighter than the
  // model whose output it formats.
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return sign * y;
}

export function evaluate(rules, dist, ramp, opts = {}) {
  const {
    bankroll = null, roundsPerHour = 70, hoursPlanned = 100,
    tcDependentVariance = true,
  } = opts;
  let wr = 0;
  let variance = 0;
  let playedP = 0;
  for (const tc of counts(dist)) {
    const p = probAt(dist, tc);
    const bet = ramp.bet(tc);
    if (bet <= 0) continue;
    playedP += p;
    wr += p * bet * evAtTc(tc, rules);
    variance += p * bet * bet * varianceAtTc(tc, tcDependentVariance);
  }
  const sd = variance > 0 ? Math.sqrt(variance) : 0;
  const warnings = [...ramp.warnings];
  if (wr <= 0) {
    warnings.push("this configuration is EV-NEGATIVE: you would lose money playing it. The ramp is too flat, the penetration too shallow, or the rules too poor to beat the house edge you pay on low counts.");
  }
  const n0Rounds = wr > 0 ? variance / (wr * wr) : Infinity;
  const expected = wr * roundsPerHour * hoursPlanned;
  const sdPlanned = sd * Math.sqrt(roundsPerHour * hoursPlanned);
  return {
    currency: rules.currency,
    fractionOfRoundsPlayed: playedP,
    winRatePerRound: wr,
    winRatePerPlayedHand: playedP > 0 ? wr / playedP : 0,
    variancePerRound: variance,
    sdPerRound: sd,
    winRatePerHour: wr * roundsPerHour,
    sdPerHour: sd * Math.sqrt(roundsPerHour),
    handsPlayedPerHour: playedP * roundsPerHour,
    n0Rounds,
    n0Hours: Number.isFinite(n0Rounds) ? n0Rounds / roundsPerHour : Infinity,
    bankroll,
    riskOfRuin: bankroll === null ? null : riskOfRuin(wr, variance, bankroll),
    hoursPlanned,
    expectedProfit: expected,
    sdOverPlanned: sdPlanned,
    probOfProfit: sdPlanned > 0 ? phi(expected / sdPlanned) : 0,
    warnings,
  };
}

export function riskOfRuin(winRatePerRound, variancePerRound, bankroll) {
  if (winRatePerRound <= 0) return 1;
  if (variancePerRound <= 0) return 0;
  return Math.exp((-2 * winRatePerRound * bankroll) / variancePerRound);
}

// Only meaningful for a ramp fixed in currency. With Kelly-sized bets, win rate
// scales as B and variance as B^2, so the ruin exponent is scale-invariant and
// this question has no answer -- use kellyForRor instead.
export function bankrollForRor(targetRor, winRatePerRound, variancePerRound) {
  if (!(targetRor > 0 && targetRor < 1)) throw new Error("targetRor must be between 0 and 1");
  if (winRatePerRound <= 0) return Infinity;
  return (-Math.log(targetRor) * variancePerRound) / (2 * winRatePerRound);
}

export const kellyForRor = (targetRor) => -2 / Math.log(targetRor);
export const rorForKelly = (f) => (f <= 0 ? 0 : Math.exp(-2 / f));
