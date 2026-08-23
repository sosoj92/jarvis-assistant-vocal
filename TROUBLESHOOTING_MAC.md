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

### `PortAudioError: Error querying device -1` au démarrage

Aucun périphérique d'**entrée** n'est visible. Deux causes, dans cet ordre :

1. **Ton Mac n'a pas de micro intégré.** Les **Mac mini** et **Mac Studio** n'en
   ont aucun (contrairement aux MacBook et iMac). Branche un micro USB, un
   casque avec micro, ou connecte des AirPods.
2. **L'autorisation Microphone n'est pas accordée** au terminal. Sans elle,
   PortAudio ne voit *aucune* entrée. Réglages Système → Confidentialité et
   sécurité → Microphone → coche ton terminal, puis **relance-le**.

Pour voir ce que le système expose :

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

Une liste vide (ou sans ligne « in ») confirme le diagnostic.

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

### Je veux Claude mais pas payer ElevenLabs

Installe une voix **Piper** (locale, gratuite, illimitée) : Jarvis la prend
automatiquement dès qu'aucune clé ElevenLabs n'est configurée.

```bash
mkdir -p voix
curl -L -o voix/fr_FR-siwis-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx
curl -L -o voix/fr_FR-siwis-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json
```

Les **deux** fichiers sont nécessaires. Laisse `elevenlabs.cle` vide dans
`config.yaml` : au démarrage, le journal indique alors
« pas de cle ElevenLabs : repli sur la voix locale Piper ».

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

### `NSWindow should only be instantiated on the main thread!` puis Jarvis meurt (code 134)

C'était l'overlay. Cocoa exige que toute fenêtre naisse sur le thread principal
— occupé par l'assistant — alors que l'overlay vit dans un thread secondaire.
Tk y lève une exception **Objective-C**, qui n'est pas rattrapable en Python :
elle avorte tout le processus.

**Corrigé** : Jarvis refuse désormais de démarrer l'overlay sur macOS et
l'annonce au lancement. Si tu vois encore ce plantage, tu es sur une version
antérieure :

```bash
git pull
```

### Aucune interface ne s'ouvre

C'est normal : l'overlay flottant est indisponible sur Mac (voir ci-dessus), et
le **panneau web** est désactivé par défaut. Pour l'activer, dans `config.yaml` :

```yaml
serveur:
  actif: true
  port: 8790
```

Relance Jarvis, puis ouvre dans ton navigateur :

- **http://localhost:8790/panneau** — état, budget, permissions, réglages
- **http://localhost:8790/cockpit** — tableau de bord (si `cockpit.actif: true`)

Le panneau n'est accessible qu'en **local** : une garde refuse toute requête
venant d'une autre machine.

### « Hey Jarvis » ne déclenche rien

Quand il t'entend, Jarvis affiche `[micro] Oui ?` et émet un bip. Si rien
n'apparaît, le score du mot-clé n'atteint jamais le seuil. Un seul outil pour
trancher entre les trois causes possibles :

```bash
uv run python scripts/test_micro.py
```

Il affiche un vumètre **et** le score du mot-clé en direct, puis conclut :

- **barre plate** → aucun son n'arrive : mauvais périphérique dans
  `audio.micro`, autorisation refusée, ou micro coupé matériellement.
- **barre qui bouge, score qui plafonne** → parle plus près, ou baisse le
  seuil : `assistant.seuil_reveil` (0.5 par défaut, essaie `0.35`).
- **`DETECTE`** → le mot-clé marche ; le blocage est en aval (clé API, LLM).
  Enchaîne sur `uv run python scripts/doctor.py`.

Détache bien les deux mots — « HEY … JARVIS » — à 30-50 cm du micro.

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

### `UserWarning: Specified provider 'CUDAExecutionProvider' is not in available provider names`

Sans conséquence. onnxruntime annonce simplement que CUDA n'existe pas sur Mac
et bascule sur `CoreMLExecutionProvider` / `CPUExecutionProvider`. Le mot-clé
fonctionne normalement.

### `Warning: You are sending unauthenticated requests to the HF Hub`

Sans conséquence non plus : c'est le téléchargement du modèle Whisper, en
anonyme. Il réussit, juste avec une limite de débit plus basse.

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
