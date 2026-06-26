param(
    [string]$Python = "python",
    [switch]$InstallDeps,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($InstallDeps) {
    & $Python -m pip install -r requirements-build.txt
}

if ($Clean -and (Test-Path ".\build")) {
    Remove-Item -LiteralPath ".\build" -Recurse -Force
}

& $Python -m nuitka `
    --standalone `
    --assume-yes-for-downloads `
    --enable-plugin=tk-inter `
    --windows-console-mode=disable `
    --include-package=codex_migrator `
    --output-dir=build `
    --output-filename=CodexRecordMigrator.exe `
    main.py

Write-Host "Nuitka build output: $Root\build\main.dist\CodexRecordMigrator.exe"
