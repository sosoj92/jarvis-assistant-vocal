"""Messagerie Gmail (IMAP/SMTP) : lire, lire en detail, brouillon, envoi, corbeille.

envoyer_mail et mettre_a_la_corbeille sont marques confirmation=True : le systeme
demande l'accord vocal de l'utilisateur avant d'agir.
"""
import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from core.config import reglage
from core.registre import outil

MAIL_ADRESSE = reglage("mail.adresse", "")
MAIL_MOT_DE_PASSE_APP = reglage("mail.mot_de_passe_app", "")
IMAP_SERVEUR = "imap.gmail.com"
SMTP_SERVEUR = "smtp.gmail.com"
SMTP_PORT = 465

# Brouillon en attente, rempli par preparer_mail puis envoye par envoyer_mail.
_BROUILLON = {}

# UID des mails du dernier lire_mails, pour lire_mail / corbeille par numero.
_DERNIERS_MAILS = []


def _mail_configure():
    return bool(MAIL_ADRESSE and MAIL_MOT_DE_PASSE_APP)


def _mail_mdp():
    """Mot de passe d'application sans espaces (Google l'affiche par groupes)."""
    return MAIL_MOT_DE_PASSE_APP.replace(" ", "")


def _decoder_entete(valeur):
    """Rend lisible un en-tete de mail encode (sujet, expediteur)."""
    if not valeur:
        return ""
    try:
        return str(make_header(decode_header(valeur)))
    except Exception:
        return valeur


def _corps_texte(message):
    """Extrait le texte brut d'un message, multipart ou non."""
    if message.is_multipart():
        for partie in message.walk():
            disposition = str(partie.get("Content-Disposition", ""))
            if partie.get_content_type() == "text/plain" and "attachment" not in disposition:
                charge = partie.get_payload(decode=True) or b""
                return charge.decode(partie.get_content_charset() or "utf-8", "replace")
        return ""
    charge = message.get_payload(decode=True) or b""
    return charge.decode(message.get_content_charset() or "utf-8", "replace")


@outil(
    nom="lire_mails",
    description="Liste les derniers mails recus (expediteur et objet) pour faire "
                "le tri. A utiliser pour 'lis mes mails', 'j'ai quoi comme mails', "
                "'fais le tri de ma boite'.",
    parametres={
        "type": "object",
        "properties": {
            "nombre": {"type": "integer",
                       "description": "Combien de mails lister (5 par defaut, max 10)."}
        },
    },
    lent=True,
    phrase_attente="D'accord, je regarde tes mails.",
)
def lire_mails(nombre: int = 5) -> str:
    """Liste les derniers mails recus (expediteur et objet) pour faire le tri."""
    if not _mail_configure():
        return "La messagerie n'est pas configuree."
    nombre = max(1, min(int(nombre), 10))
    try:
        imap = imaplib.IMAP4_SSL(IMAP_SERVEUR)
        imap.login(MAIL_ADRESSE, _mail_mdp())
        imap.select("INBOX")
        # On travaille en UID : stables meme apres une mise a la corbeille.
        _, donnees = imap.uid("search", None, "ALL")
        ids = donnees[0].split()
        derniers = ids[-nombre:][::-1]     # les plus recents d'abord
        _DERNIERS_MAILS.clear()
        _DERNIERS_MAILS.extend(derniers)
        lignes = []
        for i, num in enumerate(derniers, 1):
            # BODY.PEEK : lire sans marquer le mail comme lu.
            _, d = imap.uid("fetch", num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            entete = d[0][1].decode("utf-8", "replace") if d and d[0] else ""
            exp, sujet = "", ""
            for ligne in entete.splitlines():
                bas = ligne.lower()
                if bas.startswith("from:"):
                    exp = _decoder_entete(ligne[5:].strip())
                elif bas.startswith("subject:"):
                    sujet = _decoder_entete(ligne[8:].strip())
            nom, adresse = parseaddr(exp)
            lignes.append(f"{i}. De {nom or adresse or exp} : « {sujet or 'sans objet'} »")
        imap.logout()
        if not lignes:
            return "Ta boite de reception est vide."
        return "Tes derniers mails. " + " ".join(lignes)
    except Exception as e:
        return f"Impossible de lire les mails : {e}"


@outil(
    nom="lire_mail",
    description="Lit en detail le contenu d'un mail de la derniere liste, par son "
                "numero. A utiliser avant de repondre a un mail, pour en connaitre "
                "le contenu et l'adresse de l'expediteur.",
    parametres={
        "type": "object",
        "properties": {
            "numero": {"type": "integer",
                       "description": "Numero du mail dans la liste (1 = le plus recent)."}
        },
        "required": ["numero"],
    },
    lent=True,
    phrase_attente="D'accord, je regarde tes mails.",
)
def lire_mail(numero: int = 1) -> str:
    """Lit en detail un mail de la derniere liste, par son numero."""
    if not _mail_configure():
        return "La messagerie n'est pas configuree."
    if not _DERNIERS_MAILS:
        return "Demande-moi d'abord de lister tes mails."
    numero = int(numero)
    if numero < 1 or numero > len(_DERNIERS_MAILS):
        return f"Je n'ai pas de mail numero {numero}."
    try:
        imap = imaplib.IMAP4_SSL(IMAP_SERVEUR)
        imap.login(MAIL_ADRESSE, _mail_mdp())
        imap.select("INBOX")
        num = _DERNIERS_MAILS[numero - 1]
        _, d = imap.uid("fetch", num, "(BODY.PEEK[])")
        brut = d[0][1] if d and d[0] else b""
        message = email.message_from_bytes(brut)
        exp = _decoder_entete(message.get("From", ""))
        sujet = _decoder_entete(message.get("Subject", ""))
        nom, adresse = parseaddr(exp)
        corps = _corps_texte(message).strip()
        imap.logout()
        if len(corps) > 1200:
            corps = corps[:1200] + "..."
        return (f"Mail de {nom or adresse} ({adresse}), objet « {sujet} ». "
                f"Contenu : {corps}")
    except Exception as e:
        return f"Impossible de lire ce mail : {e}"


@outil(
    nom="preparer_mail",
    description="Prepare un brouillon de mail SANS l'envoyer, et le lit a "
                "l'utilisateur pour validation. Toujours passer par ici avant "
                "d'envoyer. Pour une reponse, mets l'adresse de l'expediteur en "
                "destinataire et 'Re: ' devant l'objet.",
    parametres={
        "type": "object",
        "properties": {
            "destinataire": {"type": "string", "description": "Adresse email du destinataire."},
            "sujet": {"type": "string", "description": "Objet du mail."},
            "corps": {"type": "string", "description": "Texte du message."},
        },
        "required": ["destinataire", "sujet", "corps"],
    },
)
def preparer_mail(destinataire: str, sujet: str, corps: str) -> str:
    """Prepare un brouillon de mail SANS l'envoyer, et le lit pour validation."""
    if not _mail_configure():
        return "La messagerie n'est pas configuree."
    _BROUILLON.clear()
    _BROUILLON.update({
        "destinataire": destinataire.strip(),
        "sujet": sujet.strip(),
        "corps": corps.strip(),
    })
    return (f"Brouillon pret pour {destinataire}, objet « {sujet} ». "
            f"Le message dit : {corps}.")


def _annonce_envoi(args):
    # On dit ce qui part vraiment : destinataire, objet et debut du message.
    dest = _BROUILLON.get("destinataire") or "le destinataire"
    sujet = " ".join(str(_BROUILLON.get("sujet", "")).split())[:100]
    corps = " ".join(str(_BROUILLON.get("corps", "")).split())
    debut = corps[:160] + ("…" if len(corps) > 160 else "")
    return (f"Je vais envoyer le mail a {dest}"
            + (f", objet : {sujet}" if sujet else "")
            + (f". Il commence par : {debut}" if debut else "") + ".")


@outil(
    nom="envoyer_mail",
    description="Envoie le brouillon prepare. A appeler quand l'utilisateur veut "
                "envoyer le mail : le systeme lui demandera de confirmer avant.",
    confirmation=True,
    annonce=_annonce_envoi,
)
def envoyer_mail() -> str:
    """Envoie le brouillon prepare. La confirmation est geree par le systeme."""
    if not _BROUILLON:
        return "Aucun brouillon a envoyer. Prepare d'abord un message."
    try:
        msg = EmailMessage()
        msg["From"] = MAIL_ADRESSE
        msg["To"] = _BROUILLON["destinataire"]
        msg["Subject"] = _BROUILLON["sujet"]
        msg.set_content(_BROUILLON["corps"])
        with smtplib.SMTP_SSL(SMTP_SERVEUR, SMTP_PORT) as smtp:
            smtp.login(MAIL_ADRESSE, _mail_mdp())
            smtp.send_message(msg)
        destinataire = _BROUILLON["destinataire"]
        _BROUILLON.clear()
        return f"Mail envoye a {destinataire}."
    except Exception as e:
        return f"Echec de l'envoi : {e}"


def _annonce_corbeille(args):
    return f"Je vais mettre le mail numero {args.get('numero', 1)} a la corbeille."


@outil(
    nom="mettre_a_la_corbeille",
    description="Deplace un mail de la derniere liste vers la corbeille (recuperable "
                "30 jours) quand l'utilisateur dit 'supprime' ou 'jette' un mail. Ne "
                "supprime jamais definitivement.",
    parametres={
        "type": "object",
        "properties": {
            "numero": {"type": "integer",
                       "description": "Numero du mail dans la liste (1 = le plus recent)."}
        },
        "required": ["numero"],
    },
    confirmation=True,
    annonce=_annonce_corbeille,
)
def mettre_a_la_corbeille(numero: int = 1) -> str:
    """Deplace un mail vers la corbeille Gmail (recuperable 30 jours)."""
    if not _mail_configure():
        return "La messagerie n'est pas configuree."
    if not _DERNIERS_MAILS:
        return "Demande-moi d'abord de lister tes mails."
    numero = int(numero)
    if numero < 1 or numero > len(_DERNIERS_MAILS):
        return f"Je n'ai pas de mail numero {numero}."
    try:
        imap = imaplib.IMAP4_SSL(IMAP_SERVEUR)
        imap.login(MAIL_ADRESSE, _mail_mdp())
        imap.select("INBOX")
        uid = _DERNIERS_MAILS[numero - 1]
        # Gmail : ajouter le libelle \Trash deplace le message vers la corbeille.
        imap.uid("store", uid, "+X-GM-LABELS", "\\Trash")
        imap.logout()
        return "Mail mis a la corbeille, recuperable pendant trente jours."
    except Exception as e:
        return f"Impossible de mettre a la corbeille : {e}"
