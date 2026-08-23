"""Identifiants OAuth Google, partages par les integrations (Agenda, Gmail).

Un seul fichier client (google_credentials.json, telecharge depuis la console
Google Cloud) et UN JETON PAR JEU DE PERMISSIONS. Separer les jetons est
volontaire : donner l'acces au mail ne doit pas invalider l'agenda, et refuser
le mail ne doit pas casser l'agenda.

Le consentement passe par un navigateur, une seule fois. Ensuite le jeton se
rafraichit tout seul tant que l'autorisation n'est pas revoquee.

Utile la ou les mots de passe d'application ne sont PAS disponibles : sur
Google Workspace, l'administrateur peut les desactiver, et Google les retire
progressivement. OAuth est le chemin officiel.
"""
import logging
from pathlib import Path

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent

# Permissions par usage. « mail.google.com » couvre IMAP et SMTP (lecture,
# envoi, corbeille) : c'est ce dont tools/mail.py a besoin.
SCOPES_AGENDA = ["https://www.googleapis.com/auth/calendar"]
SCOPES_MAIL = ["https://mail.google.com/"]


def chemin(valeur, defaut):
    """Chemin depuis config.yaml, relatif a la racine du projet si besoin."""
    from core.config import reglage
    p = Path(reglage(valeur, "") or defaut)
    return p if p.is_absolute() else (_RACINE / p)


def identifiants(scopes, fichier_token, fichier_ident=None, interactif=True):
    """Credentials Google valides pour `scopes`.

    fichier_token : ou est stocke le jeton de CE jeu de permissions.
    interactif    : False interdit d'ouvrir un navigateur — utile depuis
                    l'assistant, ou une fenetre surgissante serait deroutante.
                    Leve alors une erreur explicite disant quoi lancer.
    """
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    fichier_token = Path(fichier_token)
    fichier_ident = Path(fichier_ident or chemin("google.credentials",
                                                 "google_credentials.json"))

    creds = None
    if fichier_token.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(fichier_token), scopes)
        except Exception as e:
            LOG.warning("google_oauth: jeton illisible (%s), reautorisation", e)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _ecrire_jeton(fichier_token, creds)
            return creds
        except Exception as e:
            LOG.warning("google_oauth: rafraichissement refuse (%s)", e)

    if not interactif:
        raise PermissionError(
            f"autorisation Google absente ou expiree ({fichier_token.name}). "
            "Lance : uv run python scripts/google_login.py mail")

    if not fichier_ident.exists():
        raise FileNotFoundError(
            f"identifiants Google absents ({fichier_ident.name}). Voir docs/mail.md.")

    flow = InstalledAppFlow.from_client_secrets_file(str(fichier_ident), scopes)
    creds = flow.run_local_server(port=0)
    _ecrire_jeton(fichier_token, creds)
    return creds


def _ecrire_jeton(fichier, creds):
    """Ecrit le jeton en 0600 : lui seul donne acces au compte.

    Le fichier d'identifiants (client_id/client_secret d'une app « bureau »)
    n'est PAS un secret au sens strict — Google documente qu'il ne peut pas
    l'etre pour une application installee. Le jeton de rafraichissement, lui,
    ouvre la boite mail : il doit etre illisible par les autres comptes de la
    machine, et n'est ecrit qu'ici pour que ce soit vrai a chaque ecriture,
    rafraichissement compris.
    """
    fichier = Path(fichier)
    fichier.write_text(creds.to_json(), encoding="utf-8")
    try:
        fichier.chmod(0o600)
    except Exception:
        LOG.warning("google_oauth: permissions non appliquees sur %s", fichier.name)


def chaine_xoauth2(adresse, jeton):
    """Chaine d'authentification SASL XOAUTH2, pour IMAP et SMTP.

    Format impose par Google : user=...^Aauth=Bearer ...^A^A (^A = octet 0x01).
    """
    return f"user={adresse}\x01auth=Bearer {jeton}\x01\x01"
