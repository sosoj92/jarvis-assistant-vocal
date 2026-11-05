"""Cockpit : app web locale (servie par le serveur unifié) — tableau de bord perso.

DOCTRINE : Jarvis détient les clés et le corps ; TOUTES les données restent LOCALES
(dossier finances/ gitignoré). Rien n'est exposé au MCP ni au réseau : garde
local-only (comme le panneau). Hermes ne reçoit que des AGRÉGATS, sur demande.

Phase 1 : la fondation + le volet FINANCES (abonnements.yaml -> total mensuel,
timeline des échéances, alertes « prélèvement demain » / « montant changé »).
Volets Énergie / Réseaux / Contenu / Maison à venir. Voir docs/cockpit.md.
"""
import calendar
import datetime as dt
import json
import logging
import math
import shutil
import subprocess
from pathlib import Path

import yaml

from core.config import reglage
from core.panneau import _local_seulement   # même garde local que le panneau

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent
_HTML = _RACINE / "web" / "cockpit.html"
_DOSSIER = _RACINE / "finances"
_ABONNEMENTS = _DOSSIER / "abonnements.yaml"
_ETAT_ABO = _DOSSIER / ".etat_abonnements.json"   # pour détecter « montant changé »


# ============================================================ fenêtre app

def _navigateur():
    chemin = reglage("cockpit.navigateur", "")
    if chemin and Path(chemin).exists():
        return chemin
    for nom in ("chrome", "msedge", "chromium"):
        exe = shutil.which(nom)
        if exe:
            return exe
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(p).exists():
            return p
    return None


def ouvrir_fenetre():
    """Ouvre le cockpit en fenêtre app (--app) sur l'écran choisi (cockpit.ecran)."""
    import time
    from core.serveur import _port, _port_ouvert
    for _ in range(40):                      # attend que le serveur écoute
        if _port_ouvert(_port()):
            break
        time.sleep(0.25)
    url = f"http://localhost:{_port()}/cockpit"
    exe = _navigateur()
    if not exe:
        from core.ouvrir_web import ouvrir_url
        ouvrir_url(url)
        return
    args = [exe, f"--app={url}", "--new-window"]
    try:
        import overlay
        rects = overlay._enum_moniteurs()
        idx = int(reglage("cockpit.ecran", 0))
        if rects and 0 <= idx < len(rects):
            l, t, _, _ = rects[idx]
            args += [f"--window-position={l + 40},{t + 40}", "--window-size=1280,860"]
    except Exception:
        pass
    try:
        subprocess.Popen(args)
        LOG.info("cockpit ouvert (%s)", url)
    except Exception:
        LOG.exception("cockpit: lancement navigateur")


# ============================================================ finances

_PERIODES = {                       # périodicité -> facteur vers le MENSUEL
    "mensuel": 1.0, "mois": 1.0,
    "annuel": 1 / 12, "an": 1 / 12, "annee": 1 / 12, "année": 1 / 12,
    "trimestriel": 1 / 3, "trimestre": 1 / 3,
    "semestriel": 1 / 6, "semestre": 1 / 6,
    "hebdomadaire": 52 / 12, "hebdo": 52 / 12, "semaine": 52 / 12,
}
_HEBDO = {"hebdomadaire", "hebdo", "semaine"}
_ALERTE_JOURS = 7                   # durée d'affichage d'un « montant changé »


def _facteur_mensuel(periodicite):
    return _PERIODES.get(sans_accents_min(periodicite), 1.0)


def _montant(valeur):
    """Montant saisi -> float. Accepte la virgule et le symbole € (« 9,99 € ») ;
    absent ou vide -> 0. Lève ValueError si la valeur reste illisible."""
    if valeur is None or valeur == "":
        return 0.0
    if isinstance(valeur, (int, float)):
        montant = float(valeur)
    else:
        # sans espaces (y compris insécables : « 1 234,50 »), ni €, virgule -> point
        texte = "".join(str(valeur).replace("€", "").split()).replace(",", ".")
        montant = float(texte)
    if not math.isfinite(montant):
        raise ValueError(f"montant non fini : {valeur!r}")
    return montant


def sans_accents_min(s):
    from core.util import sans_accents
    return sans_accents(str(s or "").lower().strip())


def _ajouter_mois(d, n):
    m = d.month - 1 + n
    an = d.year + m // 12
    mois = m % 12 + 1
    jour = min(d.day, calendar.monthrange(an, mois)[1])
    return dt.date(an, mois, jour)


def _prochaine_echeance(abo, auj):
    """Prochaine date de prélèvement >= aujourd'hui. Lève ValueError/TypeError si
    `jour` est illisible (l'appelant écarte alors la ligne)."""
    per = sans_accents_min(abo.get("periodicite", "mensuel"))
    # date d'ancrage explicite ?
    ancre = abo.get("date")
    if ancre:
        try:
            d = dt.date.fromisoformat(str(ancre))
        except ValueError:
            d = None
        if d:
            if per in _HEBDO:
                # pas de 7 jours depuis l'ancre (même jour de la semaine)
                if d < auj:
                    d += dt.timedelta(days=((auj - d).days + 6) // 7 * 7)
                return d
            pas = {"annuel": 12, "an": 12, "annee": 12, "année": 12,
                   "trimestriel": 3, "trimestre": 3, "semestriel": 6,
                   "semestre": 6}.get(per, 1)
            # Toujours compter depuis l'ancre d'origine : repartir de la date déjà
            # bornée (31/01 -> 28/02) ferait glisser l'échéance au 28 pour de bon.
            k = max(0, ((auj.year - d.year) * 12 + auj.month - d.month) // pas)
            prochaine = _ajouter_mois(d, k * pas)
            while prochaine < auj:
                k += 1
                prochaine = _ajouter_mois(d, k * pas)
            return prochaine
    # sinon : jour du mois (mensuel par défaut)
    jour = int(abo.get("jour", 1) or 1)
    jour = max(1, min(jour, 28))
    d = dt.date(auj.year, auj.month, min(jour, calendar.monthrange(auj.year, auj.month)[1]))
    if d < auj:
        d = _ajouter_mois(d, 1)
    return d


def _charger_abonnements():
    """-> (abonnements, etat_fichier) avec etat_fichier « absent », « ok » ou
    « invalide ». Un fichier invalide n'est jamais confondu avec un fichier absent."""
    if not _ABONNEMENTS.exists():
        return [], "absent"
    try:
        data = yaml.safe_load(_ABONNEMENTS.read_text(encoding="utf-8")) or []
    except Exception:
        LOG.exception("cockpit: lecture abonnements")
        return [], "invalide"
    if not isinstance(data, list):
        LOG.warning("cockpit: abonnements.yaml doit être une liste")
        return [], "invalide"
    return [a for a in data if isinstance(a, dict) and a.get("service")], "ok"


def _lire_etat():
    """État persisté -> (montants, changements, texte brut du fichier).

    Format : {"montants": {service: montant}, "changements": [{service, avant,
    apres, depuis}]}. Rétrocompatible avec l'ancien format, un dict plat
    service -> montant (sans changements mémorisés)."""
    texte, brut = "", {}
    if _ETAT_ABO.exists():
        try:
            texte = _ETAT_ABO.read_text(encoding="utf-8")
            brut = json.loads(texte) or {}
        except Exception:
            brut = {}
    if not isinstance(brut, dict):
        brut = {}
    if isinstance(brut.get("montants"), dict):
        montants, changements = brut["montants"], brut.get("changements")
    else:
        montants, changements = brut, []          # ancien format : dict plat
    propres = {}
    for nom, valeur in montants.items():
        try:
            propres[str(nom)] = _montant(valeur)
        except (ValueError, TypeError):
            pass
    return propres, (changements if isinstance(changements, list) else []), texte


def _changements_valides(changements, auj):
    """Changements encore à signaler (moins de _ALERTE_JOURS jours), entrées saines."""
    garde = []
    for c in changements:
        try:
            depuis = dt.date.fromisoformat(str(c.get("depuis")))
            entree = {"service": str(c["service"]), "avant": float(c["avant"]),
                      "apres": float(c["apres"]), "depuis": depuis.isoformat()}
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if (auj - depuis).days < _ALERTE_JOURS:
            garde.append(entree)
    return garde


def _detecter_changements(abos, auj=None, ignores=()):
    """Compare les montants aux derniers vus (persistés) -> changements « montant changé ».

    Un changement reste signalé _ALERTE_JOURS jours : un simple rafraîchissement de
    la page ne l'efface plus. `abos` : entrées valides, montant déjà normalisé.
    `ignores` : services présents mais illisibles, dont l'ancien montant est gardé
    pour signaler la hausse une fois la ligne corrigée. L'état n'est réécrit que
    s'il change."""
    auj = auj or dt.date.today()
    anciens, changements, texte = _lire_etat()
    suivis = {c["service"]: c for c in _changements_valides(changements, auj)}
    actuels = {nom: anciens[nom] for nom in ignores if nom in anciens}
    for a in abos:
        nom = str(a.get("service"))
        montant = a["montant"]
        actuels[nom] = montant
        if nom in anciens and abs(anciens[nom] - montant) > 0.001:
            suivis[nom] = {"service": nom, "avant": anciens[nom], "apres": montant,
                           "depuis": auj.isoformat()}
    # un abonnement retiré du fichier n'est plus signalé
    nouvel = {"montants": actuels,
              "changements": [c for nom, c in suivis.items() if nom in actuels]}
    contenu = json.dumps(nouvel, ensure_ascii=False)
    if contenu != texte and (texte or actuels or suivis):
        try:
            _DOSSIER.mkdir(parents=True, exist_ok=True)
            _ETAT_ABO.write_text(contenu, encoding="utf-8")
        except Exception:
            pass
    return nouvel["changements"]


def _finances(auj=None):
    auj = auj or dt.date.today()
    abos, fichier = _charger_abonnements()
    enrichis, total, par_cat, alertes, ignores = [], 0.0, {}, [], []
    for a in abos:
        service = a.get("service")
        # Une ligne illisible est écartée et signalée : elle ne fait plus tomber
        # tout le volet (erreur 500, affichée « Cockpit hors ligne »).
        try:
            montant = _montant(a.get("montant", 0))
        except (ValueError, TypeError):
            alertes.append(f"Ligne ignorée : {service}, montant illisible")
            ignores.append(str(service))
            continue
        try:
            prochaine = _prochaine_echeance(a, auj)
        except (ValueError, TypeError):
            alertes.append(f"Ligne ignorée : {service}, jour illisible")
            ignores.append(str(service))
            continue
        mensuel = round(montant * _facteur_mensuel(a.get("periodicite", "mensuel")), 2)
        total += mensuel
        cat = str(a.get("categorie", "Autres"))
        par_cat[cat] = round(par_cat.get(cat, 0.0) + mensuel, 2)
        enrichis.append({
            "service": service, "montant": montant,
            "periodicite": a.get("periodicite", "mensuel"),
            "mensuel": mensuel, "categorie": cat,
            "prochaine": prochaine.isoformat(),
            "dans_jours": (prochaine - auj).days,
        })
    enrichis.sort(key=lambda x: x["prochaine"])
    demain = auj + dt.timedelta(days=1)
    alertes = [f"Prélèvement demain : {e['service']} ({e['montant']:.2f} €)"
               for e in enrichis if e["prochaine"] == demain.isoformat()] + alertes
    if fichier == "invalide":
        # Lecture ratée : on n'écrase surtout pas les montants mémorisés, sinon la
        # prochaine hausse de prix ne serait jamais signalée.
        alertes.append("Fichier finances/abonnements.yaml illisible : corrige-le "
                       "(rien n'a été effacé).")
        changements = _changements_valides(_lire_etat()[1], auj)
    else:
        changements = _detecter_changements(enrichis, auj, ignores)
    for c in changements:
        alertes.append(f"Montant changé : {c['service']} {c['avant']:.2f} € → {c['apres']:.2f} €")
    return {
        "total_mensuel": round(total, 2),
        "total_annuel": round(total * 12, 2),
        "par_categorie": par_cat,
        "abonnements": enrichis,
        "alertes": alertes,
        "nb": len(enrichis),
        "fichier": fichier,
    }


# ============================================================ routes

def monter_routes(app):
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse

    def garde(request: Request):
        if not _local_seulement(request):
            return JSONResponse({"ok": False, "message": "Cockpit local uniquement."},
                                status_code=403)
        return None

    @app.get("/cockpit")
    def cockpit(request: Request):
        refus = garde(request)
        if refus:
            return refus
        if not _HTML.exists():
            return HTMLResponse("<h1>Cockpit</h1><p>web/cockpit.html manquant.</p>", 500)
        return HTMLResponse(_HTML.read_text(encoding="utf-8"),
                            headers={"X-Frame-Options": "DENY"})

    @app.get("/api/cockpit/finances")
    def api_finances(request: Request):
        return garde(request) or _finances()

    @app.get("/api/cockpit/transactions")
    def api_transactions(request: Request, mois: str = ""):
        if (r := garde(request)):
            return r
        from core import transactions as tx
        return {"vue": tx.vue_mois(mois or None),
                "recurrents": tx.abonnements_recurrents()}

    LOG.info("cockpit monte : /cockpit (local uniquement)")
