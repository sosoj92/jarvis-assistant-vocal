"""Google Home / Nest — EXPERIMENTAL (non testé sur matériel réel).

⚠️ Honnêteté sur l'API : la seule API Google **officielle** et stable est la
**Smart Device Management (SDM)**. Elle pilote les appareils **Nest** (thermostats,
caméras, sonnettes) et permet de **lister les appareils + lire leur état**. Elle ne
fournit **pas** de contrôle générique on/off ni de luminosité pour des lumières
tierces liées à Google Home — aucun trait `OnOff`/`Brightness` côté SDM. Il n'existe
à ce jour **aucune API serveur/Python officielle** pour piloter des lumières Google
Home. Pour des lumières : préfère l'intégration **native** (les Philips Hue sont déjà
gérées par Jarvis) ou un pont **Home Assistant**.

Ce module fournit donc, de façon honnête :
  - google_home_etat()          -> liste des appareils + état (FIABLE, officiel). N1
  - google_home_allumer(...)    -> best-effort ; message clair si non supporté. N2
  - google_home_luminosite(...) -> non supporté par l'API officielle (message clair). N2

Credentials dans config.yaml (jamais en dur), voir docs/google_home.md :
  google_home: { project_id, client_id, client_secret, refresh_token }
"""
import logging

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

LOG = logging.getLogger("jarvis")
_BASE = "https://smartdevicemanagement.googleapis.com/v1"


def _conf(cle, defaut=""):
    return reglage(f"google_home.{cle}", defaut)


def _configure():
    return all(_conf(k) for k in ("project_id", "client_id", "client_secret", "refresh_token"))


def _msg_config():
    return ("Google Home n'est pas configuré (expérimental). Renseigne "
            "google_home.project_id / client_id / client_secret / refresh_token dans "
            "config.yaml — voir docs/google_home.md.")


def _access_token():
    """Échange le refresh_token contre un access_token (OAuth2)."""
    import requests
    r = requests.post("https://oauth2.googleapis.com/token", timeout=10, data={
        "client_id": _conf("client_id"), "client_secret": _conf("client_secret"),
        "refresh_token": _conf("refresh_token"), "grant_type": "refresh_token"})
    r.raise_for_status()
    return r.json()["access_token"]


def _appareils():
    """Liste brute des appareils SDM (dicts). Lève si erreur."""
    import requests
    tok = _access_token()
    url = f"{_BASE}/enterprises/{_conf('project_id')}/devices"
    r = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=12)
    r.raise_for_status()
    return r.json().get("devices", [])


def _nom_lisible(dev):
    """Nom donné dans Google Home (parentRelations) ou type court."""
    for rel in dev.get("parentRelations", []):
        if rel.get("displayName"):
            return rel["displayName"]
    return dev.get("type", "").split(".")[-1] or "appareil"


def _trouver(devices, appareil):
    cible = sans_accents((appareil or "").lower())
    for d in devices:
        if cible in sans_accents(_nom_lisible(d).lower()):
            return d
    return None


def _resume_erreur(e):
    """Code HTTP de la reponse, sinon le type de l'erreur (le detail reste au journal)."""
    return (getattr(getattr(e, "response", None), "status_code", None)
            or type(e).__name__)


# ---------------------------------------------------------------------- outils

@outil(
    nom="google_home_etat",
    description="[EXPERIMENTAL] Liste les appareils Google Home / Nest enregistrés et "
                "leur état (via l'API officielle Smart Device Management). Pour 'mes "
                "appareils Google Home', 'état de la maison Google'.",
    lent=True,
    phrase_attente="Je regarde tes appareils Google Home.",
)
def google_home_etat() -> str:
    if not _configure():
        return _msg_config()
    try:
        devices = _appareils()
    except Exception as e:
        LOG.exception("google_home: etat")
        # Code HTTP ou type d'erreur seulement : jamais l'URL SDM brute (voix, LLM).
        return (f"Je n'accède pas à Google Home ({_resume_erreur(e)}). "
                "Vérifie la config (docs/google_home.md).")
    if not devices:
        return "Aucun appareil Google Home / Nest enregistré (côté API SDM)."
    lignes = []
    for d in devices:
        traits = d.get("traits", {})
        etat = []
        conn = traits.get("sdm.devices.traits.Connectivity", {}).get("status")
        if conn:
            etat.append(conn.lower())
        temp = traits.get("sdm.devices.traits.Temperature", {}).get("ambientTemperatureCelsius")
        if temp is not None:
            etat.append(f"{round(temp)}°C")
        lignes.append(f"{_nom_lisible(d)} ({d.get('type','').split('.')[-1]})"
                      + (f" — {', '.join(etat)}" if etat else ""))
    return "Appareils Google Home : " + " ; ".join(lignes) + "."


@outil(
    nom="google_home_allumer",
    description="[EXPERIMENTAL] Tente d'allumer/éteindre un appareil Google Home. "
                "L'API officielle (SDM) ne pilote que les Nest ; pour une lumière tierce, "
                "ce n'est pas supporté (message clair renvoyé).",
    parametres={
        "type": "object",
        "properties": {
            "appareil": {"type": "string", "description": "Nom de l'appareil dans Google Home."},
            "actif": {"type": "boolean", "description": "true = allumer, false = éteindre."},
        },
        "required": ["appareil", "actif"],
    },
    confirmation=True,
    annonce=lambda a: f"Je vais {'allumer' if a.get('actif') else 'éteindre'} "
                      f"{a.get('appareil','')} sur Google Home.",
)
def google_home_allumer(appareil: str, actif: bool = True) -> str:
    if not _configure():
        return _msg_config()
    try:
        dev = _trouver(_appareils(), appareil)
    except Exception as e:
        LOG.exception("google_home: appareils")
        return f"Je n'accède pas à Google Home ({_resume_erreur(e)})."
    if dev is None:
        return f"Appareil introuvable dans Google Home : {appareil}."
    # SDM n'expose pas de trait OnOff générique (lumières/prises tierces).
    return ("L'API officielle Google (Smart Device Management) ne permet pas "
            f"d'allumer/éteindre « {_nom_lisible(dev)} » : elle ne pilote que les Nest "
            "(thermostats/caméras). Pour des lumières, utilise l'intégration native "
            "(les Philips Hue sont déjà gérées par Jarvis) ou un pont Home Assistant — "
            "voir docs/google_home.md.")


@outil(
    nom="google_home_luminosite",
    description="[EXPERIMENTAL] Règle la luminosité d'une lumière Google Home. NON "
                "supporté par l'API officielle (SDM n'a pas de trait luminosité) — "
                "renvoie un message clair.",
    parametres={
        "type": "object",
        "properties": {
            "appareil": {"type": "string"},
            "niveau": {"type": "integer", "description": "0 à 100."},
        },
        "required": ["appareil", "niveau"],
    },
    confirmation=True,
    annonce=lambda a: f"Je vais régler {a.get('appareil','')} à {a.get('niveau','')}%.",
)
def google_home_luminosite(appareil: str, niveau: int = 50) -> str:
    if not _configure():
        return _msg_config()
    return ("La luminosité n'est pas pilotable via l'API officielle Google (Smart Device "
            "Management ne fournit pas de trait de luminosité pour les lumières tierces). "
            "Utilise l'intégration native (Philips Hue déjà gérées par Jarvis) ou un pont "
            "Home Assistant — voir docs/google_home.md.")
