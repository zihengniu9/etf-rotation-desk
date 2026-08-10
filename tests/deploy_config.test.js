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

const workflow = read(".github/workflows/update-etf-data.yml");
const pagesWorkflow = read(".github/workflows/deploy-pages.yml");
assert.ok(workflow.includes("30 1 * * 1-5"), "GitHub Actions should run at 09:30 Asia/Hong_Kong on weekdays");
assert.ok(workflow.includes("0,30 2-3 * * 1-5"), "GitHub Actions should run every 30 minutes during the morning session");
assert.ok(workflow.includes("0,30 5-6 * * 1-5"), "GitHub Actions should run every 30 minutes during the afternoon session");
assert.ok(workflow.includes("0 7 * * 1-5"), "GitHub Actions should run at 15:00 Asia/Hong_Kong on weekdays");
assert.strictEqual(workflow.includes('cron: "0 1 * * 1-5"'), false, "GitHub Actions should no longer run only once at 09:00");
assert.strictEqual(workflow.includes("Data date already refreshed"), false, "Intraday updates should not be skipped just because the data date matches");
assert.ok(workflow.includes("python run_etf_selector.py"), "Workflow should refresh ETF outputs");
assert.ok(workflow.includes("python scripts/update_industry_data.py --refresh"), "Workflow should refresh industry outputs");
assert.ok(workflow.includes("--json-output outputs/industry_flow.json"), "Workflow should publish the industry JSON dataset");
assert.ok(workflow.includes("git add outputs"), "Workflow should persist updated output history");
assert.ok(workflow.includes("git push"), "Workflow should push refreshed outputs before deployment");
assert.ok(workflow.includes("contents: write"), "Workflow needs permission to commit refreshed outputs");
assert.ok(workflow.includes("python scripts/build_static_site.py"), "Workflow should build the Pages artifact");
assert.ok(workflow.includes("pages: write"), "Pages deployment needs pages write permission");
assert.ok(workflow.includes("id-token: write"), "Pages deployment needs an OIDC token");
assert.ok(workflow.includes("actions/configure-pages@v5"), "Workflow should configure GitHub Pages");
assert.ok(workflow.includes("actions/upload-pages-artifact@v4"), "Workflow should upload the Pages artifact");
assert.ok(workflow.includes("path: dist"), "Workflow should upload only the generated dist directory");
assert.ok(workflow.includes("needs: update-data"), "Pages deployment should wait for the verified build");
assert.ok(workflow.includes("name: github-pages"), "Workflow should use the GitHub Pages environment");
assert.ok(workflow.includes("actions/deploy-pages@v5"), "Workflow should publish with the official Pages action");
assert.strictEqual(workflow.includes("NETLIFY_AUTH_TOKEN"), false, "Workflow should not require a Netlify token");
assert.strictEqual(workflow.includes("NETLIFY_SITE_ID"), false, "Workflow should not target a Netlify site");
assert.strictEqual(workflow.includes("api.netlify.com"), false, "Workflow should not call the Netlify API");
assert.strictEqual(workflow.includes("netlify-cli"), false, "Workflow should not run Netlify CLI");
assert.ok(workflow.includes("market-data-refresh"), "Unified workflow should serialize market data refreshes");
assert.ok(workflow.includes("actions/configure-pages@v5"), "Unified workflow should configure GitHub Pages");
assert.ok(workflow.includes("actions/upload-pages-artifact@v4"), "Unified workflow should upload the refreshed Pages artifact");
assert.ok(workflow.includes("actions/deploy-pages@v5"), "Unified workflow should deploy the refreshed Pages artifact");
assert.strictEqual(require("fs").existsSync(require("path").join(root, ".github/workflows/update-industry-data.yml")), false, "Industry data should not have a second scheduled workflow");

for (const pathPattern of ["web/**", "scripts/build_static_site.py"]) {
  assert.ok(pagesWorkflow.includes(`      - \"${pathPattern}\"`), `Pages workflow should deploy when ${pathPattern} changes`);
}
assert.ok(pagesWorkflow.includes("python scripts/build_static_site.py"), "Pages workflow should build the static artifact directly");
assert.ok(pagesWorkflow.includes("actions/configure-pages@v5"), "Pages workflow should configure GitHub Pages");
assert.ok(pagesWorkflow.includes("actions/upload-pages-artifact@v4"), "Pages workflow should upload the Pages artifact");
assert.ok(pagesWorkflow.includes("actions/deploy-pages@v5"), "Pages workflow should publish with the official Pages action");
assert.ok(pagesWorkflow.includes("cancel-in-progress: true"), "Pages workflow should cancel stale deployments");

const updateScript = read("scripts/update_etf_data.ps1");
assert.ok(updateScript.includes("run_etf_selector.py"), "Local scheduled update should call the ETF runner");
assert.ok(updateScript.includes("scheduled_update.log"), "Local scheduled update should append a log file");
assert.ok(updateScript.includes("$env:PYTHONPATH"), "Local scheduled update should set PYTHONPATH");
assert.ok(updateScript.includes("$MaxAttempts = 3"), "Local scheduled update should retry transient data-source failures");
assert.ok(updateScript.includes("Start-Sleep"), "Local scheduled update should wait between retries");
assert.ok(updateScript.includes("RedirectStandardError"), "Local scheduled update should capture Python stderr without aborting PowerShell logging");

const taskScript = read("scripts/install_windows_task.ps1");
for (const time of ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]) {
  assert.ok(taskScript.includes(time), `Windows scheduled task installer should include ${time}`);
}
assert.ok(taskScript.includes("Register-ScheduledTask"), "Windows installer should register a scheduled task");
assert.ok(taskScript.includes("update_etf_data.ps1"), "Windows task should invoke the update script");

const index = read("index.html");
assert.ok(index.includes("./web/"), "Root index should redirect users to the dashboard");

const industryHtml = read("web/industry_mainline_dashboard.html");
assert.ok(industryHtml.includes("../outputs/industry_flow.json?ts="), "Industry dashboard should load the JSON dataset first");
assert.ok(industryHtml.includes("../outputs/industry_flow.csv?ts="), "Industry dashboard should keep a CSV fallback");
assert.ok(industryHtml.includes("GitHub Actions 行业 JSON"), "Industry dashboard should identify its live JSON source");

const netlifyConfig = read("netlify.toml");
assert.ok(netlifyConfig.includes('command = "python scripts/build_static_site.py"'), "Netlify should build the static publish directory");
assert.ok(netlifyConfig.includes('publish = "dist"'), "Netlify should publish only the clean dist directory");

const buildScript = read("scripts/build_static_site.py");
assert.ok(buildScript.includes("shutil.copytree"), "Static build should copy dashboard folders");
assert.ok(buildScript.includes('"web"'), "Static build should publish the dashboard");
assert.ok(buildScript.includes('"outputs"'), "Static build should publish CSV outputs");
assert.ok(buildScript.includes('"index.html"'), "Static build should publish the root redirect");
assert.ok(buildScript.includes("*.csv"), "Static build should publish only CSV output data files");
assert.ok(buildScript.includes("*.json"), "Static build should publish JSON output data files");
assert.ok(buildScript.includes('DIST / ".nojekyll"'), "Static build should create a GitHub Pages .nojekyll marker");
assert.strictEqual(buildScript.includes("scheduled_update.log"), false, "Static build should not publish local scheduler logs");

console.log("deploy config tests passed");
