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
import os
import re
from core import plateforme
from core.config import definir, reglage
from core.registre import outil
from core.util import sans_accents


_VERBES_OUVERTURE = {
    "ouvre", "ouvres", "ouvrir", "lance", "lances", "lancer",
    "demarre", "demarres", "demarrer", "affiche", "affiches", "afficher",
    "accede", "accedes", "acceder", "execute", "executes", "executer",
    "va", "vas", "aller",
}
_PREFIXES_POLITES = (
    ("hey", "jarvis"), ("jarvis",),
    ("est", "ce", "que", "tu", "peux"),
    ("est", "ce", "que", "tu", "pourrais"),
    ("peux", "tu"), ("tu", "peux"),
    ("pourrais", "tu"), ("tu", "pourrais"),
    ("je", "veux", "que", "tu"),
    ("je", "voudrais", "que", "tu"),
    ("j", "aimerais", "que", "tu"),
    ("vas", "y"),
    ("s", "il", "te", "plait"), ("stp",),
)
_SUFFIXES_POLITES = (
    ("s", "il", "te", "plait"), ("stp",), ("merci",),
)
_PREFIXES_CIBLE = (
    ("l", "application"), ("l", "appli"), ("le", "logiciel"),
    ("le", "site"), ("l", "utilitaire"),
    ("sur",), ("a",), ("au",), ("aux",),
    ("le",), ("la",), ("l",),
)
_SUFFIXES_PC = (
    ("sur", "mon", "pc"), ("sur", "le", "pc"),
    ("sur", "mon", "ordinateur"), ("sur", "l", "ordinateur"),
)
_CONNECTEURS_MULTI_ETAPES = {
    "et", "puis", "ensuite", "apres", "pour", "clique", "cliquer",
    "cherche", "chercher", "recherche", "rechercher", "ecris", "ecrire",
    "tape", "taper", "connecte", "connecter", "selectionne", "selectionner",
}
_CIBLES_GENERIQUES = {
    "fichier", "un fichier", "ce fichier", "dossier", "un dossier",
    "ce dossier", "document", "un document", "ce document", "telechargements",
}
_UTILITAIRES = {
    "spotify": "spotify",
    "discord": "discord",
    "calculatrice": "calculatrice",
    "calculette": "calculatrice",
    "bloc notes": "bloc-notes",
    "notepad": "bloc-notes",
    "explorateur": "explorateur",
    "explorateur de fichiers": "explorateur",
    "parametres": "parametres",
    "reglages": "parametres",
}


def _retirer_prefixe(mots, prefixes):
    change = True
    while mots and change:
        change = False
        for prefixe in prefixes:
            if tuple(mots[:len(prefixe)]) == prefixe:
                del mots[:len(prefixe)]
                change = True
                break


def _retirer_suffixe(mots, suffixes):
    change = True
    while mots and change:
        change = False
        for suffixe in suffixes:
            if tuple(mots[-len(suffixe):]) == suffixe:
                del mots[-len(suffixe):]
                change = True
                break


def router_ouverture_simple(phrase, piece=""):
    """Route une ouverture mono-étape sans laisser le LLM choisir Astra.

    Renvoie ``(nom_outil, arguments)`` pour les formulations explicites du type
    « ouvre Spotify » ou « lance Netflix ». Une demande comportant une seconde
    action reste confiée au LLM/Astra. Les cibles inconnues passent volontairement
    par ``launch_app`` : il proposera de les configurer au lieu de piloter l'écran.
    """
    mots = re.sub(
        r"[^a-z0-9]+", " ", sans_accents(str(phrase or ""))
    ).split()
    _retirer_prefixe(mots, _PREFIXES_POLITES)
    if len(mots) >= 2 and mots[0] in {"m", "me"} and mots[1] in _VERBES_OUVERTURE:
        del mots[0]
    if (len(mots) >= 2 and mots[0] == "fais"
            and mots[1] in _VERBES_OUVERTURE):
        del mots[0]
    elif (len(mots) >= 3 and mots[0] == "fais" and mots[1] in {"m", "me", "moi"}
          and mots[2] in _VERBES_OUVERTURE):
        del mots[:2]
    if not mots or mots[0] not in _VERBES_OUVERTURE:
        return None
    navigation_web = mots[0] in {
        "va", "vas", "aller", "accede", "accedes", "acceder",
    }
    del mots[0]
    if mots and mots[0] in {"m", "me", "moi"}:
        del mots[0]
    _retirer_prefixe(mots, _PREFIXES_CIBLE)
    _retirer_suffixe(mots, _SUFFIXES_POLITES)
    _retirer_suffixe(mots, _SUFFIXES_PC)
    if not mots or any(mot in _CONNECTEURS_MULTI_ETAPES for mot in mots):
        return None

    cible = " ".join(mots)
    if cible in _CIBLES_GENERIQUES:
        return None

    # Spotify a son propre lanceur : il ouvre l'application puis reprend la
    # lecture sans passer par Astra (et sans risquer un Play/Pause aveugle).
    if cible == "spotify":
        args = {"piece": piece} if piece else {}
        return "lancer_spotify", args

    from tools.navigateur import est_demande_web
    if est_demande_web(cible):
        return "browser_open", {"url": cible}
    if navigation_web:
        # « va sur YouTube » est une navigation claire ; « va dormir » n'est
        # certainement pas une demande de lancement d'application.
        return None

    clef = _trouver(cible, _apps())
    if clef is not None:
        return "launch_app", {"nom": clef}

    utilitaire = _UTILITAIRES.get(cible)
    if utilitaire:
        return "ouvrir_application", {"nom": utilitaire}

    # Une ouverture simple d'application inconnue ne justifie jamais Astra.
    # launch_app expliquera comment ajouter son chemin à la configuration.
    return "launch_app", {"nom": cible}


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
