"""Amaran (Aputure) — pilotage des lumières vidéo par gestes/voix. JARVIS PUR :
contrôle LOCAL, temps réel, aucun cloud, aucune app.

L'amaran se pilote en Bluetooth (mesh Sidus Link), pas depuis un PC directement.
Un petit **ESP32 (~5 €)** flashé avec le firmware communautaire
`wesbos/amaran-BLE-control` rejoint le mesh et expose une **API HTTP locale**
(POST /lights/all/on, /brightness, /cct, /hsi). Jarvis lui envoie juste des requêtes.
Renseigne l'URL de l'ESP32 dans config.yaml (amaran.url). Voir docs/lumieres_video.md.

N1 (lumière, réversible, local). Non exposé au MCP (physique, reste chez moi).
"""
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import requests

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

# Couleurs -> teinte HSI (hue 0-360, saturation 100).
_COULEURS = {
    "rouge": 0, "orange": 30, "jaune": 60, "vert": 120, "cyan": 180, "turquoise": 175,
    "bleu": 220, "indigo": 250, "violet": 275, "mauve": 285, "magenta": 300,
    "rose": 325, "blanc": None,   # blanc -> repasser en CCT
}
# Formes féminines (« passe-la en bleue ») ramenées à la clé du dictionnaire.
_FEMININS = {"bleue": "bleu", "verte": "vert", "violette": "violet",
             "blanche": "blanc"}


def _configure():
    return bool(reglage("amaran.url", ""))


def _post(chemin, corps=None):
    base = reglage("amaran.url", "").rstrip("/")
    r = requests.post(f"{base}{chemin}", json=(corps or {}), timeout=6)
    r.raise_for_status()
    return r


_PIECE = (reglage("amaran.piece", "") or "").strip()
_NOMS = [str(n) for n in (reglage("amaran.noms", []) or [])]
_ALIAS = ", ".join(["amaran", "key light", "projecteur", "lumière vidéo"] + _NOMS)
_DESC = (
    f"Pilote la lumière vidéo amaran (aussi appelée : {_ALIAS}) : allumer/éteindre, "
    "intensité, température de couleur, ou couleur. Pour « allume l'amaran », « allume "
    "la key light à 60 % », « mets l'amaran en 5600 kelvin », « passe-la en bleu », "
    "« éteins la lumière vidéo »."
    + (f" Elle est dans la {_PIECE} : utilise CET outil dès que l'utilisateur parle de "
       f"« la lumière de la {_PIECE} » (allume-la EN PLUS de la lampe de la pièce si elle "
       "existe)." if _PIECE else ""))


@outil(
    nom="controler_amaran",
    description=_DESC,
    parametres={
        "type": "object",
        "properties": {
            "etat": {"type": "string", "enum": ["allumer", "eteindre"],
                     "description": "Allumer ou éteindre (optionnel)."},
            "intensite": {"type": "integer", "description": "Luminosité 0-100 (optionnel)."},
            "temperature": {"type": "integer",
                            "description": "Température en kelvin 2500-7500 (optionnel)."},
            "couleur": {"type": "string",
                        "description": "Couleur (rouge, bleu, vert…) (optionnel)."},
        },
    },
    mcp_expose=False,
)
def controler_amaran(etat: str = "", intensite: int = None,
                     temperature: int = None, couleur: str = "") -> str:
    if not _configure():
        return ("L'amaran n'est pas connecté. Il faut un ESP32 flashé avec "
                "wesbos/amaran-BLE-control et son URL dans config.yaml (amaran.url) — "
                "voir docs/lumieres_video.md.")
    try:
        faits = []
        if etat == "eteindre":
            _post("/lights/all/off")
            return "J'éteins la lumière vidéo."
        if etat == "allumer" and intensite is None and temperature is None and not couleur:
            _post("/lights/all/on")
            return "J'allume la key light."

        bri = max(0, min(100, int(intensite))) if intensite is not None else 80
        coul = sans_accents(couleur.lower()).strip()
        coul = _FEMININS.get(coul, coul)
        if coul and coul not in _COULEURS and temperature is None:
            # Rien n'est envoyé : annoncer « c'est fait » serait faux. (Avec une
            # température, le passage en kelvin ci-dessous reste valable.)
            return (f"Je ne connais pas la couleur « {couleur} » : je n'ai rien changé. "
                    "Couleurs possibles : " + ", ".join(_COULEURS) + ".")
        if coul and _COULEURS.get(coul) is not None:
            _post("/lights/all/hsi", {"intensity": bri, "hue": _COULEURS[coul],
                                      "sat": 100})
            faits.append(f"couleur {couleur}")
        elif temperature is not None or coul == "blanc":
            # « Blanc » sans température : on repasse en CCT à 5600 K (lumière du
            # jour), sinon la lampe garderait sa couleur précédente.
            k = max(2500, min(7500, int(temperature if temperature is not None else 5600)))
            _post("/lights/all/cct", {"intensity": bri, "kelvin": k, "gm": 0})
            faits.append(f"{k} kelvin" if temperature is not None else "couleur blanc")
        elif intensite is not None:
            _post("/lights/all/brightness", {"value": bri})
            faits.append(f"{bri} pour cent")
        else:
            _post("/lights/all/on")
            faits.append("allumée")
        return "C'est fait : key light " + ", ".join(faits) + "."
    except Exception as e:
        return f"L'amaran n'a pas répondu ({str(e)[:100]})."
