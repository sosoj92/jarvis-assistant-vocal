"""Installateur interactif de Jarvis, pour debutants.

    python scripts/setup.py

Verifie Python, installe les dependances, demande le mode (cloud/local), recueille
les cles / verifie Ollama, detecte le materiel, teste les integrations, et finit par
une phrase de bienvenue prononcee par Jarvis.

Concu pour etre lance meme sans dependances installees : il les installe puis se
relance tout seul dans le bon environnement.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"


def dire_titre(t):
    print("\n" + "=" * 52 + f"\n  {t}\n" + "=" * 52)


def demander(question, defaut=""):
    r = input(f"{question}{f' [{defaut}]' if defaut else ''} : ").strip()
    return r or defaut


def oui(question, defaut=True):
    d = "O/n" if defaut else "o/N"
    r = input(f"{question} ({d}) : ").strip().lower()
    if not r:
        return defaut
    return r in ("o", "oui", "y", "yes")


def lire_cle(prompt):
    """Lit une cle sans l'afficher (getpass) si on est dans un vrai terminal ;
    sinon repli sur input() visible (evite tout blocage en non-interactif)."""
    if sys.stdin.isatty():
        try:
            import getpass
            return getpass.getpass(prompt).strip()
        except Exception:
            pass
    return input(prompt).strip()


# --------------------------------------------------------- pre-requis systeme

def verifier_prerequis_mac():
    """portaudio est indispensable : sounddevice (micro + wake word) s'appuie
    dessus, et la roue Python ne l'embarque pas sur macOS. Sans lui, Jarvis
    installe tout puis echoue au premier `import sounddevice`."""
    if not MAC:
        return
    dire_titre("Pre-requis macOS")

    if not shutil.which("brew"):
        print("Homebrew n'est pas installe. Il fournit portaudio, dont depend le micro.")
        print("  Installe-le :")
        print('    /bin/bash -c "$(curl -fsSL '
              'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
        input("  Appuie sur Entree une fois Homebrew installe (ou pour continuer sans)...")

    if not shutil.which("brew"):
        print("  (!) Sans Homebrew, installe portaudio a la main, sinon le micro "
              "ne marchera pas.")
        return

    deja = subprocess.run(["brew", "list", "portaudio"],
                          capture_output=True, text=True).returncode == 0
    if deja:
        print("  portaudio deja installe.")
    elif oui("Installer portaudio (requis pour le micro) maintenant ?", True):
        subprocess.run(["brew", "install", "portaudio"], check=False)
    else:
        print("  (!) Sans portaudio, le micro et le mot-cle ne fonctionneront pas.")

    import platform as _pf
    puce = "Apple Silicon" if _pf.machine() in ("arm64", "aarch64") else "Intel"
    print(f"\n  Mac {puce} detecte.")
    if puce == "Apple Silicon":
        print("  Whisper tournera sur le CPU (int8) : c'est normal et rapide. "
              "Pas de CUDA sur Mac.")
    else:
        print("  Mac Intel : onnxruntime est plafonne a la 1.23.2 (plus de roue "
              "x86_64 macOS au-dela). C'est deja gere par pyproject.toml.")


def rappeler_permissions_mac():
    """macOS demande une autorisation explicite pour le micro et le clavier."""
    if not MAC:
        return
    dire_titre("Autorisations macOS")
    print("Au premier lancement, macOS demandera des autorisations pour le")
    print("TERMINAL (ou l'app) qui lance Jarvis. A accorder dans")
    print("Reglages Systeme > Confidentialite et securite :\n")
    print("  - Microphone .................. obligatoire (ecoute + mot-cle)")
    print("  - Accessibilite ............... touches media, bascule de fenetres")
    print("  - Enregistrement de l'ecran ... capture d'ecran, titres de fenetres")
    print("\nSi tu refuses une fois, la demande ne revient pas : il faut cocher")
    print("la case a la main dans ces reglages. Details : TROUBLESHOOTING_MAC.md")


# --------------------------------------------------------------- bootstrap

def deps_presentes():
    try:
        import yaml, requests, sounddevice  # noqa: F401
        return True
    except Exception:
        return False


def python_venv():
    p = RACINE / ".venv" / ("Scripts" if WIN else "bin") / ("python.exe" if WIN else "python")
    return p if p.exists() else None


def installer_dependances():
    dire_titre("Installation des dependances")
    if shutil.which("uv"):
        print("uv detecte -> uv sync (recommande).")
        subprocess.run(["uv", "sync"], cwd=RACINE, check=False)
    else:
        print("uv absent -> creation d'un venv + pip install.")
        if not python_venv():
            subprocess.run([sys.executable, "-m", "venv", str(RACINE / ".venv")], check=False)
        py = python_venv() or Path(sys.executable)
        subprocess.run([str(py), "-m", "pip", "install", "-r", str(RACINE / "requirements.txt")],
                       check=False)
    print("\nInstallation de Chromium pour Playwright (reservations/navigateur)...")
    py = python_venv() or Path(sys.executable)
    subprocess.run([str(py), "-m", "playwright", "install", "chromium"], cwd=RACINE, check=False)


def relancer_dans_venv():
    py = python_venv()
    if py and Path(py) != Path(sys.executable):
        print(f"\nRelancement dans l'environnement {py} ...\n")
        os.execv(str(py), [str(py), __file__, "--suite"])
    if not deps_presentes():
        print("\nDependances installees. Relance ce script :")
        print(f"   {python_venv() or 'python'} scripts/setup.py")
        sys.exit(0)


# --------------------------------------------------------------- config

def charger_exemple():
    import yaml
    conf = yaml.safe_load(
        (RACINE / "config.example.yaml").read_text(encoding="utf-8")) or {}
    return adapter_a_l_os(conf)


def adapter_a_l_os(conf):
    """Ajuste les reglages dont la bonne valeur depend du systeme.

    audio.micro vaut 1 dans l'exemple (index eprouve sous Windows). Sur macOS
    et Linux, l'index 1 designe souvent une SORTIE : on met null, qui laisse
    PortAudio prendre l'entree par defaut du systeme.
    """
    if not WIN:
        conf.setdefault("audio", {})["micro"] = None
    return conf


def ecrire_config(conf):
    import yaml
    (RACINE / "config.yaml").write_text(
        yaml.safe_dump(conf, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("\n-> config.yaml ecrit.")


CLES_CLOUD = [
    ("anthropic", "cle", True, "Claude (obligatoire en cloud)",
     "https://console.anthropic.com/  ->  API keys"),
    ("elevenlabs", "cle", False,
     "ElevenLabs (voix ; optionnel, sinon la voix integree a l'OS)",
     "https://elevenlabs.io  ->  profil  ->  API key"),
]


def config_cloud(conf):
    dire_titre("Mode CLOUD — cles API")
    conf["mode"] = "cloud"
    for section, champ, requis, libelle, lien in CLES_CLOUD:
        print(f"\n{libelle}\n  {lien}")
        val = lire_cle("  colle la cle (laisse vide pour ignorer) : ")
        if val:
            conf.setdefault(section, {})[champ] = val
        elif requis:
            print("  (!) sans cle Claude, l'assistant ne pourra pas repondre — tu pourras "
                  "la mettre plus tard dans config.yaml.")
    if oui("\nConfigurer les lumieres Philips Hue maintenant ?", False):
        pont = demander("  IP du pont Hue (ex. 192.168.1.20)")
        cle = demander("  cle Hue (voir docs/hue.md pour la generer)")
        if pont:
            conf.setdefault("hue", {}).update({"pont": pont, "cle": cle})
    print("\nLes autres integrations (Agenda, Discord, Twilio...) se configurent dans "
          "config.yaml quand tu veux — chacune a son guide dans docs/.")


def config_local(conf):
    dire_titre("Mode LOCAL — 100% hors ligne")
    conf["mode"] = "local"
    if not shutil.which("ollama"):
        print("Ollama n'est pas installe.\n  Installe-le : https://ollama.com/download")
        input("  Appuie sur Entree une fois Ollama installe...")
    modele = demander("Modele Ollama a utiliser", "qwen3.5:4b")
    conf.setdefault("ollama", {})["modele"] = modele
    if shutil.which("ollama") and oui(f"Telecharger le modele '{modele}' maintenant ?", True):
        subprocess.run(["ollama", "pull", modele], check=False)
    print("\nWhisper (transcription) se telecharge tout seul au 1er lancement.")
    print("Voix Piper (francais) : telecharge un .onnx dans voix/ (voir docs/local.md). "
          "Sinon Jarvis parlera avec la voix integree a l'OS "
          + ("(`say`)." if MAC else "(SAPI)." if WIN else "(espeak)."))


# --------------------------------------------------------------- materiel + tests

def detecter_materiel():
    dire_titre("Materiel")
    if MAC:
        try:
            from core import plateforme
            gpu = plateforme.infos_gpu()
            print(f"  {plateforme.nom_machine()}")
            if gpu:
                print(f"  GPU : {gpu} (memoire unifiee, partagee avec la RAM)")
            import psutil
            go = psutil.virtual_memory().total / (1024 ** 3)
            print(f"  Memoire : {go:.0f} Go")
            if go < 16:
                print("  (!) <16 Go : en local, prefere qwen3.5:4b (ou reste en cloud).")
        except Exception as e:
            print(f"  (detection materiel partielle : {e})")
        return
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        nom = pynvml.nvmlDeviceGetName(h)
        nom = nom.decode() if isinstance(nom, bytes) else nom
        vram = pynvml.nvmlDeviceGetMemoryInfo(h).total / (1024 ** 3)
        print(f"  GPU : {nom} — {vram:.0f} Go VRAM")
        if vram < 6:
            print("  (!) <6 Go : en local, prefere qwen3.5:2b, ou reste en cloud.")
        pynvml.nvmlShutdown()
    except Exception:
        print("  Pas de GPU NVIDIA detecte : tout marche en CPU (Whisper plus lent).")


def tester_integrations():
    dire_titre("Test des integrations configurees")
    try:
        subprocess.run([sys.executable, str(RACINE / "scripts" / "doctor.py")], check=False)
    except Exception as e:
        print(f"  (impossible de lancer doctor.py : {e})")


def test_micro_et_bienvenue():
    dire_titre("Test micro + bienvenue")
    try:
        import sounddevice as sd
        entrees = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        print(f"  {len(entrees)} entree(s) audio detectee(s).")
    except Exception:
        print("  (test micro impossible)")
    try:
        from core.voix import definir_parleur  # noqa
        # Utilise le meme chemin TTS que l'assistant.
        import importlib
        tts = importlib.import_module("core.tts").tts()
        res = tts.synthetiser("Bonjour, je suis Jarvis. Installation terminee !")
        if res is not None:
            import sounddevice as sd
            audio, freq = res
            sd.play(audio, samplerate=freq); sd.wait()
            print("  Jarvis a parle : installation terminee !")
        else:
            print("  (voix indisponible ici ; elle marchera au lancement de l'assistant)")
    except Exception as e:
        print(f"  (bienvenue vocale non jouee : {e})")


# --------------------------------------------------------------- flux

def main():
    dire_titre("Installation de Jarvis")
    v = sys.version_info
    if v < (3, 10):
        print(f"Python {v.major}.{v.minor} trop ancien. Installe Python 3.10+ (3.13 recommande).")
        sys.exit(1)
    print(f"Python {v.major}.{v.minor}.{v.micro} OK.")

    if "--suite" not in sys.argv and not deps_presentes():
        verifier_prerequis_mac()
        if oui("Installer les dependances maintenant ?", True):
            installer_dependances()
            relancer_dans_venv()
        else:
            print("Sans dependances, la suite ne peut pas tourner. Relance quand tu es pret.")
            sys.exit(0)

    if (RACINE / "config.yaml").exists() and not oui(
            "\nUn config.yaml existe deja. Le remplacer ?", False):
        print("On garde ton config.yaml existant.")
        conf = None
    else:
        conf = charger_exemple()
        dire_titre("Mode d'utilisation")
        print("  1) cloud  — Claude + ElevenLabs (qualite max, cle API requise)")
        print("  2) local  — Ollama + Piper (100% hors ligne, gratuit, GPU recommande)")
        choix = demander("Ton choix (1/2)", "1")
        (config_local if choix.strip() == "2" else config_cloud)(conf)
        ecrire_config(conf)

    detecter_materiel()
    tester_integrations()
    test_micro_et_bienvenue()

    rappeler_permissions_mac()

    dire_titre("Termine !")
    lanceur = "./launch_jarvis.sh" if not WIN else "lancer_jarvis.bat"
    print(f"Lance Jarvis :  {lanceur}   (puis dis « Hey Jarvis »)")
    print("           ou :  uv run python jarvis14.py")
    print("Un souci ? Diagnostic :  uv run python scripts/doctor.py")
    if MAC:
        print("Problemes courants sur Mac : TROUBLESHOOTING_MAC.md")


if __name__ == "__main__":
    main()
