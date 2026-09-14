// Ramp & Ruin -- the betting-software half of the toolkit, in the browser.
//
// Everything is computed live from the rules: nothing is precomputed and
// shipped, so any game can be priced, not just the presets. The heavy piece is
// the strategy chart (a few hundred exact EV evaluations), which is computed on
// demand and yielded between rows so the page stays responsive on a phone.

import { RANK_NAMES } from "./engine/cards.js";
import {
  DoubleRule, HoleCard, PRESETS, Surrender, baseEdge, baseEdgeRange,
  edgeComponents, makeRules, maxTableSpread, penetrationFraction,
} from "./engine/rules.js";
import {
  UPCARDS, basicStrategy, cardsForHard, cardsForPair, cardsForSoft, chartLookup,
  findDeviation, insuranceIndex, rankDeviations,
} from "./engine/strategy.js";
import {
  KINDS, KIND_LABELS, Progress, betQuestion, checkAnswer, clearProgress,
  countQuestion, deviationQuestion, loadProgress, pickKind, saveProgress,
  strategyQuestion, trueCountQuestion,
} from "./engine/trainer.js";
import { counts, probAtOrAbove, simulateTcDistribution } from "./engine/frequency.js";
import {
  bankrollForRor, breakevenTc, evAtTc, evaluate, kellyForRor, kellyRamp,
  rorForKelly, spreadRamp,
} from "./engine/risk.js";

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const state = {
  preset: "ambassador",
  rules: { ...PRESETS.ambassador },
  bankroll: 100000,
  kelly: 0.4,
  maxSpread: 8,
  wong: 1,
  hours: 100,
  roundsPerHour: 70,
  targetRor: 0.05,
  tab: "betting",
  drill: null,
  dist: null,
  chart: null,
  chartKey: null,
};

// --- formatting -----------------------------------------------------------

const money = (v, r) =>
  `${r.currency} ${Math.round(v).toLocaleString("en-US")}`;
const pct = (v, dp = 2) => `${(v * 100).toFixed(dp)}%`;
const signed = (v) => (v >= 0 ? `+${v}` : `${v}`);
const hours = (h) =>
  !Number.isFinite(h) ? "never" : h >= 1000
    ? `${Math.round(h / 100) / 10}k` : `${Math.round(h)}`;

// --- controls -------------------------------------------------------------

function field(label, control, wide = false) {
  const f = el("div", wide ? "field wide" : "field");
  const l = el("label", null, label);
  l.htmlFor = control.id;
  f.append(l, control);
  return f;
}

function numberInput(id, value, opts = {}) {
  const i = el("input");
  i.type = "number";
  i.id = id;
  i.value = value;
  Object.assign(i, opts);
  return i;
}

function select(id, options, value) {
  const s = el("select");
  s.id = id;
  for (const [v, label] of options) {
    const o = el("option", null, label);
    o.value = v;
    s.append(o);
  }
  s.value = value;
  return s;
}

function buildRail() {
  const rail = $("#railBody");
  rail.replaceChildren();
  const r = state.rules;

  const game = el("div", "group");
  game.append(el("h3", null, "Game"));
  const presetSel = select("preset",
    [...Object.entries(PRESETS).map(([k, v]) => [k, v.name]), ["custom", "Custom"]],
    state.preset);
  presetSel.addEventListener("change", () => {
    const key = presetSel.value;
    if (key !== "custom") {
      state.preset = key;
      state.rules = { ...PRESETS[key] };
      invalidate({ rebuildRail: true });
    }
  });
  game.append(field("Preset", presetSel, true));

  const ruleFields = [
    ["decks", "Decks", numberInput("decks", r.decks, { min: 1, max: 8, step: 1 })],
    ["dealerHitsSoft17", "Dealer soft 17",
      select("s17", [["false", "Stands (S17)"], ["true", "Hits (H17)"]], String(r.dealerHitsSoft17))],
    ["doubleRule", "Doubling", select("dbl", [
      [DoubleRule.ANY_TWO, "Any two cards"],
      [DoubleRule.NINE_TO_ELEVEN, "9-11 only"],
      [DoubleRule.TEN_ELEVEN, "10-11 only"]], r.doubleRule)],
    ["doubleAfterSplit", "Double after split",
      select("das", [["true", "Allowed"], ["false", "Not allowed"]], String(r.doubleAfterSplit))],
    ["resplitAces", "Resplit aces",
      select("rsa", [["false", "No"], ["true", "Yes"]], String(r.resplitAces))],
    ["maxSplitHands", "Split to",
      select("sp", [["2", "2 hands"], ["3", "3 hands"], ["4", "4 hands"]], String(r.maxSplitHands))],
    ["surrender", "Surrender", select("sur", [
      [Surrender.NONE, "Not offered"],
      [Surrender.LATE_VS_10, "Late, vs 10"],
      [Surrender.LATE_VS_9_10, "Late, vs 9-10"],
      [Surrender.LATE_ALL, "Late, any upcard"],
      [Surrender.EARLY_VS_10, "Early, vs 10"],
      [Surrender.EARLY_ALL, "Early, any upcard"]], r.surrender)],
    ["holeCard", "Hole card", select("hc", [
      [HoleCard.PEEK, "Dealer peeks (US)"],
      [HoleCard.ENHC_ORIGINAL_ONLY, "None, original bet only"],
      [HoleCard.ENHC_ALL_BETS, "None, all bets lost"]], r.holeCard)],
    ["blackjackPayout", "Blackjack pays", select("bj", [
      ["1.5", "3:2"], ["1.4", "7:5"], ["1.2", "6:5"], ["1", "1:1"]], String(r.blackjackPayout))],
  ];
  for (const [key, label, control] of ruleFields) {
    control.addEventListener("change", () => {
      let v = control.value;
      if (v === "true" || v === "false") v = v === "true";
      else if (control.type === "number" || !Number.isNaN(Number(v))) {
        if (["decks", "maxSplitHands", "blackjackPayout"].includes(key)) v = Number(v);
      }
      state.rules = makeRules({ ...state.rules, [key]: v, name: "Custom rules" });
      state.preset = "custom";
      invalidate({ rebuildRail: true });
    });
    game.append(field(label, control, control.tagName === "SELECT"));
  }
  rail.append(game);

  const table = el("div", "group");
  table.append(el("h3", null, "Table"));
  const pen = el("input");
  pen.type = "range";
  pen.id = "pen";
  pen.min = String(Math.max(0.5, r.decks * 0.35));
  pen.max = String(r.decks - 0.25);
  pen.step = "0.25";
  pen.value = String(r.penetrationDecksDealt);
  pen.addEventListener("input", () => {
    state.rules = makeRules({ ...state.rules, penetrationDecksDealt: Number(pen.value) });
    state.preset = "custom";
    invalidate({ penChanged: true });
    $("#penLabel").textContent = penLabel(state.rules);
  });
  const penRow = field("Penetration", pen);
  penRow.querySelector("label").innerHTML =
    `Penetration<br><span class="num" id="penLabel" style="font-size:11.5px;color:var(--ink-faint)">${penLabel(r)}</span>`;
  table.append(penRow);

  for (const [key, label, opts] of [
    ["playersAtTable", "Players (with you)", { min: 1, max: 7, step: 1 }],
    ["tableMin", "Table minimum", { min: 1, step: 5 }],
    ["tableMax", "Table maximum", { min: 2, step: 100 }],
  ]) {
    const input = numberInput(key, r[key], opts);
    input.addEventListener("change", () => {
      state.rules = makeRules({ ...state.rules, [key]: Number(input.value) });
      state.preset = "custom";
      invalidate({ penChanged: key === "playersAtTable", rebuildRail: true });
    });
    table.append(field(label, input));
  }
  const cur = el("input");
  cur.type = "text";
  cur.id = "cur";
  cur.value = r.currency;
  cur.addEventListener("change", () => {
    state.rules = { ...state.rules, currency: cur.value.trim().slice(0, 5) || "?" };
    invalidate({});
  });
  table.append(field("Currency", cur));
  rail.append(table);

  const you = el("div", "group");
  you.append(el("h3", null, "You"));
  const inputs = [
    ["bankroll", "Bankroll", { min: 0, step: 1000 }],
    ["kelly", "Kelly fraction", { min: 0.05, max: 1, step: 0.05 }],
    ["maxSpread", "Max spread (cover)", { min: 1, max: 50, step: 1 }],
    ["hours", "Hours planned", { min: 1, step: 10 }],
    ["roundsPerHour", "Rounds per hour", { min: 20, max: 200, step: 5 }],
  ];
  for (const [key, label, opts] of inputs) {
    const input = numberInput(key, state[key], opts);
    input.addEventListener("change", () => {
      state[key] = Number(input.value);
      invalidate({});
    });
    you.append(field(label, input));
  }
  const wongSel = select("wong",
    [["none", "Play every round"], ["0", "Sit out below TC 0"],
     ["1", "Sit out below TC +1"], ["2", "Sit out below TC +2"]],
    state.wong === null ? "none" : String(state.wong));
  wongSel.addEventListener("change", () => {
    state.wong = wongSel.value === "none" ? null : Number(wongSel.value);
    invalidate({});
  });
  you.append(field("Wonging", wongSel, true));
  const rorSel = select("ror",
    [["0.01", "1%"], ["0.05", "5%"], ["0.1", "10%"], ["0.2", "20%"]],
    String(state.targetRor));
  rorSel.addEventListener("change", () => {
    state.targetRor = Number(rorSel.value);
    invalidate({});
  });
  you.append(field("Target risk of ruin", rorSel, true));
  rail.append(you);
}

const penLabel = (r) =>
  `${r.penetrationDecksDealt} of ${r.decks} decks · ${Math.round(penetrationFraction(r) * 100)}%`;

// --- computation ----------------------------------------------------------

function ensureDist() {
  if (!state.dist) {
    state.dist = simulateTcDistribution(state.rules, { nShoes: 12000 });
  }
  return state.dist;
}

function invalidate({ penChanged = false, rebuildRail = false } = {}) {
  if (penChanged || rebuildRail) state.dist = null;
  state.chart = null;
  if (rebuildRail) buildRail();
  render();
}

// --- rendering ------------------------------------------------------------

function render() {
  const canvas = $("#canvas");
  canvas.replaceChildren();
  canvas.append(tabs());
  if (state.tab === "betting") renderBetting(canvas);
  else if (state.tab === "chart") renderChart(canvas);
  else renderDrill(canvas);
}

function tabs() {
  const wrap = el("section", "panel");
  const bar = el("div", "tabs");
  for (const [key, label] of [["betting", "Bankroll & ramp"], ["chart", "Strategy chart"], ["drill", "Drill"]]) {
    const b = el("button", null, label);
    b.type = "button";
    b.setAttribute("aria-selected", String(state.tab === key));
    b.addEventListener("click", () => { state.tab = key; render(); });
    bar.append(b);
  }
  wrap.append(bar);
  const r = state.rules;
  const [lo, hi] = baseEdgeRange(r);
  const pad = el("div", "pad");
  pad.style.paddingTop = "12px";
  pad.style.paddingBottom = "12px";
  pad.innerHTML = `<div style="font-size:13px;color:var(--ink-dim)">
    <strong style="color:var(--ink)">${r.name}</strong> — off the top
    <span class="num" style="color:var(--ink)">${pct(baseEdge(r))}</span>
    <span style="color:var(--ink-faint)">(${pct(lo)} … ${pct(hi)})</span>
    · break-even at true count <span class="num" style="color:var(--ink)">${signed(breakevenTc(r).toFixed(2))}</span>
    · insurance at <span class="num" style="color:var(--ink)">${signed(insuranceIndex(r).toFixed(2))}</span>
  </div>`;
  wrap.append(pad);
  return wrap;
}

function renderBetting(canvas) {
  const r = state.rules;
  const dist = ensureDist();
  const ramp = kellyRamp(r, dist, {
    bankroll: state.bankroll, kellyFraction: state.kelly,
    maxSpread: state.maxSpread, wongOutBelow: state.wong,
  });
  const rep = evaluate(r, dist, ramp, {
    bankroll: state.bankroll, roundsPerHour: state.roundsPerHour,
    hoursPlanned: state.hours,
  });

  canvas.append(verdictBlock(r, dist, rep, ramp));
  canvas.append(tileRow(r, rep, ramp));
  const row = el("div");
  row.style.display = "grid";
  row.style.gap = "18px";
  row.style.gridTemplateColumns = "minmax(0,1fr)";
  if (window.matchMedia("(min-width: 720px)").matches) {
    row.style.gridTemplateColumns = "minmax(280px,340px) minmax(0,1fr)";
  }
  row.append(walletCard(r, dist, ramp), spreadTable(r, dist));
  canvas.append(row);
  canvas.append(penetrationPanel(r));
  if (rep.warnings.length) canvas.append(warningsPanel(rep.warnings));
}

function verdictBlock(r, dist, rep, ramp) {
  const viable = rep.winRatePerRound > 0;
  const need = bankrollForRor(state.targetRor, rep.winRatePerRound, rep.variancePerRound);
  const box = el("div", viable ? "verdict" : "verdict no");
  box.append(el("div", "stripe"));
  const body = el("div", "body");
  body.append(el("div", "tag", viable ? "Playable" : "Not playable"));
  const p = el("p");
  if (!viable) {
    p.innerHTML = `At a ${ramp.spread.toFixed(1)}× spread this loses
      <strong>${money(-rep.winRatePerHour, r)}/hour</strong>. The ramp is too flat
      to overcome the ${pct(-baseEdge(r))} you pay on low counts — widen the
      spread, sit out more rounds, or find deeper penetration.`;
  } else {
    const afford = need <= state.bankroll;
    p.innerHTML = `About <strong>${money(rep.winRatePerHour, r)}/hour</strong>
      at a ${ramp.spread.toFixed(1)}× spread, playing
      ${Math.round(rep.fractionOfRoundsPlayed * 100)}% of rounds dealt.
      Holding this ramp at ${pct(state.targetRor, 0)} risk of ruin needs
      <strong>${money(need, r)}</strong> —
      ${afford ? "which you have." : `you are ${money(need - state.bankroll, r)} short.`}`;
    if (!afford) box.className = "verdict no";
  }
  body.append(p);
  box.append(body);
  return box;
}

function tileRow(r, rep, ramp) {
  const grid = el("div", "tiles");
  const tiles = [
    ["Win rate", money(rep.winRatePerHour, r) + "/h",
      `${money(rep.winRatePerPlayedHand, r)} per hand played`,
      rep.winRatePerHour > 0 ? "goodish" : "badish"],
    ["Swing", "±" + money(rep.sdPerHour, r),
      "one standard deviation per hour", ""],
    ["N₀", hours(rep.n0Hours) + " h",
      "until expected win equals one SD", rep.n0Hours > 800 ? "warnish" : ""],
    ["Risk of ruin", rep.riskOfRuin === null ? "—" : pct(rep.riskOfRuin, 1),
      `at ${money(state.bankroll, r)}`,
      rep.riskOfRuin > state.targetRor ? "badish" : "goodish"],
    ["Ahead after " + state.hours + "h", pct(rep.probOfProfit, 0),
      `expect ${money(rep.expectedProfit, r)}`,
      rep.probOfProfit >= 0.5 ? "" : "warnish"],
    ["Spread", ramp.spread.toFixed(1) + "×",
      `${money(ramp.bottomBet, r)} to ${money(ramp.topBet, r)}`, ""],
  ];
  for (const [k, v, n, cls] of tiles) {
    const t = el("div", "tile" + (cls ? " " + cls : ""));
    t.append(el("div", "k", k), el("div", "v", v), el("div", "n", n));
    grid.append(t);
  }
  return grid;
}

function walletCard(r, dist, ramp) {
  const panel = el("section", "panel");
  const head = el("header");
  head.append(el("h2", null, "Bet ramp"));
  head.append(el("span", "note", "screenshot this"));
  panel.append(head);
  const pad = el("div", "pad");
  const card = el("div", "wallet");
  card.append(el("h3", null, `${r.name} · ${state.kelly} Kelly`));
  const t = el("table");
  t.innerHTML = "<thead><tr><th>True count</th><th>Bet</th><th>Edge</th></tr></thead>";
  const tb = el("tbody");
  const all = counts(dist);
  const played = all.filter((t) => ramp.bet(t) > 0);
  const topBet = ramp.topBet;
  // Show every count down to the first you would bet at, and every count up to
  // the one that first reaches your top bet. Beyond that the bet stops changing,
  // so the rest collapses into a single row rather than being dropped.
  const capAt = played.find((t) => ramp.bet(t) >= topBet);
  const rows = all.filter((t) => t <= capAt && (dist.probs[t] || 0) >= 0.0008);
  for (const tc of rows) {
    const bet = ramp.bet(tc);
    const tr = el("tr");
    tr.append(el("td", "n", signed(tc)));
    const bcell = el("td", "n bet");
    if (bet <= 0) { bcell.className = "n sit"; bcell.textContent = "sit out"; }
    else bcell.textContent = money(bet, r);
    tr.append(bcell);
    const e = evAtTc(tc, r);
    const ec = el("td", "n", pct(e, 1));
    ec.style.color = e > 0 ? "var(--good)" : "var(--ink-faint)";
    tr.append(ec);
    tb.append(tr);
  }
  if (capAt !== undefined && capAt < Math.max(...all)) {
    const tr = el("tr");
    tr.append(el("td", "n", `${signed(capAt)} and up`));
    tr.append(el("td", "n bet", money(topBet, r)));
    const ec = el("td", "n", "—");
    ec.style.color = "var(--ink-faint)";
    tr.append(ec);
    tb.append(tr);
  }
  t.append(tb);
  card.append(t);
  const foot = el("p", null,
    state.wong === null
      ? `Table ${money(r.tableMin, r)}–${money(r.tableMax, r)}. Bets rounded to the minimum.`
      : `Sit out below true count ${signed(state.wong)}. Bets rounded to the minimum.`);
  foot.style.cssText = "font-size:11.5px;color:var(--ink-faint);margin:9px 0 0;line-height:1.45";
  card.append(foot);
  pad.append(card);
  panel.append(pad);
  return panel;
}

function spreadTable(r, dist) {
  const panel = el("section", "panel");
  const head = el("header");
  head.append(el("h2", null, "If you played a fixed spread instead"));
  head.append(el("span", "note",
    `bankroll for ${pct(state.targetRor, 0)} ruin · a flat 1-to-N shape, not the Kelly ramp above`));
  panel.append(head);
  const wrap = el("div", "scroll");
  const t = el("table");
  t.innerHTML = `<thead><tr><th>Spread</th><th>Top bet</th><th>Bankroll</th>
    <th>Win/hour</th><th>N₀</th><th></th></tr></thead>`;
  const tb = el("tbody");
  for (const spread of [2, 4, 6, 8, 12, 16, 20]) {
    const ramp = spreadRamp(r, dist, {
      maxSpread: spread, unit: r.tableMin, wongOutBelow: state.wong,
    });
    const rep = evaluate(r, dist, ramp, { roundsPerHour: state.roundsPerHour });
    const need = bankrollForRor(state.targetRor, rep.winRatePerRound, rep.variancePerRound);
    const top = r.tableMin * spread;
    const tr = el("tr");
    tr.append(el("td", "n", spread + "×"), el("td", "n", money(top, r)));
    tr.append(el("td", "n", Number.isFinite(need) ? money(need, r) : "—"));
    tr.append(el("td", "n", money(rep.winRatePerHour, r)));
    tr.append(el("td", "n", hours(rep.n0Hours)));
    let chip;
    if (rep.winRatePerRound <= 0) chip = ["no", "EV-negative"];
    else if (top > r.tableMax) chip = ["cap", "over table max"];
    else if (need > state.bankroll) chip = ["no", "unaffordable"];
    else chip = ["ok", "affordable"];
    const c = el("td");
    c.style.textAlign = "right";
    c.append(el("span", "chip " + chip[0], chip[1]));
    tr.append(c);
    tb.append(tr);
  }
  t.append(tb);
  wrap.append(t);
  panel.append(wrap);
  return panel;
}

function penetrationPanel(r) {
  const panel = el("section", "panel");
  const head = el("header");
  head.append(el("h2", null, "What the cut card is worth"));
  head.append(el("span", "note", "same rules, same spread, different penetration"));
  panel.append(head);

  const rows = [];
  for (const frac of [0.5, 0.58, 0.67, 0.75, 0.83, 0.9]) {
    const pen = Math.round(r.decks * frac * 4) / 4;
    if (pen >= r.decks || pen <= 0) continue;
    const rr = makeRules({ ...r, penetrationDecksDealt: pen });
    const d = simulateTcDistribution(rr, { nShoes: 5000 });
    const ramp = spreadRamp(rr, d, {
      maxSpread: state.maxSpread, unit: rr.tableMin, wongOutBelow: state.wong,
    });
    const rep = evaluate(rr, d, ramp, { roundsPerHour: state.roundsPerHour });
    rows.push({ pen, frac: pen / r.decks, win: rep.winRatePerHour,
      p4: probAtOrAbove(d, 4) });
  }

  const pad = el("div", "pad");
  pad.append(penChart(rows, r));
  const wrap = el("div", "scroll");
  const t = el("table");
  t.innerHTML = `<thead><tr><th>Decks dealt</th><th>Of shoe</th>
    <th>P(TC ≥ +4)</th><th>Win/hour</th></tr></thead>`;
  const tb = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    tr.append(el("td", "n", row.pen.toFixed(2)));
    tr.append(el("td", "n", Math.round(row.frac * 100) + "%"));
    tr.append(el("td", "n", row.p4.toFixed(3)));
    const w = el("td", "n", money(row.win, r));
    if (row.win <= 0) w.style.color = "var(--bad)";
    tr.append(w);
    tb.append(tr);
  }
  t.append(tb);
  wrap.append(t);
  pad.append(wrap);
  panel.append(pad);
  return panel;
}

// A small column chart. One scale, every label naming a value the chart
// reaches, colours from the theme tokens, and room in the viewBox for the
// outermost labels.
function penChart(rows, r) {
  const W = 520, H = 150, padL = 46, padR = 10, padT = 14, padB = 26;
  const max = Math.max(1, ...rows.map((x) => x.win));
  const min = Math.min(0, ...rows.map((x) => x.win));
  const span = max - min || 1;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const y = (v) => padT + plotH * (1 - (v - min) / span);
  const bw = Math.min(48, (plotW / rows.length) * 0.62);

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", "100%");
  svg.style.maxWidth = W + "px";
  svg.style.display = "block";
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Win rate per hour by penetration");

  const ns = (tag, attrs, text) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };

  for (const v of [min, min + span / 2, max]) {
    svg.append(ns("line", {
      x1: padL, x2: W - padR, y1: y(v), y2: y(v),
      stroke: "var(--line)", "stroke-width": 1,
    }));
    svg.append(ns("text", {
      x: padL - 6, y: y(v) + 3.5, "text-anchor": "end",
      "font-size": 9.5, fill: "var(--ink-faint)",
      "font-family": "IBM Plex Mono, monospace",
    }, Math.round(v).toString()));
  }
  rows.forEach((row, i) => {
    const cx = padL + (plotW / rows.length) * (i + 0.5);
    const top = y(Math.max(0, row.win));
    const bottom = y(Math.min(0, row.win));
    svg.append(ns("rect", {
      x: cx - bw / 2, y: top, width: bw, height: Math.max(1.5, bottom - top),
      rx: 3, fill: row.win > 0 ? "var(--accent)" : "var(--bad)",
    }));
    svg.append(ns("text", {
      x: cx, y: H - 8, "text-anchor": "middle", "font-size": 9.5,
      fill: "var(--ink-faint)", "font-family": "IBM Plex Mono, monospace",
    }, Math.round(row.frac * 100) + "%"));
  });
  return svg;
}

function warningsPanel(warnings) {
  const panel = el("section", "panel");
  const head = el("header");
  head.append(el("h2", null, "Worth knowing"));
  panel.append(head);
  const pad = el("div", "pad");
  const ul = el("ul", "warn-list");
  for (const w of warnings) ul.append(el("li", null, w));
  pad.append(ul);
  panel.append(pad);
  return panel;
}

// --- strategy chart -------------------------------------------------------

const SYM = { hit: "H", stand: "S", double: "D", split: "P", surrender: "R" };
// Explicit, not built by string concatenation: a token name assembled at
// runtime cannot be checked, and one typo renders a swatch with no colour.
const ACTION_SWATCH = {
  hit: "var(--act-hit)", stand: "var(--act-stand)", double: "var(--act-double)",
  split: "var(--act-split)", surrender: "var(--act-sur)",
};

function renderChart(canvas) {
  const r = state.rules;
  const key = JSON.stringify(r);
  const panel = el("section", "panel");
  const head = el("header");
  head.append(el("h2", null, "Basic strategy, computed for these rules"));
  head.append(el("span", "note", "not a lookup — every cell is an exact EV comparison"));
  panel.append(head);
  const body = el("div", "pad");
  panel.append(body);
  canvas.append(panel);

  if (state.chart && state.chartKey === key) {
    drawChart(body, state.chart, r);
    return;
  }
  const busy = el("div", "busy", "Computing 340 cells…");
  const bar = el("div", "bar");
  const fill = el("i");
  bar.append(fill);
  busy.append(bar);
  body.append(busy);

  // Yield between groups so the progress bar actually paints on a phone.
  (async () => {
    const cells = [];
    const groups = ["hard", "soft", "pair"];
    let done = 0;
    for (const g of groups) {
      await new Promise((res) => setTimeout(res, 0));
      const part = basicStrategy(r).filter((c) => c.category === g);
      cells.push(...part);
      done += 1;
      fill.style.width = `${(done / groups.length) * 100}%`;
    }
    state.chart = dedupe(cells);
    state.chartKey = key;
    body.replaceChildren();
    drawChart(body, state.chart, r);
  })();
}

// basicStrategy is called once per group above for progress; keep the first
// occurrence of each cell so a repeat call cannot double the rows.
function dedupe(cells) {
  const seen = new Set();
  const out = [];
  for (const c of cells) {
    const k = `${c.category}|${c.label}|${c.upcard}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(c);
  }
  return out;
}

function drawChart(body, cells, r) {
  const groups = [["hard", "Hard totals"], ["soft", "Soft totals"], ["pair", "Pairs"]];
  for (const [cat, title] of groups) {
    const rows = new Map();
    for (const c of cells) {
      if (c.category !== cat) continue;
      if (!rows.has(c.label)) rows.set(c.label, new Map());
      rows.get(c.label).set(c.upcard, c);
    }
    const h = el("h3", null, title);
    h.style.cssText = "font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-faint);margin:14px 0 7px";
    body.append(h);
    const wrap = el("div", "scroll");
    const t = el("table", "chart-grid");
    const thead = el("thead");
    const hr = el("tr");
    hr.append(el("th"));
    for (const u of [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) hr.append(el("th", null, RANK_NAMES[u]));
    thead.append(hr);
    t.append(thead);
    const tb = el("tbody");
    for (const [label, byUp] of rows) {
      const tr = el("tr");
      tr.append(el("td", "rl", label));
      for (const u of [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) {
        const c = byUp.get(u);
        const td = el("td");
        const span = el("span", "cell " + c.action + (c.close ? " close" : ""), SYM[c.action]);
        span.title = `${label} vs ${RANK_NAMES[u]}: ${c.action} (EV ${c.ev.toFixed(4)}${c.close ? ", close call" : ""})`;
        td.append(span);
        tr.append(td);
      }
      tb.append(tr);
    }
    t.append(tb);
    wrap.append(t);
    body.append(wrap);
  }
  const legend = el("div", "legend");
  for (const [k, label] of [["hit", "Hit"], ["stand", "Stand"], ["double", "Double"],
    ["split", "Split"], ["surrender", "Surrender"]]) {
    const s = el("span");
    const i = el("i");
    i.style.background = ACTION_SWATCH[k];
    s.append(i, document.createTextNode(label));
    legend.append(s);
  }
  const dot = el("span", null, "· a dot marks a cell decided by less than 0.01 in EV");
  dot.style.color = "var(--ink-faint)";
  legend.append(dot);
  body.append(legend);
}

// --- boot -----------------------------------------------------------------

function initTheme() {
  const btn = $("#theme");
  const stored = (() => { try { return localStorage.getItem("rr-theme"); } catch { return null; } })();
  if (stored) document.documentElement.setAttribute("data-theme", stored);
  btn.addEventListener("click", () => {
    const now = document.documentElement.getAttribute("data-theme");
    const isDark = now === "dark" ||
      (!now && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("rr-theme", next); } catch { /* private mode */ }
  });
}

// The controls panel is a disclosure so a phone leads with results, but on a
// wide screen it is the left rail and should simply be open.
function initRail() {
  const rail = $("#rail");
  const wide = window.matchMedia("(min-width: 980px)");
  const sync = () => { if (wide.matches) rail.open = true; };
  sync();
  wide.addEventListener("change", sync);
}

// Offline support, where the host provides it. The artifact build is served as
// a lone file with no sibling sw.js, so registration simply fails there and the
// app carries on -- everything it needs is already inline.
function initOffline() {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {
      /* no service worker here; the page works regardless */
    });
  });
}

initTheme();
initOffline();
initRail();
buildRail();
render();

// ==========================================================================
// Drill
// ==========================================================================

const DRILL_STORE = "rr-drill-settings-v1";
const ACTION_KEYS = [
  ["hit", "Hit", "H"], ["stand", "Stand", "S"], ["double", "Double", "D"],
  ["split", "Split", "P"], ["surrender", "Surrender", "R"],
];

function loadDrillSettings() {
  const base = { kinds: ["count", "truecount", "strategy"], speed: 2, cards: 12, rounds: 20 };
  try {
    const raw = localStorage.getItem(DRILL_STORE);
    if (!raw) return base;
    const saved = JSON.parse(raw);
    const kinds = Array.isArray(saved.kinds)
      ? saved.kinds.filter((k) => KINDS.includes(k)) : base.kinds;
    return { ...base, ...saved, kinds: kinds.length ? kinds : base.kinds };
  } catch { return base; }
}

function saveDrillSettings(s) {
  try {
    localStorage.setItem(DRILL_STORE, JSON.stringify({
      kinds: s.kinds, speed: s.speed, cards: s.cards, rounds: s.rounds,
    }));
  } catch { /* private window; settings just will not persist */ }
}

function drillState() {
  if (!state.drill) {
    const saved = loadDrillSettings();
    state.drill = {
      phase: "setup", ...saved,
      progress: loadProgress(),
      index: 0, correct: 0, question: null, input: "",
      askedAt: 0, lastMs: 0, wasRight: null,
      chart: null, chartKey: null,
      devs: null, devsKey: null, devsProgress: 0,
      timer: null,
    };
  }
  return state.drill;
}

const rulesKey = (r) => JSON.stringify([
  r.decks, r.dealerHitsSoft17, r.doubleRule, r.doubleAfterSplit, r.resplitAces,
  r.maxSplitHands, r.surrender, r.holeCard, r.blackjackPayout,
]);

function stopDrillTimers() {
  const d = state.drill;
  if (d && d.timer) { clearTimeout(d.timer); d.timer = null; }
}

function renderDrill(canvas) {
  const d = drillState();
  const panel = el("section", "panel");
  const head = el("header");
  head.append(el("h2", null, "Drill"));
  head.append(el("span", "note", "questions generated from the chart for these exact rules"));
  panel.append(head);
  const body = el("div", "pad");
  panel.append(body);
  canvas.append(panel);

  if (d.phase === "setup") drawSetup(body, d);
  else if (d.phase === "preparing") drawPreparing(body, d);
  else if (d.phase === "done") drawDone(body, d);
  else drawStage(body, d);
}

function drawSetup(body, d) {
  const wrap = el("div", "drill-setup");

  const kindsBlock = el("div");
  kindsBlock.append(labelled("What to practise"));
  const chips = el("div", "chips");
  for (const kind of KINDS) {
    const b = el("button", null, KIND_LABELS[kind]);
    b.type = "button";
    b.setAttribute("aria-pressed", String(d.kinds.includes(kind)));
    if (kind === "bet" && state.bankroll <= 0) b.disabled = true;
    b.addEventListener("click", () => {
      d.kinds = d.kinds.includes(kind)
        ? d.kinds.filter((k) => k !== kind)
        : [...d.kinds, kind];
      if (!d.kinds.length) d.kinds = [kind];
      saveDrillSettings(d);
      render();
    });
    chips.append(b);
  }
  kindsBlock.append(chips);
  if (d.kinds.includes("deviation")) {
    const n = el("p", null,
      "Index plays need a one-off scan of every cell for these rules — about "
      + "half a minute the first time, then remembered.");
    n.style.cssText = "font-size:12px;color:var(--ink-faint);margin:7px 0 0;max-width:52ch";
    kindsBlock.append(n);
  }
  wrap.append(kindsBlock);

  if (d.kinds.includes("count")) {
    const speed = el("div");
    speed.append(labelled("Card speed"));
    const chips2 = el("div", "chips");
    for (const [v, label] of [[1, "1/sec"], [1.5, "1.5/sec"], [2, "2/sec"], [3, "3/sec"], [4, "4/sec"]]) {
      const b = el("button", null, label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(d.speed === v));
      b.addEventListener("click", () => { d.speed = v; saveDrillSettings(d); render(); });
      chips2.append(b);
    }
    speed.append(chips2);
    const cards = el("div");
    cards.style.marginTop = "12px";
    cards.append(labelled("Cards per round"));
    const chips3 = el("div", "chips");
    for (const v of [6, 12, 20, 30, 52]) {
      const b = el("button", null, String(v));
      b.type = "button";
      b.setAttribute("aria-pressed", String(d.cards === v));
      b.addEventListener("click", () => { d.cards = v; saveDrillSettings(d); render(); });
      chips3.append(b);
    }
    cards.append(chips3);
    speed.append(cards);
    wrap.append(speed);
  }

  const rounds = el("div");
  rounds.append(labelled("Questions"));
  const chips4 = el("div", "chips");
  for (const v of [10, 20, 40, 100]) {
    const b = el("button", null, String(v));
    b.type = "button";
    b.setAttribute("aria-pressed", String(d.rounds === v));
    b.addEventListener("click", () => { d.rounds = v; saveDrillSettings(d); render(); });
    chips4.append(b);
  }
  rounds.append(chips4);
  wrap.append(rounds);

  const row = el("div", "btn-row");
  const go = el("button", "btn", "Start drilling");
  go.type = "button";
  go.addEventListener("click", () => startDrill(d));
  row.append(go);
  const sum = d.progress.summary();
  if (sum.answered) {
    const reset = el("button", "btn ghost", "Erase history");
    reset.type = "button";
    reset.addEventListener("click", () => {
      clearProgress();
      d.progress = new Progress();
      render();
    });
    row.append(reset);
  }
  wrap.append(row);

  if (sum.answered) wrap.append(progressBlock(d));
  else {
    const p = el("p", null,
      "Nothing drilled yet. Misses come back most often, then slow answers — "
      + "so the questions follow your weak spots rather than a fixed order.");
    p.style.cssText = "font-size:12.5px;color:var(--ink-faint);max-width:56ch;margin:0";
    wrap.append(p);
  }
  body.append(wrap);
}

function labelled(text) {
  const h = el("h3", null, text);
  h.style.cssText = "font-size:11px;letter-spacing:.09em;text-transform:uppercase;"
    + "color:var(--ink-faint);font-weight:600;margin:0 0 8px";
  return h;
}

function progressBlock(d) {
  const wrap = el("div");
  const sum = d.progress.summary();
  wrap.append(labelled("Your history"));
  const line = el("div", "scoreline");
  line.innerHTML = `<span><b>${Math.round(sum.accuracy * 100)}%</b> correct</span>
    <span><b>${sum.answered}</b> answered</span>
    <span><b>${sum.meanSeconds.toFixed(1)}s</b> average</span>`;
  wrap.append(line);

  const byKind = d.progress.byKind();
  const grid = el("div", "kind-stats");
  grid.style.marginTop = "11px";
  for (const kind of KINDS) {
    const s = byKind[kind];
    if (!s || !s.seen) continue;
    const t = el("div", "kind-stat");
    t.append(el("div", "k", KIND_LABELS[kind]));
    t.append(el("div", "v", Math.round((s.correct / s.seen) * 100) + "%"));
    t.append(el("div", "n", `${s.seen} asked · ${(s.totalMs / s.seen / 1000).toFixed(1)}s each`));
    grid.append(t);
  }
  if (grid.children.length) wrap.append(grid);

  const weak = d.progress.weakest(6);
  if (weak.length) {
    const h = labelled("Coming up most often");
    h.style.marginTop = "16px";
    wrap.append(h);
    const ul = el("ul", "warn-list");
    for (const [key, s] of weak) {
      const li = el("li", null,
        `${prettyItem(key)} — ${Math.round((s.correct / s.seen) * 100)}% over ${s.seen}, `
        + `${(s.totalMs / s.seen / 1000).toFixed(1)}s each`);
      ul.append(li);
    }
    wrap.append(ul);
  }
  return wrap;
}

function prettyItem(key) {
  const [kind, rest] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
  if (kind === "count") return `Running count over ${rest} cards`;
  if (kind === "truecount") return `True count with ${rest} decks left`;
  if (kind === "bet") return `Bet at true count ${signed(Number(rest))}`;
  const [category, label, up] = rest.split("|");
  const hand = category === "hard" ? `Hard ${label}` : label;
  return `${hand} vs ${up}${kind === "deviation" ? " (index)" : ""}`;
}

// --- material -------------------------------------------------------------

async function startDrill(d) {
  const r = state.rules;
  const key = rulesKey(r);
  const needsChart = d.kinds.includes("strategy") || d.kinds.includes("deviation");
  const needsDevs = d.kinds.includes("deviation");

  if ((needsChart && d.chartKey !== key) || (needsDevs && d.devsKey !== key)) {
    d.phase = "preparing";
    d.devsProgress = 0;
    render();
    await new Promise((res) => setTimeout(res, 30));

    if (needsChart && d.chartKey !== key) {
      d.chart = chartLookup(basicStrategy(r));
      d.chartKey = key;
    }
    if (needsDevs && d.devsKey !== key) {
      const cached = readCachedDevs(key);
      d.devs = cached || await scanDeviations(r, (frac) => {
        d.devsProgress = frac;
        const bar = document.getElementById("prepBar");
        if (bar) bar.style.width = `${Math.round(frac * 100)}%`;
      });
      if (!cached) writeCachedDevs(key, d.devs);
      d.devsKey = key;
    }
  }

  d.index = 0;
  d.correct = 0;
  d.times = [];
  nextQuestion(d);
}

function readCachedDevs(key) {
  try {
    const raw = localStorage.getItem("rr-devs-" + hash(key));
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function writeCachedDevs(key, devs) {
  try { localStorage.setItem("rr-devs-" + hash(key), JSON.stringify(devs)); }
  catch { /* quota or private window; it will just be recomputed next time */ }
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(36);
}

// Scans every cell for an index, one row at a time so the progress bar
// actually paints. Ranked by value at this penetration, so the drill asks about
// the indices worth money rather than the seventy that exist.
async function scanDeviations(r, onProgress) {
  const dist = ensureDist();
  const rows = [
    ...hardLabels().map((l) => ["hard", cardsForHard(Number(l)), l]),
    ...softLabels().map((l) => ["soft", cardsForSoft(11 + Number(l.split(",")[1])), l]),
    ...pairLabels().map((l) => ["pair", cardsForPair(pairRank(l)), l]),
  ];
  const found = [];
  for (let i = 0; i < rows.length; i++) {
    await new Promise((res) => setTimeout(res, 0));
    const [category, cards, label] = rows[i];
    for (const up of UPCARDS) {
      const d = findDeviation(category, cards, label, up, r, [-6, 8]);
      if (d) found.push(d);
    }
    // Leave the last slice of the bar for ranking, which is not free either.
    onProgress(((i + 1) / rows.length) * 0.9);
  }

  await new Promise((res) => setTimeout(res, 0));
  const probs = {};
  for (const tc of counts(dist)) probs[tc] = dist.probs[tc];
  const ranked = rankDeviations(r, probs, found);
  onProgress(1);
  return ranked.filter((x) => x.value > 0).slice(0, 20).map((x) => x.deviation);
}

const pairRank = (label) => {
  const left = label.split(",")[0];
  return left === "A" ? 9 : left === "T" ? 8 : Number(left) - 2;
};

const hardLabels = () => Array.from({ length: 16 }, (_, i) => String(i + 5));
const softLabels = () => Array.from({ length: 8 }, (_, i) => `A,${i + 2}`);
const pairLabels = () =>
  ["2,2", "3,3", "4,4", "5,5", "6,6", "7,7", "8,8", "9,9", "T,T", "A,A"];

function drawPreparing(body, d) {
  const stage = el("div", "stage");
  stage.append(el("div", "prompt", "Working out the index plays"));
  stage.append(el("div", "sub-prompt",
    "Every cell, at every count, for these rules. Done once, then remembered."));
  const bar = el("div", "bar");
  const fill = el("i");
  fill.id = "prepBar";
  fill.style.width = `${Math.round(d.devsProgress * 100)}%`;
  bar.append(fill);
  bar.style.maxWidth = "260px";
  bar.style.width = "100%";
  stage.append(bar);
  body.append(stage);
}

// --- asking ---------------------------------------------------------------

function nextQuestion(d) {
  const r = state.rules;
  if (d.index >= d.rounds) {
    d.phase = "done";
    saveProgress(d.progress);
    render();
    return;
  }
  const available = d.kinds.filter((k) => {
    if (k === "deviation") return d.devs && d.devs.length;
    if (k === "bet") return state.bankroll > 0;
    return true;
  });
  const kind = pickKind(available.length ? available : ["count"], d.progress);

  if (kind === "count") {
    d.question = countQuestion(r, d.cards);
    d.phase = "flashing";
    d.flashIndex = -1;
    d.input = "";
    render();
    flashNext(d);
    return;
  }
  if (kind === "truecount") d.question = trueCountQuestion(r);
  else if (kind === "strategy") d.question = strategyQuestion(Object.keys(d.chart),
    Object.fromEntries(Object.entries(d.chart).map(([k, v]) => [k, v.action])), d.progress);
  else if (kind === "deviation") d.question = deviationQuestion(d.devs, d.progress);
  else d.question = betQuestion(r, currentRampBets(), d.progress);

  d.phase = "asking";
  d.input = "";
  d.askedAt = performance.now();
  render();
}

function currentRampBets() {
  const dist = ensureDist();
  const ramp = kellyRamp(state.rules, dist, {
    bankroll: state.bankroll, kellyFraction: state.kelly,
    maxSpread: state.maxSpread, wongOutBelow: state.wong,
  });
  const out = {};
  for (const tc of counts(dist)) {
    if ((dist.probs[tc] || 0) >= 0.005) out[tc] = ramp.bet(tc);
  }
  return Object.keys(out).length ? out : { 0: state.rules.tableMin };
}

function flashNext(d) {
  stopDrillTimers();
  d.flashIndex += 1;
  if (d.flashIndex >= d.question.cards.length) {
    d.phase = "asking";
    d.askedAt = performance.now();
    render();
    return;
  }
  render();
  d.timer = setTimeout(() => flashNext(d), 1000 / d.speed);
}

function drawStage(body, d) {
  const q = d.question;
  const stage = el("div", "stage");

  const meta = el("div", "meta");
  meta.append(el("span", null, `${Math.min(d.index + 1, d.rounds)} / ${d.rounds}`));
  meta.append(el("span", null, `${d.correct} right`));
  meta.append(el("span", null, KIND_LABELS[q.kind]));
  stage.append(meta);

  if (d.phase === "flashing") {
    const card = el("div", "flashcard");
    card.textContent = q.faces[d.flashIndex] ?? "";
    stage.append(card);
    const dealt = el("div", "dealt");
    for (let i = 0; i < d.flashIndex; i++) dealt.append(el("span", null, q.faces[i]));
    stage.append(dealt);
    const skip = el("button", "btn ghost", "Skip to the answer");
    skip.type = "button";
    skip.addEventListener("click", () => {
      stopDrillTimers();
      d.flashIndex = q.cards.length;
      flashNext(d);
    });
    stage.append(skip);
  } else if (d.phase === "asking") {
    stage.append(questionPrompt(q));
    if (q.kind === "strategy" || q.kind === "deviation") stage.append(actionPad(d));
    else stage.append(entryDisplay(d), keypad(d));
  } else if (d.phase === "feedback") {
    stage.append(feedbackBlock(d));
    const go = el("button", "btn", d.index >= d.rounds ? "See results" : "Next");
    go.type = "button";
    go.addEventListener("click", () => nextQuestion(d));
    stage.append(go);
  }

  body.append(stage);
  const track = el("div", "progress-track");
  const fill = el("i");
  fill.style.width = `${(d.index / d.rounds) * 100}%`;
  track.append(fill);
  body.append(track);

  const row = el("div", "btn-row");
  row.style.marginTop = "12px";
  const stop = el("button", "btn ghost", "Stop");
  stop.type = "button";
  stop.addEventListener("click", () => {
    stopDrillTimers();
    saveProgress(d.progress);
    d.phase = d.index > 0 ? "done" : "setup";
    render();
  });
  row.append(stop);
  body.append(row);
}

function questionPrompt(q) {
  const wrap = el("div");
  wrap.style.cssText = "display:flex;flex-direction:column;gap:6px;align-items:center";
  if (q.kind === "count") {
    wrap.append(el("div", "prompt", "Running count?"));
  } else if (q.kind === "truecount") {
    const p = el("div", "prompt");
    p.innerHTML = `Running count <span class="up">${signed(q.runningCount)}</span>,
      about ${q.decksRemaining} decks left`;
    wrap.append(p, el("div", "sub-prompt", "True count?"));
  } else if (q.kind === "bet") {
    const p = el("div", "prompt");
    p.innerHTML = `True count <span class="up">${signed(q.trueCount)}</span>`;
    wrap.append(p, el("div", "sub-prompt", `What do you bet, in ${state.rules.currency}?`));
  } else {
    const p = el("div", "prompt");
    p.innerHTML = `${q.hand} vs <span class="up">${q.upcard}</span>`;
    wrap.append(p);
    wrap.append(el("div", "sub-prompt",
      q.kind === "deviation" ? `at true count ${signed(q.trueCount)}` : "what is the play?"));
  }
  return wrap;
}

function entryDisplay(d) {
  const e = el("div", "entry" + (d.input ? "" : " empty"), d.input || "—");
  e.id = "entry";
  return e;
}

function keypad(d) {
  const pad = el("div", "keypad");
  const press = (ch) => {
    if (ch === "back") d.input = d.input.slice(0, -1);
    else if (ch === "sign") {
      d.input = d.input.startsWith("-") ? d.input.slice(1) : "-" + d.input;
    } else if (d.input.replace("-", "").length < 6) d.input += ch;
    const e = document.getElementById("entry");
    if (e) {
      e.textContent = d.input || "—";
      e.className = "entry" + (d.input ? "" : " empty");
    }
  };
  for (const ch of ["1", "2", "3", "4", "5", "6", "7", "8", "9"]) {
    const b = el("button", null, ch);
    b.type = "button";
    b.addEventListener("click", () => press(ch));
    pad.append(b);
  }
  const neg = el("button", null, "±");
  neg.type = "button";
  neg.addEventListener("click", () => press("sign"));
  const zero = el("button", null, "0");
  zero.type = "button";
  zero.addEventListener("click", () => press("0"));
  const back = el("button", null, "⌫");
  back.type = "button";
  back.addEventListener("click", () => press("back"));
  pad.append(neg, zero, back);
  const go = el("button", "go wide", "Answer");
  go.type = "button";
  go.addEventListener("click", () => submit(d, d.input));
  pad.append(go);
  return pad;
}

function actionPad(d) {
  const pad = el("div", "actions");
  for (const [value, label, letter] of ACTION_KEYS) {
    const b = el("button");
    b.type = "button";
    b.append(document.createTextNode(label));
    b.append(el("small", null, letter));
    b.addEventListener("click", () => submit(d, value));
    pad.append(b);
  }
  return pad;
}

function submit(d, response) {
  if (d.phase !== "asking") return;
  const ms = performance.now() - d.askedAt;
  const right = checkAnswer(d.question, response);
  d.progress.record(d.question.itemKey, right, ms);
  d.lastMs = ms;
  d.wasRight = right;
  d.given = response;
  d.correct += right ? 1 : 0;
  d.index += 1;
  d.times.push(ms);
  d.phase = "feedback";
  saveProgress(d.progress);
  render();
}

function feedbackBlock(d) {
  const q = d.question;
  const wrap = el("div", "feedback " + (d.wasRight ? "right" : "wrong"));
  wrap.append(el("div", "verdict-word", d.wasRight ? "Correct" : "No"));
  const truth = q.kind === "strategy" || q.kind === "deviation"
    ? q.answer
    : q.kind === "truecount" ? q.answer.toFixed(2)
      : q.kind === "bet" ? money(q.answer, state.rules) : signed(q.answer);
  wrap.append(el("div", "truth", truth));
  if (!d.wasRight) wrap.append(el("div", "why", q.explain));
  const clock = el("div", "clock", `${(d.lastMs / 1000).toFixed(1)}s`);
  if (q.kind === "count") {
    clock.textContent += ` · ${(q.cards.length / (d.lastMs / 1000 + q.cards.length / d.speed)).toFixed(1)} cards/sec including the deal`;
  }
  wrap.append(clock);
  return wrap;
}

function drawDone(body, d) {
  const stage = el("div", "stage");
  const pctRight = d.index ? d.correct / d.index : 0;
  stage.append(el("div", "prompt",
    pctRight >= 0.9 ? "Sharp." : pctRight >= 0.7 ? "Getting there." : "Worth another round."));
  const line = el("div", "scoreline");
  const mean = d.times.length ? d.times.reduce((a, b) => a + b, 0) / d.times.length / 1000 : 0;
  line.innerHTML = `<span><b>${d.correct}/${d.index}</b> correct</span>
    <span><b>${Math.round(pctRight * 100)}%</b></span>
    <span><b>${mean.toFixed(1)}s</b> average</span>`;
  stage.append(line);
  const row = el("div", "btn-row");
  const again = el("button", "btn", "Go again");
  again.type = "button";
  again.addEventListener("click", () => startDrill(d));
  const back = el("button", "btn ghost", "Change what you drill");
  back.type = "button";
  back.addEventListener("click", () => { d.phase = "setup"; render(); });
  row.append(again, back);
  stage.append(row);
  body.append(stage);
  body.append(progressBlock(d));
}
