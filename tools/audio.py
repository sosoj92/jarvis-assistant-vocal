"""Sortie audio à la voix : « passe sur le casque / sur les enceintes ». JARVIS PUR
(matériel, temps réel). N1, non exposé au MCP (périphérique physique, reste local).
Multiplateforme : sounddevice/PortAudio énumère les sorties de la même façon sur
Windows, macOS et Linux.

Crucial en stream : envoyer les annonces dans MON casque, pas dans le micro du live.
Alias configurables dans config.yaml → audio.sorties (nom d'appareil ou index).
"""
from core.config import definir, reglage
from core.registre import outil
from core.util import sans_accents


def _sorties():
    import sounddevice as sd
    return [(i, d.get("name", "")) for i, d in enumerate(sd.query_devices())
            if d.get("max_output_channels", 0) > 0]


def _resoudre(cible):
    """(device, label) : device = index int ou None (défaut système). Lève si introuvable."""
    c = sans_accents((cible or "").lower()).strip()
    if c in ("defaut", "par defaut", "defaut windows", "windows", "defaut systeme",
             "mac", "macos", "auto", "systeme"):
        return None, "la sortie par défaut du système"

    # alias config (casque / enceintes / ...) -> nom ou index
    cible_reelle = cible
    for nom, val in (reglage("audio.sorties", {}) or {}).items():
        if c == sans_accents(nom.lower()) or c in sans_accents(nom.lower()):
            cible_reelle = val
            break

    if isinstance(cible_reelle, int) or (isinstance(cible_reelle, str)
                                         and str(cible_reelle).strip().isdigit()):
        idx = int(cible_reelle)
        for i, nom in _sorties():
            if i == idx:
                return idx, nom
        raise ValueError("index inconnu")

    cn = sans_accents(str(cible_reelle).lower())
    for i, nom in _sorties():
        if cn and cn in sans_accents(nom.lower()):
            return i, nom
    raise ValueError("nom introuvable")


@outil(
    nom="sortie_audio",
    description="Change le périphérique de SORTIE de ma voix (haut-parleur). Pour "
                "« passe sur le casque », « parle dans les enceintes », « mets le son "
                "sur le casque », « remets la sortie par défaut ». En stream : garder "
                "les annonces dans le casque, hors du micro du live.",
    parametres={
        "type": "object",
        "properties": {
            "cible": {"type": "string", "description": "casque, enceintes, un nom "
                      "d'appareil, un index, ou « défaut »."},
        },
        "required": ["cible"],
    },
    mcp_expose=False,
)
def sortie_audio(cible: str) -> str:
    try:
        device, label = _resoudre(cible)
    except Exception:
        alias = list((reglage("audio.sorties", {}) or {}).keys())
        aide = (" Alias connus : " + ", ".join(alias) + ".") if alias else \
               " Ajoute des alias dans config.yaml (audio.sorties)."
        return f"Je n'ai pas trouvé cette sortie audio.{aide}"
    definir("audio.haut_parleur", device)
    return f"C'est fait, ma voix sort maintenant sur {label}."
