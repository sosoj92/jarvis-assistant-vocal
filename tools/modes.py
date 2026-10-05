"""Modes / ambiances lumineuses : off, retour, film, stream (et sur mesure).

Chaque mode est une liste d'etapes appliquees aux lumieres Hue. Presets integres,
surchargeables/extensibles via config.yaml (section `modes`). Utilise aussi par la
detection de presence (mode off en partant, mode retour en revenant).
"""
from core.config import reglage
from core.registre import outil
from core.util import sans_accents

# Presets integres. Chaque etape : {piece, eteindre|allumer|couleur, luminosite?}.
_MODES_DEFAUT = {
    "off": [{"piece": "toutes", "eteindre": True}],
    "retour": [{"piece": "toutes", "allumer": True, "luminosite": 30}],
    "film": [
        {"piece": "toutes", "eteindre": True},
        {"piece": "salon", "couleur": "orange", "luminosite": 15},
    ],
    "stream": [{"piece": "salon", "allumer": True, "luminosite": 80}],
}


def _norm(s):
    return " ".join(sans_accents(s).replace("'", " ").split())


def _resoudre(nom):
    """Ramene une formulation libre a un nom de mode."""
    n = _norm(nom)
    if any(k in n for k in ("retour", "rentre", "reviens", "je reviens")):
        return "retour"
    if any(k in n for k in ("film", "cinema", "movie")):
        return "film"
    if any(k in n for k in ("stream", "direct", "live")):
        return "stream"
    if any(k in n for k in ("off", "eteindre", "eteins", "eteint", "m en vais",
                            "depart", "je pars", "sortie", "tout couper", "dodo")):
        return "off"
    return n


def _modes():
    return {**_MODES_DEFAUT, **(reglage("modes", {}) or {})}


def activer(nom):
    """Applique un mode (helper reutilise par la detection de presence)."""
    from tools.lumieres import allumer_lumiere, changer_couleur, regler_luminosite

    cle = _resoudre(nom)
    modes = _modes()
    etapes = modes.get(cle)
    if etapes is None:
        return f"Mode inconnu : {nom}. Modes disponibles : {', '.join(modes)}."

    for etape in etapes:
        piece = etape.get("piece", "toutes")
        if etape.get("eteindre"):
            allumer_lumiere(piece, False)
            continue
        if etape.get("couleur"):
            changer_couleur(piece, etape["couleur"])
        elif etape.get("allumer", True):
            allumer_lumiere(piece, True)
        if "luminosite" in etape:
            regler_luminosite(piece, etape["luminosite"])
    return f"Mode {cle} active."


@outil(
    nom="activer_mode",
    mcp_expose=False,
    description="Active une ambiance lumineuse : off (tout eteindre / je m'en vais), "
                "retour (lumieres douces), film (salon tamise), stream. A utiliser "
                "pour 'mode film', 'mode stream', 'tout eteindre', 'je m'en vais'. "
                "Des modes sur mesure peuvent exister dans config.yaml.",
    parametres={
        "type": "object",
        "properties": {
            "mode": {"type": "string",
                     "description": "Nom du mode ou intention (off, retour, film, "
                                    "stream, 'je m'en vais', 'tout eteindre'...)."}
        },
        "required": ["mode"],
    },
)
def activer_mode(mode: str) -> str:
    return activer(mode)
