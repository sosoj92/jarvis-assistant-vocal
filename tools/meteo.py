"""Meteo et localisation (Open-Meteo, gratuit, sans cle ; position via IP).

il_fait_nuit() sert aussi a l'allumage automatique au demarrage (voir lumieres).
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime

from core.config import reglage
from core.registre import outil

# Position devinee via l'IP publique, mise en cache pour la session.
_LIEU = {}

# Codes meteo WMO (renvoyes par Open-Meteo) -> description en francais.
_CODES_METEO = {
    0: "ciel degage", 1: "plutot degage", 2: "partiellement nuageux",
    3: "couvert", 45: "brouillard", 48: "brouillard givrant",
    51: "bruine legere", 53: "bruine", 55: "bruine dense",
    61: "pluie faible", 63: "pluie", 65: "pluie forte",
    66: "pluie verglacante", 67: "pluie verglacante forte",
    71: "neige faible", 73: "neige", 75: "neige forte", 77: "grains de neige",
    80: "averses faibles", 81: "averses", 82: "fortes averses",
    85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grele", 99: "orage violent avec grele",
}


def _localiser():
    """Position (lat, lon, ville) pour la météo. Priorité :
    1. meteo.ville en config (géocodée) — à utiliser si l'IP se trompe (VPN...) ;
    2. sinon auto via l'IP publique (ip-api) ;
    3. repli Paris.
    Mise en cache pour la session."""
    if _LIEU:
        return _LIEU
    # 1) Ville forcée en config (géocodage Open-Meteo, gratuit sans clé).
    ville_cfg = (reglage("meteo.ville", "") or "").strip()
    if ville_cfg:
        try:
            q = urllib.parse.quote(ville_cfg)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=fr"
            with urllib.request.urlopen(url, timeout=5) as reponse:
                res = (json.loads(reponse.read().decode("utf-8")).get("results") or [])
            if res:
                r0 = res[0]
                _LIEU.update({"lat": r0["latitude"], "lon": r0["longitude"],
                              "ville": r0.get("name", ville_cfg)})
                return _LIEU
        except Exception:
            pass  # géocodage KO -> on retombe sur l'IP
    # 2) Auto via IP publique.
    try:
        url = "http://ip-api.com/json/?fields=lat,lon,city"
        with urllib.request.urlopen(url, timeout=5) as reponse:
            d = json.loads(reponse.read().decode("utf-8"))
        _LIEU.update({"lat": d["lat"], "lon": d["lon"], "ville": d.get("city", "")})
    except Exception:
        _LIEU.update({"lat": 48.8566, "lon": 2.3522, "ville": "Paris"})   # 3) repli
    return _LIEU


def _open_meteo(params):
    """Interroge Open-Meteo (gratuit, sans cle). Renvoie le JSON ou leve."""
    lieu = _localiser()
    url = (f"https://api.open-meteo.com/v1/forecast?"
           f"latitude={lieu['lat']}&longitude={lieu['lon']}&timezone=auto&{params}")
    with urllib.request.urlopen(url, timeout=6) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


@outil(
    nom="meteo",
    mcp_expose=True,
    description="Donne la meteo actuelle (temperature, ciel) pour la position de "
                "l'utilisateur.",
    lent=True,
    phrase_attente="Je regarde la meteo.",
)
def meteo(ville: str = "") -> str:
    """Donne la meteo actuelle du lieu (temperature et ciel)."""
    try:
        d = _open_meteo("current=temperature_2m,weather_code,wind_speed_10m")
        actuel = d["current"]
        temp = round(actuel["temperature_2m"])
        ciel = _CODES_METEO.get(actuel["weather_code"], "temps variable")
        vent = round(actuel.get("wind_speed_10m", 0))
        lieu = _LIEU.get("ville") or "ta position"
        return f"A {lieu}, il fait {temp} degres, {ciel}, vent {vent} km/h."
    except Exception as e:
        return f"Meteo indisponible : {e}"


def il_fait_nuit():
    """Vrai s'il fait nuit dehors (avant le lever ou apres le coucher du soleil)."""
    try:
        d = _open_meteo("daily=sunrise,sunset&forecast_days=1")
        lever = datetime.fromisoformat(d["daily"]["sunrise"][0])
        coucher = datetime.fromisoformat(d["daily"]["sunset"][0])
        maintenant = datetime.now()
        return maintenant < lever or maintenant >= coucher
    except Exception:
        return False
