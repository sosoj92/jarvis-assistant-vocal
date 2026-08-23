# 🍎 Jarvis sur macOS — problèmes courants

Chaque entrée : le **symptôme exact** que tu vois, la cause, le correctif.
Installation depuis zéro → [INSTALL_MAC.md](INSTALL_MAC.md)

Réflexe n°1, avant de chercher ici :

```bash
uv run python scripts/doctor.py
```

---

## Installation

### `OSError: PortAudio library not found`

Aussi : `ImportError` sur `import sounddevice`, ou Jarvis qui démarre puis
s'arrête net avant « Chargement des modèles ».

La roue Python de `sounddevice` n'embarque pas PortAudio sur macOS.

```bash
brew install portaudio
uv sync --reinstall-package sounddevice
```

Si `brew` répond `command not found` après l'avoir installé (Apple Silicon) :

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
exec $SHELL -l
```

### `uv sync` échoue sur `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`

Symptôme : `Distribution not found` ou `no wheels with a matching platform tag`
sur un paquet `nvidia-*`.

CUDA n'existe pas sur Mac. Ces paquets portent désormais le marqueur
`sys_platform != 'darwin'` dans `pyproject.toml` — tu vois cette erreur si tu
es sur une version du dépôt **antérieure au portage macOS**, ou si tu as un
`uv.lock` périmé :

```bash
git pull
uv lock && uv sync
```

### <a id="onnxruntime-introuvable-apple-silicon-sur-macos-1213"></a>`onnxruntime` introuvable (Apple Silicon sur macOS 12/13)

Symptôme : `no wheels with a matching platform tag (e.g. macosx_13_0_arm64)`.

Les roues Apple Silicon d'onnxruntime sont marquées `macosx_14_0_arm64` depuis
la 1.24 : elles exigent **macOS 14 Sonoma**. Deux options.

1. Mettre à jour vers macOS 14+ (recommandé).
2. Rester en 12/13 et redescendre à la dernière version compatible :

```bash
uv add "onnxruntime==1.23.2"
uv sync
```

openWakeWord, faster-whisper et piper-tts fonctionnent avec la 1.23.2.

Sur **Mac Intel**, rien à faire : le plafond est déjà dans `pyproject.toml`
(plus aucune roue `x86_64` macOS après la 1.23.2).

### `command not found: uv` quand je double-clique `launch_jarvis.sh`

Un script lancé par le Finder n'hérite pas du PATH de ton Terminal.
`launch_jarvis.sh` cherche déjà `uv` dans `~/.local/bin`, `~/.cargo/bin`,
`/opt/homebrew/bin` et `/usr/local/bin`. Si le tien est ailleurs :

```bash
export UV_BIN=/chemin/vers/uv
```

### `permission denied: ./launch_jarvis.sh`

```bash
chmod +x *.sh
```

### Le script s'ouvre dans TextEdit au lieu de s'exécuter

Le Finder n'exécute pas les `.sh` par double-clic par défaut. Soit tu le lances
depuis le Terminal (`./launch_jarvis.sh`), soit : clic droit → Ouvrir avec →
Terminal.app, puis « Toujours ouvrir avec ».

---

## Micro et mot-clé

### Jarvis ne réagit pas à « Hey Jarvis »

Dans l'ordre :

1. **Autorisation micro.** Réglages Système → Confidentialité et sécurité →
   Microphone → coche **Terminal** (ou iTerm). Puis **relance le terminal** :
   l'autorisation n'est prise en compte qu'au redémarrage du processus.
2. **Bon périphérique.**
   ```bash
   uv run python -c "import sounddevice as sd; print(sd.query_devices())"
   ```
   Mets l'index voulu dans `config.yaml` → `audio.micro`, ou `null` pour
   l'entrée système.
3. **Seuil trop haut.** `config.yaml` → `assistant.seuil` (0.025 par défaut).
   Les micros internes de MacBook sont peu sensibles : essaie `0.015`.

### macOS ne m'a jamais demandé l'autorisation micro

Elle a été refusée une fois, ou accordée à un autre terminal. macOS ne
redemande pas. Coche la case à la main dans Réglages Système, puis relance.

Pour repartir de zéro (redemande l'autorisation au prochain lancement) :

```bash
tccutil reset Microphone
```

### Le micro marche, mais Jarvis n'entend rien en visio

Zoom, Teams et Meet peuvent prendre le micro en exclusivité. Choisis un autre
périphérique d'entrée dans `audio.micro`, ou un micro USB dédié.

---

## Voix

### Jarvis répond par écrit mais ne parle pas

Teste la voix de secours du système :

```bash
say -v Thomas "Bonjour, je suis Jarvis"
```

- **Rien ne sort** → aucune voix française installée. Réglages Système →
  Accessibilité → Contenu énoncé → Voix système → Gérer les voix → ajoute
  **Thomas** ou **Amélie**. Jarvis la détecte automatiquement.
- **Ça parle** → le problème est en amont : clé ElevenLabs absente ou invalide
  (mode cloud), ou pas de `.onnx` dans `voix/` (mode local). `doctor.py` le dit
  dans sa section **Voix (TTS)**.

### La voix est anglaise alors que le texte est français

Aucune voix `fr_FR` / `fr_CA` n'est installée : `say` retombe sur la voix par
défaut. `say -v '?' | grep fr_` doit renvoyer au moins une ligne.

### La voix sort dans les mauvaises enceintes

Dis « passe sur le casque » (outil `sortie_audio`), ou dans `config.yaml` :

```yaml
audio:
  haut_parleur: null        # null = sortie par défaut du système
  sorties:
    casque: "AirPods"       # sous-chaîne du nom de l'appareil
    enceintes: "MacBook"
```

---

## Commandes système

### « Pause », « suivant », « monte le son » ne font rien

Le volume passe par `osascript` et marche toujours. Les **touches média**
passent par un évènement système qui exige l'**Accessibilité** :

Réglages Système → Confidentialité et sécurité → Accessibilité → coche ton
terminal, puis relance-le.

Sans cette autorisation, Jarvis retombe automatiquement sur AppleScript et
pilote quand même Spotify, Musique et VLC s'ils sont ouverts.

### « Lance OBS » répond « Impossible de lancer OBS »

Sur macOS, une app se désigne par son **nom** ou son bundle `.app`, pas par un
chemin `.exe`. Dans `config.yaml` :

```yaml
apps:
  obs: "OBS"                             # nom de l'app (le plus simple)
  borderlands: "/Applications/Jeu.app"   # ou le bundle complet
  un_jeu_steam: "steam://rungameid/XXXX" # les protocoles marchent aussi
```

Vérifie à la main : `open -a "OBS"`.

### « Éteins le PC » ne fait rien / demande un mot de passe

macOS n'a pas d'arrêt différé sans droits admin. Jarvis tient donc la minuterie
lui-même, puis demande l'arrêt à System Events — ce qui exige l'autorisation
**Automatisation** pour « System Events », proposée au premier essai. Si tu l'as
refusée : Réglages Système → Confidentialité et sécurité → Automatisation →
ton terminal → coche **System Events**.

« Annule l'extinction » fonctionne pendant tout le délai.

### Le raccourci Ctrl+Alt+M (couper le micro) ne marche pas

Attendu. Les raccourcis clavier **globaux** utilisent la lib `keyboard`, qui
exige `sudo` sur macOS — Jarvis les saute proprement et l'annonce au démarrage.

À la place : la voix, le panneau web, ou un raccourci maison via l'app
**Raccourcis** (action « Exécuter un script shell ») auquel tu assignes une
combinaison de touches.

### `capture_screen` renvoie une image noire

Autorisation **Enregistrement de l'écran** manquante : Réglages Système →
Confidentialité et sécurité → Enregistrement de l'écran → coche ton terminal,
puis relance-le. C'est la même autorisation qui donne les **titres** de
fenêtres aux gestes.

---

## Overlay et interface

### L'overlay vole le focus / bloque les clics

Sur Mac, tkinter n'offre pas l'équivalent de `WS_EX_TRANSPARENT` : l'overlay est
cliquable. Si ça gêne un jeu ou un montage, déplace-le
(`overlay.coin`, `overlay.ecran`) ou coupe-le :

```yaml
overlay:
  actif: false
```

### L'overlay apparaît dans mon stream OBS

Attendu : `WDA_EXCLUDEFROMCAPTURE` est une API Windows, sans équivalent macOS.
Mets l'overlay sur un écran que tu ne captures pas (`overlay.ecran`), ou
coupe-le pendant le live.

---

## Performances

### Whisper est lent

Normal au premier lancement (le modèle se télécharge). Ensuite, sur Mac,
Whisper tourne sur **CPU** : CTranslate2 n'a pas de backend Metal, ce n'est pas
un réglage manquant. Sur Apple Silicon en int8, c'est confortable. Si c'est
trop lent :

```yaml
whisper:
  modele: small     # au lieu de medium
```

### Le Mac chauffe / les ventilateurs s'emballent en mode local

Le modèle Ollama partage la mémoire unifiée avec tout le reste. Choisis un
modèle adapté : `qwen3.5:9b` à partir de 16 Go, `qwen3.5:4b` à 8 Go. Ou passe
en `mode: cloud`.

### « GPU indisponible » au démarrage

Ce n'est pas une erreur sur Mac : il n'y a pas de CUDA. Jarvis affiche
« Whisper sur Apple Silicon (pas de CUDA sur ce système) » et continue.

---

## Reconnaissance musicale

### « C'est quoi ce son ? » ne capte pas l'audio du Mac

macOS n'a aucun loopback système. Pour capter le son *joué par le Mac* :

```bash
brew install blackhole-2ch
```

puis crée un **périphérique agrégé** (Configuration audio et MIDI) qui combine
BlackHole et tes enceintes, et choisis-le comme sortie.

Sans ça, dis simplement « c'est quoi cette musique » : Jarvis écoute au micro,
et ça marche très bien.

---

## Toujours bloqué ?

```bash
uv run python scripts/doctor.py       # état de chaque composant
uv run python scripts/test_mac.py     # test des outils système un par un
uv run python -m pytest tests/ -q     # vérifie le portage lui-même
```

Si un test du portage échoue, c'est un bug du code, pas de ta configuration :
ouvre une issue avec la sortie complète de `doctor.py`.
