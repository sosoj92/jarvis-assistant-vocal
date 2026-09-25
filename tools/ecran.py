"""Capture d'écran et lecture visuelle ponctuelle, sans contrôle du PC."""
import logging

from core.registre import outil

LOG = logging.getLogger("jarvis.ecran")

# Côté le plus large envoyé au modèle de vision.
LARGEUR_CAPTURE = 1568

# Derniere capture : geometrie du moniteur (pixels physiques) + dimensions de
# l'image ENVOYÉE au modèle. Sert à tools/souris.py pour convertir des coordonnées
# vues dans l'image -> coordonnees ecran reelles (cf. cliquer_ecran).
_DERNIERE = None


def derniere_capture():
    """Renvoie {moniteur, largeur, hauteur} de la derniere capture, ou None."""
    return _DERNIERE


def _fenetre_active(moniteur_global):
    """Rectangle borné de la fenêtre Windows active, ou None en repli."""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        gauche = max(int(rect.left), int(moniteur_global["left"]))
        haut = max(int(rect.top), int(moniteur_global["top"]))
        droite = min(int(rect.right),
                     int(moniteur_global["left"] + moniteur_global["width"]))
        bas = min(int(rect.bottom),
                  int(moniteur_global["top"] + moniteur_global["height"]))
        if droite - gauche < 80 or bas - haut < 80:
            return None
        return {"left": gauche, "top": haut,
                "width": droite - gauche, "height": bas - haut}
    except Exception:
        return None


@outil(
    nom="capture_screen",
    description="Capture l'ecran de l'utilisateur pour VOIR ce qui y est affiche. A "
                "utiliser des que la question fait reference a l'ecran ou a ce qui est "
                "visible : 'qu'est-ce que c'est', 'lis ca', 'cette erreur', 'mon ecran', "
                "'ce message', 'traduis ce texte', 'qu'est-ce qui est ouvert', etc. "
                "L'image est renvoyee et tu peux ensuite la decrire ou la lire.",
    parametres={
        "type": "object",
        "properties": {
            "ecran": {"type": "integer",
                      "description": "Ecran a capturer : 0 = principal (defaut), "
                                     "1 = premier, 2 = deuxieme."},
            "cible": {"type": "string", "enum": ["ecran", "fenetre_active"],
                      "description": "Zone à capturer. Par défaut : écran complet."},
        },
    },
    lent=True,
    phrase_attente="Je regarde ton ecran.",
)
def capture_screen(ecran: int = 0, cible: str = "ecran"):
    """Capture l'écran et renvoie une image JPEG (base64) au modèle de vision.

    ecran : 0 = ecran principal (defaut), 1 = premier ecran, 2 = deuxieme...
    Renvoie un dict {"image": {...}, "apercu": ...} en cas de succes, sinon une
    chaine d'erreur. Le dispatch transforme l'image en bloc image.
    """
    from core.poste_distant import executer_outil_principal
    distant = executer_outil_principal(
        "capture_screen", {"ecran": ecran, "cible": cible})
    if distant is not None:
        return distant

    try:
        import base64
        import io
        import mss
        from PIL import Image
    except ImportError:
        return "La capture d'ecran n'est pas installee (mss et Pillow)."

    try:
        with mss.mss() as sct:
            # monitors[0] = tous les ecrans reunis ; [1] = principal, [2] = second...
            moniteurs = sct.monitors
            if ecran and 1 <= ecran < len(moniteurs):
                zone = moniteurs[ecran]
            else:
                zone = moniteurs[1] if len(moniteurs) > 1 else moniteurs[0]
            if str(cible).lower() == "fenetre_active":
                zone = _fenetre_active(moniteurs[0]) or zone
            brut = sct.grab(zone)

        image = Image.frombytes("RGB", brut.size, brut.rgb)
        largeur, hauteur = image.size
        if largeur > LARGEUR_CAPTURE:
            ratio = LARGEUR_CAPTURE / largeur
            image = image.resize((LARGEUR_CAPTURE, max(1, round(hauteur * ratio))))

        # Memorise la geometrie pour un eventuel clic (tools/souris.py).
        global _DERNIERE
        _DERNIERE = {"moniteur": dict(zone),
                     "largeur": image.size[0], "hauteur": image.size[1]}

        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=80)
        b64 = base64.b64encode(tampon.getvalue()).decode("ascii")
        return {
            "image": {"media_type": "image/jpeg", "data": b64},
            "apercu": f"Capture ecran {ecran or 1} ({image.size[0]}x{image.size[1]}).",
        }
    except Exception:
        LOG.exception("capture d'écran impossible")
        return "Impossible de capturer l'écran."


def analyser_ecran(question: str) -> str:
    """Analyse une seule capture avec le modèle quotidien, jamais avec Astra."""
    from core import cloud
    from core.routage import mode_actuel

    if mode_actuel() == "local":
        return ("La vision d'écran locale n'est pas encore branchée. "
                "Repasse en mode hybride pour cette lecture.")
    capture = capture_screen(cible="fenetre_active")
    if not isinstance(capture, dict) or not capture.get("image"):
        return f"Je ne peux pas voir l'écran : {capture}"
    if not cloud.disponible():
        return "Aucun fournisseur cloud avec vision n'est configuré."
    systeme = (
        "Tu aides l'utilisateur à comprendre une capture de sa fenêtre active. "
        "Réponds en français, brièvement et précisément. Décris seulement ce qui "
        "est utile à sa question. Ne prétends effectuer aucune action. Si une "
        "information sensible apparaît, ne la recopie pas intégralement."
    )
    try:
        return cloud.repondre_vision(
            systeme, question, capture["image"]["data"], qualite=False)
    except Exception:
        LOG.exception("analyse ponctuelle de l'écran impossible")
        return "Je n'arrive pas à analyser l'écran pour le moment."
