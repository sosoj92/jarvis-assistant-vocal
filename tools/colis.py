"""Suivi de colis a partir des mails d'expedition et de livraison (Gmail, lecture seule).

Jarvis lit lui-meme sa boite avec ses identifiants (config.yaml) : seuls l'expediteur,
l'objet et la date des mails recents sont analyses, sur la machine, sans service cloud
ni API de transporteur. Pour chaque colis, l'etape la plus recente est retenue.
"""
import datetime as dt
import email
import imaplib
import re
from email.utils import parseaddr, parsedate_to_datetime

from core.config import reglage
from core.registre import outil
from core.util import sans_accents
from tools import mail

_MOIS_IMAP = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Etapes, de la moins a la plus avancee (l'ordre departage deux mails du meme jour).
_ETAPES = (
    ("expedie", "est en route", re.compile(
        r"expedie|expedition|en route|en chemin|en transit|pris en charge|a ete envoye"
        r"|shipped|on its way|dispatched")),
    ("relais", "t'attend en point relais", re.compile(
        r"point relais|point retrait|disponible (en|au|dans)|a retirer|pret a etre retire"
        r"|ready for pickup|consigne|locker")),
    ("livraison", "arrive aujourd'hui", re.compile(
        r"en cours de livraison|livree?s? aujourd'hui|livraison (prevue )?aujourd'hui"
        r"|arrive aujourd'hui|out for delivery|en tournee|arriving today")),
    ("livre", "a été livré", re.compile(
        # « livre » seul peut etre un livre : il faut un verbe ou le feminin « livree ».
        r"(a ete|ont ete|est|sont|bien|vient d'etre|colis) livres?\b|\blivrees?\b|^livres?\b"
        r"|\bdelivered\b|a ete distribue|a ete remis")),
)
_RANG = {cle: rang for rang, (cle, _, _) in enumerate(_ETAPES)}
# Une livraison annoncee pour plus tard n'est pas une livraison effectuee.
_FUTUR = re.compile(r"sera livre|livre demain|livraison prevue|estimated|prevue le|prevue pour")
# Le mail doit parler d'un envoi, pas seulement contenir « en route ».
_INDICE_COLIS = re.compile(
    r"colis|commande|livraison|paquet|envoi|order|package|shipment|parcel|suivi|tracking")
_PUBLICITE = re.compile(
    r"livraison (offerte|gratuite)|free (shipping|delivery)|frais de port|promo|soldes"
    r"|reduction|-\s?\d+\s?%|code promo|newsletter|black friday|donnez votre avis"
    r"|laissez un avis|evaluez|notez|satisfaction|enquete|comment s'est passe")
# Numero de commande ou de suivi (il contient au moins un chiffre : « commande Amazon » n'en est pas un).
_IDENTIFIANT = re.compile(
    r"\b\d{3}-\d{7}-\d{7}\b|\b[A-Z]{2}\d{9}[A-Z]{2}\b|\b1Z[0-9A-Z]{16}\b"
    r"|(?:commande|order|colis|n°|no\.?)\s*[:#°]?\s*#?((?=[A-Z-]*\d)[A-Z0-9][A-Z0-9-]{4,})", re.I)
_EXPEDITEUR_GENERIQUE = re.compile(r"no-?reply|ne-?pas-?repondre|notification|info|service", re.I)


def _marchand(expediteur):
    """Nom lisible de l'expediteur : nom affiche, sinon le domaine (amazon.fr -> Amazon)."""
    nom, adresse = parseaddr(expediteur or "")
    nom = re.sub(r"\s*\(.*?\)|[\"']", "", nom).strip()
    if nom and not _EXPEDITEUR_GENERIQUE.fullmatch(nom):
        return nom[:40]
    domaine = (adresse.split("@")[-1] if "@" in adresse else "").split(".")
    principal = domaine[-2] if len(domaine) >= 2 else (domaine[0] if domaine else "")
    return principal.capitalize() or "Un marchand"


def _etape(sujet):
    """Etape d'envoi d'un objet de mail, ou None s'il ne s'agit pas d'un colis."""
    plat = sans_accents(sujet or "")
    if _PUBLICITE.search(plat) or not _INDICE_COLIS.search(plat):
        return None
    for cle, _, motif in reversed(_ETAPES):          # la plus avancee d'abord
        if cle == "livre" and _FUTUR.search(plat):
            continue
        if motif.search(plat):
            return cle
    return None


def analyser(entetes, maintenant=None):
    """Colis en cours a partir d'en-tetes {expediteur, sujet, date}. Fonction pure.

    Un colis = un marchand et, si l'objet en contient un, un numero de commande ou de
    suivi. Les colis livres depuis plus d'un jour et demi sont ignores.
    """
    maintenant = maintenant or dt.datetime.now().astimezone()
    colis = {}
    for entete in entetes:
        etape = _etape(entete.get("sujet"))
        date = entete.get("date")
        if etape is None or date is None:
            continue
        identifiant = _IDENTIFIANT.search(entete.get("sujet") or "")
        cle = (_marchand(entete.get("expediteur")),
               (identifiant.group(1) or identifiant.group(0)).upper() if identifiant else "")
        actuel = colis.get(cle)
        if actuel is None or (date, _RANG[etape]) > (actuel["date"], _RANG[actuel["etape"]]):
            colis[cle] = {"marchand": cle[0], "etape": etape, "date": date,
                          "sujet": entete.get("sujet") or ""}
    # « Livre » sans numero apres « expedie, commande 123 » chez le meme marchand : meme colis,
    # tant que ce marchand n'a qu'une commande numerotee en cours (sinon on ne devine pas).
    for (marchand, ident), suivi in list(colis.items()):
        if ident:
            continue
        numerotes = [cle for cle in colis if cle[0] == marchand and cle[1]]
        if len(numerotes) == 1:
            ancien = colis[numerotes[0]]
            if (suivi["date"], _RANG[suivi["etape"]]) >= (ancien["date"], _RANG[ancien["etape"]]):
                del colis[numerotes[0]]
            else:
                del colis[(marchand, ident)]
    garde = [c for c in colis.values()
             if not (c["etape"] == "livre" and maintenant - c["date"] > dt.timedelta(hours=36))]
    return sorted(garde, key=lambda c: (-_RANG[c["etape"]], c["marchand"].lower()))


def _phrase(colis):
    libelle = dict((cle, texte) for cle, texte, _ in _ETAPES)[colis["etape"]]
    return f"{colis['marchand']} {libelle}"


def _lire_entetes(jours):
    """En-tetes (expediteur, objet, date) des mails recus ces derniers jours, sans les marquer lus."""
    depuis = dt.date.today() - dt.timedelta(days=jours)
    critere = f'(SINCE "{depuis.day:02d}-{_MOIS_IMAP[depuis.month - 1]}-{depuis.year}")'
    imap = imaplib.IMAP4_SSL(mail.IMAP_SERVEUR)
    try:
        imap.login(mail.MAIL_ADRESSE, mail._mail_mdp())
        imap.select("INBOX", readonly=True)
        _, donnees = imap.uid("search", None, critere)
        uids = (donnees[0] or b"").split()[-300:]
        if not uids:
            return []
        _, reponse = imap.uid("fetch", b",".join(uids),
                              "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    entetes = []
    for element in reponse or []:
        if not isinstance(element, tuple):
            continue
        message = email.message_from_bytes(element[1])
        try:
            date = parsedate_to_datetime(message.get("Date"))
            date = date if date.tzinfo else date.astimezone()
        except (TypeError, ValueError):
            date = None
        entetes.append({"expediteur": mail._decoder_entete(message.get("From")),
                        "sujet": mail._decoder_entete(message.get("Subject")),
                        "date": date})
    return entetes


def colis_en_cours(jours=None):
    jours = int(jours or reglage("colis.jours", 10) or 10)
    return analyser(_lire_entetes(max(1, min(jours, 30))))


def colis_du_brief():
    """Phrase courte pour le brief, ou "" s'il n'y a rien a dire (ou pas de messagerie)."""
    if not bool(reglage("colis.dans_brief", True)) or not mail._mail_configure():
        return ""
    try:
        colis = colis_en_cours()
    except Exception:
        return ""
    if not colis:
        return ""
    phrases = [_phrase(c) for c in colis[:5]]
    liste = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " et " + phrases[-1]
    return f"Côté colis : {liste}."


@outil(
    nom="suivi_colis",
    description="Indique ou en sont les colis attendus, d'apres les mails d'expedition et "
                "de livraison recents. A utiliser pour 'ou en sont mes colis', 'j'ai un "
                "colis', 'mon colis arrive quand', 'qu'est-ce qui doit arriver'.",
    parametres={"type": "object", "properties": {}},
    lent=True,
    phrase_attente="Je regarde tes mails de livraison.",
)
def suivi_colis() -> str:
    if not mail._mail_configure():
        return "La messagerie n'est pas configuree, je ne peux pas suivre tes colis."
    try:
        colis = colis_en_cours()
    except Exception as e:
        return f"Impossible de verifier tes colis : {e}"
    if not colis:
        return "Aucun colis en cours dans tes mails de ces derniers jours."
    nombre = len(colis)
    detail = " ; ".join(_phrase(c) for c in colis[:8])
    return f"Tu as {nombre} colis {'suivi' if nombre == 1 else 'suivis'} : {detail}."
