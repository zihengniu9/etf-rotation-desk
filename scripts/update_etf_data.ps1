param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "python",
  [int]$MaxAttempts = 3,
  [int]$RetryDelaySeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$OutputDir = Join-Path $ProjectRoot "outputs"
$LogPath = Join-Path $OutputDir "scheduled_update.log"
$Runner = Join-Path $ProjectRoot "run_etf_selector.py"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location -LiteralPath $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$startedAt] start ETF scheduled update" | Tee-Object -FilePath $LogPath -Append

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
  $attemptStartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$attemptStartedAt] attempt $attempt/$MaxAttempts" | Tee-Object -FilePath $LogPath -Append

  $stdoutPath = Join-Path $OutputDir "scheduled_update.stdout.tmp"
  $stderrPath = Join-Path $OutputDir "scheduled_update.stderr.tmp"
  Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

  $process = Start-Process `
    -FilePath $Python `
    -ArgumentList @($Runner) `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -NoNewWindow `
    -Wait `
    -PassThru

  if (Test-Path -LiteralPath $stdoutPath) {
    Get-Content -LiteralPath $stdoutPath | Tee-Object -FilePath $LogPath -Append
  }
  if (Test-Path -LiteralPath $stderrPath) {
    Get-Content -LiteralPath $stderrPath | Tee-Object -FilePath $LogPath -Append
  }

  $exitCode = $process.ExitCode
  if ($exitCode -eq 0) {
    $finishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$finishedAt] completed ETF scheduled update" | Tee-Object -FilePath $LogPath -Append
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    exit 0
  }

  $failedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$failedAt] attempt $attempt/$MaxAttempts failed exit=$exitCode" | Tee-Object -FilePath $LogPath -Append
  Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  if ($attempt -lt $MaxAttempts) {
    Start-Sleep -Seconds $RetryDelaySeconds
  }
}

$finishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$finishedAt] failed ETF scheduled update after $MaxAttempts attempts" | Tee-Object -FilePath $LogPath -Append
throw "ETF scheduled update failed after $MaxAttempts attempts"
