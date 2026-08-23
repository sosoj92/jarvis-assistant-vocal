"""Contrôle vocal de l'overlay de réponses (la mini-fenêtre qui affiche à l'écrit
ce que Jarvis dit). JARVIS PUR : affichage local. Outils N1, non exposés au MCP
(l'overlay est sur MON écran, pas pilotable à distance ni par Hermes).

Voir docs/overlay.md.
"""
from core.config import definir, reglage
from core.registre import outil

try:
    import overlay as _overlay
except Exception:
    _overlay = None


def _indispo():
    return ("L'overlay n'est pas disponible (vérifie overlay.actif dans "
            "config.yaml, et que tkinter est présent).")


@outil(
    nom="afficher_reponses",
    description="Affiche ou masque l'overlay de réponses (la fenêtre flottante qui "
                "montre à l'écrit ce que je dis). Pour « affiche les réponses », "
                "« masque les réponses », « montre le texte de tes réponses ».",
    parametres={
        "type": "object",
        "properties": {
            "visible": {"type": "boolean",
                        "description": "true = afficher l'overlay, false = le masquer."}
        },
        "required": ["visible"],
    },
    mcp_expose=False,
)
def afficher_reponses(visible: bool = True) -> str:
    if _overlay is None:
        return _indispo()
    _overlay.set_actif(bool(visible))
    definir("overlay.actif", bool(visible))
    return "J'affiche mes réponses à l'écran." if visible else "Je masque l'overlay."


@outil(
    nom="afficher_reponse",
    description="Réaffiche MA DERNIÈRE réponse dans la fenêtre overlay (surcharge "
                "ponctuelle). Pour « affiche-le », « montre-le à l'écran », « remets-le "
                "en fenêtre », « affiche ça ».",
    mcp_expose=False,
)
def afficher_reponse() -> str:
    if _overlay is None:
        return _indispo()
    ok = _overlay.reafficher()
    return "Je l'affiche." if ok else "Je n'ai pas de réponse récente à afficher."


@outil(
    nom="mode_silencieux_visuel",
    description="Active/désactive le mode silencieux visuel : je réponds SANS parler, "
                "la réponse s'affiche seulement dans l'overlay (pratique en call/stream). "
                "Pour « réponds sans parler », « mode silencieux », « en silence », et "
                "l'inverse « reparle », « remets la voix ».",
    parametres={
        "type": "object",
        "properties": {
            "actif": {"type": "boolean",
                      "description": "true = muet (affichage seul), false = voix + affichage."}
        },
        "required": ["actif"],
    },
    mcp_expose=False,
)
def mode_silencieux_visuel(actif: bool = True) -> str:
    if _overlay is None:
        return _indispo()
    _overlay.set_actif(True)        # l'affichage doit être visible pour être utile
    _overlay.set_muet(bool(actif))
    definir("overlay.actif", True)
    definir("overlay.muet_visuel", bool(actif))
    # En muet, ce message ne sera pas prononcé : il s'affichera dans l'overlay.
    return ("Mode silencieux : je réponds à l'écran sans parler."
            if actif else "Je reparle normalement.")


@outil(
    nom="reglage_overlay",
    description="Règle l'overlay de réponses : opacité (0.3-1), écran cible (0 = "
                "principal, 1 = 2e écran…), et masquage à la capture OBS. Pour « mets "
                "l'overlay sur le 2e écran », « rends l'overlay plus transparent », "
                "« cache l'overlay du stream ».",
    parametres={
        "type": "object",
        "properties": {
            "opacite": {"type": "number", "description": "Opacité 0.3-1.0 (optionnel)."},
            "ecran": {"type": "integer", "description": "Index moniteur (optionnel)."},
            "exclure_obs": {"type": "boolean",
                            "description": "true = invisible pour OBS/capture (optionnel)."},
        },
    },
    mcp_expose=False,
)
def reglage_overlay(opacite: float = None, ecran: int = None,
                    exclure_obs: bool = None) -> str:
    if _overlay is None:
        return _indispo()
    chg = {}
    if opacite is not None:
        chg["opacite"] = max(0.3, min(1.0, float(opacite)))
        definir("overlay.opacite", chg["opacite"])
    if ecran is not None:
        chg["ecran"] = int(ecran)
        definir("overlay.ecran", int(ecran))
    if exclure_obs is not None:
        chg["exclure_obs"] = bool(exclure_obs)
        definir("overlay.exclure_obs", bool(exclure_obs))
    if not chg:
        return "Rien à changer (précise opacité, écran ou exclure_obs)."
    _overlay.configurer(**chg)
    return "C'est réglé."
