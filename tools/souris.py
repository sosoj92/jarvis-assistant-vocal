"""Controle de la souris : Jarvis clique sur ce qu'il VOIT.

Chaine complete : capture_screen envoie l'ecran a Claude, Claude repere
l'element voulu dans l'image, puis appelle cliquer_ecran avec les coordonnees
DE CETTE IMAGE. La conversion vers l'ecran reel se fait ici.

Pourquoi ce detour plutot que des coordonnees ecran directes : entre ce que
Claude voit et l'ecran, il y a DEUX transformations. Sur Retina, mss capture en
pixels (2x les points), puis l'image est redimensionnee a 1568 px de large. Un
clic calcule sur les pixels tomberait au double de la distance voulue. On
convertit donc en FRACTIONS du moniteur, ce qui annule les deux facteurs d'un
coup et reste juste sur n'importe quel ecran.

Autorisation requise sur macOS : Accessibilite (Reglages Systeme >
Confidentialite et securite), pour le terminal qui lance Jarvis.
"""
from core import plateforme
from core.registre import outil
from tools.ecran import derniere_capture

_MSG_PERMISSION = (
    "Je n'ai pas pu piloter la souris. Sur macOS, autorise l'Accessibilite pour "
    "ton terminal dans Reglages Systeme > Confidentialite et securite, puis "
    "relance-le.")


def _vers_ecran(x, y):
    """(x, y) de l'image envoyee a Claude -> coordonnees ecran en points.

    Leve ValueError si aucune capture n'a ete faite, ou si le point est hors
    de l'image : mieux vaut refuser que cliquer au hasard.
    """
    capture = derniere_capture()
    if not capture:
        raise ValueError("pas-de-capture")

    largeur, hauteur = capture["largeur"], capture["hauteur"]
    x, y = float(x), float(y)
    if not (0 <= x <= largeur and 0 <= y <= hauteur):
        raise ValueError(f"hors-image ({largeur}x{hauteur})")

    m = capture["moniteur"]
    return (round(m["left"] + (x / largeur) * m["width"]),
            round(m["top"] + (y / hauteur) * m["height"]))


@outil(
    nom="cliquer_ecran",
    description="Clique a un endroit precis de l'ecran. A utiliser APRES "
                "capture_screen : donne les coordonnees x,y telles que tu les "
                "vois DANS L'IMAGE capturee (origine en haut a gauche), pas des "
                "coordonnees ecran. Pour 'clique sur le bouton envoyer', "
                "'ouvre ce menu', 'ferme cette fenetre'. Prends une capture "
                "d'abord si tu n'en as pas de recente.",
    parametres={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Abscisse dans l'image capturee."},
            "y": {"type": "integer", "description": "Ordonnee dans l'image capturee."},
            "bouton": {"type": "string", "enum": ["gauche", "droite", "milieu"],
                       "description": "Bouton a utiliser. gauche par defaut."},
            "double": {"type": "boolean",
                       "description": "true pour un double-clic (ouvrir un fichier)."},
        },
        "required": ["x", "y"],
    },
    confirmation=True,
    annonce=lambda args: "Je clique sur l'ecran.",
)
def cliquer_ecran(x: int, y: int, bouton: str = "gauche", double: bool = False) -> str:
    try:
        ex, ey = _vers_ecran(x, y)
    except ValueError as e:
        if str(e) == "pas-de-capture":
            return ("Je n'ai pas de capture d'ecran recente : prends-en une avec "
                    "capture_screen, puis redonne-moi les coordonnees.")
        return f"Ces coordonnees sont hors de l'image capturee {e}."

    if not plateforme.souris_deplacer(ex, ey):
        return _MSG_PERMISSION
    try:
        if not plateforme.souris_cliquer(bouton, double):
            return _MSG_PERMISSION
    except ValueError:
        return f"Bouton inconnu : {bouton}."
    quoi = "Double-clic" if double else "Clic"
    return f"{quoi} {bouton} effectue."


@outil(
    nom="deplacer_souris",
    description="Deplace le curseur sans cliquer, pour survoler un element et "
                "faire apparaitre une infobulle ou un menu. Coordonnees DANS "
                "L'IMAGE de la derniere capture d'ecran.",
    parametres={
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["x", "y"],
    },
)
def deplacer_souris(x: int, y: int) -> str:
    try:
        ex, ey = _vers_ecran(x, y)
    except ValueError as e:
        if str(e) == "pas-de-capture":
            return "Prends d'abord une capture d'ecran."
        return f"Coordonnees hors de l'image {e}."
    if not plateforme.souris_deplacer(ex, ey):
        return _MSG_PERMISSION
    return "Curseur deplace."


@outil(
    nom="defiler_ecran",
    description="Fait defiler la page ou la fenetre sous le curseur. Pour "
                "'descends', 'remonte', 'scroll vers le bas', 'page suivante'.",
    parametres={
        "type": "object",
        "properties": {
            "sens": {"type": "string", "enum": ["haut", "bas", "gauche", "droite"]},
            "crans": {"type": "integer",
                      "description": "Amplitude, 3 par defaut (1 = petit, 10 = grand)."},
        },
        "required": ["sens"],
    },
)
def defiler_ecran(sens: str, crans: int = 3) -> str:
    sens = (sens or "").lower().strip()
    amplitude = max(1, min(int(crans or 3), 20)) * 60
    vertical = horizontal = 0
    if sens == "haut":
        vertical = amplitude
    elif sens == "bas":
        vertical = -amplitude
    elif sens == "gauche":
        horizontal = amplitude
    elif sens == "droite":
        horizontal = -amplitude
    else:
        return f"Sens inconnu : {sens}."

    if not plateforme.souris_defiler(vertical, horizontal):
        return _MSG_PERMISSION
    return f"Defilement vers le {sens}."


@outil(
    nom="taper_texte",
    description="Tape du texte au clavier dans l'application active, comme si "
                "l'utilisateur l'ecrivait. Pour remplir un champ ou une barre "
                "de recherche APRES avoir clique dedans.",
    parametres={
        "type": "object",
        "properties": {
            "texte": {"type": "string", "description": "Le texte a taper."},
        },
        "required": ["texte"],
    },
    confirmation=True,
    annonce=lambda args: "Je tape le texte.",
)
def taper_texte(texte: str) -> str:
    texte = (texte or "").strip()
    if not texte:
        return "Il me faut un texte a taper."
    if not plateforme.taper_texte(texte):
        return _MSG_PERMISSION
    return f"Texte saisi ({len(texte)} caracteres)."
