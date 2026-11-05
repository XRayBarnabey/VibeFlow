# VibeFlow — scripts d'installation et de lancement

`setup.ps1` crée un environnement Python isolé (`.venv`), installe les
dépendances et vérifie la présence de FFmpeg. Il est idempotent et ne modifie
pas le système. Il génère aussi `VibeFlow.lnk`, le raccourci Windows avec
l'icône VibeFlow utilisée par la barre des tâches.

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

`create_shortcut.ps1` peut être relancé seul pour recréer le raccourci :

```powershell
.\scripts\create_shortcut.ps1
```

Sous PowerShell, si l'exécution de scripts est bloquée :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```
