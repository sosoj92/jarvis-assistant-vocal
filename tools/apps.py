"""Lancement d'applications et de jeux, via un mapping dans config.yaml.

apps: { "borderlands": "C:\\...\\game.exe",           # Windows : chemin .exe
        "borderlands_mac": "/Applications/Jeu.app",   # macOS : bundle .app
        "obs": "OBS",                                 # macOS : nom d'application
        "spotify": "spotify:",
        "un_jeu_steam": "steam://rungameid/XXXX" }

Le lancement passe par core/plateforme.ouvrir() : os.startfile sur Windows,
`open` sur macOS (gere .app, fichiers, URL et protocoles), xdg-open sur Linux.

Si l'app demandee est inconnue, Jarvis propose de l'ajouter ; l'ajout passe par
ajouter_app (confirmation requise) qui ecrit dans config.yaml.
"""
from core import plateforme
from core.config import definir, reglage
from core.registre import outil
from core.util import sans_accents


def _apps():
    return reglage("apps", {}) or {}


def _trouver(nom, apps):
    """Retrouve la clef correspondant a `nom` (exacte puis souple)."""
    cible = sans_accents(nom.strip())
    for k in apps:
        if sans_accents(k) == cible:
            return k
    for k in apps:
        kn = sans_accents(k)
        if cible and (cible in kn or kn in cible):
            return k
    return None


@outil(
    nom="launch_app",
    description="Lance une application ou un jeu configure (Borderlands, Spotify, "
                "OBS...). Pour 'lance Borderlands', 'ouvre Spotify', 'demarre OBS'. "
                "Supporte les jeux Steam (steam://rungameid). Si l'app est inconnue, "
                "renvoie un message : propose alors a l'utilisateur de l'ajouter.",
    parametres={
        "type": "object",
        "properties": {
            "nom": {"type": "string", "description": "Nom de l'application ou du jeu."}
        },
        "required": ["nom"],
    },
)
def launch_app(nom: str) -> str:
    apps = _apps()
    clef = _trouver(nom, apps)
    if clef is None:
        return (f"Je ne connais pas {nom}. Donne-moi son chemin d'installation, "
                "ou son identifiant Steam (steam deux points slash slash rungameid "
                "slash numero), et je l'ajouterai.")
    cible = apps[clef]
    try:
        # gere .exe/.app, fichiers, et protocoles (steam://, spotify:)
        plateforme.ouvrir(cible)
        return f"{clef} lance."
    except Exception as e:
        return f"Impossible de lancer {clef} : {e}"


def _annonce_ajout(args):
    return f"Je vais ajouter {args.get('nom', 'cette application')} a tes applications."


@outil(
    nom="ajouter_app",
    description="Ajoute une application ou un jeu au mapping (config.yaml) : un nom "
                "et un chemin .exe (Windows) ou .app / nom d'application (macOS), "
                "OU un identifiant Steam (steam://rungameid/NUMERO). "
                "A utiliser quand l'utilisateur donne le chemin d'une app inconnue.",
    parametres={
        "type": "object",
        "properties": {
            "nom": {"type": "string", "description": "Nom court de l'application."},
            "chemin": {"type": "string",
                       "description": "Chemin du .exe (Windows) ou du .app / nom "
                                      "d'application (macOS), ou identifiant "
                                      "steam://rungameid/..."},
        },
        "required": ["nom", "chemin"],
    },
    confirmation=True,
    annonce=_annonce_ajout,
)
def ajouter_app(nom: str, chemin: str) -> str:
    nom = (nom or "").strip()
    chemin = (chemin or "").strip()
    if not nom or not chemin:
        return "Il me faut un nom et un chemin."
    apps = _apps()
    apps[nom.lower()] = chemin
    definir("apps", apps)
    return f"{nom} ajoute. Tu peux maintenant dire : lance {nom}."
