const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web/market_mode.html"), "utf8");
function source(name, next) {
  return html.slice(html.indexOf(`      function ${name}(`), html.indexOf(`      function ${next}(`));
}
const data = name => JSON.parse(fs.readFileSync(path.join(root, `outputs/${name}.json`), "utf8").replace(/^\uFEFF/, ""));
const signal = {date: "2026-09-08", score: 81};
const review = {data_as_of: "2026-09-11", market: {limit_up: 40, limit_down: 0, max_boards: 4}};
const factor = {data_as_of: "2026-09-11", market: {score: 69.1}};
const industry = {data_as_of: "2026-09-11", rows: []};
const health = {modules: ["short", "industry", "etf"].map(key => ({key, state: "current", data_as_of: "2026-09-11"}))};
const context = vm.createContext({
  window: {}, FALLBACK: {},
  num: (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback,
  clamp: (value, min, max) => Math.min(max, Math.max(min, value)),
  $: () => ({classList: {add() {}, remove() {}}}),
  render: snapshot => { context.rendered = snapshot; },
});
vm.runInContext(source("buildShortView", "formatGeneratedAt"), context);
vm.runInContext(source("loadLocal", "hydrateFileFallback"), context);
vm.runInContext(html.slice(html.indexOf("      function hydrateFileFallback("), html.indexOf('      $("refresh").addEventListener')), context);

function freshness(short, dates = {}) {
  return context.dataFreshness({asOf: "2026-09-11", dataDates: {short: short.data_as_of, industry: industry.data_as_of, etf: "2026-09-11", ...dates}, dashboardStatus: health});
}
const close = context.buildShortView(signal, review, factor);
assert.equal(close.basis, "close");
assert.equal(close.data_as_of, review.data_as_of);
assert.equal(close.score, 69.1);
assert.equal(close.auctionPoints, null, "Close data must not stand in for auction evidence");
assert.equal(freshness(close).blocked, false);
const oldAuction = context.buildShortView(signal, null, factor);
assert.equal(oldAuction.basis, "auction");
assert.equal(freshness(oldAuction).blocked, true, "Stale auction remains blocked without newer review");
const currentAuction = context.buildShortView({...signal, date: review.data_as_of}, review, factor);
assert.equal(currentAuction.basis, "auction", "Do not change existing same-day source selection");
assert.equal(freshness(currentAuction).blocked, false);
assert.equal(freshness(close, {industry: "2026-09-10"}).blocked, true);
assert.equal(freshness(close, {etf: ""}).missing[0], "etf");
assert.equal(freshness(context.buildShortView(null, null, null)).blocked, true);

async function load(values) {
  context.fetchJson = file => Promise.resolve(values[path.basename(file, ".json")]);
  context.fetchCsv = () => Promise.resolve([]);
  await context.loadLocal();
  assert.ok(context.rendered);
  return context.rendered;
}
(async () => {
  const files = {shortterm_signal: signal, latest_market_review: review, shortterm_factor_preview: factor, industry_flow_latest: industry, dashboard_status: health};
  const live = await load(files);
  assert.equal(live.dataDates.short, "2026-09-11");
  assert.equal(context.dataFreshness(live).blocked, false);
  Object.assign(context.window, {SHORT_SIGNAL: signal, LATEST_MARKET_REVIEW: review, SHORT_FACTOR_PREVIEW: factor, INDUSTRY_FLOW: industry, DASHBOARD_STATUS: health});
  context.hydrateFileFallback();
  assert.equal(context.FALLBACK.dataDates.short, live.dataDates.short);
  assert.equal(context.dataFreshness(context.FALLBACK).blocked, false);
  context.window.DASHBOARD_STATUS = null;
  context.hydrateFileFallback();
  assert.equal(context.FALLBACK.dataDates.etf, "", "Missing dates must not be filled with the reference date");
  const missing = await load({...files, dashboard_status: null});
  assert.equal(context.dataFreshness(missing).blocked, true);

  const actual = Object.fromEntries(Object.keys(files).map(key => [key, data(key)]));
  const actualSnapshot = await load(actual);
  assert.equal(actualSnapshot.dataDates.short, actualSnapshot.short.data_as_of);
  console.log("Actual snapshot:", actualSnapshot.asOf, actualSnapshot.short.basis, context.dataFreshness(actualSnapshot));
  console.log("market freshness tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
