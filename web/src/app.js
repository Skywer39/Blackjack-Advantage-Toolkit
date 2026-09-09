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
import { basicStrategy, insuranceIndex } from "./engine/strategy.js";
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
  else renderChart(canvas);
}

function tabs() {
  const wrap = el("section", "panel");
  const bar = el("div", "tabs");
  for (const [key, label] of [["betting", "Bankroll & ramp"], ["chart", "Strategy chart"]]) {
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
    i.style.background = `var(--act-${k === "surrender" ? "sur" : k})`;
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

initTheme();
initRail();
buildRail();
render();
