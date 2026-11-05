"""Outils vocaux : activer/couper ou calibrer les gestes de la main (webcam).

Le tracking tourne dans un sous-process isolé (Python 3.11 + MediaPipe) ; voir
core/gestes.py et docs/gestes.md. mcp_expose=False : la caméra n'est JAMAIS pilotable
à distance (ni MCP, ni Hermes).
"""
import re

from core.registre import outil
from core.util import sans_accents


def _mots_commande(phrase: str):
    """Normalise une commande et retire wake word/formules de politesse."""
    mots = re.sub(
        r"[^a-z0-9]+", " ", sans_accents((phrase or "").lower())
    ).split()
    prefixes = (
        ("hey", "jarvis"), ("jarvis",),
        ("est", "ce", "que", "tu", "peux"), ("peux", "tu"), ("tu", "peux"),
        ("est", "ce", "que", "tu", "pourrais"),
        ("pourrais", "tu"), ("tu", "pourrais"),
        ("je", "veux", "que", "tu"),
        ("je", "voudrais", "que", "tu"),
        ("j", "aimerais", "que", "tu"),
        ("vas", "y"),
        ("s", "il", "te", "plait"), ("stp",),
    )
    change = True
    while mots and change:
        change = False
        for prefixe in prefixes:
            if tuple(mots[:len(prefixe)]) == prefixe:
                del mots[:len(prefixe)]
                change = True
                break
    return mots


# Une phrase qui parle de média, de minuteur, d'appel ou de document n'est jamais
# un ordre caméra : « mets la chanson Les yeux de la mama », « lance la playlist
# mains libres » ou « lance une visio Teams » doivent rejoindre leur propre outil
# au lieu d'allumer la webcam. Comparaison sur des mots entiers.
_MARQUEURS_HORS_CAMERA = {
    "chanson", "chansons", "musique", "musiques", "morceau", "morceaux",
    "titre", "titres", "album", "albums", "playlist", "playlists",
    "spotify", "netflix", "video", "videos",
    "minuteur", "minuteurs", "chronometre", "alarme", "alarmes",
    "rappel", "rappels", "teams", "zoom", "appel", "appels", "appelle",
    "document", "documents", "fichier", "fichiers",
}


def _hors_camera(mots) -> bool:
    return any(mot in _MARQUEURS_HORS_CAMERA for mot in mots)


def demande_mode_visio(phrase: str):
    """True=active les mains visibles, False=les coupe, None=pas un ordre visio."""
    mots = _mots_commande(phrase)
    if _hors_camera(mots):
        return None
    texte = " ".join(mots)
    # « gestes »/« mains » seuls ne suffisent plus (« lance la playlist mains
    # libres ») : il faut « les gestes », « mes mains » ou « la caméra des
    # gestes » juste après le verbe.
    gestes_explicites = (
        (" ".join(mots[1:3]) in {"les gestes", "mes mains"}
         or " ".join(mots[1:5]) == "la camera des gestes")
        and not any(mot.startswith("calibr") or mot in {"demo", "video", "reconnaissance"}
                    for mot in mots)
    )
    cible_visio = ("visio" in mots or "mode vision" in texte
                   or "controle gestuel" in texte
                   or "controle par gestes" in texte
                   or any(expression in texte for expression in (
                       "controle avec les mains", "controle par les mains",
                       "controle avec mes mains", "controle par mes mains"))
                   or gestes_explicites)
    if not cible_visio:
        return None
    if any(expression in texte for expression in (
            "quitte le mode visio", "quitter le mode visio",
            "quitte le mode vision", "quitter le mode vision",
            "sors du mode visio", "sort du mode visio",
            "coupe le mode visio", "desactive le mode visio",
            "arrete le mode visio", "ferme le mode visio",
            "sors du mode vision", "coupe le mode vision",
            "desactive le mode vision", "arrete le mode vision",
            "ferme le mode vision", "coupe le controle gestuel",
            "arrete le controle par gestes", "coupe les gestes",
            "desactive les gestes", "arrete les gestes")):
        return False
    if texte in {"regarde mes mains", "suis mes mains"}:
        return True
    if mots and mots[0] in {
            "passe", "passes", "passer", "mets", "met", "active", "actives",
            "activer", "lance", "lances", "lancer", "ouvre", "ouvres", "ouvrir",
            "demarre", "demarres", "demarrer", "utilise", "utilises", "utiliser",
            "controle", "controles", "controler"}:
        return True
    return None


def demande_mode_regard(phrase: str):
    """True=active le regard, False=le coupe, None=pas un ordre de regard."""
    mots = _mots_commande(phrase)
    if not any(mot in mots for mot in ("regard", "yeux", "oculaire")):
        return None
    if _hors_camera(mots):
        return None
    texte = " ".join(mots)
    if any(expression in texte for expression in (
            "quitte le mode regard", "quitter le mode regard",
            "quitte le controle oculaire", "quitter le controle oculaire",
            "sors du mode regard", "sort du mode regard",
            "coupe le mode regard", "desactive le mode regard",
            "arrete le mode regard", "ferme le mode regard",
            "coupe le controle du regard", "arrete le controle du regard",
            "ferme le controle du regard", "arrete le suivi oculaire",
            "coupe le suivi oculaire", "arrete le suivi des yeux",
            "coupe le suivi des yeux")):
        return False
    if mots and mots[0] in {
            "passe", "passes", "passer", "mets", "met", "active", "actives",
            "activer", "lance", "lances", "lancer", "ouvre", "ouvres", "ouvrir",
            "demarre", "demarres", "demarrer", "utilise", "utilises", "utiliser",
            "controle", "controles", "controler", "pilote", "pilotes", "piloter"}:
        return True
    return None


def demande_calibration_gestes(phrase: str) -> bool:
    """Vrai uniquement pour un ordre explicite d'ouverture de la calibration."""
    mots = _mots_commande(phrase)
    if not mots or mots[0] not in {
            "lance", "lancer", "ouvre", "ouvrir", "demarre", "demarrer",
            "calibre", "calibrer", "recalibre", "recalibrer", "regle", "regler",
            "ajuste", "ajuster", "refais", "refaire", "teste", "tester",
            "lances", "ouvres", "demarres", "calibres", "recalibres",
            "regles", "ajustes", "testes"}:
        return False
    texte = " ".join(mots)
    calibration = "calibr" in texte or "reconnaissance" in texte
    cible = any(m in mots for m in ("geste", "gestes", "main", "mains", "webcam"))
    return calibration and cible


def demande_demo_gestes(phrase: str) -> bool:
    """Vrai pour un ordre explicite de démo visible avec actions réelles."""
    mots = _mots_commande(phrase)
    if not mots or mots[0] not in {
            "lance", "lancer", "ouvre", "ouvrir", "demarre", "demarrer",
            "active", "activer", "montre", "montrer", "teste", "tester"}:
        return False
    cible = any(m in mots for m in ("geste", "gestes", "main", "mains", "webcam"))
    visible = ("demo" in mots or "video" in mots
               or ("calibration" in mots and "action" in mots))
    return cible and visible


@outil(
    nom="controler_gestes",
    description="Active ou coupe le contrôle par gestes de la main (webcam). A utiliser "
                "pour 'active les gestes', 'coupe les gestes', 'allume/éteins la caméra "
                "des gestes' ou 'Jarvis regarde mes mains'.",
    parametres={
        "type": "object",
        "properties": {
            "actif": {"type": "boolean", "description": "true = activer, false = couper."}
        },
        "required": ["actif"],
    },
)
def controler_gestes(actif: bool) -> str:
    from core import gestes
    return gestes.demarrer() if actif else gestes.arreter()


@outil(
    nom="lancer_calibration_gestes",
    description="Ouvre sur le PC la fenêtre locale de calibration de la webcam et "
                "des gestes. À utiliser pour 'lance/ouvre la calibration des gestes', "
                "'je veux calibrer mes mains' ou 'teste la reconnaissance des mains'. "
                "Ne pas confondre avec controler_gestes, qui active le contrôle réel.",
    parametres={"type": "object", "properties": {}},
)
def lancer_calibration_gestes() -> str:
    from core import gestes
    return gestes.lancer_calibration()


@outil(
    nom="lancer_demo_gestes",
    description="Ouvre la caméra avec les repères et les diagnostics visibles, tout "
                "en appliquant réellement les gestes sur le PC. Pour 'ouvre la démo "
                "des gestes' ou 'lance les gestes visibles pour ma vidéo'. "
                "Local uniquement.",
    parametres={"type": "object", "properties": {}},
    mcp_expose=False,
)
def lancer_demo_gestes() -> str:
    from core import gestes
    return gestes.demarrer_demo()


@outil(
    nom="lancer_mode_regard",
    description="Active localement le contrôle du pointeur par le regard. Ouvre la "
                "calibration des yeux puis le suivi réel. À utiliser pour 'passe en "
                "mode regard' ou 'active le contrôle avec les yeux'. La webcam reste "
                "locale et le clic gauche par sourcils est actif après calibration.",
    parametres={"type": "object", "properties": {}},
    mcp_expose=False,
)
def lancer_mode_regard() -> str:
    from core import gestes
    return gestes.demarrer_regard()


@outil(
    nom="quitter_mode_regard",
    description="Coupe le contrôle du regard et libère la webcam. À utiliser pour "
                "'quitte/coupe/ferme le mode regard'.",
    parametres={"type": "object", "properties": {}},
    mcp_expose=False,
)
def quitter_mode_regard() -> str:
    from core import gestes
    return gestes.arreter_regard()
