const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "../web");
const market = fs.readFileSync(path.join(root, "market_mode.html"), "utf8");
const contract = fs.readFileSync(path.join(root, "dashboard_contract.js"), "utf8");
const hubCss = fs.readFileSync(path.join(root, "dashboard_hub.css"), "utf8");
const redCss = fs.readFileSync(path.join(root, "red_theme.css"), "utf8");
const etfAlias = fs.readFileSync(path.join(root, "etf_rotation.html"), "utf8");

assert.ok(market.includes('id="strategy-hub"'));
assert.ok(market.includes('id="current-mode-desk"'));
assert.ok(market.includes('id="daily-review"'));
assert.ok(market.includes('id="trend-module-section" hidden'));
assert.ok(market.includes('.mode-fill { display:block;'));
assert.ok(market.includes('src="./dashboard_contract.js?v=20260831"'));
assert.ok(market.includes('href="./index.html"'));
assert.ok(market.includes('latest_market_review.json'));
assert.ok(market.includes('dividend_factor_snapshot.json'));
assert.ok(market.includes('dashboard_status.json'));
for (const fallback of ["shortterm_signal.js", "industry_flow_latest.js", "etf_local_data.js", "trend_engine_snapshot.js"]) {
  assert.ok(market.includes(fallback), `missing file fallback: ${fallback}`);
}
assert.ok(market.includes('fetchJson("../outputs/industry_flow_latest.json")'));
assert.ok(market.includes("hydrateFileFallback();"));
assert.ok(market.includes("outputs 快照 · 收盘数据"));
assert.ok(market.includes('var sig=all[0],indData=all[1],picks=all[2],ranks=all[3],hots=all[4],trendData=all[5],latestReview=all[6],dividendData=all[7],dashboardStatus=all[8]'));
assert.ok(market.includes('id="data-health-grid"'));
assert.ok(market.includes('数据覆盖与新鲜度'));
assert.ok(market.includes('复盘日期'));
assert.ok(market.includes("renderHub();"));
assert.ok(market.includes("renderCurrentDesk();"));
assert.ok(market.includes("renderDailyReview();"));
for (const key of ["trend", "growth", "dividend", "short", "industry", "etf"]) {
  assert.ok(contract.includes(`key: "${key}"`), `missing module contract: ${key}`);
}
assert.ok(hubCss.includes(".module-grid"));
assert.ok(hubCss.includes(".data-health-grid"));
assert.ok(hubCss.includes("@media (max-width: 620px)"));
assert.ok(/@media \(max-width: 1180px\)[\s\S]*?grid-template-columns: repeat\(5, minmax\(0, 1fr\)\)/.test(redCss));
assert.ok(/@media \(max-width: 700px\)[\s\S]*?grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/.test(redCss));
assert.ok(/@media \(max-width: 1180px\)[\s\S]*?overflow: visible !important/.test(redCss));
assert.ok(redCss.includes("scrollbar-width: none !important"));
for (const page of ["index.html", "market_mode.html", "industry_mainline_dashboard.html", "shortterm_dashboard.html", "trend_engine.html", "growth_factor.html", "dividend_factor.html", "shortterm_factor_preview.html", "market_overview.html"]) {
  const html = fs.readFileSync(path.join(root, page), "utf8");
  assert.ok(html.includes("red_theme.css?v=20260831-nav-grid"), `stale shared theme cache key: ${page}`);
}
assert.ok(etfAlias.includes('window.location.replace("./index.html")'));

console.log("dashboard hub tests passed");
