param(
  [ValidateSet("Morning", "Intraday", "Close", "Full")]
  [string]$Mode = "Full",
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "",
  [string]$ShorttermRoot = "C:\Users\69449\WorkBuddy\2026-08-22-20-19-58\dashboard",
  [string]$TunnelProxy = "http://127.0.0.1:7897",
  [switch]$Push
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $Python) {
  $bundledPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  $Python = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { "python" }
}
$LogDir = Join-Path $ProjectRoot "outputs"
$LogPath = Join-Path $LogDir "dashboard_daily_update.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $ProjectRoot

function Write-RunLog([string]$Message) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  $line | Tee-Object -FilePath $LogPath -Append
}

function Get-RequiredEnvironment([string]$Name) {
  $value = [Environment]::GetEnvironmentVariable($Name, "Process")
  if (-not $value) { $value = [Environment]::GetEnvironmentVariable($Name, "User") }
  if (-not $value) { throw "$Name is not configured in the process or user environment" }
  [Environment]::SetEnvironmentVariable($Name, $value, "Process")
}

function Invoke-Step([string]$Label, [string]$File, [string[]]$Arguments) {
  Write-RunLog "START $Label"
  & $File @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit=$LASTEXITCODE" }
  Write-RunLog "DONE  $Label"
}

function Test-Tunnel {
  $uri = [uri]$TunnelProxy
  $probe = Test-NetConnection $uri.Host -Port $uri.Port -WarningAction SilentlyContinue
  if (-not $probe.TcpTestSucceeded) { throw "tun tunnel is not listening at $TunnelProxy" }
  $status = & curl.exe --proxy $TunnelProxy --ssl-no-revoke --connect-timeout 15 --max-time 30 -sS -o NUL -w "%{http_code}" https://openapi.iwencai.com
  if ($LASTEXITCODE -ne 0 -or -not $status -or $status -eq "000") {
    throw "tun HTTPS verification failed at $TunnelProxy (status=$status)"
  }
  Write-RunLog "tun verified via HTTPS (endpoint status=$status)"
}

function Get-HongKongDate {
  $tz = [TimeZoneInfo]::FindSystemTimeZoneById("China Standard Time")
  return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz).Date
}

function Invoke-Morning([string]$TargetDate) {
  $signal = Join-Path $ShorttermRoot "signal_0925.py"
  if (-not (Test-Path -LiteralPath $signal)) { throw "short-term signal generator not found: $signal" }
  Invoke-Step "short-term 09:25 signal" $Python @($signal, "--date", $TargetDate)
  Invoke-Step "dashboard status" $Python @("scripts/build_dashboard_status.py")
  Invoke-Step "static site build" $Python @("scripts/build_static_site.py")
}

function Invoke-Intraday([string]$TargetDate) {
  Invoke-Step "ETF rotation" "powershell.exe" @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/update_etf_data.ps1",
    "-ProjectRoot", $ProjectRoot, "-Python", $Python, "-MaxAttempts", "1"
  )
  Invoke-Step "industry mainline" $Python @("scripts/update_industry_data.py", "--refresh", "--as-of", $TargetDate)
  Invoke-Step "industry stock roles" $Python @("scripts/update_industry_stock_roles.py")
  Invoke-Step "dashboard status" $Python @("scripts/build_dashboard_status.py")
  Invoke-Step "static site build" $Python @("scripts/build_static_site.py")
}

function Invoke-Close([string]$TargetDate) {
  $reviewClose = Join-Path $ShorttermRoot "review_close.py"
  $buildFactors = Join-Path $ShorttermRoot "research\build_factors.py"
  if (-not (Test-Path -LiteralPath $reviewClose)) { throw "short-term close reviewer not found: $reviewClose" }
  if (-not (Test-Path -LiteralPath $buildFactors)) { throw "short-term factor builder not found: $buildFactors" }

  Invoke-Step "short-term close review" $Python @($reviewClose, "--date", $TargetDate, "--force")
  Invoke-Step "short-term close factors" $Python @($buildFactors, "--date", $TargetDate)
  Invoke-Step "latest market review" $Python @("scripts/update_latest_review.py", "--as-of", $TargetDate)
  Invoke-Step "trend current cross-section" $Python @(
    "scripts/run_wencai_trend_analysis.py", "--as-of", $TargetDate,
    "--history-input", "outputs/trend_history.csv.gz"
  )
  Invoke-Step "industry mainline" $Python @("scripts/update_industry_data.py", "--refresh", "--as-of", $TargetDate)
  Invoke-Step "industry stock roles" $Python @("scripts/update_industry_stock_roles.py")
  Invoke-Step "ETF rotation" "powershell.exe" @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/update_etf_data.ps1",
    "-ProjectRoot", $ProjectRoot, "-Python", $Python, "-MaxAttempts", "1"
  )
  Invoke-Step "dividend quality" $Python @("scripts/update_dividend_factor.py", "--as-of", $TargetDate)
  Invoke-Step "short-term live snapshot" $Python @("scripts/build_shortterm_live.py")
  Invoke-Step "short-term rule plan" $Python @("scripts/build_shortterm_plan.py")
  Invoke-Step "dashboard status" $Python @("scripts/build_dashboard_status.py")
  Invoke-Step "static site build" $Python @("scripts/build_static_site.py")
}

function Push-Outputs([string]$TargetDate, [string]$RunMode) {
  Write-RunLog "START git publish"
  & git add -- outputs
  if ($LASTEXITCODE -ne 0) { throw "git add outputs failed" }
  & git diff --cached --quiet
  if ($LASTEXITCODE -eq 0) {
    Write-RunLog "No generated output changes to publish"
    return
  }
  & git config user.name "AI Stock Dashboard Bot"
  & git config user.email "dashboard-bot@users.noreply.github.com"
  & git commit -m "Update dashboard data $TargetDate ($($RunMode.ToLowerInvariant()))"
  if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
  & git pull --rebase origin main
  if ($LASTEXITCODE -ne 0) { throw "git pull --rebase failed; automatic push stopped" }
  & git push origin HEAD:main
  if ($LASTEXITCODE -ne 0) { throw "git push failed" }
  Write-RunLog "DONE  git publish"
}

try {
  Write-RunLog "dashboard update mode=$Mode"
  Get-RequiredEnvironment "IWENCAI_API_KEY"
  $baseUrl = [Environment]::GetEnvironmentVariable("IWENCAI_BASE_URL", "Process")
  if (-not $baseUrl) { $baseUrl = [Environment]::GetEnvironmentVariable("IWENCAI_BASE_URL", "User") }
  if (-not $baseUrl) { $baseUrl = "https://openapi.iwencai.com" }
  $env:IWENCAI_BASE_URL = $baseUrl
  $env:HTTPS_PROXY = $TunnelProxy
  $env:HTTP_PROXY = $TunnelProxy
  $env:PYTHONPATH = Join-Path $ProjectRoot "src"
  $env:PYTHONIOENCODING = "utf-8"
  Test-Tunnel

  $target = Get-HongKongDate
  if ($target.DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)) {
    Write-RunLog "Weekend detected; no market-data mutation"
    exit 0
  }
  $targetDate = $target.ToString("yyyy-MM-dd")
  if ($Mode -in @("Morning", "Full")) { Invoke-Morning $targetDate }
  if ($Mode -eq "Intraday") { Invoke-Intraday $targetDate }
  if ($Mode -in @("Close", "Full")) { Invoke-Close $targetDate }
  if ($Push) { Push-Outputs $targetDate $Mode }
  Write-RunLog "dashboard update completed"
} catch {
  Write-RunLog ("FAILED " + $_.Exception.Message)
  throw
}
