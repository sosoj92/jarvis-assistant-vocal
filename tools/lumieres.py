"""Lumieres Philips Hue (API locale) : allumer, luminosite, couleur.

Contient aussi charger_pieces_hue() (recuperation des pieces au demarrage) et
allumer_si_nuit() (allumage automatique au lancement s'il fait nuit) — appeles
par jarvis14.py, pas exposes comme outils.
"""
import difflib
import json
import urllib.request

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

HUE_PONT = reglage("hue.pont", "")
HUE_CLE = reglage("hue.cle", "")
PIECE_NUIT = reglage("assistant.piece_nuit", "chambre")

# Pieces connues du pont, remplies au demarrage : {nom_normalise: (id, nom)}.
_PIECES_HUE = {}

# Couleurs par nom francais -> (teinte, saturation) au format Hue.
# La teinte va de 0 a 65535, la saturation de 0 (blanc) a 254 (couleur vive).
_COULEURS_HUE = {
    "rouge": (0, 254),
    "orange": (5000, 254),
    "jaune": (10000, 254),
    "vert": (25500, 254),
    "turquoise": (32000, 254),
    "cyan": (35000, 254),
    "bleu": (46920, 254),
    "indigo": (48000, 254),
    "violet": (50000, 254),
    "magenta": (54000, 254),
    "rose": (56100, 254),
    "blanc": (0, 0),
}


def _hue_requete(chemin, methode="GET", corps=None):
    """Appelle l'API locale du pont Hue. Renvoie le JSON decode ou leve."""
    url = f"http://{HUE_PONT}/api/{HUE_CLE}/{chemin}"
    donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
    requete = urllib.request.Request(url, data=donnees, method=methode)
    if donnees is not None:
        requete.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(requete, timeout=5) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def charger_pieces_hue():
    """Recupere les pieces (groups) du pont pour pouvoir les nommer a la voix."""
    _PIECES_HUE.clear()
    try:
        groupes = _hue_requete("groups")
    except Exception as e:
        print(f"Philips Hue indisponible : {e}")
        return
    for ident, groupe in groupes.items():
        nom = groupe.get("name", "")
        if nom:
            _PIECES_HUE[sans_accents(nom)] = (ident, nom)
    if _PIECES_HUE:
        noms = ", ".join(v[1] for v in _PIECES_HUE.values())
        print(f"Philips Hue : {len(_PIECES_HUE)} piece(s) : {noms}")


def _cible_hue(piece):
    """Renvoie (id, nom_lisible) pour une piece ou pour toutes les lumieres.

    Le groupe 0 designe l'ensemble des lumieres cote pont. La comparaison est
    souple : Whisper transcrit mal et l'utilisateur dit "le salon", pas "salon".
    Renvoie None si la piece reste introuvable.
    """
    cible = sans_accents(piece.strip())
    if cible in ("toutes", "tout", "toute", "partout", "toutes les pieces",
                 "toutes les lumieres", "la maison", "maison"):
        return ("0", "Toutes les lumieres")

    if cible in _PIECES_HUE:
        return _PIECES_HUE[cible]

    meilleur, score_max = None, 0.0
    for norme, (ident, nom) in _PIECES_HUE.items():
        if norme in cible or cible in norme:
            return (ident, nom)
        score = difflib.SequenceMatcher(None, cible, norme).ratio()
        if score > score_max:
            meilleur, score_max = (ident, nom), score
    return meilleur if score_max >= 0.6 else None


def _agir_hue(ident, action):
    """Applique une action sur un groupe. Renvoie True si le pont a accepte."""
    reponses = _hue_requete(f"groups/{ident}/action", "PUT", action)
    return all("success" in r for r in reponses)


@outil(
    nom="allumer_lumiere",
    mcp_expose=False,
    description="Allume ou eteint les lumieres Philips Hue d'une piece, ou de "
                "toutes les pieces. A utiliser quand l'utilisateur dit 'allume le "
                "salon', 'eteins la chambre', 'eteins tout'.",
    parametres={
        "type": "object",
        "properties": {
            "piece": {
                "type": "string",
                "description": "Nom de la piece (salon, chambre, cuisine...) "
                               "ou 'toutes' pour l'ensemble des lumieres.",
            },
            "allumer": {
                "type": "boolean",
                "description": "true pour allumer, false pour eteindre.",
            },
        },
        "required": ["piece", "allumer"],
    },
)
def allumer_lumiere(piece: str, allumer: bool = True) -> str:
    """Allume ou eteint une piece (ou toutes les lumieres)."""
    trouve = _cible_hue(piece)
    if trouve is None:
        return f"Piece inconnue : {piece}."
    ident, nom = trouve
    try:
        ok = _agir_hue(ident, {"on": bool(allumer)})
    except Exception as e:
        return f"Hue injoignable : {e}"
    verbe = "allumee" if allumer else "eteinte"
    if not ok:
        return f"Le pont a refuse d'agir sur {nom}."
    return f"{nom} : lumiere {verbe}."


@outil(
    nom="regler_luminosite",
    mcp_expose=False,
    description="Regle la luminosite des lumieres Hue d'une piece en pourcentage. "
                "A utiliser pour 'baisse le salon a 30 pour cent', 'mets la chambre "
                "au maximum'.",
    parametres={
        "type": "object",
        "properties": {
            "piece": {"type": "string", "description": "Nom de la piece ou 'toutes'."},
            "pourcentage": {"type": "integer",
                            "description": "Luminosite voulue, de 0 a 100."},
        },
        "required": ["piece", "pourcentage"],
    },
)
def regler_luminosite(piece: str, pourcentage: int) -> str:
    """Regle la luminosite d'une piece en pourcentage (0 a 100)."""
    trouve = _cible_hue(piece)
    if trouve is None:
        return f"Piece inconnue : {piece}."
    ident, nom = trouve

    pourcentage = max(0, min(int(pourcentage), 100))
    # Cote Hue la luminosite (bri) va de 1 a 254 ; 0 % revient a eteindre.
    if pourcentage == 0:
        action = {"on": False}
    else:
        action = {"on": True, "bri": max(1, round(pourcentage / 100 * 254))}

    try:
        ok = _agir_hue(ident, action)
    except Exception as e:
        return f"Hue injoignable : {e}"
    if not ok:
        return f"Le pont a refuse d'agir sur {nom}."
    return f"{nom} a {pourcentage} pour cent."


@outil(
    nom="changer_couleur",
    mcp_expose=False,
    description="Change la couleur des lumieres Hue d'une piece a partir d'un nom "
                "de couleur en francais. Pour 'mets le salon en bleu', 'passe la "
                "chambre en rouge'.",
    parametres={
        "type": "object",
        "properties": {
            "piece": {"type": "string", "description": "Nom de la piece ou 'toutes'."},
            "couleur": {"type": "string",
                        "description": "Nom de la couleur en francais (rouge, bleu, "
                                       "vert, orange, violet, rose, blanc...)."},
        },
        "required": ["piece", "couleur"],
    },
)
def changer_couleur(piece: str, couleur: str) -> str:
    """Change la couleur d'une piece a partir d'un nom de couleur en francais."""
    trouve = _cible_hue(piece)
    if trouve is None:
        return f"Piece inconnue : {piece}."
    ident, nom = trouve

    cle = sans_accents(couleur.strip())
    valeurs = _COULEURS_HUE.get(cle)
    if valeurs is None:
        for nom_couleur, v in _COULEURS_HUE.items():
            if nom_couleur in cle or cle in nom_couleur:
                valeurs = v
                break
    if valeurs is None:
        return f"Couleur inconnue : {couleur}."

    teinte, saturation = valeurs
    try:
        ok = _agir_hue(ident, {"on": True, "hue": teinte, "sat": saturation})
    except Exception as e:
        return f"Hue injoignable : {e}"
    if not ok:
        return f"Le pont a refuse d'agir sur {nom}."
    return f"{nom} en {couleur}."


def allumer_si_nuit():
    """Au demarrage : allume PIECE_NUIT s'il fait deja sombre dehors.

    « Nuit » = avant le lever ou apres le coucher du soleil, calcule pour ta
    position et la date du jour (donc plus tard en ete, plus tot en hiver).
    """
    from tools.meteo import il_fait_nuit
    if not PIECE_NUIT or not (HUE_PONT and HUE_CLE):
        return
    if il_fait_nuit():
        resultat = allumer_lumiere(PIECE_NUIT, True)
        print(f"  [auto] Il fait nuit -> {resultat}")
