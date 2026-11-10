<#
.SYNOPSIS
    Creates a verified, timestamped backup of the Hire-Steward source code.
.DESCRIPTION
    Safely copies project source files, tests, migrations, frontend assets,
    and documentation to $env:LOCALAPPDATA\HireSteward\backups\backup_<timestamp>.
    Excludes .git, .env, virtual environments, caches, and database files.
    Generates a full manifest and independently verifies every file against SHA-256.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       HIRE-STEWARD VERIFIED SOURCE CODE BACKUP             " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

$backupScript = Join-Path $RepoRoot "scratch\create_verified_backup.py"
if (-not (Test-Path $backupScript)) {
    Write-Error "Backup helper script not found at $backupScript"
}

Write-Host "Executing verified backup pipeline..." -ForegroundColor Gray
uv run python -u $backupScript

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nSource-code backup completed and 100% verified against SHA-256!" -ForegroundColor Green
} else {
    Write-Error "Source-code backup failed with exit code $LASTEXITCODE."
}
