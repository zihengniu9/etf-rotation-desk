# AI Low-Buy Stock Selector

Minimal research CLI for screening Tonghuashun hot stocks (`883910`) whose MA5 is consistently rising, whose latest close is close to MA5, and whose recent pullback is not obvious.

Run tests:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

Run a live smoke test:

```powershell
python run_selector.py --board-code 883910 --top 20 --output outputs/picks.csv
```

This is a research filter, not investment advice.

## ETF dashboard automation

Run the ETF dashboard update once:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update_etf_data.ps1
```

Install a local Windows scheduled task for 09:00 every day:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
```

For online deployment, push this repository to GitHub and add
`NETLIFY_AUTH_TOKEN` plus `NETLIFY_SITE_ID` as repository secrets.
`.github/workflows/update-etf-data.yml` runs at 09:00 Asia/Hong_Kong on weekdays,
refreshes `outputs/`, commits the updated data, and deploys the static dashboard
to Netlify.
