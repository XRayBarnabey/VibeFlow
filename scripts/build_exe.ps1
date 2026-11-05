# VibeFlow - builds a standalone Windows executable.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Environnement introuvable. Lancez d'abord .\scripts\setup.ps1."
    exit 1
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or
    -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Error "FFmpeg et ffprobe doivent etre disponibles dans le PATH."
    exit 1
}

Write-Host "Installation de PyInstaller..." -ForegroundColor Cyan
& $python -m pip install --quiet "pyinstaller>=6.10"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Construction de VibeFlow.exe..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean VibeFlow.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $root "dist\VibeFlow.exe"
if (-not (Test-Path $exe)) {
    Write-Error "L'executable n'a pas ete cree."
    exit 1
}

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ""
Write-Host "Executable cree : $exe ($size Mo)" -ForegroundColor Green
