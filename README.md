# 🤖 Jarvis — assistant vocal local

*[English version](README.en.md)*

![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Mode](https://img.shields.io/badge/modes-hybrid%20%7C%20quality%20%7C%20local-orange)

**Jarvis est un assistant vocal en français qui tourne sur ton PC Windows.** Tu dis
*« Hey Jarvis »*, tu parles, et il agit puis te répond à voix haute.

Ce qu'il fait, en bref :

- 💡 pilote ta maison et ton PC : lumières Hue, OBS, applis, volume, extinction ;
- 📅 gère ton agenda, résume tes mails, Discord et Instagram ;
- 🌐 agit dans ton navigateur : résumer une page, réserver un resto ;
- 🧠 retient tes préférences et peut confier les recherches longues à l'agent local Hermes ;
- 📡 peut écouter dans d'autres pièces grâce à des satellites audio ;
- 🔐 demande toujours confirmation avant une action importante (mail, appel, réservation).

Il marche avec une IA en ligne (OpenAI ou Claude) **ou 100 % hors ligne** (Ollama).
Il faut Windows 11 et un micro. Toutes les intégrations sont facultatives.

👉 Liste complète des fonctionnalités, architecture et roadmap :
[docs/fonctionnalites.md](docs/fonctionnalites.md)

## 🎚️ Les trois modes

| Mode | LLM | Voix | Usage |
|---|---|---|---|
| **hybride** *(défaut)* | modèle quotidien économique du fournisseur choisi — Luna pour OpenAI, Haiku pour Claude par défaut | moteur choisi séparément | demandes courtes en cloud, tâches de fond confiées à Hermes |
| **qualité** | profil le plus puissant du même fournisseur | moteur choisi séparément | demandes exigeantes et raisonnement renforcé |
| **local** | Ollama (`qwen3.5:4b`…) | Piper, Kokoro ou Windows | **100 % hors ligne**, aucune API et aucun coût d'usage |

La transcription de la voix reste locale dans les trois modes. Bascule avec `mode:` dans `config.yaml`, ou à la voix « passe en local ». Détails, matériel conseillé et coûts : [docs/local.md](docs/local.md), [docs/costs.md](docs/costs.md).

## 🚀 Installation Windows en un clic

Sur **Windows 11**, télécharge le dépôt puis double-clique sur
**`INSTALLER_JARVIS.bat`**. Il installe [uv](https://docs.astral.sh/uv/) et Git avec
`winget` s'ils manquent, puis Python 3.13 et les dépendances aux versions exactes de
`uv.lock`, Chromium, et lance l'assistant de configuration (`scripts/setup.py`). Ton
`config.yaml` existant est conservé. Ensuite, lance Jarvis avec **`lancer_jarvis.bat`**.
Sur un PC à processeur ARM (Snapdragon), Whisper local n'existe pas : Jarvis
transcrit alors la voix avec OpenAI (clé `openai.cle`, jamais en mode local), et la
voix Piper comme la recherche DuckDuckGo y sont indisponibles
([#14](https://github.com/sosoj92/jarvis-assistant-vocal/issues/14)).

## 🚀 Démarrage rapide (installation manuelle)

Prérequis : **Python 3.13**, [uv](https://docs.astral.sh/uv/), Windows 11, un micro.

```bash
uv sync
uv run playwright install chromium        # pour les réservations / le navigateur
copy config.example.yaml config.yaml      # puis remplis ce dont tu as besoin
uv run python jarvis14.py
```

Dis **« Hey Jarvis »**. Il faut soit la clé API du fournisseur cloud sélectionné
(`openai.cle` ou `anthropic.cle`), soit un modèle Ollama en mode local. Tout le reste
est optionnel.

Débutant complet ? Vois **[INSTALL_WITH_AI.md](INSTALL_WITH_AI.md)** — à coller dans
n'importe quelle IA gratuite, elle t'installe tout pas à pas. Ou lance l'installateur
interactif : `python scripts/setup.py`. Un souci ? `python scripts/doctor.py` diagnostique.

## 🤝 Se faire aider par une IA

Colle le contenu de **[INSTALL_WITH_AI.md](INSTALL_WITH_AI.md)** dans n'importe quel chatbot gratuit
(Claude.ai, ChatGPT, Gemini) : il t'installe Jarvis pas à pas.

## ⚙️ Configuration

Tout est dans un unique `config.yaml` **non versionné** (copié depuis
`config.example.yaml`, qui documente chaque clé). Nouvelles sections côté config :
`cloud`/`openai`/`anthropic` (LLM cloud), `tts`/`elevenlabs` (voix), `hermes` (délégation), `integrations`/`hub` (Vault + génération), `suivi` (pipeline
de contenus), `securite.toujours` (autorisations N2 mémorisées), `budget.prix`
(coût LLM), `serveur`/`pont_iphone`. Guides par intégration :

| Intégration | Guide |
|---|---|
| Fournisseurs cloud (OpenAI / Claude) | [docs/openai.md](docs/openai.md) |
| Modes local / hybride / qualité | [docs/local.md](docs/local.md) |
| Routage 3 modes, coûts & budgets | [docs/costs.md](docs/costs.md) |
| Philips Hue | [docs/hue.md](docs/hue.md) |
| OBS | [docs/obs.md](docs/obs.md) |
| Google Agenda + iCal | [docs/agenda.md](docs/agenda.md) |
| Détection de présence | [docs/presence.md](docs/presence.md) |
| Bot Discord | [docs/discord.md](docs/discord.md) |
| Appels Twilio | [docs/appels.md](docs/appels.md) |
| Navigateur (Chrome CDP) | [docs/navigateur.md](docs/navigateur.md) |
| Réservations web | [docs/reservation.md](docs/reservation.md) |
| Instagram | [docs/instagram.md](docs/instagram.md) |
| Serveur MCP | [docs/mcp.md](docs/mcp.md) |
| Pont iPhone (Raccourcis) | [docs/iphone.md](docs/iphone.md) |
| **Hermes (délégation, cloisonnement)** | [docs/hermes.md](docs/hermes.md) |
| **Hub de contenu (Vault + génération)** | [docs/hub_contenu.md](docs/hub_contenu.md) |
| **Suivi de contenus** | [docs/suivi_contenu.md](docs/suivi_contenu.md) |
| **Panneau web (modèles · état · permissions)** | [docs/panneau.md](docs/panneau.md) |
| **Extinction / Wake-on-LAN** | [docs/wol.md](docs/wol.md) |
| **Gestes de la main (webcam)** | [docs/gestes.md](docs/gestes.md) |
| **Satellites audio multi-pièces** | [installation et matériel](docs/satellite_installation.md) · [protocole](docs/satellite.md) · [Raspberry/Linux détaillé](docs/satellite_pi.md) |
| **Ancien PC serveur + nouveau PC principal** | [docs/poste_principal_windows.md](docs/poste_principal_windows.md) |
| **H24 sans deuxième PC : PC unique, NAS, mini-PC ou VPS** | [docs/hebergement_h24.md](docs/hebergement_h24.md) |
| **Reconnaissance musicale (Shazam-like)** | [docs/musique.md](docs/musique.md) |
| **Spotify (playlist des musiques reconnues)** | [docs/spotify.md](docs/spotify.md) |
| **Cockpit (tableau de bord perso, local)** | [docs/cockpit.md](docs/cockpit.md) |
| **Overlay de réponses (fenêtre flottante)** | [docs/overlay.md](docs/overlay.md) |
| **Google Home / Nest** *(⚠️ expérimental)* | [docs/google_home.md](docs/google_home.md) |
| **Alexa / Echo** *(via API non officielle)* | [docs/alexa.md](docs/alexa.md) |
| **Latence perçue (UX)** | [docs/latency.md](docs/latency.md) |

## 🛡️ Éthique & Sécurité

La confiance est intégrée, pas rajoutée :

- **Confirmation vocale** avant toute action irréversible (envoi de mail, réservation, suppression, appel…).
- **Les appels se présentent** honnêtement : *« Bonjour, je suis l'assistant vocal automatisé de [prénom]… »* — jamais en se faisant passer pour un humain.
- **Jamais** de mot de passe ni de données bancaires saisis, jamais de paiement automatique.
- **Domaines protégés** (banque, impôts, santé) sur ton vrai navigateur = **lecture seule**.
- **Secrets & données perso jamais versionnés** (`config.yaml`, mémoire, logs, transcriptions d'appels, tokens OAuth — tous gitignorés).
- Au téléphone, Jarvis ne confirme que ce que tu as validé **avant** l'appel.
- **Niveaux de permission N1/N2/N3** : chaque outil a un niveau — **N1** sûr (auto, local + iPhone), **N2** sensible (confirmation ; « toujours autoriser » révocable), **N3** critique (confirmation à chaque fois, jamais mémorisable, **jamais à distance**). Extinction du PC, mails, appels, réservations = N3.
- **Pont iPhone** : à distance, s'exécutent sans confirmation les outils **sûrs (N1)** exposés, plus ceux que tu listes toi-même dans `pont_iphone.domotique_distante` (vide par défaut ; un N2 placé là perd sa confirmation à distance, un **N3 reste toujours refusé**). Toute autre action sensible est refusée (« à faire à la voix à la maison »), et après la lecture d'un contenu externe seules les lectures passent. Un token volé ne peut donc faire que ce que tu as ouvert : n'y mets que des actions physiques réversibles (lumières, ambiances).
- **Cloisonnement Hermes** : Hermes lit le Vault et les outils **en lecture seule**, écrit uniquement des brouillons — **aucun credential** dans son environnement.

## 🤝 Contribuer

Ajouter un outil = un seul fichier dans `tools/` avec un décorateur `@outil(...)` — il
est auto-découvert, aucun câblage. Issues et PR bienvenues. Merci de ne jamais committer
de vrais secrets (vois `.gitignore`).

## 📄 Licence

MIT — voir [LICENSE](LICENSE).
