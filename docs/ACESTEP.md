# Génération musicale locale avec ACE-Step 1.5

VibeFlow peut demander une piste musicale à **ACE-Step 1.5**, exécuté en local.
La synchronisation, la timeline et les accents restent gérés par VibeFlow.

## Matériel

| VRAM | Configuration recommandée |
|---|---|
| ≤ 6 Go | DiT 2B Turbo, LM désactivé |
| **6–8 Go** (RTX 3070) | **DiT 2B Turbo + LM 0.6B, backend `pt`, offload CPU** |
| 16–20 Go | 2B SFT ou XL Turbo + LM 1.7B |
| ≥ 20 Go | XL SFT + LM 4B |

Le modèle **XL** (4B) n'est pas adapté à 8 Go : il demande ≥12 Go avec offload
et 20 Go sans. Sur RTX 3070, rester en **2B Turbo**.

## Installation gérée par VibeFlow (recommandé)

L'application ACE Music n'est pas nécessaire. Dans VibeFlow :

1. Onglet **Analyse → Moteur local ACE-Step**.
2. **Installer** : téléchargement de l'archive officielle
   `ACE-Step-1.5.7z` (~2,4 Go), extraction dans
   `%USERPROFILE%\VibeFlow\ace-step\ACE-Step-1.5`.
3. VibeFlow écrit automatiquement un `.env` :
   `2B Turbo`, `LM 0.6B`, backend `pt`, offload auto.
4. Les modèles déjà présents dans une installation ACE Music sont copiés si
   possible ; sinon le serveur les télécharge au premier démarrage.
5. **Démarrer** lance le serveur sur `127.0.0.1:8021` et attend `/health`.
   Le bouton à côté de **Générer** fait la même chose, avec un voyant :
   vert prêt, orange démarrage, vert clignotant travail, rouge erreur, et une
   estimation du temps de démarrage.
6. **Arrêter** libère la VRAM ; **Journaux** affiche la sortie du serveur.

Le serveur utilise l'environnement Python/PyTorch embarqué du paquet portable :
aucune installation séparée de CUDA 12 n'est nécessaire, et le blocage
`checkCuda` de l'application Electron n'intervient pas.

Espace disque : ~2,4 Go d'archive (supprimée après installation), ~10 Go
extraits, ~7 Go de modèles si aucun n'est réutilisé. L'extraction peut prendre
10 à 20 minutes selon le disque et le CPU.

## Démarrage manuel (alternative)

Le paquet portable ACE-Step expose une API REST. Lance :

```text
start_api_server.bat
```

ou, si tu utilises l'application ACE-Step Desktop, démarre son serveur local.

Adresse par défaut dans VibeFlow : `http://127.0.0.1:8021`.

Vérification :

```powershell
Invoke-RestMethod http://127.0.0.1:8021/health
```

Réponse attendue : `data.status = "ok"`.

## Réglages Windows importants

Le serveur peut planter au démarrage avec :

```
UnicodeEncodeError: 'charmap' codec can't encode characters...
```

C'est un problème d'encodage de la console Windows (cp1252), pas un problème
CUDA. Définis, au niveau utilisateur :

```powershell
[Environment]::SetEnvironmentVariable('PYTHONIOENCODING','utf-8','User')
[Environment]::SetEnvironmentVariable('PYTHONUTF8','1','User')
```

Puis quitte complètement l'application et relance-la.

Dans le fichier `.env` du dossier ACE-Step :

```ini
ACESTEP_CONFIG_PATH=acestep-v15-turbo
ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B
ACESTEP_LM_BACKEND=pt
ACESTEP_INIT_LLM=auto
```

## Utilisation dans VibeFlow

1. Importer la vidéo et le gyro, attendre la préécoute locale.
2. Carte **Génération IA — ACE-Step** :
   - serveur : `http://127.0.0.1:8021`
   - prompt : style souhaité
   - **Rythme VibeFlow prioritaire** (coché par défaut) : ACE-Step est envoyé
     sans batterie ; VibeFlow ajoute les kicks/impacts exacts sur les figures et
     duque la nappe. Décoche pour écouter ACE-Step seul.
3. Cliquer **Générer avec ACE-Step**.
4. VibeFlow envoie la durée, le BPM, la tonalité (`A minor`, 4/4) et la
   structure des sections, puis attend la fin de la tâche.
5. La piste est téléchargée, muxée avec la vidéo et jouée dans le lecteur.
6. Export WAV/MP4 : c'est la piste active (IA ou locale) qui est exportée.

## Ce que VibeFlow envoie réellement

ACE-Step ne reçoit **pas** de liste de timestamps ni de carte des figures. La
requête contient :

- `audio_duration` : durée exacte de la vidéo ;
- `bpm` : tempo du plan courant (Évasion ~84, Pulse ~127) ;
- `key_scale` : `A minor` ;
- `time_signature` : `4` ;
- `prompt` : style + structure textuelle des sections ;
- `thinking=false`, `batch_size=1`, `audio_format=wav`.

La requête complète est écrite dans `%TEMP%/VibeFlow/<cache>/ai/last_request.json`.

Conséquence : ACE-Step produit une **nappe** cohérente, mais ne peut pas placer
un kick à 41,7 s. C'est le rôle du mode hybride : VibeFlow garde le rythme
événementiel exact, ACE-Step apporte l'harmonie et la texture.

## Réglages par style

| Objectif | Style VibeFlow | Rythme prioritaire | Prompt ACE-Step |
|---|---|---|---|
| Techno | Pulse (~127 BPM) | coché | techno progressive, sans batterie |
| Ambiant / aérien | Évasion (~84 BPM) | coché | ambient cinématique, sans batterie |
| Écoute ACE-Step seul | indifférent pour le BPM | décoché | style complet avec batterie |

En mode hybride, éviter de demander une batterie à ACE-Step : le prompt reçoit
automatiquement « no drums, no percussion ».

## API utilisée

| Endpoint | Rôle |
|---|---|
| `GET /health` | disponibilité |
| `GET /v1/models` | modèles DiT disponibles |
| `POST /release_task` | créer la génération |
| `POST /query_result` | suivre la tâche |
| `GET /v1/audio?path=…` | télécharger le WAV |

Le client est dans `vibeflow/providers/acestep.py`. Il n'utilise que la
bibliothèque standard (aucune dépendance supplémentaire).

## Dépannage

- **Serveur injoignable** : vérifier le port et `Get-NetTCPConnection -LocalPort 8021 -State Listen`.
- **OOM / écran noir** : passer en 2B Turbo + LM 0.6B, `batch_size=1`.
- **Génération lente** : c'est normal sur 8 Go avec offload CPU ; la durée
  dépend de la longueur demandée.
- **Piste générée trop courte/longue** : ACE-Step reçoit la durée exacte de la
  vidéo ; VibeFlow muxe en `-shortest`.
- **Le style ne suit pas la vidéo** : ACE-Step ne voit pas les images. Il reçoit
  la structure et le BPM. Pour un vrai montage image, il faudra un modèle
  vidéo→musique (Taan) ou un lit généré puis accentué par VibeFlow.

## Licence

ACE-Step 1.5 est publié sous licence MIT (code). Vérifier la licence des poids
sur Hugging Face avant un usage commercial.
