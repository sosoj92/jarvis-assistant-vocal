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


def _resoudre(nom, modes=None):
    """Ramene une formulation libre a un nom de mode."""
    n = _norm(nom)
    modes = _modes() if modes is None else modes
    # 1) Nom exact d'un mode (preset ou sur mesure), avant tout mot-cle : un mode
    # « office » ne doit pas etre detourne vers « off » par sous-chaine.
    noms = {_norm(str(cle)): cle for cle in modes}
    if n in noms:
        return noms[n]
    # 2) Mode sur mesure cite en mots entiers (« active le mode office »).
    cadre = f" {n} "
    for norme in sorted(noms, key=len, reverse=True):
        if norme and noms[norme] not in _MODES_DEFAUT and f" {norme} " in cadre:
            return noms[norme]
    # 3) Intentions libres vers les presets.
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


def _appliquer(nom):
    """Applique un mode. Renvoie (cle, nombre d'actions, echecs) ; cle None si
    le mode est inconnu. Les fonctions Hue ne levent pas : elles renvoient un
    texte, compare ici aux debuts de messages d'echec connus."""
    from tools.lumieres import (PREFIXES_ECHEC, allumer_lumiere, changer_couleur,
                                regler_luminosite)

    modes = _modes()
    cle = _resoudre(nom, modes)
    etapes = modes.get(cle)
    if etapes is None:
        return None, 0, []

    actions, echecs = 0, []

    def noter(resultat):
        nonlocal actions
        actions += 1
        if str(resultat).startswith(PREFIXES_ECHEC):
            echecs.append(str(resultat))

    for etape in etapes:
        piece = etape.get("piece", "toutes")
        if etape.get("eteindre"):
            noter(allumer_lumiere(piece, False))
            continue
        if etape.get("couleur"):
            noter(changer_couleur(piece, etape["couleur"]))
        elif etape.get("allumer", True):
            noter(allumer_lumiere(piece, True))
        if "luminosite" in etape:
            noter(regler_luminosite(piece, etape["luminosite"]))
    return cle, actions, echecs


def appliquer(nom):
    """Applique un mode et renvoie (cle, echecs) : liste vide = tout a reussi.

    Pour les scenes qui annoncent le resultat (« lumieres eteintes ») : elles ne
    doivent le dire que si echecs est vide. cle vaut None si le mode est inconnu.
    """
    cle, _actions, echecs = _appliquer(nom)
    return cle, echecs


def activer(nom):
    """Applique un mode (helper reutilise par la detection de presence)."""
    cle, actions, echecs = _appliquer(nom)
    if cle is None:
        return f"Mode inconnu : {nom}. Modes disponibles : {', '.join(_modes())}."
    if not echecs:
        return f"Mode {cle} active."
    etat = "non applique" if len(echecs) >= actions else "partiellement applique"
    return f"Mode {cle} {etat} — {echecs[0]}"


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
