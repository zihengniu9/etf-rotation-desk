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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
```

Run the complete dashboard update manually:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update_dashboard_daily.ps1 -Mode Full -Push
```

For an ETF-only refresh, use `scripts\update_etf_data.ps1`.

Logs are appended to `outputs/scheduled_update.log` and
`outputs/dashboard_daily_update.log`. The unified runner retries Git pull/push
transient failures up to three times and records Git stderr without treating
normal fetch progress as a failure.
