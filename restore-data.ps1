<#
.SYNOPSIS
    Restores a Hire-Steward personal data backup into a separate database or runs a recovery drill.
.DESCRIPTION
    Safely validates a backup package, its cryptographic manifest, and restores
    into an isolated drill database or a specified new separate database.
    Supports secure hidden interactive passphrase input for encrypted backups.
    NEVER overwrites existing databases (jobpilot, jobpilot_test, jobpilot_e2e, jobpilot_workspace).
#>

[CmdletBinding()]
param(
    [string]$BackupDir = "",
    [string]$TargetDatabase = "",
    [switch]$Drill = $false,
    [string]$PassphraseEnv = "",
    [switch]$PromptPassphrase = $false
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       HIRE-STEWARD DATA RESTORE & DRILL UTILITY            " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

$cleanUpPass = $false
if ($PromptPassphrase -and [string]::IsNullOrWhiteSpace($env:HIRE_STEWARD_BACKUP_PASSPHRASE) -and [string]::IsNullOrWhiteSpace($PassphraseEnv)) {
    $sec = Read-Host -Prompt "Enter backup decryption passphrase (hidden)" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    if (-not [string]::IsNullOrEmpty($plain)) {
        $env:HIRE_STEWARD_BACKUP_PASSPHRASE = $plain
        $cleanUpPass = $true
    }
}

try {
    if ($Drill -or [string]::IsNullOrWhiteSpace($TargetDatabase)) {
        $cmdArgs = @("run", "python", "-m", "backend.app.backup_cli", "drill")
        if (-not [string]::IsNullOrWhiteSpace($BackupDir)) {
            $cmdArgs += @("--backup-dir", $BackupDir)
        }
        if (-not [string]::IsNullOrWhiteSpace($PassphraseEnv)) {
            $cmdArgs += @("--passphrase-env", $PassphraseEnv)
        }
    } else {
        $cmdArgs = @("run", "python", "-m", "backend.app.backup_cli", "restore", "--target-database", $TargetDatabase)
        if (-not [string]::IsNullOrWhiteSpace($BackupDir)) {
            $cmdArgs += @("--backup-dir", $BackupDir)
        }
        if (-not [string]::IsNullOrWhiteSpace($PassphraseEnv)) {
            $cmdArgs += @("--passphrase-env", $PassphraseEnv)
        }
    }

    uv @cmdArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "  OPERATION COMPLETED SUCCESSFULLY                          " -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Cyan
    } else {
        Write-Error "Restore operation failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($cleanUpPass) {
        $env:HIRE_STEWARD_BACKUP_PASSPHRASE = $null
    }
}
