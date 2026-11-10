<#
.SYNOPSIS
    Creates a verified, timestamped backup of the Hire-Steward personal workspace data.
.DESCRIPTION
    Safely dumps the 'jobpilot_workspace' PostgreSQL database using pg_dump custom format (-Fc),
    copies all evidence storage artifacts (original binaries and text extractions),
    and generates an authenticated Encrypt-then-MAC cryptographic manifest when encrypted.
    Supports secure interactive hidden passphrase input so passphrases are never typed in CLI commands.
    Target: $env:LOCALAPPDATA\HireSteward\backups\data_<timestamp>.
#>

[CmdletBinding()]
param(
    [string]$Database = "jobpilot_workspace",
    [switch]$RunDrill = $false,
    [string]$PassphraseEnv = "",
    [switch]$Encrypt = $false
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       HIRE-STEWARD PERSONAL DATA BACKUP                    " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

$cleanUpPass = $false
if ($Encrypt -and [string]::IsNullOrWhiteSpace($env:HIRE_STEWARD_BACKUP_PASSPHRASE) -and [string]::IsNullOrWhiteSpace($PassphraseEnv)) {
    Write-Host "Encrypted backup requested." -ForegroundColor Yellow
    $sec = Read-Host -Prompt "Enter backup encryption passphrase (hidden)" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    if (-not [string]::IsNullOrEmpty($plain)) {
        $env:HIRE_STEWARD_BACKUP_PASSPHRASE = $plain
        $cleanUpPass = $true
    }
}

try {
    $cmdArgs = @("run", "python", "-m", "backend.app.backup_cli", "backup", "--database", $Database)
    if ($RunDrill) {
        $cmdArgs += "--drill"
    }
    if ($Encrypt) {
        $cmdArgs += "--encrypt"
    }
    if (-not [string]::IsNullOrWhiteSpace($PassphraseEnv)) {
        $cmdArgs += @("--passphrase-env", $PassphraseEnv)
    }

    uv @cmdArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "  DATA BACKUP COMPLETED AND VERIFIED                        " -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Cyan
    } else {
        Write-Error "Data backup failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($cleanUpPass) {
        $env:HIRE_STEWARD_BACKUP_PASSPHRASE = $null
    }
}
