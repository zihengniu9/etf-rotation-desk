# ETF Dashboard Deployment

This project is a static dashboard backed by CSV files in `outputs/`.

## GitHub Pages deployment

GitHub Actions only validates and publishes the static bundle. It does not
collect market data because the data source requires the authenticated local
tun tunnel on the Windows machine. The workflow in
`.github/workflows/deploy-pages.yml` runs after changes reach `main` and
publishes `index.html`, `web/`, and generated `outputs/` files.

One-time setup:

1. Open repository `Settings > Pages`.
2. Under `Build and deployment`, set `Source` to `GitHub Actions`.

Public URL: `https://zihengniu9.github.io/etf-rotation-desk/web/`

The repository, dashboard, and generated CSV files are public. GitHub Secrets
are not copied into the static artifact. The public page root redirects to
`./web/` so it works under the repository path used by GitHub Pages.

## Local Windows schedule

Install the local task:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_dashboard_tasks.ps1
```

Run the complete dashboard update manually:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update_dashboard_daily.ps1 -Mode Full -Push
```

For an ETF-only refresh, use `scripts\update_etf_data.ps1`.

The unified tasks run hidden and non-interactively. Morning runs at 09:28,
intraday runs every half hour in the trading sessions (09:30-11:30 and
13:00-15:00), and the full close bundle runs at 16:20, weekdays only.
Battery power does not cancel updates. Failed or busy runs retry after five
minutes, up to three times; a per-project lock prevents overlapping writes.
Changes to the installer take effect only after rerunning it on the collector.

Each collection step captures stdout and stderr in a local
`outputs/dashboard_step_*.log` file, has a 20-minute deadline, and terminates
its process tree on timeout. These logs are excluded from the public bundle.
Python UTF-8 mode is set for collectors and their nested subprocesses; setting
only PYTHONIOENCODING does not fix Windows' default GBK subprocess decoding.
The close runner reads the 09:25 signal JSON through UTF-8 aware Python code,
so Chinese signal payloads cannot stop the close bundle. If an independent
module still fails, the other modules continue and publish their fresh
outputs; the run records the failure and returns a non-zero result so the
scheduled task retries it.
If a scheduler run ends without DONE or FAILED in the main log, inspect its
LastTaskResult as well: external termination may prevent exception logging.

Logs are appended to `outputs/scheduled_update.log` and
`outputs/dashboard_daily_update.log`. The unified runner retries Git pull/push
transient failures up to three times. Publication merges committed data and
remote changes in a temporary clone, so a merge failure cannot leave the live
collector in a detached HEAD or unfinished rebase. JSON-only JS fallbacks are
regenerated from their unconflicted JSON source; actual source-data conflicts
stop publication and preserve both sides. All three tasks share a process lock.

Retry an already collected snapshot (including weekends, without API access):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update_dashboard_daily.ps1 -Mode PublishOnly -Push
```

An unchanged output directory still retries unpublished commits. The machine
must be awake with the configured user session and tunnel available for data
collection; GitHub Pages does not run the collector.
