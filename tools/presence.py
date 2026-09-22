"""Detection de presence : ping l'iPhone sur le wifi en arriere-plan.

- Ping toutes les `intervalle` secondes (IP fixe dans config.yaml).
- Absent plus de `seuil_absence` secondes -> active le mode "off".
- De retour -> active le mode "retour" (facultatif).
- Journalise les evenements et se desactive/reactive a la voix.
"""
import threading
import time

from core import plateforme
from core.config import definir, reglage
from core.journal import obtenir
from core.registre import outil

LOG = obtenir()

# Etat runtime du service.
_ETAT = {"actif": True, "present": None, "absent_depuis": None}


def _joignable(ip):
    """Vrai si l'IP repond au ping. Multiplateforme, sans fenetre console."""
    return plateforme.ping(ip, timeout_ms=800)


def _boucle():
    ip = reglage("presence.ip", "")
    intervalle = int(reglage("presence.intervalle", 60))
    seuil = int(reglage("presence.seuil_absence", 600))
    mode_absence = reglage("presence.mode_absence", "off")
    mode_retour = reglage("presence.mode_retour", "retour")
    if not ip:
        return

    from tools.modes import activer
    off_declenche = False

    while True:
        if _ETAT["actif"]:
            # Deux essais : les iPhone dorment parfois cote wifi.
            present = _joignable(ip) or _joignable(ip)
            maintenant = time.time()

            if present:
                if _ETAT["present"] is False:
                    LOG.info("presence: iPhone de retour")
                    if mode_retour:
                        activer(mode_retour)
                _ETAT["present"] = True
                _ETAT["absent_depuis"] = None
                off_declenche = False
            else:
                if _ETAT["absent_depuis"] is None:
                    _ETAT["absent_depuis"] = maintenant
                    LOG.info("presence: iPhone absent")
                elif (not off_declenche
                      and maintenant - _ETAT["absent_depuis"] >= seuil):
                    LOG.info("presence: absence > %ds, mode %s", seuil, mode_absence)
                    activer(mode_absence)
                    off_declenche = True
                _ETAT["present"] = False

        time.sleep(intervalle)


def demarrer_presence():
    """Lance le service de detection en tache de fond (si configure)."""
    ip = reglage("presence.ip", "")
    if not ip:
        return
    _ETAT["actif"] = bool(reglage("presence.actif", True))
    threading.Thread(target=_boucle, daemon=True).start()
    etat = "active" if _ETAT["actif"] else "en pause"
    print(f"Detection de presence {etat} (iPhone {ip}).")


@outil(
    nom="detection_presence",
    description="Active ou desactive la detection de presence (ping de l'iPhone). "
                "Pour 'desactive la detection de presence', 'reactive la presence'.",
    parametres={
        "type": "object",
        "properties": {
            "actif": {"type": "boolean",
                      "description": "true pour activer, false pour desactiver."}
        },
        "required": ["actif"],
    },
)
def detection_presence(actif: bool = True) -> str:
    _ETAT["actif"] = bool(actif)
    definir("presence.actif", bool(actif))
    return "Detection de presence " + ("activee." if actif else "desactivee.")
