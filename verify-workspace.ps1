<#
.SYNOPSIS
    Performs comprehensive verification of the Hire-Steward personal workspace.
.DESCRIPTION
    Audits Docker container health, PostgreSQL database reachability, Alembic
    revision head, dedicated evidence storage accessibility, loopback binding,
    application health, and zero-spend AI provider configurations.
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       HIRE-STEWARD WORKSPACE VERIFICATION SUITE            " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$allPassed = $true

function Report-Check {
    param(
        [string]$Name,
        [bool]$Success,
        [string]$Details = ""
    )
    if ($Success) {
        Write-Host "  [PASS] $Name" -ForegroundColor Green
        if ($Details) { Write-Host "         $Details" -ForegroundColor DarkGray }
    } else {
        Write-Host "  [FAIL] $Name" -ForegroundColor Red
        if ($Details) { Write-Host "         ERROR: $Details" -ForegroundColor Yellow }
        $script:allPassed = $false
    }
}

# 1. Docker Status
$dockerRunning = $false
try {
    $dockerInfo = docker info 2>$null
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch {}
Report-Check "Docker Engine running" $dockerRunning

# 2. PostgreSQL Container
$containerHealthy = $false
try {
    $health = docker inspect autonomous-job-search-agent-db-1 --format '{{.State.Health.Status}}' 2>$null
    if ($health -eq "healthy") { $containerHealthy = $true }
} catch {}
Report-Check "PostgreSQL container healthy" $containerHealthy "Container: autonomous-job-search-agent-db-1"

# 3. Workspace Database Reachability & Migration
$dbPassed = $false
$dbDetail = ""
try {
    $checkCmd = @"
import psycopg
url = 'postgresql://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_workspace'
try:
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT version_num FROM alembic_version;')
            v = cur.fetchone()[0]
            print(f'VERSION:{v}')
except Exception as e:
    print(f'ERROR:{e}')
"@
    $res = uv run python -c $checkCmd 2>&1
    if ($res -match "VERSION:(.*)") {
        $ver = $matches[1].Trim()
        if ($ver -eq "0009_binary_docs_attempts") {
            $dbPassed = $true
            $dbDetail = "Head version: $ver"
        } else {
            $dbDetail = "Unexpected migration version: $ver"
        }
    } else {
        $dbDetail = $res
    }
} catch {
    $dbDetail = $_.ToString()
}
Report-Check "Database 'jobpilot_workspace' migration head" $dbPassed $dbDetail

# 4. Evidence Storage Configuration & Permissions
$storagePassed = $false
$storageDetail = ""
$evidencePath = Join-Path $env:LOCALAPPDATA "HireSteward\workspace\evidence"
try {
    if (Test-Path $evidencePath) {
        $probeFile = Join-Path $evidencePath "probe.tmp"
        Set-Content -Path $probeFile -Value "storage-probe" -Force
        $readContent = Get-Content -Path $probeFile -Raw
        Remove-Item -Path $probeFile -Force
        if ($readContent.Trim() -eq "storage-probe") {
            $storagePassed = $true
            $storageDetail = "Path: $evidencePath (Writable)"
        } else {
            $storageDetail = "Read/Write mismatch"
        }
    } else {
        $storageDetail = "Directory does not exist: $evidencePath"
    }
} catch {
    $storageDetail = $_.ToString()
}
Report-Check "Evidence Storage isolation & permissions" $storagePassed $storageDetail

# 5. Application Liveness (/health)
$livenessPassed = $false
$livenessDetail = ""
try {
    $healthResp = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($healthResp.status -eq "ok") {
        $livenessPassed = $true
        $livenessDetail = "Liveness: ok"
    } else {
        $livenessDetail = "Unexpected health response: $($healthResp | ConvertTo-Json -Compress)"
    }
} catch {
    $livenessDetail = "Could not reach $BaseUrl/health: $_"
}
Report-Check "Application Liveness (/health)" $livenessPassed $livenessDetail

# 6. Application Readiness (/ready)
$readinessPassed = $false
$readinessDetail = ""
try {
    $readyResp = Invoke-RestMethod -Uri "$BaseUrl/ready" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($readyResp.status -eq "ready") {
        $readinessPassed = $true
        $readinessDetail = "Status: ready (Schema and migrations verified)"
    } else {
        $readinessDetail = "Readiness degraded: $($readyResp | ConvertTo-Json -Compress)"
    }
} catch {
    $readinessDetail = "Could not reach $BaseUrl/ready: $_"
}
Report-Check "Application Readiness (/ready)" $readinessPassed $readinessDetail

# 7. System Diagnostics & Loopback Enforcement (/api/v1/system/status)
$sysPassed = $false
$sysDetail = ""
try {
    $sysResp = Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/status" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($sysResp.status -eq "healthy" -and $sysResp.loopback_enforced -eq $true) {
        $sysPassed = $true
        $sysDetail = "Status: healthy, Loopback: enforced, Storage: writable"
    } else {
        $sysDetail = "Diagnostics: $($sysResp | ConvertTo-Json -Compress)"
    }
} catch {
    $sysDetail = "Could not reach $BaseUrl/api/v1/system/status: $_"
}
Report-Check "System Diagnostics & Loopback Enforcement" $sysPassed $sysDetail

# 8. AI Provider Safety & Zero-Spend Budget
$aiPassed = $false
$aiDetail = ""
try {
    $aiResp = Invoke-RestMethod -Uri "$BaseUrl/api/v1/ai/status" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($aiResp.paid_ai_enabled -eq $false -and ($aiResp.active_mode -eq "OFFLINE_MOCK" -or $aiResp.provider_mode -eq "OFFLINE_MOCK") -and $aiResp.committed_spend_usd -eq 0.0) {
        $aiPassed = $true
        $aiDetail = "Mode: OFFLINE_MOCK, Paid AI: False, Committed Spend: `$0.00"
    } else {
        $aiDetail = "AI config not pinned to zero-spend: $($aiResp | ConvertTo-Json -Compress)"
    }
} catch {
    $aiDetail = "Could not reach $BaseUrl/api/v1/ai/status: $_"
}
Report-Check "AI Safety & Zero-Spend Mock Guarantees" $aiPassed $aiDetail

Write-Host "============================================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "  RESULT: ALL VERIFICATION CHECKS PASSED                     " -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "  RESULT: ONE OR MORE VERIFICATION CHECKS FAILED             " -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 1
}
