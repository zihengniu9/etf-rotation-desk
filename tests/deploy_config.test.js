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
assert.ok(workflow.includes("30 6 * * *"), "GitHub Actions should run daily at 14:30 Asia/Hong_Kong");
assert.ok(workflow.includes("python run_etf_selector.py"), "Workflow should refresh ETF outputs");
assert.ok(workflow.includes("git add outputs"), "Workflow should persist updated output history");
assert.ok(workflow.includes("contents: write"), "Workflow needs permission to commit refreshed outputs");
assert.ok(workflow.includes("python scripts/build_static_site.py"), "Workflow should build the Netlify publish directory");
assert.ok(workflow.includes("NETLIFY_AUTH_TOKEN"), "Workflow should deploy with a Netlify auth token secret");
assert.ok(workflow.includes("NETLIFY_SITE_ID"), "Workflow should deploy to an explicit Netlify site id");
assert.ok(workflow.includes("netlify-cli deploy"), "Workflow should deploy using the Netlify CLI");
assert.ok(workflow.includes("--prod"), "Workflow should publish scheduled runs to Netlify production");
assert.ok(workflow.includes("--dir=dist"), "Workflow should deploy the clean static dist directory");

const updateScript = read("scripts/update_etf_data.ps1");
assert.ok(updateScript.includes("run_etf_selector.py"), "Local scheduled update should call the ETF runner");
assert.ok(updateScript.includes("scheduled_update.log"), "Local scheduled update should append a log file");
assert.ok(updateScript.includes("$env:PYTHONPATH"), "Local scheduled update should set PYTHONPATH");
assert.ok(updateScript.includes("$MaxAttempts = 3"), "Local scheduled update should retry transient data-source failures");
assert.ok(updateScript.includes("Start-Sleep"), "Local scheduled update should wait between retries");
assert.ok(updateScript.includes("RedirectStandardError"), "Local scheduled update should capture Python stderr without aborting PowerShell logging");

const taskScript = read("scripts/install_windows_task.ps1");
assert.ok(taskScript.includes("14:30"), "Windows scheduled task installer should default to 14:30");
assert.ok(taskScript.includes("Register-ScheduledTask"), "Windows installer should register a scheduled task");
assert.ok(taskScript.includes("update_etf_data.ps1"), "Windows task should invoke the update script");

const index = read("index.html");
assert.ok(index.includes("./web/"), "Root index should redirect users to the dashboard");

const netlifyConfig = read("netlify.toml");
assert.ok(netlifyConfig.includes('command = "python scripts/build_static_site.py"'), "Netlify should build the static publish directory");
assert.ok(netlifyConfig.includes('publish = "dist"'), "Netlify should publish only the clean dist directory");

const buildScript = read("scripts/build_static_site.py");
assert.ok(buildScript.includes("shutil.copytree"), "Static build should copy dashboard folders");
assert.ok(buildScript.includes('"web"'), "Static build should publish the dashboard");
assert.ok(buildScript.includes('"outputs"'), "Static build should publish CSV outputs");
assert.ok(buildScript.includes('"index.html"'), "Static build should publish the root redirect");
assert.ok(buildScript.includes("*.csv"), "Static build should publish only CSV output data files");
assert.strictEqual(buildScript.includes("scheduled_update.log"), false, "Static build should not publish local scheduler logs");

console.log("deploy config tests passed");
