const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

const requirements = read("requirements.txt");
for (const dependency of ["akshare", "pandas", "numpy", "requests", "openpyxl", "lxml"]) {
  assert.ok(requirements.includes(dependency), `requirements.txt should include ${dependency}`);
}

const validateWorkflow = read(".github/workflows/validate-dashboard.yml");
const pagesWorkflow = read(".github/workflows/deploy-pages.yml");
assert.strictEqual(validateWorkflow.includes("schedule:"), false, "Hosted CI must not collect market data on a cron");
assert.strictEqual(validateWorkflow.includes("openapi.iwencai.com"), false, "Hosted CI must not call Wencai");
assert.ok(validateWorkflow.includes("python -m unittest discover"), "CI should validate Python factors");
assert.ok(validateWorkflow.includes("node tests/web_dashboard.test.js"), "CI should validate dashboard contracts");
assert.ok(validateWorkflow.includes("node tests/deploy_config.test.js"), "CI should validate deployment configuration");
assert.ok(validateWorkflow.includes("python scripts/build_static_site.py"), "CI should verify the static bundle");
assert.ok(validateWorkflow.includes("authenticated local tun tunnel"), "CI should document the local tunnel trust boundary");
assert.strictEqual(fs.existsSync(path.join(root, ".github/workflows/update-etf-data.yml")), false, "Remote market-data collector should be removed");

for (const pathPattern of ["web/**", "outputs/**", "scripts/build_static_site.py"]) {
  assert.ok(pagesWorkflow.includes(`      - "${pathPattern}"`), `Pages workflow should deploy when ${pathPattern} changes`);
}
assert.ok(pagesWorkflow.includes("python scripts/build_static_site.py"), "Pages workflow should build the static artifact directly");
assert.ok(pagesWorkflow.includes("actions/configure-pages@v5"), "Pages workflow should configure GitHub Pages");
assert.ok(pagesWorkflow.includes("actions/upload-pages-artifact@v4"), "Pages workflow should upload the Pages artifact");
assert.ok(pagesWorkflow.includes("actions/deploy-pages@v5"), "Pages workflow should publish with the official Pages action");
assert.ok(pagesWorkflow.includes("cancel-in-progress: true"), "Pages workflow should cancel stale deployments");

const etfUpdateScript = read("scripts/update_etf_data.ps1");
assert.ok(etfUpdateScript.includes("run_etf_selector.py"), "Local ETF update should call the selector");
assert.ok(etfUpdateScript.includes("scheduled_update.log"), "Local ETF update should append a log file");
assert.ok(etfUpdateScript.includes("$env:PYTHONPATH"), "Local ETF update should set PYTHONPATH");
assert.ok(etfUpdateScript.includes("$MaxAttempts = 1"), "Network collection should make one initial attempt by default");
assert.ok(etfUpdateScript.includes("RedirectStandardError"), "Local ETF update should capture Python stderr");

const dailyRunner = read("scripts/update_dashboard_daily.ps1");
for (const mode of ["Morning", "Intraday", "Close", "Full"]) {
  assert.ok(dailyRunner.includes(`\"${mode}\"`), `Daily runner should support ${mode}`);
}
assert.ok(dailyRunner.includes("Test-Tunnel"), "Daily runner should verify the tunnel before collection");
assert.ok(dailyRunner.includes("curl.exe --proxy $TunnelProxy"), "Tunnel verification should use HTTPS through the proxy");
assert.ok(dailyRunner.includes("https://openapi.iwencai.com"), "Tunnel probe should target the official HTTPS endpoint");
assert.strictEqual(dailyRunner.includes("ws://"), false, "Daily runner must not use WebSocket");
assert.strictEqual(dailyRunner.includes("wss://"), false, "Daily runner must not use WebSocket");
assert.ok(dailyRunner.includes('Get-RequiredEnvironment "IWENCAI_API_KEY"'), "Daily runner should require the API key from environment storage");
assert.ok(dailyRunner.includes('"-MaxAttempts", "1"'), "Daily runner should enforce a single ETF collection attempt");
assert.ok(dailyRunner.includes("git add -- outputs"), "Daily runner should stage generated outputs only");
assert.ok(dailyRunner.includes("git pull --rebase origin main"), "Daily runner should integrate remote changes before publishing");
assert.ok(dailyRunner.includes("git push origin HEAD:main"), "Daily runner should publish generated outputs to main");

const taskInstaller = read("scripts/install_dashboard_tasks.ps1");
for (const time of ["09:28", "10:00", "11:30", "14:00", "16:20"]) {
  assert.ok(taskInstaller.includes(time), `Windows task installer should include ${time}`);
}
for (const task of ["AI Stock Dashboard Morning", "AI Stock Dashboard Intraday", "AI Stock Dashboard Close"]) {
  assert.ok(taskInstaller.includes(task), `Windows task installer should register ${task}`);
}
assert.ok(taskInstaller.includes("Register-ScheduledTask"), "Windows installer should register scheduled tasks");
assert.ok(taskInstaller.includes("update_dashboard_daily.ps1"), "Windows tasks should invoke the unified runner");

const index = read("index.html");
assert.ok(index.includes("./web/market_mode.html"), "Root index should open the market-mode decision page first");

const industryHtml = read("web/industry_mainline_dashboard.html");
assert.ok(industryHtml.includes("../outputs/industry_flow.json?ts="), "Industry dashboard should load the JSON dataset first");
assert.ok(industryHtml.includes("../outputs/industry_flow.csv?ts="), "Industry dashboard should keep a CSV fallback");
assert.ok(industryHtml.includes("svg.getScreenCTM()"), "Industry trend crosshair should account for SVG transforms");
assert.ok(industryHtml.includes("window.setInterval"), "Industry dashboard should poll for intraday updates");
assert.ok(industryHtml.includes("visibilitychange"), "Industry dashboard should refresh after returning to the tab");

const etfApp = read("web/app.js");
assert.ok(etfApp.includes("AUTO_REFRESH_INTERVAL_MS = 2 * 60 * 1000"), "ETF dashboard should poll every two minutes during trading hours");
assert.ok(etfApp.includes('cache: "no-store"'), "ETF dashboard refreshes should bypass the browser cache");
assert.ok(etfApp.includes('globalScope.addEventListener("focus"'), "ETF dashboard should refresh when the window regains focus");

const netlifyConfig = read("netlify.toml");
assert.ok(netlifyConfig.includes('command = "python scripts/build_static_site.py"'), "Netlify should build the static publish directory");
assert.ok(netlifyConfig.includes('publish = "dist"'), "Netlify should publish only the clean dist directory");

const buildScript = read("scripts/build_static_site.py");
assert.ok(buildScript.includes("shutil.copytree"), "Static build should copy dashboard folders");
assert.ok(buildScript.includes('"web"'), "Static build should publish the dashboard");
assert.ok(buildScript.includes('"outputs"'), "Static build should publish generated data");
assert.ok(buildScript.includes('"index.html"'), "Static build should publish the root redirect");
for (const pattern of ["*.csv", "*.json", "*.js"]) {
  assert.ok(buildScript.includes(`"${pattern}"`), `Static build should publish ${pattern} outputs`);
}
assert.ok(buildScript.includes('DIST / ".nojekyll"'), "Static build should create a GitHub Pages .nojekyll marker");
assert.strictEqual(buildScript.includes("dashboard_daily_update.log"), false, "Static build should not publish local scheduler logs");

const statusBuilder = read("scripts/build_dashboard_status.py");
assert.ok(statusBuilder.includes('"industry_flow_latest.json"'), "Status builder should create a compact latest-industry payload");
assert.ok(statusBuilder.includes('"industry_flow_latest.js"'), "Status builder should create a file-protocol industry fallback");
assert.ok(statusBuilder.includes('"trend_engine_snapshot.js"'), "Status builder should create a file-protocol trend fallback");
assert.ok(statusBuilder.includes('"shortterm_signal.js"'), "Status builder should keep the short-term file fallback synchronized");

console.log("deploy config tests passed");
