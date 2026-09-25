"""Controle de la souris : Jarvis clique sur ce qu'il VOIT (Windows).

Chaine : capture_screen envoie l'ecran au LLM, qui repere l'element voulu
DANS L'IMAGE, puis appelle cliquer_ecran avec les coordonnees telles qu'il les
voit dans cette image. La conversion vers l'ecran reel se fait ici.

Pourquoi ce detour plutot que des coordonnees ecran directes : entre l'image que
voit Claude et l'ecran il y a un redimensionnement (l'image est ramenee a 1568 px
de large). On convertit donc les coordonnees image en FRACTIONS du moniteur, ce
qui annule le facteur d'echelle et reste juste sur n'importe quel ecran.

Idee et approche reprises de la PR macOS de la communaute (arturod67), reecrites
en natif Windows (ctypes) pour ce depot.

SECURITE : cliquer est SENSIBLE (peut declencher n'importe quoi a l'ecran).
- confirmation=True : Jarvis annonce et attend le « oui » avant chaque clic.
- mcp_expose=False : LOCAL uniquement, jamais expose au pont iPhone / a Hermes.
  Un token vole ne peut pas piloter ta souris.
"""
import ctypes
import time

from core.registre import outil
from tools.ecran import derniere_capture

# Positionnement en pixels PHYSIQUES (juste meme si l'appli n'est pas DPI-aware,
# pour coller a la capture mss qui est en pixels physiques).
_user32 = ctypes.windll.user32

# (down, up) pour mouse_event selon le bouton.
_BOUTONS = {
    "gauche": (0x0002, 0x0004),   # LEFTDOWN, LEFTUP
    "droite": (0x0008, 0x0010),   # RIGHTDOWN, RIGHTUP
    "milieu": (0x0020, 0x0040),   # MIDDLEDOWN, MIDDLEUP
}
_MONITEURS_GESTE = {}


def _placer_curseur(x, y):
    """Place le curseur en (x, y) pixels physiques. True si ok."""
    try:
        if _user32.SetPhysicalCursorPos(int(x), int(y)):   # respecte le DPI
            return True
    except Exception:
        pass
    try:
        return bool(_user32.SetCursorPos(int(x), int(y)))
    except Exception:
        return False


def _coordonnees_pointeur(x, y, moniteur):
    """Coordonnées normalisées [0,1] -> pixels physiques d'un moniteur."""
    x, y = float(x), float(y)
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("coordonnees-normalisees-invalides")
    return (round(moniteur["left"] + x * max(0, moniteur["width"] - 1)),
            round(moniteur["top"] + y * max(0, moniteur["height"] - 1)))


def _moniteur_geste(numero=1):
    """Géométrie mise en cache ; 1=principal, 2=second écran."""
    numero = max(1, int(numero or 1))
    if numero not in _MONITEURS_GESTE:
        import mss
        with mss.mss() as sct:
            moniteurs = sct.monitors
            cible = moniteurs[numero] if numero < len(moniteurs) else moniteurs[1]
            _MONITEURS_GESTE[numero] = dict(cible)
    return _MONITEURS_GESTE[numero]


def controler_pointeur_geste(x, y, clic=False, moniteur=1):
    """Déplace le pointeur depuis le tracker local authentifié.

    Ce n'est volontairement pas un outil LLM/MCP. Le clic éventuel est produit
    uniquement par un pincement physique lorsque cette option locale est active.
    """
    try:
        ex, ey = _coordonnees_pointeur(x, y, _moniteur_geste(moniteur))
    except Exception:
        return False
    if not _placer_curseur(ex, ey):
        return False
    if clic:
        down, up = _BOUTONS["gauche"]
        _user32.mouse_event(down, 0, 0, 0, 0)
        _user32.mouse_event(up, 0, 0, 0, 0)
    return True


def _vers_ecran(x, y):
    """(x, y) de l'image vue par Claude -> coordonnees ecran en pixels physiques.

    Leve ValueError si aucune capture recente, ou si le point est hors de
    l'image : mieux vaut refuser que cliquer au hasard.
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
                "capture_screen : donne les coordonnees x,y telles que tu les VOIS "
                "DANS L'IMAGE capturee (origine en haut a gauche), PAS des coordonnees "
                "ecran. Pour « clique sur le bouton envoyer », « ouvre ce menu », "
                "« ferme cette fenetre ». Prends une capture d'abord si tu n'en as "
                "pas de recente.",
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
    mcp_expose=False,
)
def cliquer_ecran(x: int, y: int, bouton: str = "gauche", double: bool = False) -> str:
    from core.poste_distant import executer_outil_principal
    distant = executer_outil_principal("cliquer_ecran", {
        "x": x, "y": y, "bouton": bouton, "double": double,
    })
    if distant is not None:
        return str(distant)

    bouton = (bouton or "gauche").lower()
    if bouton not in _BOUTONS:
        return f"Bouton inconnu : {bouton} (gauche, droite ou milieu)."
    try:
        ex, ey = _vers_ecran(x, y)
    except ValueError as e:
        if str(e) == "pas-de-capture":
            return ("Je n'ai pas de capture d'ecran recente : prends-en une avec "
                    "capture_screen, puis redonne-moi les coordonnees.")
        return f"Ces coordonnees sont hors de l'image capturee {e}."

    if not _placer_curseur(ex, ey):
        return "Je n'ai pas pu deplacer la souris."
    down, up = _BOUTONS[bouton]
    try:
        for i in range(2 if double else 1):
            _user32.mouse_event(down, 0, 0, 0, 0)
            _user32.mouse_event(up, 0, 0, 0, 0)
            if double and i == 0:
                time.sleep(0.06)
    except Exception as e:
        return f"Le clic a echoue ({e})."
    quoi = "Double-clic" if double else "Clic"
    return f"{quoi} {bouton} effectue."
