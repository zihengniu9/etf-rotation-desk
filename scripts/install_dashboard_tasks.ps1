param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "",
  [string]$MorningTime = "09:28",
  [string[]]$IntradayTimes = @("10:00", "11:30", "14:00"),
  [string]$CloseTime = "16:20"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$Runner = Join-Path $ProjectRoot "scripts\update_dashboard_daily.ps1"
if (-not (Test-Path -LiteralPath $Runner)) { throw "Daily runner not found: $Runner" }

function Register-DashboardTask([string]$Name, [string]$Mode, [string[]]$Times) {
  $argumentParts = @(
    '-NoProfile'
    '-ExecutionPolicy'
    'Bypass'
    '-File'
    ('"{0}"' -f $Runner)
    '-Mode'
    $Mode
    '-ProjectRoot'
    ('"{0}"' -f $ProjectRoot)
    '-Push'
  )
  if ($Python) { $argumentParts += @('-Python', ('"{0}"' -f $Python)) }
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($argumentParts -join " ")
  $triggers = foreach ($time in $Times) {
    $at = [datetime]::ParseExact($time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
    New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $at
  }
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings `
    -Description "AI stock dashboard $Mode update; verifies tun, refreshes data, and pushes GitHub." -Force | Out-Null
}

Register-DashboardTask "AI Stock Dashboard Morning" "Morning" @($MorningTime)
Register-DashboardTask "AI Stock Dashboard Intraday" "Intraday" $IntradayTimes
Register-DashboardTask "AI Stock Dashboard Close" "Close" @($CloseTime)

Write-Host "Installed dashboard tasks:"
Write-Host "- Morning:  $MorningTime"
Write-Host "- Intraday: $($IntradayTimes -join ', ')"
Write-Host "- Close:    $CloseTime"
Write-Host 'Each task verifies IWENCAI_API_KEY and tun before making HTTPS requests.'
