# Journal des versions

## 1.0.0 — 2026-11-05

Première version stable de VibeFlow.

### Fonctionnalités

- Import vidéo FPV et journaux gyroscopiques GCSV/CSV, avec détection du fichier
  gyro posé à côté de la vidéo.
- Synchronisation vidéo ↔ gyro par corrélation, avec correction manuelle.
- Analyse du pilotage : figures, axes, scores et sensibilité réglable.
- Composition musicale locale en deux styles (Évasion, Pulse), 7 kits de
  percussions et 6 timbres d'accents.
- Pistes d'accents manuels illimitées : touche, couleur, son, activation,
  placement en temps réel, sélection, déplacement et suppression.
- Génération ACE-Step 1.5 locale optionnelle, mode hybride et comparateur A/B.
- Audio vidéo optionnel, thème clair/sombre, zoom d'interface.
- Exports WAV et MP4, projet `.vibeflow`.
- Interface PySide6/Qt 6 et traitement 100 % local.
- Exécutable Windows autonome `VibeFlow.exe` (FFmpeg inclus, aucun Python à
  installer), publié dans les releases GitHub.
