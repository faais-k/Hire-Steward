<#
.SYNOPSIS
    Stops the Hire-Steward personal workspace server cleanly.
.DESCRIPTION
    Terminates only the local Uvicorn process associated with the workspace.
    Explicitly preserves Docker containers, PostgreSQL databases, and data volumes.
#>

[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       HIRE-STEWARD WORKSPACE SHUTDOWN                      " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$pidFile = Join-Path $env:LOCALAPPDATA "HireSteward\workspace\server.pid"
$stopped = $false

# 1. Check PID file first
if (Test-Path $pidFile) {
    $recordedPid = (Get-Content $pidFile -ErrorAction SilentlyContinue).Trim()
    if ($recordedPid -match "^\d+$") {
        $proc = Get-Process -Id ([int]$recordedPid) -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -match "python|uv") {
            Write-Host "Stopping recorded server process and child processes (PID: $recordedPid)..." -NoNewline
            # Terminate any child processes launched by uv/uvicorn
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ParentProcessId -eq ([int]$recordedPid) } | ForEach-Object {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id ([int]$recordedPid) -Force -ErrorAction SilentlyContinue
            Write-Host " STOPPED" -ForegroundColor Green
            $stopped = $true
        }
    }
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. Check port 8000 listener if not already stopped
if (-not $stopped) {
    $conn = Get-NetTCPConnection -LocalPort $Port -LocalAddress "127.0.0.1" -ErrorAction SilentlyContinue
    if ($conn) {
        $procId = $conn.OwningProcess
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -match "python|uv") {
            Write-Host "Stopping process on port $Port (PID: $procId, Name: $($proc.ProcessName))..." -NoNewline
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host " STOPPED" -ForegroundColor Green
            $stopped = $true
        } else {
            Write-Warning "Port $Port is occupied by PID $procId ($($proc.ProcessName)) which is not a recognized workspace process."
        }
    }
}

if ($stopped) {
    Write-Host "`nWorkspace application stopped cleanly." -ForegroundColor Green
    Write-Host "Note: PostgreSQL container and Docker volumes remain intact and running." -ForegroundColor Gray
} else {
    Write-Host "`nNo active workspace process found listening on port $Port." -ForegroundColor Yellow
}
