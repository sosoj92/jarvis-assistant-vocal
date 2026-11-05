"""Installateur interactif de Jarvis, pour debutants.

    python scripts/setup.py

Verifie Python, installe les dependances, demande le mode (cloud/local), recueille
les cles / verifie Ollama, detecte le materiel, teste les integrations, et finit par
une phrase de bienvenue prononcee par Jarvis.

Concu pour etre lance meme sans dependances installees : il les installe puis se
relance tout seul dans le bon environnement.
"""
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
WIN = sys.platform == "win32"


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


def _exiger(resultat, etape):
    """Arrete l'installateur si une etape indispensable echoue, au lieu de se
    relancer puis de planter plus loin sur un module manquant."""
    if resultat.returncode != 0:
        print(f"\n(!) Echec de « {etape} » (code {resultat.returncode}). Rien n'est configure.")
        print("    Jarvis exige Python 3.13+. Le plus simple : INSTALLER_JARVIS.bat (Windows)")
        print("    ou uv (https://docs.astral.sh/uv/), qui installe lui-meme le bon Python.")
        sys.exit(1)


def installer_dependances():
    dire_titre("Installation des dependances")
    if shutil.which("uv"):
        print("uv detecte -> uv sync (recommande).")
        _exiger(subprocess.run(["uv", "sync"], cwd=RACINE, check=False), "uv sync")
    else:
        print("uv absent -> creation d'un venv + pip install.")
        if not python_venv():
            subprocess.run([sys.executable, "-m", "venv", str(RACINE / ".venv")], check=False)
        py = python_venv() or Path(sys.executable)
        _exiger(subprocess.run([str(py), "-m", "pip", "install", "-r",
                                str(RACINE / "requirements.txt")], check=False),
                "pip install -r requirements.txt")
    print("\nInstallation de Chromium pour Playwright (reservations/navigateur)...")
    py = python_venv() or Path(sys.executable)
    r = subprocess.run([str(py), "-m", "playwright", "install", "chromium"], cwd=RACINE,
                       check=False)
    if r.returncode != 0:   # seuls les reservations et le navigateur en dependent
        print("  (!) Chromium non installe ; plus tard : uv run playwright install chromium")


def relancer_dans_venv():
    py = python_venv()
    if py and Path(py) != Path(sys.executable):
        print(f"\nRelancement dans l'environnement {py} ...\n")
        # subprocess.call et non os.execv : sous Windows, execv detache un nouveau
        # processus et rend la main au terminal, qui se dispute alors les input().
        sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), "--suite"]))
    if not deps_presentes():
        print("\nDependances installees. Relance ce script :")
        print(f"   {python_venv() or 'python'} scripts/setup.py")
        sys.exit(0)


# --------------------------------------------------------------- config

def est_cle_factice(valeur):
    """Vrai pour une valeur d'exemple de config.example.yaml (« sk-proj-... »,
    « ta-cle-hue »...). Meme regle que scripts/doctor.py (scripts autonomes)."""
    v = str(valeur or "").strip()
    return "..." in v or v.lower().startswith("ta-cle")


def charger_exemple():
    import yaml
    conf = yaml.safe_load((RACINE / "config.example.yaml").read_text(encoding="utf-8")) or {}
    # Une cle d'exemple non vide passerait pour une vraie : Jarvis appellerait le
    # fournisseur avec « sk-proj-... » (401 a chaque demande) et doctor la dirait
    # presente. On vide donc les cles LLM factices ; la vraie est demandee ensuite.
    for section in ("openai", "anthropic"):
        bloc = conf.get(section)
        if isinstance(bloc, dict) and est_cle_factice(bloc.get("cle")):
            bloc["cle"] = ""
    return conf


def ecrire_config(conf):
    import yaml
    (RACINE / "config.yaml").write_text(
        yaml.safe_dump(conf, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("\n-> config.yaml ecrit.")


CLES_CLOUD = [
    ("anthropic", "cle", True, "Claude (obligatoire en cloud)",
     "https://console.anthropic.com/  ->  API keys"),
    ("elevenlabs", "cle", False, "ElevenLabs (voix ; optionnel, sinon voix Windows)",
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
            if section == "anthropic":
                # Ce mode annonce Claude : sans ce choix explicite, l'exemple
                # laisserait cloud.fournisseur: openai, sans cle OpenAI.
                conf["cloud"] = {**(conf.get("cloud") or {}), "fournisseur": "anthropic"}
        elif requis:
            print("  (!) sans cle Claude, l'assistant ne pourra pas repondre — tu pourras "
                  "la mettre plus tard dans config.yaml (anthropic.cle, avec "
                  "cloud.fournisseur: anthropic).")
    if oui("\nConfigurer les lumieres Philips Hue maintenant ?", False):
        pont = demander("  IP du pont Hue (ex. 192.168.1.20)")
        # Saisie masquee comme les cles cloud : le terminal est parfois copie tel quel.
        cle = lire_cle("  cle Hue (voir docs/hue.md pour la generer) : ")
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
          "Sinon Jarvis parlera avec la voix Windows.")


# --------------------------------------------------------------- materiel + tests

def detecter_materiel():
    dire_titre("Materiel")
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
    if v < (3, 13):
        # pyproject exige 3.13 (audioop-lts n'existe pas avant) : pip echouerait.
        print(f"Python {v.major}.{v.minor} trop ancien : Jarvis exige Python 3.13+.")
        print("Le plus simple : INSTALLER_JARVIS.bat (Windows), ou avec uv :")
        print("   uv run python scripts/setup.py   (uv installe lui-meme Python 3.13)")
        sys.exit(1)
    print(f"Python {v.major}.{v.minor}.{v.micro} OK.")

    if "--suite" not in sys.argv and not deps_presentes():
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

    dire_titre("Termine !")
    print("Lance Jarvis :  double-clic sur lancer_jarvis.bat, ou  uv run python jarvis14.py")
    print("               (puis dis « Hey Jarvis »)")
    print("Un souci ? Diagnostic :  python scripts/doctor.py")


if __name__ == "__main__":
    main()
