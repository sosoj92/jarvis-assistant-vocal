"""Diagnostic d'une installation Jarvis existante.

    python scripts/doctor.py

Affiche l'etat de chaque composant (Python, dependances, materiel, mode, LLM, voix,
et chaque integration configuree) avec des marques claires et comment corriger.
Ne lance PAS l'assistant : il se contente de verifier.
"""
import importlib
import shutil
import socket
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from core import plateforme  # noqa: E402  (apres l'ajout de RACINE au sys.path)

OK, KO, WARN, INFO = "  \033[92m[OK]\033[0m", "  \033[91m[X]\033[0m", "  \033[93m[!]\033[0m", "  [i]"
try:
    import colorama  # colore le terminal Windows si dispo
    colorama.just_fix_windows_console()
except Exception:
    if sys.platform == "win32":
        OK, KO, WARN, INFO = "  [OK]", "  [X]", "  [!]", "  [i]"

_scores = {"ok": 0, "ko": 0, "warn": 0}


def ok(msg):
    print(f"{OK} {msg}"); _scores["ok"] += 1


def ko(msg, fix=""):
    print(f"{KO} {msg}")
    if fix:
        print(f"       -> {fix}")
    _scores["ko"] += 1


def warn(msg, fix=""):
    print(f"{WARN} {msg}")
    if fix:
        print(f"       -> {fix}")
    _scores["warn"] += 1


def titre(t):
    print(f"\n=== {t} ===")


def reglage(chemin, defaut=None):
    try:
        from core.config import reglage as _r
        return _r(chemin, defaut)
    except Exception:
        return defaut


# ---------------------------------------------------------------- verifs

def v_systeme():
    titre("Systeme")
    ok(plateforme.nom_machine())
    if plateforme.EST_MAC:
        # Homebrew fournit portaudio, dont depend sounddevice (micro + wake word).
        if shutil.which("brew"):
            ok("Homebrew present")
        else:
            warn("Homebrew absent",
                 "installe-le (brew.sh) : il fournit portaudio, dont depend le micro.")
        if plateforme.est_apple_silicon():
            print(f"{INFO} Apple Silicon : Whisper tourne sur CPU (int8), c'est normal "
                  "et rapide. Pas de CUDA sur Mac.")
        else:
            print(f"{INFO} Mac Intel : onnxruntime plafonne a la 1.23.2 (plus de roue "
                  "x86_64 macOS au-dela). C'est gere par pyproject.toml.")
        print(f"{INFO} Permissions a accorder au terminal qui lance Jarvis : Micro "
              "(obligatoire), Accessibilite (touches media/fenetres), "
              "Enregistrement de l'ecran (capture + titres de fenetres).")


def v_python():
    titre("Python")
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        ko(f"Python {v.major}.{v.minor} trop ancien", "installe Python 3.10+ (3.13 recommande).")


def v_dependances():
    titre("Dependances")
    requis = ["yaml", "requests", "sounddevice", "numpy"]
    optionnels = {"faster_whisper": "transcription", "anthropic": "mode cloud",
                  "playwright": "reservations/navigateur", "mcp": "serveur MCP",
                  "piper": "voix locale", "twilio": "appels", "discord": "Discord"}
    for m in requis:
        try:
            importlib.import_module(m)
            ok(f"{m}")
        except Exception:
            ko(f"{m} manquant", "lance : uv sync   (ou pip install -r requirements.txt)")
    for m, role in optionnels.items():
        try:
            importlib.import_module(m)
            ok(f"{m} ({role})")
        except Exception:
            warn(f"{m} absent ({role}) — optionnel")


def v_config():
    titre("Configuration")
    if (RACINE / "config.yaml").exists():
        ok("config.yaml present")
    else:
        ko("config.yaml absent",
           "copie config.example.yaml en config.yaml (ou lance scripts/setup.py).")
        return False
    mode = reglage("mode", "cloud")
    print(f"{INFO} mode : {mode}")
    return True


def v_materiel():
    titre("Materiel (GPU)")
    try:
        import pynvml
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        for i in range(n):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            nom = pynvml.nvmlDeviceGetName(h)
            nom = nom.decode() if isinstance(nom, bytes) else nom
            vram = pynvml.nvmlDeviceGetMemoryInfo(h).total / (1024 ** 3)
            ok(f"GPU : {nom} — {vram:.0f} Go VRAM")
            print(f"{INFO} modele local conseille : {_reco_modele(vram)}")
        pynvml.nvmlShutdown()
    except Exception:
        if plateforme.EST_MAC:
            gpu = plateforme.infos_gpu()
            ok(f"GPU Apple : {gpu}" if gpu else "GPU integre a la puce Apple")
            print(f"{INFO} memoire unifiee : le modele local partage la RAM. "
                  f"Modele conseille : {_reco_modele_apple()}")
            print(f"{INFO} pas de CUDA sur Mac : Whisper tourne sur CPU (int8).")
            return
        print(f"{INFO} modele local conseille : {_reco_modele(None)}")
        warn("aucun GPU NVIDIA detecte", "ca marche en CPU, mais Whisper sera plus lent.")


def _reco_modele_apple():
    """Suggestion Ollama selon la memoire unifiee du Mac (partagee CPU/GPU)."""
    try:
        import psutil
        go = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return "qwen3.5:4b"
    if go >= 32:
        return "qwen3.5:27b (ou 9b si tu gardes OBS ouvert)"
    if go >= 16:
        return "qwen3.5:9b"
    if go >= 8:
        return "qwen3.5:4b"
    return "qwen3.5:2b (tool-calling limite) ou mode cloud"


def _reco_modele(vram):
    """Suggestion de modele Ollama selon la VRAM (a jour : voir ollama.com/library)."""
    if vram is None:
        return "sans GPU -> petit modele (qwen3.5:2b) ou mode cloud"
    if vram >= 16:
        return "qwen3.5:27b (ou 9b), large marge avec Whisper"
    if vram >= 10:
        return "qwen3.5:9b"
    if vram >= 6:
        return "qwen3.5:4b (teste : rapide et fiable ; le 9b passe mais plus lent)"
    return "qwen3.5:2b (tool-calling limite) ou mode cloud"


def v_llm():
    titre("Modele de langage (LLM)")
    mode = reglage("mode", "cloud")
    if mode == "local":
        hote = reglage("ollama.hote", "http://localhost:11434")
        modele = reglage("ollama.modele", "qwen3.5:4b")
        try:
            import requests
            tags = requests.get(f"{hote.rstrip('/')}/api/tags", timeout=4).json()
            noms = [m.get("name", "") for m in tags.get("models", [])]
            if any(modele.split(":")[0] in n for n in noms):
                ok(f"Ollama joignable, modele '{modele}' present")
            else:
                ko(f"Ollama joignable mais '{modele}' absent", f"lance : ollama pull {modele}")
        except Exception:
            ko("Ollama injoignable", "installe/lance Ollama (ollama.com), puis 'ollama serve'.")
    else:
        if reglage("anthropic.cle", ""):
            ok("cle Anthropic (Claude) presente")
        else:
            ko("cle Anthropic absente", "mets anthropic.cle (console.anthropic.com) dans config.yaml.")


def v_voix():
    titre("Voix (TTS)")
    mode = reglage("mode", "cloud")
    if mode == "local":
        moteur = (reglage("voix_locale", "piper") or "piper").lower()
        if moteur == "kokoro":
            m = reglage("kokoro.modele", "")
            if m and Path(m).exists():
                ok("voix Kokoro trouvee")
            else:
                warn("Kokoro selectionne mais modele introuvable (kokoro.modele)",
                     f"voir docs/local.md ; sinon Jarvis parle avec la "
                     f"{plateforme.nom_voix_systeme()}.")
        else:
            modele = reglage("piper.modele", "")
            voix_dir = list((RACINE / "voix").glob("*.onnx")) if (RACINE / "voix").exists() else []
            if modele and Path(modele).exists() or voix_dir:
                ok("voix Piper trouvee")
            else:
                warn("aucune voix Piper (.onnx)", "telecharge une voix FR dans voix/ (voir "
                     f"docs/local.md). Sinon Jarvis parle avec la "
                     f"{plateforme.nom_voix_systeme()}.")
    else:
        if reglage("elevenlabs.cle", ""):
            ok("cle ElevenLabs presente")
        else:
            warn("pas de cle ElevenLabs",
                 f"Jarvis parlera avec la {plateforme.nom_voix_systeme()}. Optionnel.")
    if plateforme.voix_systeme_disponible():
        ok(f"voix de secours disponible : {plateforme.nom_voix_systeme()}")
    else:
        warn("aucune voix de secours integree a l'OS",
             "sans ElevenLabs ni Piper, Jarvis restera muet.")


def _port_ouvert(hote, port, timeout=2):
    try:
        socket.create_connection((hote, port), timeout).close()
        return True
    except Exception:
        return False


def v_integrations():
    titre("Integrations")
    # Hue
    pont = reglage("hue.pont", "")
    if pont and "X" not in str(pont):
        if _port_ouvert(pont, 443) or _port_ouvert(pont, 80):
            ok(f"pont Hue joignable ({pont})")
        else:
            ko(f"pont Hue injoignable ({pont})", "verifie l'IP du pont (docs/hue.md).")
    else:
        warn("Hue non configure (optionnel)")
    # OBS
    if reglage("obs.mot_de_passe", ""):
        host, port = reglage("obs.host", "localhost"), int(reglage("obs.port", 4455))
        if _port_ouvert(host, port):
            ok(f"OBS WebSocket ouvert ({host}:{port})")
        else:
            warn(f"OBS injoignable ({host}:{port})", "lance OBS + active le serveur WebSocket (docs/obs.md).")
    # cles simplement presentes
    for label, chemin, fix in [
        ("Gmail", "mail.mot_de_passe_app", "mot de passe d'application Google"),
        ("Discord", "discord.token", "token du bot (docs/discord.md)"),
        ("Twilio", "twilio.auth_token", "identifiants Twilio (docs/appels.md)"),
    ]:
        if reglage(chemin, ""):
            ok(f"{label} configure")
        else:
            warn(f"{label} non configure (optionnel)", fix)
    # Google (fichiers)
    if (RACINE / (reglage("agenda.credentials", "google_credentials.json"))).exists():
        ok("identifiants Google presents")
    else:
        warn("Google Agenda non configure (optionnel)", "docs/agenda.md")
    # Instagram
    if reglage("instagram.comptes", None) or reglage("instagram.access_token", ""):
        ok("Instagram configure")
    else:
        warn("Instagram non configure (optionnel)")


def v_micro():
    titre("Micro")
    try:
        import sounddevice as sd
        idx = plateforme.peripherique_audio(
            reglage("audio.micro", plateforme.micro_defaut()))
        entrees = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        if not entrees:
            ko("aucun micro detecte",
               "branche un micro." + ("  Sur macOS, verifie aussi Reglages Systeme > "
                                      "Confidentialite > Microphone." if plateforme.EST_MAC
                                      else ""))
            return
        libelle = "entree par defaut du systeme" if idx is None else f"index {idx}"
        ok(f"{len(entrees)} entree(s) audio ; micro configure : {libelle}")
        try:
            nom = sd.query_devices(sd.default.device[0] if idx is None else idx)["name"]
            print(f"{INFO} {libelle} = {nom}")
        except Exception:
            warn(f"le reglage audio.micro={idx} semble invalide",
                 "choisis un index valide (voir la liste ci-dessus), ou mets null "
                 "pour laisser le systeme choisir.")
    except OSError as e:
        # PortAudio absent : c'est LE probleme d'installation classique sur Mac.
        if plateforme.EST_MAC:
            ko(f"PortAudio indisponible ({e})",
               "installe-le : brew install portaudio, puis relance uv sync.")
        else:
            warn(f"impossible de tester le micro ({e})")
    except Exception as e:
        warn(f"impossible de tester le micro ({e})")


def main():
    print("=" * 48)
    print("  Diagnostic de Jarvis (doctor)")
    print("=" * 48)
    v_systeme()
    v_python()
    v_dependances()
    if v_config():
        v_materiel()
        v_llm()
        v_voix()
        v_integrations()
        v_micro()
    print("\n" + "=" * 48)
    print(f"  Bilan : {_scores['ok']} OK, {_scores['warn']} avertissement(s), "
          f"{_scores['ko']} probleme(s).")
    if _scores["ko"] == 0:
        print("  Tout est bon a l'essentiel. Lance : uv run python jarvis14.py")
    else:
        print("  Corrige les [X] ci-dessus, puis relance ce diagnostic.")
    print("=" * 48)


if __name__ == "__main__":
    main()
