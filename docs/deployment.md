# ETF Dashboard Deployment

This project is a static dashboard backed by CSV files in `outputs/`.

## Cloud schedule

The GitHub Actions workflow at `.github/workflows/update-etf-data.yml` runs at
every 30 minutes during A-share trading hours, using these Asia/Hong_Kong slots:
`09:30`, `10:00`, `10:30`, `11:00`, `11:30`, `13:00`, `13:30`, `14:00`, `14:30`, and `15:00`.

Each run:

1. Installs Python dependencies from `requirements.txt`.
2. Runs `python run_etf_selector.py`.
3. Runs the Python and web checks.
4. Commits refreshed `outputs/` so historical curve records are preserved.
5. Builds `dist/` with `index.html`, `web/`, and `outputs/`.
6. Uploads `dist/` as a GitHub Pages artifact.
7. Publishes the artifact to the public `github-pages` environment.

One-time setup:

1. Open repository `Settings > Pages`.
2. Under `Build and deployment`, set `Source` to `GitHub Actions`.
3. Run `Update ETF data` manually once from the Actions tab.

Public URL: `https://zihengniu9.github.io/etf-rotation-desk/web/`

The repository, dashboard, and generated CSV files are public. GitHub Secrets
are not copied into the static artifact. The public page root redirects to
`./web/` so it works under the repository path used by GitHub Pages.

## Local Windows schedule

Install the local task:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
```

Run once manually:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update_etf_data.ps1
```

Logs are appended to `outputs/scheduled_update.log`. The script retries transient
data-source failures up to three times.
