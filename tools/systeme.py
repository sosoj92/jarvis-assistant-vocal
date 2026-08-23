"""Outils systeme : lancer une application, controler le media, le volume, et
l'extinction propre de l'ordinateur (N3, avec delai annulable).

Tout le specifique OS (touches multimedia, volume, extinction) est delegue a
core/plateforme.py : ce module ne connait ni Windows, ni macOS, ni Linux.
"""
from core import plateforme
from core.config import reglage
from core.registre import outil

_ACTIONS_MEDIA = ("pause", "suivant", "precedent", "muet")


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

    # Raccourcis communs, avec la cible propre a chaque systeme quand elle differe.
    communs = {
        "spotify": "spotify:",
        "navigateur": "https://www.google.com",
        "internet": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "discord": "Discord" if not plateforme.EST_WINDOWS else None,
    }
    par_os = {
        "calculatrice": "Calculator" if plateforme.EST_MAC else "calc",
        "bloc-notes": "TextEdit" if plateforme.EST_MAC else "notepad",
        "explorateur": "Finder" if plateforme.EST_MAC else "explorer",
        "parametres": ("x-apple.systempreferences:" if plateforme.EST_MAC
                       else "ms-settings:"),
        "terminal": "Terminal" if plateforme.EST_MAC else "cmd",
    }
    raccourcis = {**communs, **par_os}

    if nom_min == "discord" and plateforme.EST_WINDOWS:
        import subprocess
        maj = plateforme.dossier_donnees("Discord") / "Update.exe"
        if maj.exists():
            subprocess.Popen([str(maj), "--processStart", "Discord.exe"])
            return "Discord lance."
        return "Discord introuvable."

    cible = raccourcis.get(nom_min) or nom

    try:
        if str(cible).startswith("http"):
            plateforme.ouvrir_url(cible)
        else:
            plateforme.ouvrir(cible)
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

    action : pause, suivant, precedent, muet
    """
    action = action.lower().strip()
    if action not in _ACTIONS_MEDIA:
        return f"Action inconnue : {action}"

    if plateforme.media(action):
        return f"Fait : {action}."
    if plateforme.EST_MAC:
        return ("Je n'ai pas pu piloter la lecture. Autorise Jarvis dans Reglages "
                "Systeme > Confidentialite et securite > Accessibilite, ou ouvre "
                "un lecteur reconnu (Spotify, Musique).")
    return f"Je n'ai pas pu faire : {action}."


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
    try:
        niveau = plateforme.volume_ajuster(sens, crans)
    except Exception as e:
        return f"Je n'ai pas pu regler le volume ({e})."
    if niveau >= 0:
        return f"Volume {sens}, a {niveau} %."
    return f"Volume {sens}."


# -------------------------------------------------- extinction du PC (N3, physique)

def _annonce_extinction(_args):
    delai = int(reglage("assistant.delai_extinction", 30))
    return (f"Je vais couper les lumieres puis eteindre l'ordinateur dans {delai} "
            "secondes, annulable en disant « annule l'extinction »")


@outil(
    nom="eteindre_pc",
    description="Eteint proprement l'ordinateur. A n'utiliser QUE si "
                "l'utilisateur demande explicitement d'eteindre le PC/le Mac/"
                "l'ordinateur ('eteins le PC', 'arrete l'ordinateur', 'coupe le "
                "Mac'). Coupe d'abord les lumieres (scene d'extinction), puis "
                "programme l'arret avec un delai annulable en disant « annule "
                "l'extinction ». N'est JAMAIS declenchable a distance.",
    confirmation=True,
    annonce=_annonce_extinction,
)
def eteindre_pc() -> str:
    """Scene d'extinction (lumieres) PUIS arret programme, annulable."""
    # 1) Scene d'extinction AVANT l'arret (coupe les lumieres, etc.).
    try:
        from tools import modes
        modes.activer(reglage("assistant.scene_extinction", "off"))
    except Exception:
        pass
    # 2) Arret programme, annulable pendant le delai.
    delai = max(5, int(reglage("assistant.delai_extinction", 30)))
    try:
        ok, detail = plateforme.programmer_extinction(delai)
    except Exception as e:
        return f"Je n'ai pas pu programmer l'extinction ({e})."
    if not ok:
        if detail == "deja_en_cours":
            return ("Une extinction est deja en cours. Dis « annule l'extinction » "
                    "pour l'arreter.")
        return f"Je n'ai pas pu programmer l'extinction ({detail})."
    return (f"Lumieres coupees. L'ordinateur s'eteint dans {delai} secondes. "
            "Dis « annule l'extinction » si tu changes d'avis.")


@outil(
    nom="annuler_extinction",
    description="Annule une extinction de l'ordinateur deja programmee (par "
                "'eteins le PC'). Pour 'annule l'extinction', 'n'eteins pas', "
                "'annule l'arret', 'finalement non'.",
)
def annuler_extinction() -> str:
    """Annule l'arret programme."""
    try:
        if plateforme.annuler_extinction():
            return "C'est annule, l'ordinateur reste allume."
        return "Il n'y avait aucune extinction en cours."
    except Exception as e:
        return f"Je n'ai pas pu annuler l'extinction ({e})."
