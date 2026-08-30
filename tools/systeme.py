"""Outils systeme Windows : lancer une application, controler le media, le volume,
et l'extinction propre du PC (N3, avec delai annulable)."""
import ctypes
import os
import subprocess
import time
import webbrowser
from pathlib import Path

from core.config import reglage
from core.registre import outil

# Codes des touches multimedia Windows
_TOUCHES = {
    "muet": 0xAD,
    "baisser": 0xAE,
    "monter": 0xAF,
    "suivant": 0xB0,
    "precedent": 0xB1,
    "pause": 0xB3,
}


def _presser(code, fois=1):
    for _ in range(fois):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)
        time.sleep(0.02)


@outil(
    nom="ouvrir_application",
    description="Lance une application ou ouvre un site web",
    parametres={
        "type": "object",
        "properties": {
            "nom": {
                "type": "string",
                "description": "Nom de l'application ou du site "
                               "(spotify, discord, youtube, calculatrice...)",
            }
        },
        "required": ["nom"],
    },
)
def ouvrir_application(nom: str) -> str:
    """Lance une application ou un site."""
    nom_min = nom.lower().strip()

    raccourcis = {
        "spotify": "spotify:",
        "discord": None,  # traite plus bas
        "navigateur": "https://www.google.com",
        "internet": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "calculatrice": "calc",
        "bloc-notes": "notepad",
        "explorateur": "explorer",
        "parametres": "ms-settings:",
    }

    if nom_min == "discord":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Discord"
        maj = base / "Update.exe"
        if maj.exists():
            subprocess.Popen([str(maj), "--processStart", "Discord.exe"])
            return "Discord lance."
        return "Discord introuvable."

    cible = raccourcis.get(nom_min, nom)

    try:
        if str(cible).startswith("http"):
            webbrowser.open(cible)
        else:
            # os.startfile (pas de shell) -> évite l'injection de commande via un
            # nom piégé (ex. 'x" & calc & "'). Repli argv-list si indisponible.
            try:
                os.startfile(cible)                        # noqa: S606 (pas de shell)
            except AttributeError:
                subprocess.Popen(["cmd", "/c", "start", "", cible], shell=False)
        return f"{nom} lance."
    except Exception as e:
        return f"Impossible de lancer {nom} : {e}"


@outil(
    nom="controler_media",
    description="Controle la lecture audio ou video en cours",
    parametres={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["pause", "suivant", "precedent", "muet"],
                "description": "Action a effectuer",
            }
        },
        "required": ["action"],
    },
)
def controler_media(action: str) -> str:
    """Controle la lecture et le volume.

    action : pause, suivant, precedent, monter, baisser, muet
    """
    action = action.lower().strip()
    if action not in _TOUCHES:
        return f"Action inconnue : {action}"

    fois = 5 if action in ("monter", "baisser") else 1
    _presser(_TOUCHES[action], fois)
    return f"Fait : {action}."


@outil(
    nom="regler_volume",
    description="Monte ou baisse le volume du systeme",
    parametres={
        "type": "object",
        "properties": {
            "sens": {"type": "string", "enum": ["monter", "baisser"]},
            "crans": {
                "type": "integer",
                "description": "Nombre de crans, 2 % chacun. 10 par defaut.",
            },
        },
        "required": ["sens"],
    },
)
def regler_volume(sens: str, crans: int = 10) -> str:
    """Monte ou baisse le volume d'un nombre de crans (2 % par cran)."""
    sens = sens.lower().strip()
    if sens not in ("monter", "baisser"):
        return "Sens invalide."
    _presser(_TOUCHES[sens], max(1, min(crans, 50)))
    return f"Volume {sens}."


# -------------------------------------------------- extinction du PC (N3, physique)

def _annonce_extinction(_args):
    delai = int(reglage("assistant.delai_extinction", 30))
    return (f"Je vais couper les lumieres puis eteindre le PC dans {delai} secondes, "
            "annulable en disant « annule l'extinction »")


@outil(
    nom="eteindre_pc",
    description="Eteint proprement l'ordinateur (extinction Windows). A n'utiliser QUE si "
                "l'utilisateur demande explicitement d'eteindre le PC/l'ordinateur "
                "('eteins le PC', 'arrete l'ordinateur', 'coupe le PC'). Coupe d'abord les "
                "lumieres (scene d'extinction), puis programme l'arret avec un delai "
                "annulable en disant « annule l'extinction ». N'est JAMAIS declenchable a "
                "distance.",
    confirmation=True,
    annonce=_annonce_extinction,
)
def eteindre_pc() -> str:
    """Scene d'extinction (lumieres) PUIS arret Windows programme, annulable (shutdown /a)."""
    # 1) Scene d'extinction AVANT l'arret (coupe les lumieres, etc.).
    try:
        from tools import modes
        modes.activer(reglage("assistant.scene_extinction", "off"))
    except Exception:
        pass
    # 2) Arret programme, annulable pendant le delai.
    delai = max(5, int(reglage("assistant.delai_extinction", 30)))
    try:
        r = subprocess.run(
            ["shutdown", "/s", "/t", str(delai), "/c",
             "Extinction demandee via Jarvis. Dis « annule l'extinction » pour l'arreter."],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0x45B:  # 1115 : un arret est deja programme
            return "Une extinction est deja en cours. Dis « annule l'extinction » pour l'arreter."
        if r.returncode != 0:
            return f"Je n'ai pas pu programmer l'extinction ({(r.stderr or '').strip()[:120]})."
    except Exception as e:
        return f"Je n'ai pas pu programmer l'extinction ({e})."
    return (f"Lumieres coupees. Le PC s'eteint dans {delai} secondes. "
            "Dis « annule l'extinction » si tu changes d'avis.")


@outil(
    nom="annuler_extinction",
    description="Annule une extinction du PC deja programmee (par 'eteins le PC'). Pour "
                "'annule l'extinction', 'n'eteins pas', 'annule l'arret', 'finalement non'.",
)
def annuler_extinction() -> str:
    """Annule l'arret programme (shutdown /a)."""
    try:
        r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return "C'est annule, le PC reste allume."
        return "Il n'y avait aucune extinction en cours."
    except Exception as e:
        return f"Je n'ai pas pu annuler l'extinction ({e})."
