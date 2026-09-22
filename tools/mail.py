"""Messagerie Gmail (IMAP/SMTP) : lire, lire en detail, brouillon, envoi, corbeille.

Deux authentifications possibles, choisies automatiquement :

  - OAuth 2.0 (XOAUTH2) si mail.oauth vaut true. C'est LE chemin sur Google
    Workspace, ou l'administrateur peut interdire les mots de passe
    d'application. Consentement une fois par navigateur :
    uv run python scripts/google_login.py mail
  - mot de passe d'application, sinon (compte Google personnel avec 2FA).

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


def _oauth_actif():
    """Vrai si on doit s'authentifier en OAuth plutot qu'en mot de passe."""
    return bool(reglage("mail.oauth", False))


def _mail_configure():
    if not MAIL_ADRESSE:
        return False
    return _oauth_actif() or bool(MAIL_MOT_DE_PASSE_APP)


def _mail_mdp():
    """Mot de passe d'application sans espaces (Google l'affiche par groupes)."""
    return MAIL_MOT_DE_PASSE_APP.replace(" ", "")


def _jeton_oauth():
    """Jeton d'acces Google, rafraichi si besoin. Leve si pas encore autorise."""
    from core import google_oauth
    creds = google_oauth.identifiants(
        google_oauth.SCOPES_MAIL,
        google_oauth.chemin("mail.token", "google_token_mail.json"),
        interactif=False)          # jamais de navigateur depuis l'assistant
    return creds.token


def _imap():
    """Connexion IMAP authentifiee, quelle que soit la methode configuree."""
    imap = imaplib.IMAP4_SSL(IMAP_SERVEUR)
    if _oauth_actif():
        from core.google_oauth import chaine_xoauth2
        chaine = chaine_xoauth2(MAIL_ADRESSE, _jeton_oauth())
        imap.authenticate("XOAUTH2", lambda _: chaine.encode())
    else:
        imap.login(MAIL_ADRESSE, _mail_mdp())
    return imap


def _smtp():
    """Connexion SMTP authentifiee, quelle que soit la methode configuree."""
    smtp = smtplib.SMTP_SSL(SMTP_SERVEUR, SMTP_PORT)
    if _oauth_actif():
        import base64
        from core.google_oauth import chaine_xoauth2
        chaine = chaine_xoauth2(MAIL_ADRESSE, _jeton_oauth())
        code, reponse = smtp.docmd(
            "AUTH", "XOAUTH2 " + base64.b64encode(chaine.encode()).decode())
        if code != 235:
            raise smtplib.SMTPAuthenticationError(code, reponse)
    else:
        smtp.login(MAIL_ADRESSE, _mail_mdp())
    return smtp


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
        imap = _imap()
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
        imap = _imap()
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
    dest = _BROUILLON.get("destinataire") or "le destinataire"
    return f"Je vais envoyer le mail a {dest}."


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
        with _smtp() as smtp:
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
        imap = _imap()
        imap.select("INBOX")
        uid = _DERNIERS_MAILS[numero - 1]
        # Gmail : ajouter le libelle \Trash deplace le message vers la corbeille.
        imap.uid("store", uid, "+X-GM-LABELS", "\\Trash")
        imap.logout()
        return "Mail mis a la corbeille, recuperable pendant trente jours."
    except Exception as e:
        return f"Impossible de mettre a la corbeille : {e}"
