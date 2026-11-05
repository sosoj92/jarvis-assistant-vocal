"""Suivi de contenus : ton pipeline video, de l'idee a la publication.

Une liste EDITABLE A LA MAIN et par Jarvis (contenus.yaml, non versionne). Chaque
contenu : titre, statut, plateforme, deadline (AAAA-MM-JJ), notes, cree_le.

Le hub d'inspirations/generation vit ailleurs (core/hub_contenu.py, tools/contenu.py) ;
ici on ne fait QUE le suivi d'avancement.

Doctrine : Jarvis TIENT la liste (ecriture vocale) ; Hermes la LIT seulement, via
l'outil MCP `etat_contenus`, pour croiser "ce qui m'inspire" (vault) avec "ce que
j'ai en cours" et suggerer les priorites. Jamais d'ecriture cote Hermes.
"""
import datetime as dt
import logging
import os
import re
import tempfile
from pathlib import Path

import yaml

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent

# Pipeline ordonne : chaque etape d'une video, de sa naissance a sa publication.
STATUTS = ["idee", "script", "tournage", "montage", "publie"]

# Tolerance vocale : mots entendus -> statut canonique.
_SYN = {
    "idee": "idee", "concept": "idee",
    "script": "script", "ecriture": "script", "texte": "script", "ecrit": "script",
    "tournage": "tournage", "tourner": "tournage", "tourne": "tournage", "filmer": "tournage",
    "montage": "montage", "monter": "montage", "montee": "montage", "edit": "montage",
    "publie": "publie", "publier": "publie", "publiee": "publie", "poste": "publie",
    "postee": "publie", "sorti": "publie", "sortie": "publie", "en ligne": "publie",
}

_LIBELLES = {"idee": "idee(s)", "script": "en script", "tournage": "en tournage",
             "montage": "en montage", "publie": "publie(s)"}


# ------------------------------------------------------------------- stockage

def _fichier():
    p = reglage("suivi.fichier", "contenus.yaml") or "contenus.yaml"
    p = Path(p)
    return p if p.is_absolute() else (_RACINE / p)


def _charger():
    f = _fichier()
    if not f.exists():
        return []
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        LOG.exception("suivi: contenus.yaml illisible")
        return []
    return data if isinstance(data, list) else []


def _charger_pour_ecriture():
    """Lecture STRICTE avant ecriture : (contenus, None), ou (None, message).

    Le fichier est edite a la main : s'il est illisible (YAML invalide, ou pas une
    liste), le reecrire a partir d'une liste vide effacerait tout le suivi. Les
    outils d'ecriture refusent donc d'ecrire et le disent. Absent ou vide -> [].
    """
    f = _fichier()
    if not f.exists():
        return [], None
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        LOG.warning("suivi: contenus.yaml illisible (%s)", type(e).__name__)
        marque = getattr(e, "problem_mark", None)
        ligne = f" (ligne {marque.line + 1})" if marque is not None else ""
        return None, (f"Ton fichier {f.name} est illisible{ligne}, je n'y ecris rien : "
                      "corrige-le d'abord.")
    except OSError as e:
        LOG.warning("suivi: contenus.yaml inaccessible (%s)", type(e).__name__)
        return None, f"Je n'arrive pas a lire ton fichier {f.name}, je n'y ecris rien."
    if data is None:
        return [], None
    if not isinstance(data, list):
        return None, (f"Ton fichier {f.name} n'est pas une liste de contenus, je n'y "
                      "ecris rien : corrige-le d'abord.")
    return data, None


def _sauver(contenus):
    """Ecriture atomique : fichier temporaire du meme dossier puis os.replace,
    pour ne jamais laisser un contenus.yaml tronque."""
    f = _fichier()
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=f.parent,
                                         prefix=f".{f.name}.", suffix=".tmp",
                                         delete=False) as fh:
            tmp = fh.name
            yaml.safe_dump(contenus, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, f)
    except BaseException:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


# --------------------------------------------------------------------- helpers

def _normaliser_statut(texte):
    t = sans_accents((texte or "").lower().strip())
    if t in _SYN:
        return _SYN[t]
    for mot, statut in _SYN.items():
        if mot in t:
            return statut
    return None


# Mots vides ignores dans le rapprochement. Pas de seuil de longueur : « Video A »
# et « Video B », ou « Episode 1 » et « Episode 2 », doivent rester distincts.
_MOTS_VIDES = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "au", "aux",
               "en", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
               "sur", "pour", "avec", "dans", "par"}


def _mots_titre(texte):
    """Mots entiers significatifs d'un titre normalise (mots vides retires)."""
    return {m for m in re.findall(r"\w+", texte) if m not in _MOTS_VIDES}


def _trouver(contenus, titre):
    """Index du contenu au titre le plus proche, ou None (exact puis inclusion).

    L'inclusion porte sur des MOTS entiers, pas des caracteres : « IA » ne doit
    pas correspondre a « Les medias sociaux » (« ia » est dans « medias »)."""
    cible = sans_accents((titre or "").lower().strip())
    if not cible:
        return None
    for i, c in enumerate(contenus):
        if sans_accents(str(c.get("titre", "")).lower()) == cible:
            return i
    mots_cible = _mots_titre(cible)
    for i, c in enumerate(contenus):
        mots = _mots_titre(sans_accents(str(c.get("titre", "")).lower()))
        # Ensembles non vides : un titre fait de mots vides serait sinon inclus
        # dans n'importe quelle cible.
        if mots and mots_cible and (mots_cible <= mots or mots <= mots_cible):
            return i
    return None


def _date(valeur):
    try:
        return dt.date.fromisoformat(str(valeur)[:10])
    except (ValueError, TypeError):
        return None


def _retards_et_bientot(contenus):
    """(retards, bientot) : contenus NON publies dont la deadline est passee (< 0 j)
    ou proche (<= 3 j). Chaque element : (contenu, nb_jours_absolu)."""
    auj = dt.date.today()
    retards, bientot = [], []
    for c in contenus:
        if c.get("statut") == "publie":
            continue
        d = _date(c.get("deadline"))
        if not d:
            continue
        delta = (d - auj).days
        if delta < 0:
            retards.append((c, -delta))
        elif delta <= 3:
            bientot.append((c, delta))
    retards.sort(key=lambda x: -x[1])
    bientot.sort(key=lambda x: x[1])
    return retards, bientot


# --------------------------------------------------- croisement agenda (Google)

# Mots trop generiques pour rapprocher un contenu d'un evenement agenda.
_MOTS_GENERIQUES = {"video", "reel", "reels", "short", "shorts", "montage",
                    "tournage", "script", "publie", "contenu", "publication"}


def _mots_cles(txt):
    return {m for m in sans_accents(str(txt).lower()).split()
            if len(m) >= 5 and m not in _MOTS_GENERIQUES}


def _agenda_a_venir(jours=21):
    """Evenements agenda a venir : [(datetime, titre, calendrier, est_deadline)].
    Renvoie [] si l'agenda n'est pas configure/joignable (degradation propre) ;
    ne declenche JAMAIS le flux OAuth interactif (verifie le token d'abord)."""
    try:
        import datetime as _dt
        from tools import agenda
        if not agenda._chemin("agenda.token", "google_token.json").exists():
            return []
        service = agenda._service(interactif=False)
        debut = _dt.datetime.now().astimezone()
        fin = debut + _dt.timedelta(days=jours)
        evs = []
        for cid, info in agenda._calendriers(service).items():
            try:
                res = service.events().list(
                    calendarId=cid, timeMin=debut.isoformat(), timeMax=fin.isoformat(),
                    singleEvents=True, orderBy="startTime", maxResults=50).execute()
            except Exception:
                continue
            for e in res.get("items", []):
                d, _tj = agenda._debut_ev(e)
                if d is None:
                    continue
                evs.append((d, e.get("summary", "(sans titre)"),
                            info["nom"], agenda._est_loopstr(info["nom"])))
        evs.sort(key=lambda x: x[0])
        return evs
    except Exception:
        LOG.info("suivi: agenda indisponible pour le croisement")
        return []


def _croisement_agenda(contenus):
    """Rapproche contenus <-> evenements agenda + prochaines deadlines agenda.
    Renvoie une phrase (ou "" si l'agenda est vide/indispo)."""
    evs = _agenda_a_venir()
    if not evs:
        return ""
    from tools import agenda
    bouts = []
    # 1) contenus (non publies) qui ont un creneau a l'agenda
    rappro = []
    for c in contenus:
        if c.get("statut") == "publie":
            continue
        titre = sans_accents(str(c.get("titre", "")).lower()).strip()
        if not titre:
            continue
        mots = _mots_cles(titre)
        for d, sujet, _cal, _dl in evs:
            sp = sans_accents(sujet.lower())
            if titre in sp or sp in titre or (mots and mots & _mots_cles(sujet)):
                rappro.append((c.get("titre", ""), d))
                break
    if rappro:
        rappro.sort(key=lambda x: x[1])
        items = " ; ".join(f"« {t} » {agenda._jour_fr(d)}" for t, d in rappro[:3])
        bouts.append(f"Callé à l'agenda : {items}.")
    # 2) prochaines deadlines de l'agenda (calendriers Loopstr)
    deadlines = [(d, s) for d, s, _c, dl in evs if dl][:3]
    if deadlines:
        items = " ; ".join(f"{s} {agenda._jour_fr(d)}" for d, s in deadlines)
        bouts.append(f"Deadlines à l'agenda : {items}.")
    return " ".join(bouts)


def contenus_du_brief():
    """Phrase pour le brief matinal : UNIQUEMENT les retards / echeances proches,
    ou "" s'il n'y a rien a signaler. Croise le pipeline avec les deadlines."""
    retards, bientot = _retards_et_bientot(_charger())
    bouts = []
    if retards:
        noms = ", ".join(str(c.get("titre", "")) for c, _ in retards[:3])
        bouts.append(f"Cote contenu, en retard : {noms}.")
    if bientot:
        noms = ", ".join(str(c.get("titre", "")) for c, _ in bientot[:3])
        bouts.append(f"A boucler bientot : {noms}.")
    return " ".join(bouts)


# ----------------------------------------------------------------------- outils

@outil(
    nom="nouvelle_idee_video",
    description="Cree une nouvelle idee de video dans le suivi de contenus (statut 'idee'). "
                "Pour 'nouvelle idee de video : ...', 'ajoute une idee de contenu ...'. "
                "L'idee est aussi ajoutee a tes notes.",
    parametres={
        "type": "object",
        "properties": {
            "titre": {"type": "string", "description": "Le titre / sujet de la video."},
            "plateforme": {"type": "string",
                           "description": "instagram, tiktok, youtube... (optionnel)."},
            "deadline": {"type": "string", "description": "AAAA-MM-JJ (optionnel)."},
        },
        "required": ["titre"],
    },
)
def nouvelle_idee_video(titre: str, plateforme: str = "", deadline: str = "") -> str:
    titre = (titre or "").strip()
    if not titre:
        return "Il me faut un titre pour l'idee."
    contenus, erreur = _charger_pour_ecriture()
    if erreur:
        return erreur
    if _trouver(contenus, titre) is not None:
        return f"« {titre} » est deja dans ton suivi."
    contenus.append({
        "titre": titre,
        "statut": "idee",
        "plateforme": (plateforme or "").strip(),
        "deadline": (deadline or "").strip(),
        "notes": "",
        "cree_le": dt.date.today().isoformat(),
    })
    _sauver(contenus)
    # Lien avec les notes : l'idee apparait aussi dans notes/idees.md (pour sortir_idee).
    try:
        from tools.notes import ajouter_note
        ajouter_note(titre, "idees", source="suivi contenus")
    except Exception:
        LOG.exception("suivi: lien note")
    return f"Nouvelle idee ajoutee au suivi : « {titre} », en statut idee."


@outil(
    nom="changer_statut_contenu",
    description="Fait avancer un contenu dans le pipeline (idee -> script -> tournage -> "
                "montage -> publie). Pour 'passe [titre] en tournage', 'marque [titre] "
                "comme publie', '[titre] est en montage'.",
    parametres={
        "type": "object",
        "properties": {
            "titre": {"type": "string", "description": "Titre (ou partie du titre) du contenu."},
            "statut": {"type": "string",
                       "description": "idee, script, tournage, montage ou publie."},
        },
        "required": ["titre", "statut"],
    },
)
def changer_statut_contenu(titre: str, statut: str) -> str:
    statut_c = _normaliser_statut(statut)
    if statut_c is None:
        return (f"Je ne connais pas le statut « {statut} ». Les etapes sont : "
                + ", ".join(STATUTS) + ".")
    contenus, erreur = _charger_pour_ecriture()
    if erreur:
        return erreur
    i = _trouver(contenus, titre)
    if i is None:
        return f"Je ne trouve pas « {titre} » dans ton suivi."
    ancien = contenus[i].get("statut", "idee")
    vrai_titre = contenus[i].get("titre", titre)
    if ancien == statut_c:
        return f"« {vrai_titre} » etait deja en {statut_c}."
    contenus[i]["statut"] = statut_c
    _sauver(contenus)
    return f"C'est note : « {vrai_titre} » passe de {ancien} a {statut_c}."


@outil(
    nom="ou_j_en_suis",
    description="Fait le point sur ton pipeline de contenus : combien d'idees, de scripts, "
                "de tournages, de montages, ce qui est en retard ou a echeance proche, et "
                "croise avec ton agenda Google (creneaux et deadlines). Pour 'ou j'en suis', "
                "'ou en sont mes videos', 'mon pipeline de contenu'.",
    lent=True,
    phrase_attente="Je fais le point sur tes contenus, un instant.",
)
def ou_j_en_suis() -> str:
    contenus = _charger()
    if not contenus:
        return ("Ton suivi de contenus est vide. Dis « nouvelle idee de video : ... » "
                "pour commencer.")
    comptes = {s: 0 for s in STATUTS}
    for c in contenus:
        s = c.get("statut", "idee")
        comptes[s] = comptes.get(s, 0) + 1
    morceaux = [f"{comptes[s]} {_LIBELLES[s]}" for s in STATUTS if comptes.get(s)]
    resume = "Ton pipeline : " + ", ".join(morceaux) + "."

    retards, bientot = _retards_et_bientot(contenus)
    if retards:
        items = " ; ".join(f"« {c.get('titre','')} » (deadline depassee de {j} j)"
                           for c, j in retards[:3])
        resume += f" En retard : {items}."
    if bientot:
        items = " ; ".join(
            f"« {c.get('titre','')} » ({'aujourd’hui' if j == 0 else f'dans {j} j'})"
            for c, j in bientot[:3])
        resume += f" Echeance proche : {items}."
    if not retards and not bientot:
        resume += " Rien en retard, tu es a jour."

    # Croisement avec le Google Agenda (creneaux + deadlines). Degrade en silence
    # si l'agenda n'est pas configure.
    agenda_txt = _croisement_agenda(contenus)
    if agenda_txt:
        resume += " " + agenda_txt
    return resume


@outil(
    nom="etat_contenus",
    mcp_expose=True,
    description="Renvoie l'etat COMPLET du suivi de contenus (titre, statut, plateforme, "
                "deadline, notes), au format texte. Sert a croiser les contenus en cours "
                "avec les inspirations du vault pour decider quoi prioriser.",
)
def etat_contenus() -> str:
    contenus = _charger()
    if not contenus:
        return "Suivi de contenus vide."
    lignes = []
    for c in contenus:
        plat = f", {c['plateforme']}" if c.get("plateforme") else ""
        dl = f", deadline {c['deadline']}" if c.get("deadline") else ""
        notes = f" — {c['notes']}" if c.get("notes") else ""
        lignes.append(
            f"- {c.get('titre', '(sans titre)')} "
            f"[{c.get('statut', 'idee')}{plat}{dl}]{notes}")
    return "Suivi de contenus :\n" + "\n".join(lignes)
