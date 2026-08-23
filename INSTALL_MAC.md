# 🍎 Installer Jarvis sur macOS

Guide complet pour **Mac Intel** et **Apple Silicon** (M1 → M4).
Un souci en cours de route ? → [TROUBLESHOOTING_MAC.md](TROUBLESHOOTING_MAC.md)

> Jarvis a été écrit pour Windows. Tout le code spécifique à un système est
> maintenant regroupé dans `core/plateforme.py`, et macOS y est traité au même
> niveau que Windows. Ce qui **ne marche pas encore** sur Mac est listé
> honnêtement en fin de page — rien n'est promis à moitié.

---

## 1. Pré-requis

| Élément | Version | Pourquoi |
|---|---|---|
| macOS | **12 Monterey minimum**. **14 Sonoma** si Apple Silicon (voir note ⚠️) | PyObjC, onnxruntime |
| Homebrew | à jour | fournit `portaudio` |
| Python | **3.13** (3.10+ accepté) | `.python-version` du projet |
| uv | dernière | gère l'environnement et les versions |

⚠️ **Apple Silicon + macOS 12/13** : `onnxruntime` ne publie plus de roue pour
ces versions. Voir [le contournement](TROUBLESHOOTING_MAC.md#onnxruntime-introuvable-apple-silicon-sur-macos-1213).
Sur **Mac Intel**, aucun souci : le projet plafonne automatiquement onnxruntime
à la 1.23.2, la dernière avec une roue `x86_64` macOS.

### Homebrew

```bash
# S'il n'est pas déjà là :
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Sur Apple Silicon, Homebrew s'installe dans `/opt/homebrew` et te demande
d'ajouter une ligne à ton `~/.zprofile` — **fais-le**, sinon `brew` sera
introuvable au prochain terminal :

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

### portaudio — l'étape à ne pas sauter

`sounddevice` (le micro **et** le mot-clé « Hey Jarvis ») s'appuie sur
PortAudio, que la roue Python **n'embarque pas** sur macOS. Sans lui, tout
s'installe puis Jarvis plante au démarrage sur
`OSError: PortAudio library not found`.

```bash
brew install portaudio
```

### uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL -l          # recharge le PATH
uv --version            # doit répondre
```

`uv` installe aussi Python 3.13 tout seul : pas besoin d'un Python système.

---

## 2. Installation

```bash
git clone https://github.com/sosoj92/jarvis-assistant-vocal
cd jarvis-assistant-vocal
uv sync                 # crée .venv et installe tout
```

Puis l'installateur interactif, qui vérifie les pré-requis macOS, écrit
`config.yaml`, détecte le matériel et finit par une phrase de bienvenue :

```bash
uv run python scripts/setup.py
```

Il te demande le mode :

- **cloud** — Claude + ElevenLabs. Qualité maximale, clé API requise.
- **local** — Ollama + Piper. 100 % hors ligne. Sur Mac, le modèle partage la
  mémoire unifiée : compte 16 Go pour `qwen3.5:9b`, 8 Go pour `qwen3.5:4b`.

Enfin, le navigateur pour les réservations :

```bash
uv run playwright install chromium
```

---

## 3. Autorisations macOS

macOS demande une autorisation explicite, **accordée au terminal (ou à l'app)
qui lance Jarvis** — pas à Jarvis lui-même. Réglages Système →
Confidentialité et sécurité :

| Autorisation | Nécessaire pour | Sans elle |
|---|---|---|
| **Microphone** | écoute, mot-clé « Hey Jarvis » | ❌ Jarvis n'entend rien |
| **Accessibilité** | touches média, Cmd+Tab par geste | les commandes « pause », « suivant » retombent sur AppleScript (Spotify/Musique seulement) |
| **Enregistrement de l'écran** | `capture_screen`, titres de fenêtres | pas de capture ; le nom de l'app reste connu, pas le titre |

**Le piège :** si tu refuses une fois, macOS ne redemande plus. Il faut cocher
la case à la main dans ces réglages, puis **relancer le terminal**.

Astuce : lance toujours Jarvis depuis le **même** terminal (Terminal.app *ou*
iTerm, pas les deux) — les autorisations sont accordées par application.

---

## 4. Lancer

```bash
./launch_jarvis.sh
```

Puis dis **« Hey Jarvis »**.

| Script bash | Équivalent Windows | Rôle |
|---|---|---|
| `launch_jarvis.sh` | `lancer_jarvis.bat` | lance l'assistant |
| `launch_mcp_server.sh` | `lancer_serveur_mcp.bat` | serveur MCP en HTTP |
| `update_jarvis.sh` | `mettre_a_jour_jarvis.bat` | met à jour les dépendances |
| `save_jarvis.sh` | `sauvegarder_jarvis.bat` | commit + push |
| `chrome_jarvis.sh` | `Chrome + Jarvis.bat` | Chrome avec port de débogage |

Ils sont déjà exécutables. Si `git clone` a perdu le bit :
`chmod +x *.sh`

### Lancer au démarrage de session

Réglages Système → Général → Ouverture → **+** → choisis `launch_jarvis.sh`.
Le script cherche `uv` dans `~/.local/bin`, `/opt/homebrew/bin` et
`/usr/local/bin`, justement parce que le PATH d'un élément d'ouverture n'est
pas celui du Terminal.

---

## 5. Vérifier que tout marche

```bash
uv run python scripts/doctor.py     # diagnostic complet
uv run python -m pytest tests/ -q   # tests du portage
uv run python scripts/test_mac.py   # test manuel des outils système
```

`doctor.py` affiche une section **Système** avec ta puce, Homebrew, et les
autorisations à accorder.

---

## 6. Régler le micro

Sur Windows, `audio.micro` vaut `1`. Sur macOS cet index désigne souvent une
**sortie** : `scripts/setup.py` écrit donc `null` dans ton `config.yaml`, ce qui
laisse Jarvis prendre l'entrée système.

⚠️ Si tu as copié `config.example.yaml` **à la main** plutôt que de lancer
l'installateur, mets `audio.micro: null` toi-même — sinon Jarvis écoutera le
mauvais périphérique. Pour forcer un micro précis :

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

puis dans `config.yaml` :

```yaml
audio:
  micro: 2                # l'index affiché, ou null pour l'entrée système
  haut_parleur: null      # null = sortie par défaut du système
```

---

## 7. Ce qui marche, et ce qui ne marche pas

### ✅ Identique à Windows

Claude et Ollama · Whisper (STT) · ElevenLabs et Piper (TTS) · mot-clé
openWakeWord · volume · touches média · lancement d'applications · fenêtre au
premier plan · capture d'écran · extinction différée annulable · stats
CPU/RAM/disque · Hue, OBS, Gmail, Discord, Agenda, Instagram, Twilio,
Playwright · serveur MCP · panneau web et cockpit.

### ⚠️ Différences assumées

| Sujet | Sur Mac |
|---|---|
| **Température GPU** | non exposée par macOS sans droits admin. `get_system_stats` donne la puce et le nombre de cœurs, pas la température — il ne l'invente pas. |
| **Whisper** | tourne sur CPU. CTranslate2 n'a pas de backend Metal. En int8 sur Apple Silicon, c'est rapide. |
| **Extinction** | macOS n'a pas de `shutdown` différé sans mot de passe admin. Jarvis tient donc la minuterie lui-même puis demande l'arrêt à System Events. « Annule l'extinction » marche pareil. |
| **Overlay** | flottant et au-dessus, mais **cliquable** (pas de clic-transparent) et **visible pour OBS** (pas d'exclusion de capture). En stream, mets-le sur un écran non capturé (`overlay.ecran`) ou coupe-le (`overlay.actif: false`). |
| **Raccourcis clavier globaux** | désactivés : la lib `keyboard` exige `sudo` sur macOS. Utilise la voix, le panneau web, ou un raccourci Automator. |
| **Son du système (Shazam)** | macOS n'a pas de loopback. Il faut [BlackHole](https://github.com/ExistentialAudio/BlackHole) (`brew install blackhole-2ch`). Sans lui, la reconnaissance passe par le micro, ce qui marche très bien. |

---

## 8. Et Windows dans tout ça ?

Rien n'est cassé. Les `.bat` et `.ps1` sont toujours là, `core/plateforme.py`
garde exactement le comportement Windows d'origine (touches multimédia via
`keybd_event`, `os.startfile`, `shutdown /s /t`, SAPI), et la résolution des
dépendances a été vérifiée sur `x86_64-pc-windows-msvc` en plus des deux
architectures macOS. Ce portage ajoute macOS, il ne remplace pas Windows.
