param(
  [string]$TaskName = "ETF Rotation Daily Update",
  [Alias("Time")]
  [string[]]$Times = @("09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"),
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

$arguments = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$UpdateScript`"",
  "-ProjectRoot", "`"$ProjectRoot`"",
  "-Python", "`"$Python`""
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$triggers = foreach ($time in $Times) {
  $at = [datetime]::ParseExact($time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
  New-ScheduledTaskTrigger -Daily -At $at
}
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $triggers `
  -Settings $settings `
  -Description "Refresh ETF rotation data and backtest outputs at: $($Times -join ', ')." `
  -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' at: $($Times -join ', ')."
Write-Host "Manual run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`""
