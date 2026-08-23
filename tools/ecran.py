"""Capture d'ecran : Jarvis peut VOIR ce qui est affiche (bloc image envoye a Claude)."""
from core.registre import outil

# Cote le plus large envoye a Claude (recommandation vision d'Anthropic).
LARGEUR_CAPTURE = 1568

# Geometrie de la DERNIERE capture, pour que le controle souris puisse
# convertir les coordonnees vues par Claude en coordonnees ecran.
#
# Le piege : sur un ecran Retina, mss capture des PIXELS (2x) alors que la
# souris travaille en POINTS, et l'image est ensuite REDIMENSIONNEE a 1568 px
# avant d'etre envoyee a Claude. Trois espaces differents. On evite toute
# arithmetique fragile en ne gardant que le rectangle du moniteur (en points,
# tel que mss le donne) et la taille de l'image finale : la conversion se fait
# alors en FRACTIONS, insensible au facteur Retina.
_DERNIERE_CAPTURE = {}


def derniere_capture():
    """{"moniteur": {left, top, width, height}, "largeur", "hauteur"} ou {}."""
    return dict(_DERNIERE_CAPTURE)


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
                                     "1 = premier, 2 = deuxieme."}
        },
    },
    lent=True,
    phrase_attente="Je regarde ton ecran.",
)
def capture_screen(ecran: int = 0):
    """Capture l'ecran et renvoie une image JPEG (base64) que Claude peut voir.

    ecran : 0 = ecran principal (defaut), 1 = premier ecran, 2 = deuxieme...
    Renvoie un dict {"image": {...}, "apercu": ...} en cas de succes, sinon une
    chaine d'erreur. Le dispatch transforme l'image en bloc image.
    """
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
                cible = moniteurs[ecran]
            else:
                cible = moniteurs[1] if len(moniteurs) > 1 else moniteurs[0]
            brut = sct.grab(cible)

        image = Image.frombytes("RGB", brut.size, brut.rgb)
        largeur, hauteur = image.size
        if largeur > LARGEUR_CAPTURE:
            ratio = LARGEUR_CAPTURE / largeur
            image = image.resize((LARGEUR_CAPTURE, max(1, round(hauteur * ratio))))

        _DERNIERE_CAPTURE.clear()
        _DERNIERE_CAPTURE.update({
            "moniteur": {"left": cible["left"], "top": cible["top"],
                         "width": cible["width"], "height": cible["height"]},
            "largeur": image.size[0], "hauteur": image.size[1],
        })

        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=80)
        b64 = base64.b64encode(tampon.getvalue()).decode("ascii")
        return {
            "image": {"media_type": "image/jpeg", "data": b64},
            "apercu": (f"Capture ecran {ecran or 1} "
                       f"({image.size[0]}x{image.size[1]}). Pour cliquer sur un "
                       f"element de cette image, utilise cliquer_ecran avec ses "
                       f"coordonnees DANS CETTE IMAGE."),
        }
    except Exception as e:
        return f"Impossible de capturer l'ecran : {e}"
