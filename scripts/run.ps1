# VibeFlow — lancement
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Environnement introuvable. Exécutez d'abord .\scripts\setup.ps1" -ForegroundColor Yellow
    exit 1
}

& $venvPython -m vibeflow
exit $LASTEXITCODE
