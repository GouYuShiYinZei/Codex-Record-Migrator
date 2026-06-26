param(
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Exe = Join-Path $Root "build\main.dist\CodexRecordMigrator.exe"
if (-not (Test-Path $Exe)) {
    throw "Nuitka output not found. Run .\build.ps1 first."
}

if (-not $IsccPath) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $IsccPath = $cmd.Source
    }
}

if (-not $IsccPath) {
    $ProgramFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $ProgramFiles = [Environment]::GetFolderPath("ProgramFiles")
    $LocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $candidates = @(
        (Join-Path $LocalAppData "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path $ProgramFilesX86 "Inno Setup 6\ISCC.exe"),
        (Join-Path $ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            $IsccPath = $candidate
            break
        }
    }
}

if (-not $IsccPath) {
    throw "ISCC.exe was not found. Install Inno Setup 6 or pass -IsccPath."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
& $IsccPath (Join-Path $Root "installer\codex-record-migrator.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
}
Write-Host "Installer output: $Root\dist"
