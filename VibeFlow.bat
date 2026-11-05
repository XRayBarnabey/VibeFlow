@echo off
rem VibeFlow — lancement par double-clic
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo VibeFlow n'est pas encore installe.
    echo Lancez d'abord :  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
    pause
    exit /b 1
)
if exist "%~dp0VibeFlow.lnk" (
    start "" "%~dp0VibeFlow.lnk"
    exit /b 0
)
start "" ".venv\Scripts\pythonw.exe" -m vibeflow
