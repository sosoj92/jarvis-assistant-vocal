# 🤖 Jarvis — local-first voice assistant

*[Version française](README.md)*

![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Mode](https://img.shields.io/badge/modes-hybrid%20%7C%20quality%20%7C%20local-orange)

**Jarvis is a French-speaking voice assistant that runs on your Windows PC.** Say
*"Hey Jarvis"*, talk, and it acts and answers out loud.

What it does, in short:

- 💡 controls your home and PC: Hue lights, OBS, apps, volume, shutdown;
- 📅 manages your calendar, summarizes your mail, Discord and Instagram;
- 🌐 acts in your browser: summarize a page, book a restaurant;
- 🧠 remembers your preferences and can hand long research to the local Hermes agent;
- 📡 can listen in other rooms through audio satellites;
- 🔐 always asks for confirmation before an important action (mail, call, booking).

It works with an online AI (OpenAI or Claude) **or fully offline** (Ollama).
You need Windows 11 and a microphone. Every integration is optional.

👉 Full feature list, architecture and roadmap: [docs/features.en.md](docs/features.en.md)

## 🎚️ The three modes

| Mode | LLM | Voice | Usage |
|---|---|---|---|
| **hybrid** *(default)* | everyday OpenAI or Claude/Anthropic profile | selected independently | short cloud requests, background work delegated to Hermes |
| **quality** | strongest profile from the same provider | selected independently | demanding requests and stronger reasoning |
| **local** | Ollama (`qwen3.5:4b`…) | Piper, Kokoro, or Windows | **fully offline**, no API and no usage fees |

Voice transcription stays local in all three modes. Switch with `mode:` in `config.yaml`, or by voice. Details, recommended hardware and costs: [docs/local.md](docs/local.md), [docs/costs.md](docs/costs.md).

## 🚀 One-click Windows install

On **Windows 11**, download the repository and double-click
**`INSTALLER_JARVIS.bat`**. It installs [uv](https://docs.astral.sh/uv/) and Git with
`winget` when missing, then Python 3.13 and the exact dependency versions from
`uv.lock`, Chromium, and runs the setup assistant (`scripts/setup.py`). An existing
`config.yaml` is kept. Afterwards, start Jarvis with **`lancer_jarvis.bat`**. On ARM
(Snapdragon) PCs, local Whisper does not exist: Jarvis then transcribes speech with
OpenAI (`openai.cle`, never in local mode), and the Piper voice and DuckDuckGo search
are unavailable there
([#14](https://github.com/sosoj92/jarvis-assistant-vocal/issues/14)).

## 🚀 Quick start (manual install)

Requirements: **Python 3.13**, [uv](https://docs.astral.sh/uv/), Windows 11, a mic.

```bash
uv sync
uv run playwright install chromium        # for web reservations / browser
copy config.example.yaml config.yaml      # then fill in what you need
uv run python jarvis14.py
```

Say **"Hey Jarvis"**. Configure either the selected cloud provider's API key
(`openai.cle` or `anthropic.cle`) or an Ollama model in local mode. Everything else
is optional.

Complete beginner? See **[INSTALL_WITH_AI.en.md](INSTALL_WITH_AI.en.md)** — paste it into
any free AI and it installs everything step by step. Or run the interactive installer:
`python scripts/setup.py`. Trouble? `python scripts/doctor.py` diagnoses everything.

## 🤝 Getting help with AI

Paste the contents of **[INSTALL_WITH_AI.en.md](INSTALL_WITH_AI.en.md)** into any free chatbot
(Claude.ai, ChatGPT, Gemini) and it will walk you through the install.

## ⚙️ Configuration

Everything lives in a single **untracked** `config.yaml` (copy from
`config.example.yaml`, which documents every key). Per-integration guides:

| Integration | Guide |
|---|---|
| Local / hybrid / quality modes | [docs/local.md](docs/local.md) |
| Philips Hue | [docs/hue.md](docs/hue.md) |
| OBS | [docs/obs.md](docs/obs.md) |
| Google Calendar + iCal | [docs/agenda.md](docs/agenda.md) |
| Presence detection | [docs/presence.md](docs/presence.md) |
| Discord bot | [docs/discord.md](docs/discord.md) |
| Twilio phone calls | [docs/appels.md](docs/appels.md) |
| Browser (Chrome CDP) | [docs/navigateur.md](docs/navigateur.md) |
| Web reservations | [docs/reservation.md](docs/reservation.md) |
| Instagram | [docs/instagram.md](docs/instagram.md) |
| MCP server | [docs/mcp.md](docs/mcp.md) |
| iPhone bridge (Shortcuts) | [docs/iphone.md](docs/iphone.md) |
| **Cloud providers (OpenAI / Claude)** | [docs/openai.md](docs/openai.md) |
| **Hermes delegation and isolation** | [docs/hermes.md](docs/hermes.md) |
| **Content hub** | [docs/hub_contenu.md](docs/hub_contenu.md) |
| **Content tracking** | [docs/suivi_contenu.md](docs/suivi_contenu.md) |
| **Local control panel** | [docs/panneau.md](docs/panneau.md) |
| **Routing, costs and budgets** | [docs/costs.md](docs/costs.md) |
| **Safe shutdown / wake-up** | [docs/wol.md](docs/wol.md) |
| **Camera hand gestures** | [docs/gestes.md](docs/gestes.md) |
| **Multi-room audio satellites** | [installation and hardware](docs/satellite_installation.md) · [protocol](docs/satellite.md) · [detailed Raspberry/Linux setup](docs/satellite_pi.md) |
| **Music recognition** | [docs/musique.md](docs/musique.md) |
| **Private local cockpit** | [docs/cockpit.md](docs/cockpit.md) |
| **Response overlay** | [docs/overlay.md](docs/overlay.md) |
| **Google Home / Nest** *(experimental)* | [docs/google_home.md](docs/google_home.md) |
| **Alexa / Echo** *(unofficial API)* | [docs/alexa.md](docs/alexa.md) |
| **Perceived latency (UX)** | [docs/latency.md](docs/latency.md) |

## 🛡️ Ethics & Safety

Trust is built in, not bolted on:

- **Voice confirmation** before every irreversible action (send email, book, delete, call…).
- **Phone calls announce themselves** honestly: *"Hi, I'm [name]'s automated voice assistant…"* — never impersonating a human.
- **Never** enters passwords or payment details, and never auto-pays.
- **Protected domains** (banking, taxes, health) on your real browser are **read-only** — Jarvis refuses to act there.
- **Secrets & personal data are never committed** (`config.yaml`, memory, logs, call transcripts, OAuth tokens — all gitignored).
- The assistant only confirms, by phone, what you validated **before** the call.
- **N1/N2/N3 permissions** keep safe reads separate from sensitive and critical actions; N3 always requires a fresh local spoken confirmation and is never remotely executable.
- **iPhone bridge**: remotely, only the exposed safe (N1) tools run without confirmation, plus the ones you list yourself in `pont_iphone.domotique_distante` (empty by default; an N2 placed there loses its remote confirmation, an N3 is always refused). Keep that list to reversible physical actions (lights, scenes).
- **Hermes isolation** allows read-only safe tools and bounded draft output, never credentials or direct physical control.

## 🤝 Contributing

Adding a tool is a single file in `tools/` with an `@outil(...)` decorator — it's
auto-discovered, no wiring needed. Issues and PRs welcome. Please don't commit any
real secrets (check `.gitignore`).

## 📄 License

MIT — see [LICENSE](LICENSE).
