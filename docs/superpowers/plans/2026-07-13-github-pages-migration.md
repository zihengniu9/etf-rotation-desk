# GitHub Pages Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the ETF dashboard to GitHub Pages after every scheduled data refresh without using Netlify deployment credits.

**Architecture:** The existing `update-data` job continues generating, testing, and committing CSV outputs, then builds and uploads `dist/` as a Pages artifact. A dependent `deploy-pages` job publishes that artifact to the public `github-pages` environment.

**Tech Stack:** GitHub Actions, GitHub Pages, Python 3.11, Node.js assertion tests, static HTML/CSS/JavaScript, CSV.

## Global Constraints

- Preserve all weekday Asia/Hong_Kong trading-session schedule entries.
- Preserve output commits so historical curve and trade records remain in Git.
- Publish only `dist/`, containing `index.html`, `web/`, `outputs/*.csv`, and `.nojekyll`.
- Remove Netlify credentials, API checks, and deploy commands from the scheduled workflow.
- Keep the site public at `https://zihengniu9.github.io/etf-rotation-desk/web/`.
- Never copy GitHub Secrets into the Pages artifact.

---

### Task 1: Make the static artifact Pages-compatible

**Files:**
- Modify: `tests/deploy_config.test.js`
- Modify: `scripts/build_static_site.py`

**Interfaces:**
- Consumes: repository `index.html`, `web/`, and `outputs/*.csv`.
- Produces: `dist/.nojekyll` plus the existing static artifact layout.

- [ ] **Step 1: Write the failing build assertion**

Add this assertion after the existing build script assertions:

```javascript
assert.ok(buildScript.includes('DIST / ".nojekyll"'), "Static build should create a GitHub Pages .nojekyll marker");
```

- [ ] **Step 2: Run the deployment configuration test and verify failure**

Run: `node tests/deploy_config.test.js`

Expected: FAIL with `Static build should create a GitHub Pages .nojekyll marker`.

- [ ] **Step 3: Create the marker in the build script**

Add this line after `copy_outputs()` in `main()`:

```python
    (DIST / ".nojekyll").touch()
```

- [ ] **Step 4: Run the build test and inspect the artifact**

Run:

```powershell
node tests/deploy_config.test.js
python scripts/build_static_site.py
Test-Path dist\.nojekyll
```

Expected: test prints `deploy config tests passed`; `Test-Path` prints `True`.

- [ ] **Step 5: Commit the artifact change**

```powershell
git add tests/deploy_config.test.js scripts/build_static_site.py
git commit -m "Prepare static artifact for GitHub Pages"
```

### Task 2: Replace Netlify deployment with GitHub Pages

**Files:**
- Modify: `tests/deploy_config.test.js`
- Modify: `.github/workflows/update-etf-data.yml`

**Interfaces:**
- Consumes: `dist/` built by `python scripts/build_static_site.py`.
- Produces: a `github-pages` artifact and deployment URL from `actions/deploy-pages`.

- [ ] **Step 1: Replace Netlify assertions with failing Pages assertions**

Replace the Netlify-specific workflow assertions with:

```javascript
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
```

Change the build message assertion to:

```javascript
assert.ok(workflow.includes("python scripts/build_static_site.py"), "Workflow should build the Pages artifact");
```

- [ ] **Step 2: Run the test and verify failure**

Run: `node tests/deploy_config.test.js`

Expected: FAIL on the first missing Pages permission or action.

- [ ] **Step 3: Implement the Pages workflow**

Replace the workflow with this complete Pages configuration:

```yaml
name: Update ETF data

on:
  schedule:
    # A-share trading hours in Asia/Hong_Kong: 09:30-11:30 and 13:00-15:00.
    - cron: "30 1 * * 1-5"
    - cron: "0,30 2-3 * * 1-5"
    - cron: "0,30 5-6 * * 1-5"
    - cron: "0 7 * * 1-5"
  workflow_dispatch:

concurrency:
  group: etf-dashboard
  cancel-in-progress: false

jobs:
  update-data:
    permissions:
      contents: write
      pages: write
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Refresh ETF outputs
        run: python run_etf_selector.py

      - name: Verify
        run: |
          PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"
          node tests/web_dashboard.test.js
          node tests/web_style.test.js
          node tests/deploy_config.test.js

      - name: Commit refreshed outputs
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add outputs
          if git diff --cached --quiet; then
            echo "No output changes to commit."
          else
            git commit -m "Update ETF data"
            git push
          fi

      - name: Build GitHub Pages artifact
        run: python scripts/build_static_site.py

      - name: Configure GitHub Pages
        uses: actions/configure-pages@v5

      - name: Upload GitHub Pages artifact
        uses: actions/upload-pages-artifact@v4
        with:
          path: dist

  deploy-pages:
    needs: update-data
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v5
```

Use `Build GitHub Pages artifact` as the static build step name.

- [ ] **Step 4: Run workflow configuration tests**

Run: `node tests/deploy_config.test.js`

Expected: `deploy config tests passed`.

- [ ] **Step 5: Commit the workflow migration**

```powershell
git add tests/deploy_config.test.js .github/workflows/update-etf-data.yml
git commit -m "Deploy ETF dashboard with GitHub Pages"
```

### Task 3: Update deployment documentation

**Files:**
- Modify: `docs/deployment.md`

**Interfaces:**
- Consumes: the final Pages workflow and public URL.
- Produces: operator instructions for initial enablement, manual runs, and public visibility.

- [ ] **Step 1: Replace Netlify setup with Pages setup**

Document the deployment sequence and include these exact operational details:

```markdown
6. Uploads `dist/` as a GitHub Pages artifact.
7. Publishes the artifact to the public `github-pages` environment.

One-time setup:

1. Open repository `Settings > Pages`.
2. Under `Build and deployment`, set `Source` to `GitHub Actions`.
3. Run `Update ETF data` manually once from the Actions tab.

Public URL: `https://zihengniu9.github.io/etf-rotation-desk/web/`
```

Remove all Netlify secret instructions. State that the repository, dashboard,
and generated CSV files are public while GitHub Secrets are excluded from the
static artifact.

- [ ] **Step 2: Verify documentation consistency**

Run:

```powershell
rg -n "Netlify|NETLIFY_|GitHub Pages|github.io" docs/deployment.md .github/workflows/update-etf-data.yml
```

Expected: no Netlify or `NETLIFY_` references; Pages URL and workflow actions are present.

- [ ] **Step 3: Commit the documentation**

```powershell
git add docs/deployment.md
git commit -m "Document GitHub Pages deployment"
```

### Task 4: Verify, publish, and validate production

**Files:**
- Verify: all changed files and generated `dist/`

**Interfaces:**
- Consumes: committed migration on local `main`.
- Produces: pushed workflow and a verified public Pages deployment.

- [ ] **Step 1: Run the complete local verification suite**

Run:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node tests/web_dashboard.test.js
node tests/web_style.test.js
node tests/deploy_config.test.js
.\.venv\Scripts\python.exe scripts/build_static_site.py
```

Expected: all Python and Node tests pass and the static build exits with code 0.

- [ ] **Step 2: Verify the artifact contains no secrets or local logs**

Run:

```powershell
rg -n "NETLIFY_AUTH_TOKEN|nfp_" dist
Get-ChildItem dist -Recurse -Filter scheduled_update.log
```

Expected: both commands return no matches.

- [ ] **Step 3: Push `main`**

```powershell
git status --short --branch
git push origin main
```

Expected: push succeeds and `main` is synchronized with `origin/main`.

- [ ] **Step 4: Enable Pages publishing source**

In GitHub, open `Settings > Pages` and set `Source` to `GitHub Actions` if it is not already selected.

- [ ] **Step 5: Trigger and inspect the workflow**

Run `Update ETF data` with `workflow_dispatch`. Confirm `update-data` and
`deploy-pages` both complete successfully.

- [ ] **Step 6: Verify the public dashboard**

Request `https://zihengniu9.github.io/etf-rotation-desk/web/` and verify HTTP
200. Compare its displayed update timestamp with `outputs/etf_update_status.csv`.
