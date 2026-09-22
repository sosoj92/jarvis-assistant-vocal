"""Google Agenda : lecture de TOUS tes agendas + creation/suppression d'evenements.

API officielle google-api-python-client, OAuth2. Voir docs/agenda.md pour creer
les identifiants sur console.cloud.google.com.

- get_events(periode) : lit tous les agendas inclus (config agenda.calendriers ;
  vide = tous), y compris les agendas abonnes iCal (ex. deadlines Loopstr).
- create_event : cree dans l'agenda principal seulement, avec confirmation vocale.
- delete_event : supprime avec confirmation ; refuse proprement sur un agenda
  abonne (lecture seule).

Identifiants stockes localement (google_credentials.json + google_token.json),
tous deux gitignores. Aucun secret versionne.

Premier lancement (lister tes agendas pour choisir dans config.yaml) :
    uv run python -m tools.agenda
"""
import datetime as dt
import logging
from pathlib import Path

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

LOG = logging.getLogger("jarvis")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_RACINE = Path(__file__).resolve().parent.parent
_SERVICE = None

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ------------------------------------------------------------------ connexion

def _chemin(cle, defaut):
    p = reglage(cle, defaut) or defaut
    p = Path(p)
    return p if p.is_absolute() else (_RACINE / p)


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    fichier_ident = _chemin("agenda.credentials", "google_credentials.json")
    fichier_token = _chemin("agenda.token", "google_token.json")

    creds = None
    if fichier_token.exists():
        creds = Credentials.from_authorized_user_file(str(fichier_token), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not fichier_ident.exists():
                raise FileNotFoundError(
                    f"identifiants Google absents ({fichier_ident.name}). Voir docs/agenda.md.")
            flow = InstalledAppFlow.from_client_secrets_file(str(fichier_ident), SCOPES)
            creds = flow.run_local_server(port=0)
        fichier_token.write_text(creds.to_json(), encoding="utf-8")
    _SERVICE = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _SERVICE


def _calendriers(service):
    """Agendas a inclure : {id: {nom, role}}. config agenda.calendriers = ids OU noms
    (vide -> tous)."""
    items = service.calendarList().list().execute().get("items", [])
    tous = {c["id"]: {"nom": c.get("summary", ""), "role": c.get("accessRole", "")}
            for c in items}
    conf = reglage("agenda.calendriers", None)
    if not conf:
        return tous
    choisis = {cid: info for cid, info in tous.items()
               if cid in conf or info["nom"] in conf}
    return choisis or tous


# -------------------------------------------------------------------- periode

def _local(d):
    return d.astimezone()


def _periode(texte):
    """Renvoie (debut, fin, libelle) en datetimes locaux tz-aware."""
    t = sans_accents((texte or "").lower())
    maintenant = dt.datetime.now().astimezone()
    minuit = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    jour = dt.timedelta(days=1)

    def bornes(debut, nb_jours, libelle):
        return debut, debut + dt.timedelta(days=nb_jours), libelle

    if "apres-demain" in t:
        return bornes(minuit + 2 * jour, 1, "apres-demain")
    if "demain" in t:
        return bornes(minuit + jour, 1, "demain")
    if "week-end" in t or "weekend" in t:
        # prochain samedi 00h -> lundi 00h
        delta = (5 - minuit.weekday()) % 7
        sam = minuit + dt.timedelta(days=delta)
        return sam, sam + 2 * jour, "ce week-end"
    if "prochaine" in t and "semaine" in t:
        lundi = minuit + dt.timedelta(days=(7 - minuit.weekday()))
        return lundi, lundi + 7 * jour, "la semaine prochaine"
    if "semaine" in t:
        lundi = minuit - dt.timedelta(days=minuit.weekday())
        return lundi, lundi + 7 * jour, "cette semaine"
    if "mois" in t:
        debut = minuit.replace(day=1)
        mois_suivant = (debut.replace(day=28) + 4 * jour).replace(day=1)
        return debut, mois_suivant, "ce mois-ci"
    return bornes(minuit, 1, "aujourd'hui")


# -------------------------------------------------------------- mise en forme

def _debut_ev(e):
    s = e.get("start", {})
    if "dateTime" in s:
        return dt.datetime.fromisoformat(s["dateTime"]), False
    if "date" in s:
        return dt.datetime.fromisoformat(s["date"]).replace(tzinfo=dt.timezone.utc).astimezone(), True
    return None, False


def _heure_fr(d):
    return f"{d.hour}h" if d.minute == 0 else f"{d.hour}h{d.minute:02d}"


_MOIS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
         "aout", "septembre", "octobre", "novembre", "decembre")


def _jour_fr(d, fenetre=None):
    """Nom du jour, avec le MOIS des qu'il y a ambiguite.

    « mardi 18 » suffit dans la semaine en cours. Mais un evenement de
    plusieurs jours affiche sa date de DEBUT : demander « cette semaine » un
    23 aout pouvait rendre « lundi 3 » pour des vacances commencees le 3 —
    illisible, et pris pour une erreur. Des que la date sort de la fenetre
    interrogee ou s'eloigne de plus d'une semaine, on precise le mois, et
    l'appelant signale que l'evenement est en cours.
    """
    auj = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    j = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if j == auj:
        return "aujourd'hui"
    if j == auj + dt.timedelta(days=1):
        return "demain"
    if j == auj - dt.timedelta(days=1):
        return "hier"

    lointain = abs((j - auj).days) > 7
    if fenetre is not None:
        debut, fin = fenetre
        lointain = lointain or not (debut <= j < fin)
    if lointain:
        return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]}"
    return f"{_JOURS[d.weekday()]} {d.day}"


def _est_loopstr(nom):
    return "loopstr" in sans_accents(nom)


def _formuler(evenements, libelle, fenetre=None):
    """Groupe par jour, phrase naturelle en francais.

    `fenetre` = (debut, fin) de la periode interrogee. Elle sert a signaler les
    evenements DEJA COMMENCES avant la periode : sans cela, leur date de debut
    s'affiche telle quelle et donne l'impression d'un resultat errone.
    """
    par_jour = {}
    for d, tout_jour, titre, cal in evenements:
        cle = d.replace(hour=0, minute=0, second=0, microsecond=0)
        par_jour.setdefault(cle, []).append((d, tout_jour, titre, cal))

    phrases = []
    multi = len(par_jour) > 1
    for cle in sorted(par_jour):
        items = []
        commence_avant = fenetre is not None and cle < fenetre[0]
        for d, tout_jour, titre, cal in par_jour[cle]:
            quand = "toute la journee" if tout_jour else f"a {_heure_fr(d)}"
            marque = " (deadline)" if _est_loopstr(cal) else ""
            if commence_avant:
                marque += " (deja en cours)"
            items.append(f"{quand} {titre}{marque}")
        prefixe = f"{_jour_fr(cle, fenetre)} : " if multi else ""
        phrases.append(prefixe + " ; ".join(items) + ".")
    tete = "" if multi else f"{libelle.capitalize()}, tu as : "
    return (tete + " ".join(phrases)).strip()


# ---------------------------------------------------------------------- outils

def _msg_config(e):
    return (f"Je n'accede pas a ton agenda Google ({e}). Verifie les identifiants "
            "(docs/agenda.md) puis relance.")


@outil(
    nom="get_events",
    description="Lit l'agenda Google (TOUS les agendas inclus, y compris abonnes iCal) "
                "et repond naturellement. Pour 'j'ai quoi demain', 'mon planning de la "
                "semaine', 'qu'est-ce que j'ai aujourd'hui', 'ce week-end'.",
    parametres={
        "type": "object",
        "properties": {
            "periode": {"type": "string",
                        "description": "aujourd'hui, demain, cette semaine, la semaine "
                                       "prochaine, ce week-end, ce mois..."}
        },
    },
    lent=True,
    phrase_attente="Je regarde ton agenda.",
)
def get_events(periode: str = "aujourd'hui") -> str:
    try:
        service = _service()
    except Exception as e:
        LOG.exception("get_events: service")
        return _msg_config(e)
    debut, fin, libelle = _periode(periode)
    evenements = []
    for cid, info in _calendriers(service).items():
        try:
            res = service.events().list(
                calendarId=cid, timeMin=debut.isoformat(), timeMax=fin.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=50).execute()
        except Exception:
            continue
        for e in res.get("items", []):
            d, tout_jour = _debut_ev(e)
            if d is None:
                continue
            titre = e.get("summary", "(sans titre)")
            evenements.append((d, tout_jour, titre, info["nom"]))
    if not evenements:
        return f"Rien de prevu {libelle}."
    evenements.sort(key=lambda x: x[0])
    return _formuler(evenements, libelle, fenetre=(debut, fin))


# ---- creation

def _combiner(date_txt, heure_txt):
    """(date, heure) souples -> datetime local. date en ISO de preference."""
    maintenant = dt.datetime.now().astimezone()
    d = None
    date_txt = (date_txt or "").strip()
    try:
        d = dt.date.fromisoformat(date_txt[:10])
    except ValueError:
        t = sans_accents(date_txt.lower())
        base = maintenant.date()
        if "apres-demain" in t:
            d = base + dt.timedelta(days=2)
        elif "demain" in t:
            d = base + dt.timedelta(days=1)
        elif "aujourd" in t:
            d = base
        else:
            for i, nom in enumerate(_JOURS):
                if nom in t:
                    delta = (i - maintenant.weekday()) % 7 or 7
                    d = base + dt.timedelta(days=delta)
                    break
    if d is None:
        d = maintenant.date()
    # heure
    h, m = 9, 0
    ht = sans_accents((heure_txt or "").lower().replace("h", ":"))
    ht = ht.strip(": ")
    if ht:
        parts = ht.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        except ValueError:
            pass
    return dt.datetime(d.year, d.month, d.day, h, m).astimezone()


def _annonce_creation(args):
    debut = _combiner(args.get("date", ""), args.get("heure", ""))
    duree = args.get("duree_minutes", 60)
    return (f"Je vais ajouter : {args.get('titre','')} le {_jour_fr(debut)} a "
            f"{_heure_fr(debut)} pour {duree} minutes.")


@outil(
    nom="create_event",
    description="Ajoute un evenement dans l'agenda PRINCIPAL. Pour 'ajoute rdv coiffeur "
                "jeudi 15h', 'note reunion demain 10h'. Donne la date en AAAA-MM-JJ "
                "(convertis les dates relatives avec la date du jour) et l'heure en HH:MM.",
    parametres={
        "type": "object",
        "properties": {
            "titre": {"type": "string"},
            "date": {"type": "string", "description": "AAAA-MM-JJ (ou 'demain', 'jeudi')."},
            "heure": {"type": "string", "description": "HH:MM (ou '15h', '15h30')."},
            "duree_minutes": {"type": "integer", "description": "Duree en minutes (defaut 60)."},
        },
        "required": ["titre", "date", "heure"],
    },
    confirmation=True,
    annonce=_annonce_creation,
)
def create_event(titre: str, date: str, heure: str, duree_minutes: int = 60) -> str:
    try:
        service = _service()
    except Exception as e:
        return _msg_config(e)
    debut = _combiner(date, heure)
    fin = debut + dt.timedelta(minutes=duree_minutes or 60)
    cal = reglage("agenda.calendrier_principal", "primary")
    try:
        service.events().insert(calendarId=cal, body={
            "summary": titre,
            "start": {"dateTime": debut.isoformat()},
            "end": {"dateTime": fin.isoformat()},
        }).execute()
    except Exception as e:
        LOG.exception("create_event")
        return f"Je n'ai pas pu creer l'evenement ({e})."
    return f"C'est ajoute : {titre}, {_jour_fr(debut)} a {_heure_fr(debut)}."


# ---- suppression

def _trouver(service, recherche, periode):
    """Renvoie la liste des (cid, event, role, nom) correspondants dans la periode."""
    debut, fin, _ = _periode(periode)
    cible = sans_accents((recherche or "").lower())
    trouves = []
    for cid, info in _calendriers(service).items():
        try:
            res = service.events().list(
                calendarId=cid, timeMin=debut.isoformat(), timeMax=fin.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=50).execute()
        except Exception:
            continue
        for e in res.get("items", []):
            if cible in sans_accents(e.get("summary", "")):
                trouves.append((cid, e, info["role"], info["nom"]))
    return trouves


def _annonce_suppression(args):
    try:
        service = _service()
        trouves = _trouver(service, args.get("recherche", ""), args.get("periode", "cette semaine"))
    except Exception:
        trouves = []
    if not trouves:
        return "Je ne trouve aucun evenement correspondant a supprimer."
    if len(trouves) > 1:
        titres = ", ".join(e.get("summary", "") for _, e, _, _ in trouves[:4])
        return f"Plusieurs evenements correspondent ({titres}). Precise lequel."
    _, e, role, _ = trouves[0]
    d, _tj = _debut_ev(e)
    quand = f" le {_jour_fr(d)} a {_heure_fr(d)}" if d else ""
    return f"Je vais supprimer : {e.get('summary','')}{quand}."


@outil(
    nom="delete_event",
    description="Supprime un evenement de l'agenda. Pour 'annule mon rdv coiffeur', "
                "'supprime la reunion de jeudi'. Cherche par mot-cle sur la periode.",
    parametres={
        "type": "object",
        "properties": {
            "recherche": {"type": "string", "description": "Mot-cle du titre a supprimer."},
            "periode": {"type": "string", "description": "Ou chercher (defaut : cette semaine)."},
        },
        "required": ["recherche"],
    },
    confirmation=True,
    annonce=_annonce_suppression,
)
def delete_event(recherche: str, periode: str = "cette semaine") -> str:
    try:
        service = _service()
    except Exception as e:
        return _msg_config(e)
    trouves = _trouver(service, recherche, periode)
    if not trouves:
        return "Je n'ai trouve aucun evenement correspondant."
    if len(trouves) > 1:
        return ("Plusieurs evenements correspondent, je prefere ne rien supprimer. "
                "Precise le titre ou la date.")
    cid, e, role, nom = trouves[0]
    if role not in ("owner", "writer"):
        return (f"'{e.get('summary','')}' est dans l'agenda abonne \"{nom}\" (lecture "
                "seule) : je ne peux pas l'y supprimer, c'est a gerer a la source.")
    try:
        service.events().delete(calendarId=cid, eventId=e["id"]).execute()
    except Exception as ex:
        LOG.exception("delete_event")
        return f"Je n'ai pas pu supprimer ({ex})."
    return f"C'est supprime : {e.get('summary','')}."


# -------------------------------------- premier lancement : lister les agendas

if __name__ == "__main__":
    try:
        svc = _service()
        items = svc.calendarList().list().execute().get("items", [])
    except Exception as ex:
        print("Erreur :", ex)
        raise SystemExit(1)
    print(f"\n{len(items)} agenda(s) trouve(s) :\n")
    for c in items:
        print(f"  - {c.get('summary','')}   [{c.get('accessRole','')}]")
        print(f"      id: {c['id']}")
    print("\nDans config.yaml, sous agenda.calendriers, mets les noms (ou ids) a "
          "inclure, ex :\n")
    print("agenda:")
    print("  calendriers:")
    for c in items:
        print(f"    - \"{c.get('summary','')}\"")
    print("\n(Laisse la liste vide pour tout inclure.)")
