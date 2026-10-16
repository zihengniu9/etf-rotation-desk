const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web/market_mode.html"), "utf8");
function source(name, next) {
  return html.slice(html.indexOf(`      function ${name}(`), html.indexOf(`      function ${next}(`));
}
const context = vm.createContext({
  window: {},
  num: (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback,
  clamp: (value, min, max) => Math.min(max, Math.max(min, value)),
});
vm.runInContext(source("themeKey", "buildShortView"), context);
vm.runInContext(source("analyze", "renderList"), context);

const now = new Date().toISOString();
const old = new Date(Date.now() - 30 * 3600 * 1000).toISOString();
const short = {score: 50, available: true, allowResearch: true, leaderTheme: "半导体", riskReasons: []};
const base = {short, industry: {name: "银行", share: 1, breadth: 1, ratio: 0.5}, etf: {mode: "attack", pickTheme: "黄金", hotTheme: "纳指", pickScore: 0.7}};
const news = (state, extra = {}) => ({status: "ok", generated_at: now, gate: {state, reasons: [state === "block" ? "重大利空：测试" : "测试"]}, market: {score: -1}, themes: [], items: [], sources: [], ...extra});

assert.equal(context.analyze(base).mode, "etf", "Baseline: ETF attack passes its own gate");
assert.equal(context.analyze({...base, news: null}).news.applied, false, "Missing news must not take part");

const blocked = context.analyze({...base, news: news("block")});
assert.equal(blocked.mode, "defense", "A major negative blocks every attack mode");
assert.equal(blocked.riskLabel, "高");
assert.equal(blocked.newsBlocks[0].mode, "etf");

const themed = context.analyze({...base, news: news("clear", {themes: [{theme: "黄金", aliases: ["黄金", "贵金属"], score: -3.4, alert: true}]})});
assert.equal(themed.mode, "defense", "A negative theme pauses the mode that trades that theme");
assert.match(themed.newsBlocks[0].reason, /黄金/);

const otherTheme = context.analyze({...base, news: news("clear", {themes: [{theme: "医药", aliases: ["医药"], score: -5, alert: true}]})});
assert.equal(otherTheme.mode, "etf", "Unrelated theme news must not pause ETF");

const caution = context.analyze({...base, news: news("caution")});
assert.equal(caution.mode, "etf", "Caution keeps the mode");
assert.notEqual(caution.riskLabel, context.analyze(base).riskLabel, "Caution raises the risk level");

const stale = context.analyze({...base, news: {...news("block"), generated_at: old}});
assert.equal(stale.mode, "etf", "Stale news must not block");
assert.equal(stale.news.stale, true);

const failed = context.analyze({...base, news: {...news("block"), status: "error"}});
assert.equal(failed.news.applied, false, "Failed collection must not block");
assert.equal(context.newsView({...news("block"), generated_at: new Date(Date.now() + 3600 * 1000).toISOString()}).applied, false, "Future timestamps cannot be trusted");
assert.equal(context.newsView(news("unknown")).applied, false, "Unsupported gate values cannot participate");

context.window.TrendEngine = {analyze: () => ({score: 80, historyAvailable: true, status: "ready", blockers: []})};
const aligned = {short: {...short, score: 80}, industry: {...base.industry, name: "半导体"}, etf: {...base.etf, pickTheme: "半导体", hotTheme: "半导体"}};
assert.equal(context.analyze(aligned).mode, "resonance");
assert.equal(context.analyze({...aligned, news: news("caution")}).mode, "short", "Caution cancels resonance but retains the highest eligible standalone mode");
const allBlocked = context.analyze({...aligned, news: news("block")});
assert.equal(allBlocked.mode, "defense");
assert.deepEqual(Array.from(allBlocked.newsBlocks, item => item.mode), ["short", "etf", "trend"]);
delete context.window.TrendEngine;

const defenseBase = {...base, etf: {...base.etf, mode: "defense"}};
const bullish = context.analyze({...defenseBase, news: news("clear", {market: {score: 9}, themes: [{theme: "黄金", aliases: ["黄金"], score: 6, alert: false}]})});
assert.equal(bullish.mode, "defense", "Positive news never unlocks attack");

console.log("market news tests passed");
