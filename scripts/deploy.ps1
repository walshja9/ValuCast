[CmdletBinding()]
param(
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Stop-Deploy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

$branch = (& git branch --show-current 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    Stop-Deploy "Could not determine the current Git branch."
}
if ($branch -ne "master") {
    Stop-Deploy "Deploys must run from branch 'master'; current branch is '$branch'."
}

$workingTreeStatus = @(& git status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) {
    Stop-Deploy "Could not inspect the Git working tree."
}
if (-not [string]::IsNullOrWhiteSpace(($workingTreeStatus -join "`n"))) {
    Stop-Deploy "The working tree is not clean. Commit or remove all changes before deploying."
}

if ($SkipTests) {
    Write-Host "Skipping tests because -SkipTests was supplied."
}
else {
    Write-Host "Running test suite..."
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONPATH = "src;."
    & python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) {
        Stop-Deploy "Test suite failed; deployment aborted."
    }
}

$sha = (& git rev-parse HEAD 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sha)) {
    Stop-Deploy "Could not resolve local HEAD."
}
$shortSha = $sha.Substring(0, 7)
Write-Host "Deploying commit $shortSha..."

& git push origin master
if ($LASTEXITCODE -ne 0) {
    Stop-Deploy "git push origin master failed; deployment aborted."
}

$deployHook = [Environment]::GetEnvironmentVariable("RENDER_DEPLOY_HOOK")
if (-not [string]::IsNullOrWhiteSpace($deployHook)) {
    Write-Host "POSTing to RENDER_DEPLOY_HOOK to trigger Render deployment."
    try {
        $null = Invoke-RestMethod -Uri $deployHook -Method Post -TimeoutSec 30
    }
    catch {
        Write-Warning "Render deploy-hook POST failed; continuing because auto-deploy may already be running."
    }
}
else {
    Write-Host "RENDER_DEPLOY_HOOK is not set. Find it at: Render dashboard -> valucast service -> Settings -> Deploy Hook"
    Write-Host "Render auto-deploy MAY also fire on its own."
}

$readyUrl = "https://valucast.app/health/ready"
$pollIntervalSeconds = 20
$timeoutSeconds = 15 * 60
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$deploymentReady = $false

Write-Host "Polling $readyUrl for commit $shortSha..."
while ($stopwatch.Elapsed.TotalSeconds -lt $timeoutSeconds) {
    $deployedCommit = "-"
    $ready = $false

    try {
        $health = Invoke-RestMethod -Uri $readyUrl -Method Get -TimeoutSec 15
        $deployedCommit = [string]$health.commit
        $ready = [bool]$health.ready
    }
    catch {
        # The endpoint can briefly fail while Render replaces the service.
    }

    $displayCommit = $deployedCommit
    if ($displayCommit.Length -gt 7) {
        $displayCommit = $displayCommit.Substring(0, 7)
    }
    $elapsedSeconds = [int][Math]::Floor($stopwatch.Elapsed.TotalSeconds)
    $readyText = $ready.ToString().ToLowerInvariant()
    Write-Host ("[{0,3}s] commit={1} ready={2}" -f $elapsedSeconds, $displayCommit, $readyText)

    if ($ready -and $deployedCommit -eq $sha) {
        $deploymentReady = $true
        break
    }

    $remainingSeconds = $timeoutSeconds - $stopwatch.Elapsed.TotalSeconds
    if ($remainingSeconds -le 0) {
        break
    }
    $sleepSeconds = [int][Math]::Min($pollIntervalSeconds, [Math]::Ceiling($remainingSeconds))
    Start-Sleep -Seconds $sleepSeconds
}

$stopwatch.Stop()
$totalElapsedSeconds = [int][Math]::Floor($stopwatch.Elapsed.TotalSeconds)
if (-not $deploymentReady) {
    Write-Host "TIMEOUT: valucast.app did not report commit $shortSha as ready within 15 minutes." -ForegroundColor Red
    Write-Host "Manual fallback: Render dashboard -> valucast service -> Manual Deploy -> Deploy latest commit."
    exit 1
}

Write-Host "SUCCESS: valucast.app is ready on commit $sha after ${totalElapsedSeconds}s." -ForegroundColor Green

if (Test-Path -LiteralPath "scripts/smoke_check.py") {
    Write-Host "Running post-deploy smoke check..."
    & python scripts/smoke_check.py https://valucast.app $sha
    if ($LASTEXITCODE -ne 0) {
        Stop-Deploy "Post-deploy smoke check failed."
    }
    Write-Host "Smoke check passed."
}
else {
    Write-Host "Smoke check skipped: scripts/smoke_check.py does not exist."
}

exit 0
