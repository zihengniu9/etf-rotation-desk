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
6. Deploys `dist/` to Netlify production.

To use it:

1. Create or link a Netlify site.
2. Add GitHub repository secrets:
   - `NETLIFY_AUTH_TOKEN`
   - `NETLIFY_SITE_ID`
3. Push the repository to GitHub.
4. Run the workflow manually once from the Actions tab, or wait for the next trading-hours slot.

The public page root redirects to `/web/`.

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
