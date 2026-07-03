const assert = require("assert");
const fs = require("fs");
const path = require("path");
const dashboard = require("../web/app.js");

const html = fs.readFileSync(path.join(__dirname, "../web/index.html"), "utf8");
assert.ok(html.includes('class="pick-side"'));
assert.ok(html.includes('id="pick-theme"'));
assert.ok(html.includes('id="updated-at"'));
assert.ok(html.includes('id="pick-reason"'));
assert.ok(html.includes('id="rank-limit-badge"'));
assert.ok(html.includes('id="theme-limit-badge"'));
assert.ok(html.includes('id="hot-limit-badge"'));
assert.ok(
  html.indexOf("<th>评分</th>") < html.indexOf("<th>20日收益</th>") &&
    html.indexOf("<th>20日收益</th>") < html.indexOf("<th>波动</th>") &&
    html.indexOf("<th>波动</th>") < html.indexOf("<th>规模</th>"),
  "Strong ranking should show score where scale used to be and move scale to the right",
);
assert.strictEqual(html.includes('class="limit-badge">前15</span>'), false);
assert.strictEqual(html.includes('class="limit-badge">前12</span>'), false);
assert.ok(html.includes('ETF模拟组合收益曲线'));
assert.ok(html.includes('class="chart-column"'));
assert.ok(html.includes('class="chart-column"') && html.indexOf('class="curve-banner"') > html.indexOf('class="chart-column"'));
assert.ok(html.indexOf('class="curve-banner"') < html.indexOf('class="backtest-stats"'));
assert.ok(html.indexOf('class="backtest-stats"') < html.indexOf('class="chart-shell"'));
assert.ok(html.includes('./styles.css?v=20260703-trade-field-header'));
assert.strictEqual(html.includes('<h2>ETF 模拟交易</h2>'), false);
assert.strictEqual(html.includes('增强自适应 · 近一年'), false);
assert.ok(html.includes('./app.js?v=20260703-trade-field-header'));
assert.ok(html.includes('class="trade-header"'));
assert.ok(html.indexOf('class="trade-header"') < html.indexOf('id="bt-trades"'));
assert.strictEqual(html.includes('id="theme-count"'), false);
assert.strictEqual(html.includes('id="ranked-count"'), false);
assert.strictEqual(html.includes('id="top-theme"'), false);
assert.strictEqual(html.includes('id="pick-size"'), false);
assert.strictEqual(html.includes('id="pick-return"'), false);
assert.strictEqual(html.includes('id="pick-score"'), false);
assert.strictEqual(html.includes('id="pick-vol"'), false);

const csv = `code,name,theme,fund_size,score,total_return,annual_vol,latest_close
159516,国泰中证半导体材料设备主题ETF,半导体,44163729896.6748,1.327929,0.727909,0.556536,1.975
588000,华夏上证科创板50成份ETF,科创,69424258235.04,0.723163,0.336374,0.478373,2.344`;

const rows = dashboard.parseCsv(csv);
assert.strictEqual(rows.length, 2);
assert.strictEqual(rows[0].code, "159516");
assert.strictEqual(rows[0].theme, "半导体");

assert.strictEqual(dashboard.formatPercent(0.727909), "72.79%");
assert.strictEqual(dashboard.formatScore(1.327929), "1.328");
assert.strictEqual(dashboard.formatFundSize(44163729896.6748), "441.6亿");
assert.strictEqual(dashboard.formatNetValue(0.5), "0.5000");
assert.strictEqual(dashboard.formatSignedNetValue(0.125), "+0.1250");
assert.strictEqual(dashboard.formatSignedNetValue(-0.125), "-0.1250");
assert.strictEqual(dashboard.formatSignedPercent(0.125), "+12.50%");
assert.strictEqual(dashboard.formatSignedPercent(-0.125), "-12.50%");
assert.strictEqual(dashboard.formatTradeWeight({ value: "0.5", equity_after: "1.25" }), "40.00%");
assert.strictEqual(dashboard.formatTradeReturn({ action: "SELL", realized_return: "0.125" }), "+12.50%");
assert.strictEqual(dashboard.formatTradeReturn({ action: "BUY", realized_return: "0.125" }), "--");
assert.strictEqual(dashboard.formatUpdateTime([{ updated_at: "2026-07-03T15:30:00" }]), "2026-07-03 15:30:00");
assert.strictEqual(dashboard.formatShares(0.23346574), "0.2335");
assert.strictEqual(dashboard.formatHeat(12177850), "1217.8万");
assert.strictEqual(dashboard.formatCountBadge(15, "只"), "15只");
assert.strictEqual(dashboard.formatCountBadge(15, "条"), "15条");
assert.strictEqual(dashboard.formatPercent(""), "--");
assert.strictEqual(dashboard.formatScore(""), "--");
assert.strictEqual(dashboard.formatFundSize(""), "--");

const metrics = dashboard.computeDashboardMetrics(rows, [{ theme: "半导体" }, { theme: "科创" }, { theme: "医药" }]);
assert.strictEqual(metrics.rankedCount, 2);
assert.strictEqual(metrics.themeCount, 3);
assert.strictEqual(metrics.topTheme, "半导体");

const curve = [
  { date: "2026-06-01", equity: "1.0000", exposure: "0.5", total_return: "0", drawdown: "0" },
  { date: "2026-06-02", equity: "1.0500", exposure: "1.0", total_return: "0.05", drawdown: "0" },
  { date: "2026-06-03", equity: "1.0200", exposure: "0.5", total_return: "0.02", drawdown: "-0.028571" },
];
const backtestSummary = dashboard.computeBacktestSummary(curve);
assert.strictEqual(backtestSummary.netValue, "1.0200");
assert.strictEqual(backtestSummary.totalReturn, "2.00%");
assert.strictEqual(backtestSummary.maxDrawdown, "-2.86%");
assert.strictEqual(backtestSummary.exposure, "50.00%");

const points = dashboard.buildCurvePoints(curve, 100, 50, 5);
assert.strictEqual(points.split(" ").length, 3);
assert.ok(points.startsWith("5.0,45.0"));

const longCurve = Array.from({ length: 30 }, (_, index) => ({
  date: `2026-06-${String(index + 1).padStart(2, "0")}`,
  equity: String(1 + index / 100),
  exposure: "1",
  total_return: String(index / 100),
  drawdown: "0",
}));
assert.strictEqual(dashboard.filterCurveRows(longCurve, "week").length, 5);
assert.strictEqual(dashboard.filterCurveRows(longCurve, "month").length, 21);
assert.strictEqual(dashboard.filterCurveRows(longCurve, "year").length, 30);
assert.strictEqual(dashboard.filterCurveRows(longCurve, "all").length, 30);

const weekSummary = dashboard.computeBacktestSummary(dashboard.filterCurveRows(longCurve, "week"));
assert.strictEqual(weekSummary.totalReturn, "3.20%");

const areaPath = dashboard.buildCurveAreaPath(points, 100, 50, 5);
assert.ok(areaPath.startsWith("M 5.0,45.0 L"));
assert.ok(areaPath.endsWith("95.0,45.0 Z"));

const layout = dashboard.buildChartLayout(720, 360);
assert.ok(layout.axis.left < layout.plot.left);
assert.ok(layout.plot.right < layout.axis.right);
assert.ok(layout.plot.bottom < layout.timeAxis.y);

const equityScale = dashboard.buildEquityAxisScale([
  { date: "2026-06-01", equity: "1.0000" },
  { date: "2026-06-02", equity: "1.2000" },
  { date: "2026-06-03", equity: "1.1000" },
]);
assert.strictEqual(equityScale.startEquity, 1);
assert.strictEqual(equityScale.minValue, 1);
assert.strictEqual(equityScale.maxValue, 1.2);
const yAxisTicks = dashboard.buildYAxisTicks(equityScale, layout.plot);
assert.strictEqual(yAxisTicks[0].netLabel, "1.2");
assert.strictEqual(yAxisTicks[0].returnLabel, "20.00%");
assert.strictEqual(yAxisTicks[yAxisTicks.length - 1].netLabel, "1.0");
assert.strictEqual(yAxisTicks[yAxisTicks.length - 1].returnLabel, "0.00%");

const expandedScale = dashboard.buildEquityAxisScale([
  { date: "2026-06-01", equity: "1.0000" },
  { date: "2026-06-02", equity: "1.5000" },
  { date: "2026-06-03", equity: "2.0000" },
]);
const expandedTicks = dashboard.buildYAxisTicks(expandedScale, layout.plot);
assert.strictEqual(expandedTicks.length, 11);
assert.deepStrictEqual(expandedTicks.map((tick) => tick.returnLabel), [
  "100.00%",
  "90.00%",
  "80.00%",
  "70.00%",
  "60.00%",
  "50.00%",
  "40.00%",
  "30.00%",
  "20.00%",
  "10.00%",
  "0.00%",
]);
assert.deepStrictEqual(expandedTicks.map((tick) => tick.netLabel), ["2.0", "1.9", "1.8", "1.7", "1.6", "1.5", "1.4", "1.3", "1.2", "1.1", "1.0"]);

const dateTicks = dashboard.buildDateTicks(longCurve, 6);
assert.strictEqual(dateTicks.length, 6);
assert.strictEqual(dateTicks[0].date, "2026-06-01");
assert.strictEqual(dateTicks[dateTicks.length - 1].date, "2026-06-30");

const markerTrades = [
  { date: "2026-06-02", action: "BUY", code: "159516", name: "chip" },
  { date: "2026-06-03", action: "SELL", code: "159516", name: "chip" },
  { date: "2026-06-04", action: "BUY", code: "159999", name: "outside" },
];
const markers = dashboard.buildTradeMarkerPoints(curve, markerTrades, 100, 50, 5);
assert.strictEqual(markers.length, 2);
assert.strictEqual(markers[0].action, "BUY");
assert.strictEqual(markers[1].action, "SELL");
assert.ok(markers[0].x > 5);
assert.ok(markers[1].y >= 5);
const markerCounts = dashboard.countTradeActions(markers);
assert.strictEqual(markerCounts.buy, 1);
assert.strictEqual(markerCounts.sell, 1);

const hotRows = [
  { rank: "1", code: "588170", name: "科创半导体ETF华夏", heat: "13260375.5" },
  { rank: "3", code: "515050", name: "通信ETF华夏", heat: "4520341.0" },
  { rank: "5", code: "512880", name: "证券ETF国泰", heat: "3726969.0" },
];
const rankedWithHot = dashboard.applyHotRanks([
  { code: "159516", name: "国泰中证半导体材料设备主题ETF", theme: "半导体" },
  { code: "588000", name: "华夏上证科创板50成份ETF", theme: "科创" },
  { code: "159841", name: "证券公司ETF", theme: "证券" },
  { code: "515880", name: "通信ETF", theme: "通信" },
  { code: "516760", name: "农业ETF", theme: "农业" },
], hotRows);
assert.strictEqual(rankedWithHot[0].hotRank, "1");
assert.strictEqual(rankedWithHot[0].hotCode, "588170");
assert.strictEqual(rankedWithHot[1].hotRank, "");
assert.strictEqual(rankedWithHot[2].hotRank, "5");
assert.strictEqual(rankedWithHot[3].hotRank, "3");
assert.strictEqual(rankedWithHot[4].hotRank, "");

const hotLimitRows = Array.from({ length: 13 }, (_, index) => ({ rank: String(index + 1) }));
assert.strictEqual(dashboard.limitHotRows(hotLimitRows).length, 12);
assert.strictEqual(dashboard.limitHotRows(hotLimitRows)[11].rank, "12");

const themeRows = [
  { theme: "科创成长", score: "0.70" },
  { theme: "科创", score: "0.65" },
  { theme: "科综指增", score: "0.60" },
  { theme: "双创", score: "0.58" },
  { theme: "科技成长", score: "0.55" },
  { theme: "新兴科技", score: "0.54" },
  { theme: "数字经济", score: "0.53" },
  { theme: "半导体", score: "0.80" },
  { theme: "证券", score: "0.45" },
  { theme: "银行", score: "0.44" },
  { theme: "创新药", score: "0.43" },
  { theme: "制药", score: "0.425" },
  { theme: "上证580ETF", score: "0.42" },
  { theme: "上证380ETF", score: "0.41" },
  { theme: "中证1000", score: "0.40" },
  { theme: "国证2000ETF工银", score: "0.425" },
  { theme: "卫星", score: "0.39" },
  { theme: "电力", score: "0.38" },
  { theme: "军工", score: "0.37" },
  { theme: "新能源车", score: "0.365" },
  { theme: "消费", score: "0.36" },
  { theme: "传媒游戏", score: "0.355" },
  { theme: "红利", score: "0.35" },
  { theme: "黄金", score: "0.34" },
  { theme: "石化", score: "0.33" },
  { theme: "旅游酒店", score: "0.32" },
  { theme: "基建建材", score: "0.31" },
  { theme: "交通运输", score: "0.30" },
  { theme: "湖北新旧动能转换", score: "0.29" },
  { theme: "南华杭州湾区", score: "0.28" },
  { theme: "浙商之江凤凰", score: "0.27" },
];
const themeStrengthRows = dashboard.buildThemeStrengthRows(themeRows);
assert.strictEqual(themeStrengthRows.length, 15);
assert.strictEqual(new Set(themeStrengthRows.map((row) => row.theme)).size, themeStrengthRows.length);
assert.strictEqual(themeStrengthRows[0].theme, "半导体");
assert.strictEqual(themeStrengthRows[1].theme, "科创");
assert.strictEqual(themeStrengthRows[1].score, "0.70");
assert.ok(themeStrengthRows.some((row) => row.theme === "科技成长" && row.score === "0.55"));
assert.strictEqual(dashboard.normalizeThemeLabel("新兴科技"), "科技成长");
assert.strictEqual(dashboard.normalizeThemeLabel("科技成长"), "科技成长");
assert.strictEqual(dashboard.normalizeThemeLabel("数字经济"), "计算机");
assert.strictEqual(dashboard.normalizeThemeLabel("科创半导体ETF华夏"), "半导体");
assert.strictEqual(dashboard.normalizeThemeLabel("制药"), "医药");
assert.strictEqual(dashboard.normalizeThemeLabel("石化"), "化工材料");
assert.strictEqual(dashboard.normalizeThemeLabel("湖北新旧动能转换"), "区域经济");
assert.strictEqual(dashboard.normalizeThemeLabel("南华杭州湾区"), "区域经济");
assert.strictEqual(dashboard.normalizeThemeLabel("浙商之江凤凰"), "区域经济");
assert.strictEqual(dashboard.normalizeThemeLabel("国证2000ETF工银"), "宽基指数");
assert.strictEqual(dashboard.normalizeThemeLabel("道琼斯ETF"), "海外宽基");
assert.strictEqual(dashboard.normalizeThemeLabel("VRETF"), "虚拟现实");
assert.strictEqual(dashboard.normalizeThemeLabel("1000增强ETF"), "指数增强");
assert.strictEqual(dashboard.normalizeThemeLabel("国寿安保创精选88ETF"), "创业板");

const industryRows = dashboard.buildIndustryRows([
  { code: "159743", name: "博时湖北新旧动能转换ETF", theme: "湖北新旧动能转换" },
  { code: "512870", name: "南华中证杭州湾区ETF", theme: "南华杭州湾区" },
  { code: "512190", name: "浙商之江凤凰ETF", theme: "浙商之江凤凰" },
  { code: "159895", name: "易方达中证物联网主题ETF", theme: "物联网" },
]);
assert.deepStrictEqual(industryRows.map((row) => row.theme), ["区域经济", "区域经济", "区域经济", "计算机"]);

const rankLimitRows = Array.from({ length: 25 }, (_, index) => ({ code: String(index + 1).padStart(6, "0") }));
assert.strictEqual(dashboard.limitRankRows(rankLimitRows).length, 25);
assert.strictEqual(dashboard.limitRankRows(Array.from({ length: 60 }, (_, index) => ({ code: String(index + 1).padStart(6, "0") }))).length, 50);

const liveRankRows = dashboard.parseCsv(fs.readFileSync(path.join(__dirname, "../outputs/etf_rotation_rank.csv"), "utf8"));
assert.ok(dashboard.limitRankRows(dashboard.buildIndustryRows(liveRankRows)).length <= 50);
assert.strictEqual(dashboard.buildThemeStrengthRows(liveRankRows).length, 15);

console.log("web dashboard tests passed");
