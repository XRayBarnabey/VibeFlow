# VibeFlow - creates a Windows shortcut with the app icon.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$icon = Join-Path $root "vibeflow\ui\resources\vibeflow.ico"
$shortcutPath = Join-Path $root "VibeFlow.lnk"

if (-not (Test-Path $pythonw)) {
    Write-Error "Environment not found. Run .\scripts\setup.ps1 first."
    exit 1
}
if (-not (Test-Path $icon)) {
    Write-Error "Icon not found: $icon"
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m vibeflow"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "VibeFlow - FPV musical post-production"
$shortcut.Save()
Write-Host "Shortcut created: $shortcutPath" -ForegroundColor Green
