param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "",
  [string]$MorningTime = "09:28",
  [string[]]$IntradayTimes = @("09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"),
  [string]$CloseTime = "16:20",
  [string[]]$FinancialTimes = @("09:05", "16:05"),
  [switch]$FinancialOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$Runner = Join-Path $ProjectRoot "scripts\update_dashboard_daily.ps1"
if (-not (Test-Path -LiteralPath $Runner)) { throw "Daily runner not found: $Runner" }
if (-not $Python) { $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe" }
$Python = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$PythonW = Join-Path (Split-Path -Parent $Python) "pythonw.exe"
$Wrapper = Join-Path $ProjectRoot "scripts\run_dashboard_step.py"
foreach ($file in @($PythonW, $Wrapper)) {
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing windowless launcher: $file" }
}

function Register-DashboardTask([string]$Name, [string]$Mode, [string[]]$Times) {
  $argumentParts = @(
    ('"{0}"' -f $Wrapper)
    '--log'
    ('"{0}"' -f (Join-Path $ProjectRoot "outputs\task_$Mode.log"))
    '--timeout'
    '7150'
    '--'
    ('"{0}"' -f (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"))
    '-NoProfile'
    '-NonInteractive'
    '-WindowStyle'
    'Hidden'
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
  $action = New-ScheduledTaskAction -Execute $PythonW -WorkingDirectory $ProjectRoot -Argument ($argumentParts -join " ")
  $triggers = foreach ($time in $Times) {
    $at = [datetime]::ParseExact($time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
    New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $at
  }
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings `
    -Description "AI stock dashboard $Mode update; verifies tun, refreshes data, and pushes GitHub." -Force | Out-Null
}

if (-not $FinancialOnly) {
  Register-DashboardTask "AI Stock Dashboard Morning" "Morning" @($MorningTime)
  Register-DashboardTask "AI Stock Dashboard Intraday" "Intraday" $IntradayTimes
  Register-DashboardTask "AI Stock Dashboard Close" "Close" @($CloseTime)
}
Register-DashboardTask "AI Stock Dashboard Financials" "Financials" $FinancialTimes

Write-Host "Installed dashboard tasks:"
if (-not $FinancialOnly) {
  Write-Host "- Morning:  $MorningTime"
  Write-Host "- Intraday: $($IntradayTimes -join ', ')"
  Write-Host "- Close:    $CloseTime"
}
Write-Host "- Financials: $($FinancialTimes -join ', ')"
Write-Host 'Each task verifies IWENCAI_API_KEY and tun before making HTTPS requests.'
