# GitHub Pages Migration Design

## Goal

Move the ETF dashboard's production hosting from Netlify to GitHub Pages while
preserving the existing intraday update schedule and historical CSV records.
The published dashboard must remain publicly accessible and must not expose
deployment credentials.

## Public Access

The repository and GitHub Pages site are public. Anyone with the Pages URL can
view the dashboard, and the repository's source code and CSV outputs remain
publicly readable. GitHub Actions secrets are not copied into the static site or
Pages artifact.

The expected production URL is:

`https://zihengniu9.github.io/etf-rotation-desk/web/`

## Architecture

The existing scheduled workflow remains responsible for the full data refresh:

1. Run every 30 minutes during A-share trading hours on weekdays.
2. Generate the ETF CSV outputs.
3. Run Python and web verification.
4. Commit changed `outputs/` files so historical records remain in Git.
5. Build the static `dist/` artifact.
6. Upload `dist/` as a GitHub Pages artifact.
7. Deploy the artifact to the `github-pages` environment.

Netlify authentication, preflight checks, and production deployment are removed
from the scheduled workflow. The site no longer consumes Netlify production
deployment credits.

## Workflow Boundaries

Use two jobs in the existing workflow:

- `update-data` generates, verifies, commits, builds, and uploads the Pages
  artifact. It requires `contents: write` so the generated CSV history can be
  committed.
- `deploy-pages` depends on `update-data` and publishes the uploaded artifact.
  It requires only `pages: write` and `id-token: write`, and targets the
  `github-pages` environment.

The deployment job must not run when data generation, verification, or the
static build fails. A failed deployment must not delete or rewrite previously
published Pages content.

## Static Site Compatibility

Keep the current artifact layout:

- `/index.html` redirects to `./web/`.
- `/web/index.html` loads the dashboard.
- `/web/app.js` reads `../outputs/*.csv`.
- `/outputs/*.csv` contains the generated data.

These relative paths work under the repository subpath used by GitHub Pages, so
the frontend does not need a data-source rewrite.

Add a `.nojekyll` file to the built artifact so GitHub Pages serves the static
files exactly as generated.

## One-Time Repository Setting

GitHub Pages must be enabled with `Settings > Pages > Build and deployment >
Source: GitHub Actions`. This is an administrator setting and is the only
manual setup step. The `github-pages` environment is then managed by the Pages
deployment workflow.

## Verification

Update the deployment configuration test to verify:

- The workflow grants the required Pages permissions.
- The workflow configures, uploads, and deploys a Pages artifact.
- The artifact path is `dist`.
- Netlify secrets and deploy commands are absent.
- The build creates `.nojekyll` and retains the existing site and CSV layout.

Run all existing Python tests, web tests, deployment configuration tests, and a
local static build before pushing the migration.

After pushing, manually trigger `Update ETF data` once and verify:

- Both workflow jobs succeed.
- The Pages URL returns HTTP 200.
- The dashboard update timestamp matches the latest committed output.
- A subsequent scheduled run publishes without any Netlify step.

## Documentation

Update `docs/deployment.md` to describe GitHub Pages as the production target,
remove Netlify secret setup, document public visibility, and retain the local
Windows scheduling instructions.
