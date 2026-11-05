# Architecture technique de VibeFlow

## Vue d'ensemble

```
                ┌──────────────────────────────────────────────┐
                │                 Interface Qt                  │
                │  vidéo · timeline · événements · réglages     │
                └───────────────┬──────────────────────────────┘
                                │ Project (état)
   ┌────────────────────────────┼─────────────────────────────┐
   │                            │                             │
┌──▼─────────┐          ┌───────▼────────┐           ┌────────▼───────┐
│  Import    │          │   Analyse      │           │   Musique      │
│ ffprobe    │          │ gyro → figures │           │ plan + synth   │
│ GCSV/CSV   │          │ score/sensibilité│         │ 48 kHz stéréo  │
└──┬─────────┘          └───────┬────────┘           └────────┬───────┘
   │                            │                             │
   │                    ┌───────▼────────┐                    │
   │                    │  Synchronisation│                   │
   │                    │  offset vidéo↔gyro                  │
   │                    └───────┬────────┘                    │
   │                            │                             │
   └──────────────┬─────────────┴──────────────┬──────────────┘
                  │                            │
          ┌───────▼────────┐          ┌────────▼────────┐
          │ Lecteur intégré│          │     Export      │
          │ MP4 muxé A/V   │          │ WAV · MP4       │
          └────────────────┘          └─────────────────┘
```

Modules :

| Module | Rôle |
|---|---|
| `core/gyro.py` | Lecture GCSV/CSV, unités, timestamps, rééchantillonnage |
| `core/dsp.py` | Filtres Butterworth, lissage, normalisation |
| `core/analysis.py` | Détection, classification, score, sensibilité |
| `core/sync.py` | Énergie de mouvement vidéo, corrélation, offset |
| `core/rhythm.py` | Tempo, sections, patterns, accents |
| `core/synth.py` | Synthèse instrumentale et mixage |
| `core/project.py` | État, cache, rendu, export, sauvegarde |
| `media/ffmpeg.py` | ffprobe, mux, export, découverte des binaires |
| `providers/acestep.py` | Client REST du serveur ACE-Step local |
| `backend/acestep_backend.py` | Installation, démarrage/arrêt et logs du serveur ACE-Step |
| `ui/` | Fenêtre principale, timeline, lecteur, table d'événements |

## Modèle temporel

Trois horloges coexistent :

1. **Vidéo** : temps 0 = première image.
2. **Gyro** : temps 0 = premier échantillon du journal.
3. **Offset utilisateur** : `temps_vidéo = temps_gyro + offset`.

Les événements sont stockés en temps gyro. L'interface et la génération musicale
ajoutent l'offset au moment de l'affichage ou de la composition. Ainsi, corriger
le décalage ne modifie jamais les données sources : tout est recalculé.

La préécoute audio est rendue directement sur la timeline vidéo : un kick
programmé à `t = event.t_peak + offset` tombe donc sur l'image correspondante.

## Import gyroscopique

- `tscale` × `t` donne des secondes ; `gscale` × valeurs donne des rad/s.
- La fréquence n'est jamais supposée : `median(dt)` détermine la cadence native.
- Grille d'analyse : `min(400 Hz, max(100 Hz, cadence native))`.
- Les timestamps irréguliers sont respectés ; les trous > 6 × dt sont signalés.
- Les échantillons interpolés dans un trou sont marqués (métadonnée
  `invalid_samples`) pour ne pas inventer de mouvement.
- Détection d'unités : si les valeurs brutes dépassent ~25 en p99.5, elles sont
  interprétées en deg/s puis converties.

## Détection des figures

Le gyroscope mesure la vitesse angulaire **réelle** du drone, pas les sticks.
La détection travaille donc sur le déplacement angulaire intégré, ce qui est
robuste aux petites corrections.

1. Lissage passe-bas 24 Hz, accélération angulaire dérivée + passe-bas 18 Hz.
2. Épisodes de rotation par axe : `|vitesse| > 55 °/s`, fusion des interruptions
   < 120 ms, durée ≤ 3 s, `|∫ω dt| ≥ 65°`, monotonie `|∫|/∫|ω| ≥ 0.5`.
3. Classification par axe et amplitude : tonneau, inversion, tonneau 360°,
   rotations multiples, bascule, flip, flips multiples, spin, combo.
4. Changements de direction : passage par zéro de la vitesse lissée 6 Hz avec
   amplitude pic-à-pic ≥ 110°.
5. Accélérations : pics d'accélération angulaire ≥ 900 °/s² hors figure.
6. Séquence fluide : activité > 230 °/s pendant ≥ 0.9 s hors figure.
7. Fusion : figures simultanées sur plusieurs axes → combo ; doublons à
   ±120 ms supprimés ; pénalité de répétition sur 9 s.

Score (0–1) : 38 % amplitude, 27 % vitesse crête, 13 % accélération, 10 % durée,
12 % monotonie. La sensibilité filtre ensuite :

| Sensibilité | Score min | Amplitude min |
|---|---|---|
| 0 % | 0.84 | 265° |
| 50 % | 0.595 | 167° |
| 100 % | 0.35 | 70° |

## Synchronisation

`sync.video_motion_energy` extrait une vidéo basse résolution (128×72, 10 fps)
via FFmpeg et calcule la différence moyenne entre images. Cette énergie est
corrélée (Pearson) avec la vitesse angulaire lissée du gyro pour chaque
décalage candidat de −10 s à +10 s. La confiance combine le score absolu et son
écart à la distribution (z-score). L'offset n'est appliqué automatiquement que
si la corrélation est ≥ 0.25 et la confiance ≥ 45 % ; sinon l'interface demande
une vérification manuelle.

Une estimation par métadonnées (timestamp UNIX du GCSV vs `creation_time`)
sert de secours quand la corrélation échoue.

## Composition rythmique

1. **Tempo** : recherche 88–168 BPM, 24 phases par tempo, noyau gaussien
   (σ = 55 ms) pondéré par l'importance des figures, prior autour de 126 BPM.
   Le meilleur couple (BPM, phase) définit la grille.
2. **Sections** : blocs de 4 temps (≥ 2 s) ; énergie = 0.4 × moyenne +
   0.6 × percentile 88 de l'activité, médiane glissante, bonus par figure.
   Étiquettes intro / montée / groove / pic / rupture, puis fusion des voisins
   identiques.
3. **Patterns** : kick, sub, hats, open-hats, claps selon l'énergie et la
   section ; progression A mineur (i–VI–III–VII).
4. **Accents** : chaque figure retenue ajoute un kick à son timestamp exact,
   plus un impact (et un crash pour les rotations multiples). Les événements
   trop rapprochés sont fusionnés pour éviter la bouillie.
5. **Transitions** : riser avant une montée d'énergie, crash sur rupture.
6. **Nappes** : triade A mineur discrète sur intro/rupture.

## Styles musicaux

Deux arrangements partagent la même analyse et le même moteur d'accents :

| Style | Intention | Matières |
|---|---|---|
| **Évasion de l'esprit** (défaut) | Ambiant cinématique, aérien, émotionnel | Pads chauds, drone de basse, arpèges en croches, cloches, boom tonal, shimmer, nappes de bruit |
| **Pulse** | Rythmique club, plus direct | Kick four-on-floor, sub, hats, claps, impacts, crashs |

En mode Évasion, le tempo est replié dans une plage de 78–92 BPM (un vol détecté
à 127 BPM donne ~84 BPM), les kicks sont adoucis et espacés (1 et 3), et les
figures deviennent des accents **tonaux** (cloche + boom) au lieu de bruitages.
Le tempo reste calé sur le vol via la grille, mais les accents ne sont jamais
quantifiés : ils tombent au timestamp exact de la figure.

## Personnalisation du son

Le panneau `PERSONNALISATION` pilote `SoundSettings` (sauvegardé dans le projet
`.vibeflow`) :

| Réglage | Effet |
|---|---|
| Kit batterie | Timbre Pulse : Analog 808, Techno 909, Acoustique, Lo-fi |
| Accents | Guitare (cordes pincées Karplus-Strong), Piano, Cloche (style Évasion) |
| Densité | Nombre d'arpèges, de ticks et de kicks secondaires |
| Brillance | Filtre passe-bas global (1,4 kHz → 12 kHz) et timbre des cordes |
| Réverbération | Niveau de la queue convolutive et des envois |
| Graves | Niveau du drone, du sub et des impacts graves |

Par défaut : guitare, densité 65 %, brillance 60 %, réverbération 55 %,
graves 50 %, kit Analog 808. Le rendu ambiant est normalisé en crête, sans
saturation. En Pulse, le kit remplace entièrement kick/clap/hat/impact ;
en Évasion, les accents guitare/piano restent la référence.

## Interface

- Colonne gauche : vidéo et timeline dans un `QSplitter` vertical.
- Colonne droite : onglets **Musique / Analyse / Événements**.
- Séparateurs redimensionnables (vidéo/timeline et inspecteur) ; les tailles
  sont mémorisées via `QSettings`.
- En-tête : menu **Ouvrir** (vidéo, gyro, projet, sauvegarde), menu
  **Exporter** (WAV, MP4) et bascule **thème clair/sombre** mémorisée.
- Lecteur : boutons **VibeFlow / ACE-Step / Hybride** pour comparer les sources
  sans régénérer.
- Carte ACE-Step : voyant d'état du serveur (prêt, démarrage, travail, erreur)
  avec ETA, bouton Démarrer/Arrêter et préréglages de prompts.

## Génération ACE-Step (fournisseur local)

La carte **Génération IA — ACE-Step** envoie une *tempo map* au serveur local
`http://127.0.0.1:8021` :

- durée exacte de la vidéo,
- BPM estimé (ou celui du plan courant),
- tonalité `A minor`, signature `4/4`,
- prompt de style,
- structure des sections (`intro 0-17s; build 17-34s; peak …`).

Le client `providers/acestep.py` :

1. `POST /release_task` avec `thinking=false`, `batch_size=1`,
   `audio_format=wav` ;
2. interroge `POST /query_result` toutes les 2,5 s ;
3. télécharge le WAV via `GET /v1/audio?path=…`.

La piste est ensuite :

- soit utilisée seule (lit musical ACE-Step),
- soit **hybridée** avec le rythme VibeFlow : ACE-Step est invité à produire
  sans batterie ; VibeFlow filtre son plan pour ne garder que les percussions,
  passe la nappe IA en passe-haut à 80 Hz, la duque à chaque kick/impact local
  puis mixe les deux couches. Les frappes tombent donc **exactement** sur les
  figures, quelle que soit la précision rythmique d'ACE-Step.
- muxée avec la vidéo dans le même MP4 de prévisualisation.

La requête envoyée (BPM, durée, structure, prompt) est sauvegardée dans
`<cache>/ai/last_request.json` pour vérification.

Le serveur reste optionnel : sans lui, VibeFlow fonctionne exactement comme
avant. Aucune donnée ne quitte la machine.

### Sources audio comparables

VibeFlow conserve jusqu'à trois pistes pour le même vol :

- **VibeFlow** : rendu local complet ;
- **ACE-Step seul** : nappe IA brute ;
- **Hybride** : nappe IA + rythme local exact, avec ducking.

Les boutons du lecteur chargent le preview correspondant sans régénérer, en
conservant la position et l'état lecture/pause. Cela permet d'entendre
concrètement l'apport de chaque couche.

### Backend autonome

`backend/acestep_backend.py` gère le cycle de vie complet :

- détection d'une installation existante (ACE Music, `C:\ACE-Step-1.5`, copie
  VibeFlow) ;
- téléchargement de l'archive officielle (2,4 Go) avec reprise `.part` ;
- extraction `py7zr` dans `%USERPROFILE%\VibeFlow\ace-step` (chemin stable,
  hors `LOCALAPPDATA` : le Python du Microsoft Store redirige cette variable
  vers un LocalCache privé) ;
- écriture d'un `.env` dédié (2B Turbo, LM 0.6B, backend `pt`) ;
- copie des modèles déjà présents pour éviter 7 Go de téléchargement ;
- lancement du `python_embeded` avec `PYTHONIOENCODING=utf-8`, logs dans
  `server.log`, attente de `/health` ;
- arrêt propre à la fermeture de VibeFlow.

Le serveur tourne en processus enfant, sans console, et ne dépend pas de
l'application Electron ACE Music.

Performances mesurées sur RTX 3070 8 Go (2B Turbo, offload CPU) : 176 s de
musique générées en ~18 s, preview 4K muxée en quelques secondes.

## Synthèse

- 48 kHz stéréo, float32, aucun sample externe.
- Kick : sinus à pitch descendant 196→46 Hz + click filtré.
- Sub : sinus + harmoniques, enveloppe attaque/relâche.
- Hats : bruit blanc passe-haut, décroissances courtes/longues.
- Clap : bruit bande 0.9–4.2 kHz, trois bursts.
- Impact : sinus 99→27 Hz + souffle filtré.
- Riser : bruit à filtre balayé.
- Nappe : triade désaccordée, filtre passe-bas, LFO.
- Réverbération : convolution FFT avec réponse impulsionnelle stéréo
  synthétique (IR 1.35 s), coût quasi linéaire même sur 10 minutes.
- Mastering : soft-clip `tanh`, normalisation, fades.

Performances mesurées : analyse 120 s en ~0.02 s, rendu 120 s en ~0.9 s.

## Lecture vidéo/audio synchronisée

Le point délicat est de garantir que l'audio généré et l'image ne dérivent pas.
Plutôt que deux moteurs séparés (risque de dérive et de latence), VibeFlow
muxe la musique dans un MP4 temporaire :

```
ffmpeg -i vidéo -i musique.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -shortest
```

- La vidéo est **copiée** (aucun réencodage), donc l'opération reste rapide
  même en 4K.
- Qt Multimedia lit un seul flux : la synchronisation A/V est gérée par le
  pipeline multimédia, pas par l'application.
- Le seek, la pause, le volume et le pas-à-pas image sont ceux du lecteur.
- Chaque régénération écrit un fichier au nom unique (verrou Windows) puis
  nettoie les anciens.
- Cache : `%TEMP%/VibeFlow/<hash vidéo+offset+sensibilité>/`.

Ce choix est documenté dans `docs/DECISIONS.md` (ADR-005).

## Threads et réactivité

- Analyse, synchronisation et génération tournent dans un `QThreadPool`
  (2 threads) avec signaux Qt.
- Des jetons de génération empêchent l'application d'un résultat obsolète.
- Un rendu audio de 2 minutes prend < 1 s ; un mux 4K quelques centaines de ms.
- La lecture continue pendant la régénération ; la position et l'état
  lecture/pause sont restaurés au chargement du nouveau preview.

## Export

- **WAV** : copie de la piste maîtresse 48 kHz.
- **MP4** : stream copy vidéo + AAC 256 kb/s ; option de mixage de l'audio
  caméra à faible niveau (`amix`).

## Limites et évolutions

- La synchronisation par corrélation peut échouer sur des plans pauvres en
  mouvement ; le réglage manuel est prioritaire.
- Pas de stabilisation Gyroflow (hors périmètre) ; compatible avec des rushes
  stabilisés.
- La composition complète (mélodie/harmonie/arrangement long) est l'objet de la
  phase 5, sur la même grille et le même moteur de rendu.
