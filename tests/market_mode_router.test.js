const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web/market_mode.html"), "utf8");
const calendarSource = fs.readFileSync(path.join(root, "web/trading_calendar.js"), "utf8");
const hubCss = fs.readFileSync(path.join(root, "web/dashboard_hub.css"), "utf8");

function between(start, end) {
  const from = html.indexOf(start), to = html.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing source range ${start} -> ${end}`);
  return html.slice(from, to);
}

// 交易日历：节假日、周末与未覆盖年份。
const calendarScope = {};
vm.runInNewContext(calendarSource, {globalThis: calendarScope, window: undefined});
const calendar = calendarScope.TRADING_CALENDAR;
assert.equal(calendar.nextTradingDay("2026-09-30").date, "2026-10-08", "National Day closure must be skipped");
assert.equal(calendar.nextTradingDay("2026-09-24").date, "2026-09-28", "Mid-Autumn Friday closure must be skipped");
assert.equal(calendar.nextTradingDay("2026-02-13").date, "2026-02-24", "Spring Festival closure must be skipped");
assert.equal(calendar.isTradingDay("2026-10-08"), true);
assert.equal(calendar.nextTradingDay("2026-12-31").covered, false, "Uncovered years must be flagged");
assert.equal(calendar.isTradingDay("invalid"), false);
assert.equal(calendar.isTradingDay("2026-02-30"), false);
assert.equal(calendar.nextTradingDay("2026-02-30").date, "");

const context = vm.createContext({
  window: {TRADING_CALENDAR: calendar},
  num: (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback,
  clamp: (value, min, max) => Math.min(max, Math.max(min, value)),
  escapeHtml: value => String(value == null ? "" : value),
});
vm.runInContext(between("      function nextTradingDay(", "      function shanghaiNow("), context);
assert.equal(context.nextTradingDay("2026-09-30"), "2026-10-08");
assert.equal(context.nextTradingDay("2026-12-31"), "", "The page must not publish an unverified next-session date");
vm.runInContext(between("      var MODE_META = {", "      var state = {"), context);
vm.runInContext(between("      function themeKey(", "      function buildShortView("), context);
vm.runInContext(between("      function buildShortView(", "      function formatGeneratedAt("), context);
vm.runInContext(between("      function analyze(", "      function renderList("), context);
vm.runInContext(between("      function valueOrNull(", "      function renderStyleFactors("), context);
vm.runInContext(between("      function renderSwitchGrid(", "      function renderDailyReview("), context);

// 主模式：门控通过后按固定优先级 共振 > 短线 > 趋势 > ETF，不比较不同公式的分数。
const shortReady = {score: 76, available: true, allowResearch: true, limitDown: 0, leaderTheme: "医药"};
const base = {short: shortReady, industry: {name: "半导体", share: 1, breadth: 1, ratio: 1}, etf: {mode: "attack", pickTheme: "黄金", hotTheme: "通信", pickScore: 0.99}};
context.window.TrendEngine = {analyze: () => ({score: 100, historyAvailable: true, status: "ready", blockers: []})};
assert.equal(context.analyze(base).mode, "short", "Short-term outranks trend and ETF even when their scores are higher");
assert.equal(context.analyze({...base, short: {...shortReady, score: 60}}).mode, "trend", "Trend outranks ETF regardless of score");
assert.equal(context.analyze({...base, short: {...shortReady, score: 60}}).secondary, "etf");
const aligned = {...base, short: {...shortReady, leaderTheme: "半导体"}, etf: {...base.etf, hotTheme: "半导体"}};
assert.equal(context.analyze(aligned).mode, "resonance");
context.window.TrendEngine = {analyze: () => ({score: 100, historyAvailable: true, status: "blocked", blockers: ["breadth"]})};
assert.equal(context.analyze({...base, short: {...shortReady, score: 60}}).mode, "etf");
assert.deepEqual(Array.from(context.analyze(base).priority), ["resonance", "short", "trend", "etf", "defense"]);
delete context.window.TrendEngine;

// 收盘复盘缺字段时保留 null，不能显示成真实的 0。
const incomplete = context.buildShortView({date: "2026-09-29"}, {data_as_of: "2026-09-29", market: {limit_up: 0, limit_down: 10, failed_rate: null, max_boards: 0}, previous_limit_up_feedback: {avg_return: 2.6, positive_ratio: 0.58}}, null);
assert.equal(incomplete.failedRate, null);
assert.equal(incomplete.score, null);
assert.equal(incomplete.available, false);
const completeReview = {data_as_of: "2026-09-30", market: {limit_up: 60, limit_down: 0, failed_rate: 0.1, max_boards: 5}, previous_limit_up_feedback: {avg_return: 2, positive_ratio: 0.7}};
const calculated = context.buildShortView(null, completeReview, null);
assert.equal(context.buildShortView(null, completeReview, {data_as_of: "2026-09-30", market: {score: null}}).score, calculated.score, "A missing factor score must not override the computed score with zero");
const failedReview = {...completeReview, market_evidence: {complete: false}};
const sameDaySignal = {date: "2026-09-30", status: "ok", score: 81};
assert.equal(context.buildShortView(sameDaySignal, failedReview, null).basis, "auction", "Failed same-day review must not replace a valid auction signal");
assert.equal(context.buildShortView(null, failedReview, null).available, false, "An explicit failure is authoritative even when numeric fields exist");
assert.equal(context.buildShortView({date: "2026-09-30", status: "error", score: 81}, failedReview, null).available, false);
const missingSignal = context.buildShortView({date: "2026-09-30"}, null, null);
assert.equal(missingSignal.available, false);
assert.equal(missingSignal.score, null);
assert.equal(missingSignal.limitUp, null, "Missing auction metrics must not be displayed as observed zeroes");

// 风格因子：全部受约束时不强行选出“研究优先”。
const stale = {data_as_of: "2026-09-29", candidates: [{final_score: 90, score: 90, total: 90, trend_score: 90, name: "x"}]};
const view = context.styleFactorState({asOf: "2026-09-30", growth: stale, dividend: stale, shortFactor: stale, trendLatest: stale, short: {}});
assert.equal(view.preferred, null);
const fresh = {...stale, data_as_of: "2026-09-30"};
assert.equal(context.styleFactorState({asOf: "2026-09-30", growth: fresh, dividend: stale, shortFactor: stale, trendLatest: stale, short: {}}).preferred.key, "growth");

// 切换区覆盖全部五种模式，并标出当前模式。
const target = {innerHTML: ""};
context.$ = () => target;
context.state = {analysis: {mode: "trend", currentAllowed: true, eligible: {trend: true}, priority: ["resonance", "short", "trend", "etf", "defense"]}};
context.renderSwitchGrid();
for (const key of Object.keys(context.MODE_META)) {
  assert.ok(target.innerHTML.includes(context.MODE_META[key].name), `switch grid missing ${key}`);
}
assert.equal((target.innerHTML.match(/class="switch-card current"/g) || []).length, 1);
assert.ok(/switch-card current"><div class="switch-card-head"><h3>趋势交易/.test(target.innerHTML));

// 页面结构与样式约束。
assert.ok(html.includes('src="./trading_calendar.js'), "Market page must load the trading calendar");
assert.ok(!/function nextWeekday\(/.test(html), "Weekday-only next-session logic must not return");
assert.ok(/\.style-card \{[^}]*color:var\(--text\)/.test(html), "Style cards are links and need an explicit text colour");
const inlineCss = html.slice(html.indexOf("<style>"), html.indexOf("</style>"));
for (const css of [inlineCss, hubCss]) {
  const tooSmall = css.match(/font-size:\s*(?:[0-9]|1[01])(?:\.\d+)?px/g) || [];
  assert.deepEqual(tooSmall, [], "Market page text must stay at or above 12px");
}
assert.ok(/\.fresh-state\.current \{ color: var\(--success/.test(hubCss), "Current data should not use the alarm/brand red");
assert.ok(/\.fresh-state\.error \{ color: var\(--danger/.test(hubCss) || /\.fresh-state\.missing,\s*\.fresh-state\.error \{ color: var\(--danger/.test(hubCss), "Failures must use the danger colour");

console.log("market mode router tests passed");
