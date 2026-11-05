"""Loopstr : tes echeances de partenariats, depuis ton flux iCal Loopstr.

Lit l'URL iCal (config loopstr.url), la rafraichit a chaque appel avec un cache
de 15 minutes, et distingue les DEADLINES (brief, tournage, publication...) de tes
periodes de VACANCES/dispo presentes dans le meme flux.

get_deadlines(periode) -> reponse vocale naturelle des echeances.
Les deadlines du jour et de la semaine sont aussi injectees dans le brief du matin.

Donnees perso de partenariats -> mcp_expose=False (jamais expose via MCP).
"""
import logging
import re
import time

from core.config import reglage
from core.registre import outil
from core.util import sans_accents
from tools.agenda import _periode, _jour_fr

LOG = logging.getLogger("jarvis")

_CACHE_T = 0.0
_CACHE_EV = None          # liste de (debut_dt, type, titre)
_TTL = 900                # 15 min

# Mots indiquant une absence/dispo (a distinguer des deadlines de rendu).
# Mots ENTIERS seulement : « offre », « coffret », « disposition », « fermer »
# ou « repost » sont des deadlines, pas des conges.
_ABSENCE_RE = re.compile(
    r"\b(vacances?|conges?|prise de conge|indispo(?:nible|nibilites?)?s?"
    r"|dispo(?:nible|nibilites?)?s?|absente?s?|repos|fermee?s?"
    r"|holidays?|vacations?|day off|off)\b")


class FluxIndisponible(RuntimeError):
    """Flux Loopstr illisible. Le message est un libelle fixe : jamais l'URL
    (une URL iCal privee est une URL-capacite, chemin et jeton compris)."""


def _classer(titre, categories):
    s = sans_accents(f"{titre} {categories}".lower())
    return "absence" if _ABSENCE_RE.search(s) else "deadline"


def _en_local(valeur):
    """dtstart iCal (date ou datetime) -> datetime local tz-aware."""
    import datetime as dt
    if isinstance(valeur, dt.datetime):
        return valeur.astimezone() if valeur.tzinfo else valeur.replace(
            tzinfo=dt.timezone.utc).astimezone()
    if isinstance(valeur, dt.date):
        return dt.datetime(valeur.year, valeur.month, valeur.day).astimezone()
    return None


def _charger(force=False):
    """Charge et met en cache les evenements du flux Loopstr."""
    global _CACHE_T, _CACHE_EV
    if not force and _CACHE_EV is not None and (time.time() - _CACHE_T) < _TTL:
        return _CACHE_EV
    url = reglage("loopstr.url", "")
    if not url:
        return None
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    try:
        import requests
        from icalendar import Calendar
        reponse = requests.get(url, timeout=12)
        reponse.raise_for_status()
        cal = Calendar.from_ical(reponse.content)
    except Exception as e:
        # Le TYPE seul, sans trace : le message requests contient l'URL a jeton.
        LOG.warning("loopstr: chargement impossible (%s)", type(e).__name__)
        statut = getattr(getattr(e, "response", None), "status_code", None)
        raise FluxIndisponible(
            f"flux refuse, erreur {statut}" if statut else "flux injoignable"
        ) from None

    evenements = []
    for comp in cal.walk("VEVENT"):
        titre = str(comp.get("summary", "")).strip()
        cats = ""
        if comp.get("categories"):
            try:
                cats = ",".join(str(c) for c in comp.get("categories").cats)
            except Exception:
                cats = str(comp.get("categories"))
        deb = comp.get("dtstart")
        d = _en_local(deb.dt) if deb is not None else None
        if d is None or not titre:
            continue
        evenements.append((d, _classer(titre, cats), titre))
    evenements.sort(key=lambda x: x[0])
    _CACHE_EV, _CACHE_T = evenements, time.time()
    return evenements


def _echeances(periode):
    """(deadlines, absences) dans la periode, chacune liste de (dt, titre)."""
    debut, fin, libelle = _periode(periode)
    evs = _charger()
    if evs is None:
        return None, None, libelle
    deadlines = [(d, t) for d, typ, t in evs if typ == "deadline" and debut <= d < fin]
    absences = [(d, t) for d, typ, t in evs if typ == "absence" and debut <= d < fin]
    return deadlines, absences, libelle


@outil(
    nom="get_deadlines",
    description="Tes echeances de partenariats Loopstr (brief, tournage, publication, "
                "V1...). Pour 'mes deadlines', 'j'ai quoi a rendre cette semaine', 'mes "
                "partenariats'. Distingue les rendus de tes periodes de conge.",
    parametres={
        "type": "object",
        "properties": {
            "periode": {"type": "string",
                        "description": "aujourd'hui, cette semaine (defaut), la semaine "
                                       "prochaine, ce mois..."}
        },
    },
    lent=True,
    phrase_attente="Je regarde tes deadlines de partenariats.",
    mcp_expose=False,
)
def get_deadlines(periode: str = "cette semaine") -> str:
    if not reglage("loopstr.url", ""):
        return "Ton flux Loopstr n'est pas configure (loopstr.url dans config.yaml)."
    try:
        deadlines, absences, libelle = _echeances(periode)
    except FluxIndisponible as e:
        return f"Je n'ai pas pu lire ton flux Loopstr ({e})."
    except Exception as e:
        # Jamais le message brut : il pourrait contenir l'URL privee du flux.
        LOG.warning("loopstr: lecture impossible (%s)", type(e).__name__)
        return "Je n'ai pas pu lire ton flux Loopstr pour le moment."
    if deadlines is None:
        return "Ton flux Loopstr n'est pas configure."
    if not deadlines:
        base = f"Aucune echeance de partenariat {libelle}."
        if absences:
            base += " " + _phrase_absences(absences)
        return base
    morceaux = [f"{_jour_fr(d)}, {t}" for d, t in deadlines]
    phrase = f"Cote partenariats {libelle}, tu as : " + " ; ".join(morceaux) + "."
    if absences:
        phrase += " " + _phrase_absences(absences)
    return phrase


def _phrase_absences(absences):
    if not absences:
        return ""
    if len(absences) == 1:
        d, t = absences[0]
        return f"A noter : {t} ({_jour_fr(d)})."
    return "A noter, periodes de conge : " + " ; ".join(f"{t} ({_jour_fr(d)})" for d, t in absences) + "."


def deadlines_brief():
    """Courte phrase de deadlines (aujourd'hui + semaine) pour le brief du matin.

    Renvoie "" si rien ou si Loopstr non configure (le brief ne doit pas planter).
    """
    if not reglage("loopstr.url", ""):
        return ""
    try:
        deadlines, _abs, _lib = _echeances("cette semaine")
    except Exception:
        return ""
    if not deadlines:
        return ""
    morceaux = [f"{_jour_fr(d)}, {t}" for d, t in deadlines[:4]]
    return "Cote partenariats cette semaine : " + " ; ".join(morceaux) + "."
