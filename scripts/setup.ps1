# VibeFlow — installation locale
# Crée .venv, installe les dépendances, vérifie FFmpeg. Idempotent.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host ""
Write-Host "  VibeFlow — installation" -ForegroundColor Cyan
Write-Host "  -----------------------" -ForegroundColor DarkGray

# 1. Python
$python = $null
foreach ($candidate in @("python", "py -3.12", "py -3")) {
    try {
        $version = & cmd /c "$candidate --version 2>&1"
        if ($version -match "Python 3\.(1[0-9])") {
            $python = $candidate
            Write-Host "  Python    : $version ($candidate)"
            break
        }
    } catch { }
}
if (-not $python) {
    Write-Error "Python 3.10+ est requis et doit être disponible dans le PATH."
    exit 1
}

# 2. Environnement virtuel
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "  Création de l'environnement isolé .venv…"
    & cmd /c "$python -m venv .venv"
    if ($LASTEXITCODE -ne 0) { Write-Error "Création du venv impossible."; exit 1 }
} else {
    Write-Host "  Environnement : .venv (existant)"
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"

# 3. Dépendances
Write-Host "  Installation des dépendances Python…"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e .
if ($LASTEXITCODE -ne 0) { Write-Error "Installation des dépendances impossible."; exit 1 }

# 4. FFmpeg
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if (-not $ffmpeg -or -not $ffprobe) {
    Write-Host ""
    Write-Host "  ATTENTION : FFmpeg/ffprobe introuvable dans le PATH." -ForegroundColor Yellow
    Write-Host "  Installez FFmpeg (winget install Gyan.FFmpeg) puis rouvrez le terminal."
    Write-Host "  VibeFlow en a besoin pour importer et exporter les vidéos."
} else {
    $ffVersion = (& ffmpeg -version | Select-Object -First 1)
    Write-Host "  FFmpeg    : $ffVersion"
}

Write-Host ""
Write-Host "  Installation terminée." -ForegroundColor Green
Write-Host "  Création du raccourci VibeFlow avec icône…"
& (Join-Path $PSScriptRoot "create_shortcut.ps1")
Write-Host "  Lancer VibeFlow :  .\scripts\run.ps1  ou VibeFlow.lnk"
Write-Host ""
