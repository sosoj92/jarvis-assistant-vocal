"""Budget : suivi de la consommation LLM de Jarvis, par jour et par fournisseur.

Jarvis instrumente ses PROPRES appels cloud (OpenAI/Claude : tokens + cache) et estime le
cout via une table de prix configurable (budget.prix), persiste dans budget.json
(non versionne). La page Etat du panneau lit resume() (jour + mois), et croise avec
le compteur Twilio (logs/calls/compteur.json) et les insights Hermes (CLI).

Hermes tient sa propre comptabilite (hermes insights) : Jarvis ne double pas.
"""
import datetime as dt
import json
import logging
import threading
from pathlib import Path

from core.config import reglage

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent
_VERROU = threading.Lock()

# Prix par defaut ($ / million de tokens : entree, sortie). Surchargeables via
# config budget.prix. Cle = sous-chaine du nom de modele.
_PRIX_DEFAUT = {
    "gpt-6-astra": (10.0, 50.0),
    "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-5.6-luna": (0.2, 1.2),
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "opus": (5.0, 25.0),
    "mistral-large": (0.50, 1.50),
    "mistral-medium": (0.40, 2.00),
    "mistral-small": (0.10, 0.30),
    "ministral": (0.10, 0.10),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
}


def _fichier():
    return _RACINE / "budget.json"


def _charger():
    f = _fichier()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _prix(modele):
    """(prix_entree, prix_sortie) $/Mtok pour un modele, via la plus longue cle qui matche."""
    m = (modele or "").lower()
    conf = reglage("budget.prix", {}) or {}
    for cle in sorted(set(list(conf) + list(_PRIX_DEFAUT)), key=len, reverse=True):
        if cle.lower() in m:
            v = conf.get(cle) if conf.get(cle) is not None else _PRIX_DEFAUT.get(cle)
            if isinstance(v, (list, tuple)) and len(v) == 2:
                return float(v[0]), float(v[1])
    return 0.0, 0.0


def enregistrer(fournisseur, modele, tin, tout, cache_read=0, cache_creation=0):
    """Ajoute la conso d'un appel LLM au budget du jour. Cout precis (cache read 0.1x,
    cache creation 1.25x quand elle existe)."""
    try:
        pin, pout = _prix(modele)
        cout = (int(tin or 0) * pin
                + int(cache_creation or 0) * pin * 1.25
                + int(cache_read or 0) * pin * 0.1
                + int(tout or 0) * pout) / 1e6
        total_in = int(tin or 0) + int(cache_read or 0) + int(cache_creation or 0)
        jour = dt.date.today().isoformat()
        with _VERROU:
            data = _charger()
            j = data.setdefault(jour, {})
            f = j.setdefault(fournisseur,
                             {"modele": modele, "appels": 0, "tin": 0, "tout": 0, "cout": 0.0})
            f["modele"] = modele
            f["appels"] += 1
            f["tin"] += total_in
            f["tout"] += int(tout or 0)
            f["cout"] = round(f["cout"] + cout, 4)
            _fichier().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        LOG.exception("budget: enregistrement")
    _apres()


def _agreger(data, prefixe):
    """Somme par fournisseur sur toutes les dates commencant par prefixe (jour ou mois)."""
    total = {}
    for jour, parj in data.items():
        if not str(jour).startswith(prefixe):
            continue
        for fourn, v in parj.items():
            t = total.setdefault(fourn, {"modele": v.get("modele", ""), "appels": 0,
                                         "tin": 0, "tout": 0, "cout": 0.0})
            t["appels"] += v.get("appels", 0)
            t["tin"] += v.get("tin", 0)
            t["tout"] += v.get("tout", 0)
            t["cout"] = round(t["cout"] + v.get("cout", 0.0), 4)
    return total


def resume():
    """{jour: {fournisseur: {...}}, mois: {...}} de la conso Jarvis (LLM + voix)."""
    data = _charger()
    auj = dt.date.today()
    return {"jour": _agreger(data, auj.isoformat()),
            "mois": _agreger(data, auj.strftime("%Y-%m"))}


# ==================================================== N12 : voix, totaux, plafonds



def enregistrer_tts(caracteres, fournisseur="voix locale"):
    """Compte la synthese vocale (cout nul en local, trace conservee)."""
    try:
        prix1k = float(reglage("budget.prix_tts", 0.0))
        cout = (int(caracteres or 0) / 1000.0) * prix1k
        jour = dt.date.today().isoformat()
        with _VERROU:
            data = _charger()
            j = data.setdefault(jour, {})
            f = j.setdefault(fournisseur, {"modele": "voix", "appels": 0, "tin": 0,
                                           "tout": 0, "cout": 0.0, "caracteres": 0})
            f["appels"] += 1
            f["caracteres"] = f.get("caracteres", 0) + int(caracteres or 0)
            f["cout"] = round(f["cout"] + cout, 4)
            _fichier().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        LOG.exception("budget: tts")
    _apres()


def _twilio_mois():
    """Cout Twilio du mois courant (logs/calls/compteur.json)."""
    f = _RACINE / (reglage("appels.dossier", "logs/calls")) / "compteur.json"
    if not f.exists():
        return 0.0
    try:
        d = json.loads(f.read_text(encoding="utf-8")) or {}
        if d.get("mois") == dt.date.today().strftime("%Y-%m"):
            return float(d.get("cout", 0.0))
    except Exception:
        pass
    return 0.0


def _total_llm(prefixe):
    data = _charger()
    total = 0.0
    for jour, parj in data.items():
        if jour == "_meta" or not str(jour).startswith(prefixe):
            continue
        for v in parj.values():
            total += float(v.get("cout", 0.0))
    return round(total, 4)


def total(periode):
    """Cout total Jarvis (LLM + voix) + Twilio (mois). periode = 'jour' | 'mois'."""
    prefixe = (dt.date.today().isoformat() if periode == "jour"
               else dt.date.today().strftime("%Y-%m"))
    t = _total_llm(prefixe)
    if periode == "mois":
        t += _twilio_mois()
    return round(t, 4)


def plafonds():
    return (reglage("budget.plafond_jour", None), reglage("budget.plafond_mois", None))


def etat():
    """Totaux, plafonds, %, reste, depassements — base des garde-fous."""
    pj, pm = plafonds()
    pj = float(pj) if pj else None
    pm = float(pm) if pm else None
    tj, tm = total("jour"), total("mois")
    dj = bool(pj and tj >= pj)
    dm = bool(pm and tm >= pm)
    return {
        "total_jour": tj, "total_mois": tm,
        "plafond_jour": pj, "plafond_mois": pm,
        "pct_jour": (tj / pj) if pj else 0.0,
        "pct_mois": (tm / pm) if pm else 0.0,
        "reste_jour": max(0.0, (pj - tj)) if pj else 0.0,
        "reste_mois": max(0.0, (pm - tm)) if pm else 0.0,
        "depasse_jour": dj, "depasse_mois": dm, "depasse": dj or dm,
    }


# ---- meta : signaux d'alerte, crons suspendus, bascule auto ----

def _lire_meta():
    return _charger().get("_meta", {}) or {}


def _ecrire_meta(maj):
    with _VERROU:
        data = _charger()
        m = data.setdefault("_meta", {})
        m.update(maj)
        _fichier().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _auj():
    return dt.date.today().isoformat()


def deja_signale(cle):
    return _lire_meta().get("signaux", {}).get(cle) == _auj()


def marquer(cle):
    sig = _lire_meta().get("signaux", {})
    sig[cle] = _auj()
    _ecrire_meta({"signaux": sig})


def reset_signaux():
    _ecrire_meta({"signaux": {}})


def jour_a_change():
    m = _lire_meta()
    if m.get("jour") != _auj():
        deja = m.get("jour") is not None
        _ecrire_meta({"jour": _auj()})
        return deja
    return False


def memoriser_crons_suspendus(noms):
    _ecrire_meta({"crons_suspendus": list(noms or [])})


def crons_suspendus():
    return _lire_meta().get("crons_suspendus", []) or []


def activer_bascule_auto():
    _ecrire_meta({"bascule_auto": True})


def bascule_auto_active():
    return bool(_lire_meta().get("bascule_auto"))


def effacer_bascule_auto():
    _ecrire_meta({"bascule_auto": False})


def _apres():
    """Déclenche les garde-fous budgétaires (routage) après une dépense."""
    try:
        from core import routage
        routage.apres_depense()
    except Exception:
        pass
