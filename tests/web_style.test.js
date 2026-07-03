const assert = require("assert");
const fs = require("fs");
const path = require("path");

const css = fs.readFileSync(path.join(__dirname, "../web/styles.css"), "utf8").toLowerCase();

const forbidden = [
  "--green",
  "green",
  "#0f8b63",
  "rgba(15, 139, 99",
  "rgb(15, 139, 99",
];

for (const token of forbidden) {
  assert.strictEqual(css.includes(token), false, `CSS should not contain green styling token: ${token}`);
}

assert.ok(css.includes("--brand-red"), "CSS should define a primary red brand token");
assert.ok(css.includes("--brand-red-soft"), "CSS should keep red accents available as light tints");
assert.strictEqual(css.includes("--brand-red-deep"), false, "CSS should avoid heavy deep-red blocks");

const redTokenUses = (css.match(/var\(--brand-red/g) || []).length;
assert.ok(redTokenUses >= 5, `Primary red should still guide key highlights, found ${redTokenUses} uses`);
assert.strictEqual(
  /\.code\s*\{[^}]*var\(--brand-red/.test(css),
  false,
  "ETF code text should not use the red brand token",
);
assert.strictEqual(
  /\.score\s*\{[^}]*var\(--brand-red/.test(css),
  false,
  "Score text should not use the red brand token",
);
assert.ok(
  /\.pick-block\s+\.label\s*\{[^}]*color:\s*var\(--brand-red\)/.test(css),
  "The Today Pick label should keep the red brand emphasis",
);
assert.ok(
  /\.pick-reason\s*\{[^}]*font-size:\s*14px/.test(css),
  "Today Pick reason should be readable as body copy",
);
assert.strictEqual(
  /\.rank-panel\s+\.table-wrap\s*\{[^}]*max-height:\s*none/.test(css),
  true,
  "Strong ranking table should fill the stretched card and keep scrolling inside that bounded area",
);
assert.strictEqual(
  /\.rank-panel\s+\.table-wrap\s*\{[^}]*height:\s*612px/.test(css),
  false,
  "Strong ranking table should not use a fixed height that prevents bottom alignment with the theme card",
);
assert.ok(
  /\.rank-panel\s*\{[^}]*align-self:\s*stretch/.test(css),
  "Strong ranking card should stretch with the neighboring panels so their bottoms align",
);
assert.ok(
  /\.layout\s*\{[^}]*--market-panel-height:\s*clamp\(820px,\s*84vh,\s*1040px\)/.test(css),
  "Market panels should share a bounded responsive row height instead of letting the longest table define the row",
);
assert.ok(
  /\.layout\s*\{[^}]*grid-auto-rows:\s*var\(--market-panel-height\)/.test(css),
  "Market panel grid row should use the shared height so ranking and theme panels align",
);
assert.ok(
  /\.rank-panel,\s*\.theme-panel,\s*\.hot-panel\s*\{[^}]*overflow:\s*hidden/.test(css),
  "Market panels should clip internal overflow so their shared bottoms stay aligned",
);
assert.ok(
  /\.rank-panel\s+\.table-wrap\s*\{[^}]*min-height:\s*0/.test(css),
  "Strong ranking scroll area should allow flex shrinking instead of forcing the card taller",
);
assert.ok(css.includes("chart-legend"), "Backtest chart should include legend styling to reduce visual emptiness");
assert.ok(
  /\.hot-panel\s+\.hot-list\s*\{[^}]*grid-auto-rows:\s*minmax\(0,\s*1fr\)/.test(css),
  "Hot ETF rows should fill the card with even row sizing",
);
assert.ok(
  /\.theme-panel\s+\.bars\s*\{[^}]*grid-auto-rows:\s*minmax\(0,\s*1fr\)/.test(css),
  "Theme strength rows should fill the card with even row sizing",
);
assert.ok(
  /\.bar-value\s*\{[^}]*font-size:\s*13px/.test(css),
  "Theme strength values should be more legible than tiny annotation text",
);
assert.ok(
  /\.hot-row\s+strong\s*\{[^}]*font-size:\s*15px/.test(css),
  "Hot ETF codes should be prominent enough to scan",
);
assert.ok(
  /\.hot-row\s+span:not\(\.hot-rank\)\s*\{[^}]*font-size:\s*13px/.test(css),
  "Hot ETF names should be readable in the side panel",
);
assert.ok(css.includes(".curve-banner"), "Backtest chart should include a designed curve banner");
assert.ok(
  /\.curve-banner\s*\{[^}]*background:[^}]*linear-gradient/.test(css),
  "Curve banner should use a designed layered background",
);
assert.ok(
  /\.chart-column\s*\{[^}]*grid-template-rows:\s*auto\s+auto\s+minmax\(0,\s*1fr\)/.test(css),
  "Chart column should stack banner, KPIs, then let the chart consume remaining height",
);
assert.ok(
  /\.chart-shell\s*\{[^}]*height:\s*auto/.test(css),
  "Chart shell should avoid a fixed height so it can fill the available column space",
);
assert.ok(
  /\.backtest-stats\s*\{[^}]*gap:\s*0/.test(css),
  "Backtest KPIs should read as one quiet rail instead of separate cards",
);
assert.ok(
  /\.backtest-stats\s+div\s*\{[^}]*border:\s*0;[^}]*background:\s*transparent/.test(css),
  "Backtest KPI items should not compete with the curve banner as individual cards",
);
assert.ok(
  /\.backtest-lists\s*\{[^}]*grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\)/.test(css),
  "Backtest side rail should let trades adapt to the remaining height after holdings",
);
assert.ok(
  /\.backtest-lists\s*\{[^}]*height:\s*var\(--backtest-rail-height\)/.test(css),
  "Backtest side rail should be bounded to the chart column height instead of expanding with all trades",
);
assert.ok(
  /\.backtest-lists\s*\{[^}]*overflow:\s*hidden/.test(css),
  "Backtest side rail should hide overflow so the trades area scrolls internally",
);
assert.ok(
  /\.backtest-lists\s*>\s*div:last-child\s*\{[^}]*grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\)/.test(css),
  "Trades section should make the scroll area fill its available height",
);
assert.ok(
  /\.trades-scroll\s*\{[^}]*max-height:\s*none/.test(css),
  "Trades list should size from the bounded side rail rather than a stale fixed max-height",
);
assert.ok(
  /\.trades-scroll\s*\{[^}]*overflow-y:\s*auto/.test(css),
  "Trades list should keep its internal scrolling behavior",
);
assert.ok(
  /\.trade-row\s*\{[^}]*grid-template-columns:\s*1fr/.test(css),
  "Trade rows should use a stacked layout to avoid overlapping in the narrow side rail",
);
assert.ok(
  /\.trade-row\s*\{[^}]*min-height:\s*76px/.test(css),
  "Trade rows should reserve enough vertical space for identity and metrics",
);
assert.ok(
  /\.trade-metrics\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/.test(css),
  "Trade row metrics should share a stable three-column second line",
);
assert.ok(
  /\.holding-row\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1\.1fr\)\s+minmax\(0,\s*1\.5fr\)/.test(css),
  "Holding rows should keep the position summary on one line",
);
assert.ok(
  /\.holding-metrics\s*\{[^}]*grid-template-columns:\s*0\.68fr\s+1\.25fr\s+0\.7fr/.test(css),
  "Holding rows should label position, price, and floating return in a readable metric row",
);
assert.strictEqual(
  /font-size:\s*[^;]*(clamp\(|vw)/.test(css),
  false,
  "Font sizes should use fixed type-scale values instead of viewport scaling",
);
assert.strictEqual(css.includes("font-weight: 850"), false, "Typography should avoid overly heavy 850 weights");
assert.strictEqual(css.includes("font-weight: 900"), false, "Typography should avoid oversized display-heavy 900 weights");
const letterSpacingValues = Array.from(css.matchAll(/letter-spacing:\s*([^;]+);/g)).map((match) => match[1].trim());
assert.ok(letterSpacingValues.every((value) => value === "0"), "Letter spacing should stay at 0 for a calmer dashboard");

console.log("web style tests passed");
