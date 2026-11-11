<#
.SYNOPSIS
    Starts the Hire-Steward personal candidate workspace with strict safety guards.
.DESCRIPTION
    Validates Docker and PostgreSQL container readiness, verifies jobpilot_workspace
    reachability and Alembic migration head, sets dedicated local evidence storage,
    and launches the local Uvicorn server bound strictly to loopback (127.0.0.1:8000).
#>

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "      HIRE-STEWARD PERSONAL WORKSPACE LAUNCHER             " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Resolve repository root
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

# 2. Verify Docker is running
Write-Host "[1/7] Checking Docker Engine..." -NoNewline
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Error "Docker is not running. Please start Docker Desktop and retry."
    }
    Write-Host " READY" -ForegroundColor Green
} catch {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Error "Failed to invoke docker CLI: $_"
}

# 3. Check PostgreSQL container
Write-Host "[2/7] Checking PostgreSQL container 'autonomous-job-search-agent-db-1'..." -NoNewline
$containerStatus = docker inspect autonomous-job-search-agent-db-1 --format '{{.State.Status}}' 2>$null
if ($containerStatus -ne "running") {
    Write-Host " NOT RUNNING" -ForegroundColor Yellow
    Write-Host "      Starting container..." -ForegroundColor Gray
    docker start autonomous-job-search-agent-db-1 | Out-Null
    Start-Sleep -Seconds 2
}
$isHealthy = docker inspect autonomous-job-search-agent-db-1 --format '{{.State.Health.Status}}' 2>$null
Write-Host " RUNNING ($isHealthy)" -ForegroundColor Green

# 4. Resolve Database Password from .env safely without printing
$dbPassword = "local_dev_only"
if (Test-Path "$RepoRoot\.env") {
    Get-Content "$RepoRoot\.env" | ForEach-Object {
        if ($_ -match "^\s*POSTGRES_PASSWORD\s*=\s*(.*)$") {
            $dbPassword = $matches[1].Trim()
        }
    }
}
$dbUrl = "postgresql+psycopg://jobpilot:${dbPassword}@127.0.0.1:5432/jobpilot_workspace"

# 5. Check jobpilot_workspace database and Alembic head
Write-Host "[3/7] Verifying workspace database 'jobpilot_workspace'..." -NoNewline
$dbCheckScript = @"
import psycopg
url = 'postgresql://jobpilot:${dbPassword}@127.0.0.1:5432/jobpilot_workspace'
try:
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT version_num FROM alembic_version;')
            v = cur.fetchone()[0]
            print(v)
except Exception as e:
    print('ERROR:' + str(e))
"@
$versionResult = uv run python -c $dbCheckScript 2>&1
if ($versionResult -like "*ERROR*") {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Error "Cannot reach jobpilot_workspace: $versionResult"
}
$alembicVersion = $versionResult.Trim()
if ($alembicVersion -ne "0010_background_tasks") {
    Write-Host " MIGRATION PENDING" -ForegroundColor Yellow
    Write-Host "      Current version: $alembicVersion. Upgrading to head..." -ForegroundColor Gray
    $env:DATABASE_URL = $dbUrl
    uv run --locked alembic upgrade head
} else {
    Write-Host " HEAD ($alembicVersion)" -ForegroundColor Green
}

# 6. Configure dedicated Evidence Storage outside the repository
Write-Host "[4/7] Configuring dedicated evidence storage..." -NoNewline
$evidenceRoot = Join-Path $env:LOCALAPPDATA "HireSteward\workspace\evidence"
if (-not (Test-Path $evidenceRoot)) {
    New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null
}
$env:EVIDENCE_STORAGE_ROOT = $evidenceRoot
Write-Host " CONFIGURED" -ForegroundColor Green
Write-Host "      Storage Path: $evidenceRoot" -ForegroundColor DarkGray

# 7. Check if port is already occupied
Write-Host "[5/7] Checking port $Port availability..." -NoNewline
$existingConn = Get-NetTCPConnection -LocalPort $Port -LocalAddress $HostAddress -ErrorAction SilentlyContinue
$pidFile = Join-Path $env:LOCALAPPDATA "HireSteward\workspace\server.pid"
if ($existingConn) {
    $existingPid = $existingConn.OwningProcess
    Write-Host " OCCUPIED" -ForegroundColor Yellow
    Write-Host "      Process PID $existingPid is currently listening on http://${HostAddress}:${Port}" -ForegroundColor Gray
    Write-Host "      Checking server identity..." -ForegroundColor Gray
    try {
        $statusResp = Invoke-RestMethod -Uri "http://${HostAddress}:${Port}/api/v1/system/status" -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($statusResp.status -eq "healthy") {
            Write-Host "      Existing Hire-Steward instance is healthy and running." -ForegroundColor Green
            Write-Host "`n>>> WORKSPACE READY AT: http://${HostAddress}:${Port}/ <<<`n" -ForegroundColor Cyan
            return
        }
    } catch {
        Write-Warning "Port $Port is occupied by PID $existingPid which did not respond to system health check."
    }
} else {
    Write-Host " AVAILABLE" -ForegroundColor Green
}

# 8. Start Uvicorn bound strictly to loopback
Write-Host "[6/7] Starting Uvicorn on ${HostAddress}:${Port}..." -NoNewline
$env:DATABASE_URL = $dbUrl
$env:PYTHONPATH = $RepoRoot

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = "uv.exe"
$startInfo.Arguments = "run --locked uvicorn backend.app.main:app --host $HostAddress --port $Port"
$startInfo.WorkingDirectory = $RepoRoot
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.EnvironmentVariables["DATABASE_URL"] = $dbUrl
$startInfo.EnvironmentVariables["EVIDENCE_STORAGE_ROOT"] = $evidenceRoot
$startInfo.EnvironmentVariables["PYTHONPATH"] = $RepoRoot

$serverProcess = [System.Diagnostics.Process]::Start($startInfo)
if ($serverProcess) {
    $serverPid = $serverProcess.Id
    Set-Content -Path $pidFile -Value $serverPid -Force
    Write-Host " STARTED (PID: $serverPid)" -ForegroundColor Green
} else {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Error "Failed to launch Uvicorn server process."
}

# 9. Verify server health
Write-Host "[7/7] Verifying workspace health and readiness..." -NoNewline
$maxAttempts = 15
$attempt = 0
$serverReady = $false

while ($attempt -lt $maxAttempts -and -not $serverReady) {
    Start-Sleep -Milliseconds 600
    $attempt++
    try {
        $ready = Invoke-RestMethod -Uri "http://${HostAddress}:${Port}/ready" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($ready.status -eq "ready" -or $ready.database -eq "connected") {
            $serverReady = $true
        }
    } catch {
        # Retry until available
    }
}

if ($serverReady) {
    Write-Host " ONLINE" -ForegroundColor Green
    Write-Host "`n============================================================" -ForegroundColor Cyan
    Write-Host "  HIRE-STEWARD PERSONAL WORKSPACE READY                     " -ForegroundColor Green
    Write-Host "  Local URL:        http://${HostAddress}:${Port}/          " -ForegroundColor White
    Write-Host "  Database:         jobpilot_workspace                      " -ForegroundColor White
    Write-Host "  Storage:          $evidenceRoot                           " -ForegroundColor White
    Write-Host "  Server PID:       $serverPid                              " -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Cyan
} else {
    Write-Host " TIMEOUT" -ForegroundColor Red
    Write-Warning "Server did not respond to /ready within 10 seconds. Check PID $serverPid."
}
