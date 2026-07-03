param(
  [string]$TaskName = "ETF Rotation Daily Update",
  [string]$Time = "14:30",
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$UpdateScript = Join-Path $ProjectRoot "scripts\update_etf_data.ps1"
if (-not (Test-Path -LiteralPath $UpdateScript)) {
  throw "Update script not found: $UpdateScript"
}

$at = [datetime]::ParseExact($Time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
$arguments = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$UpdateScript`"",
  "-ProjectRoot", "`"$ProjectRoot`"",
  "-Python", "`"$Python`""
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Refresh ETF rotation data and backtest outputs every day at $Time." `
  -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' at $Time."
Write-Host "Manual run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`""
