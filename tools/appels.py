"""Appels telephoniques via Twilio — V1 : appel a message + reponse transcrite.

call_with_message(numero, message) : Twilio appelle, se presente honnetement,
joue le message, enregistre la reponse ; Jarvis la recupere (API REST, sans
webhook public), la transcrit avec Whisper, et t'en fait un resume.

Cas d'usage : "appelle le resto et demande s'ils sont ouverts ce soir".

SECURITE / ETHIQUE (impose) :
  - Confirmation vocale AVANT chaque appel (mecanisme Phase 0).
  - Presentation honnete en debut d'appel : "assistant vocal automatise de ...".
  - Jamais de numeros surtaxes (prefixes bloques, configurables).
  - Transcription sauvegardee dans logs/calls/ ; pas d'enregistrement au-dela.
  - Estimation de cout par appel + compteur mensuel.

V2 (conversation temps reel via Media Streams) : non incluse ici, voir docs/appels.md.
mcp_expose=False (passer des appels = sensible).
"""
import datetime as dt
import json
import logging
import time
from pathlib import Path

from core.config import reglage
from core.registre import outil

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent

# Transcripteur injecte par jarvis14 (reutilise le Whisper deja charge).
_TRANSCRIPTEUR = None

# Prefixes surtaxes / interdits par defaut (France), testes sur la forme NATIONALE
# (0X...) : 089x (numeros majores) et numeros courts 3xxx, 118xxx, 10xx.
# Surchargables via config appels.prefixes_interdits.
_INTERDITS_DEFAUT = ["089", "0899", "3", "118", "10"]


def definir_transcripteur(fn):
    """jarvis14 fournit ici une fonction chemin_audio -> texte (Whisper deja charge)."""
    global _TRANSCRIPTEUR
    _TRANSCRIPTEUR = fn


def _transcrire(chemin):
    if _TRANSCRIPTEUR is not None:
        return _TRANSCRIPTEUR(chemin)
    # Repli autonome : charge un Whisper si l'assistant n'en a pas fourni
    # (ou la transcription cloud la ou faster-whisper n'existe pas).
    try:
        from core import transcription
        modele = transcription.charger(reglage("whisper.modele", "small"))
        if modele is None:
            return f"(transcription impossible : {transcription.MESSAGE_INDISPONIBLE})"
        segments, _ = modele.transcribe(chemin, language="fr", beam_size=5)
        return " ".join(s.text for s in segments).strip()
    except Exception as e:
        LOG.exception("transcription repli")
        return f"(transcription impossible : {e})"


def _prenom():
    nom = (reglage("utilisateur.nom", "") or "").strip()
    return nom.split()[0] if nom else "mon proprietaire"


def _normaliser(numero):
    """Numero -> format E.164 (+33...). Accepte '06 12 ...', '0033...', '+33...'."""
    n = "".join(c for c in (numero or "") if c.isdigit() or c == "+")
    if n.startswith("+"):
        return n
    if n.startswith("00"):
        return "+" + n[2:]
    if n.startswith("0"):
        return "+33" + n[1:]
    return "+" + n if n else n


def _national(numero):
    """Forme nationale (0X... en France) depuis l'entree d'origine, robuste aux
    numeros courts (3200, 118712) qui ne se normalisent pas en +33."""
    n = "".join(c for c in (numero or "") if c.isdigit() or c == "+")
    if n.startswith("+33"):
        return "0" + n[3:]
    if n.startswith("0033"):
        return "0" + n[4:]
    return n  # 0X... , numero court, ou etranger (+49..., 00...) laisse tel quel


def _surtaxe(numero):
    """True si le numero est surtaxe (teste sur sa forme nationale)."""
    nat = _national(numero).replace(" ", "")
    interdits = reglage("appels.prefixes_interdits", None) or _INTERDITS_DEFAUT
    return any(nat.startswith(p.replace(" ", "")) for p in interdits)


def _config_ok():
    return all(reglage(f"twilio.{k}", "") for k in ("account_sid", "auth_token", "numero"))


# ------------------------------------------------------------- compteur de cout

def _fichier_compteur():
    dossier = _RACINE / (reglage("appels.dossier", "logs/calls"))
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / "compteur.json"


def _mois_courant():
    return dt.datetime.now().strftime("%Y-%m")


def _lire_compteur():
    f = _fichier_compteur()
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("mois") == _mois_courant():
                return d
        except Exception:
            pass
    return {"mois": _mois_courant(), "appels": 0, "minutes": 0.0, "cout": 0.0}


def _ajouter_compteur(minutes, cout):
    d = _lire_compteur()
    d["appels"] += 1
    d["minutes"] = round(d["minutes"] + minutes, 2)
    d["cout"] = round(d["cout"] + cout, 3)
    _fichier_compteur().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def _cout(minutes):
    return round(minutes * float(reglage("appels.cout_par_minute", 0.11)), 3)


# ---------------------------------------------------------------- confirmation

def _annonce(args):
    e164 = _normaliser(args.get("numero", ""))
    msg = args.get("message", "")
    est = _cout(1.0)
    return (f"Je vais appeler le {e164} et dire : «{msg}». Cout estime environ "
            f"{est} euro par minute.")


# ------------------------------------------------------------------ l'appel V1

def _twiml(message):
    from twilio.twiml.voice_response import VoiceResponse
    intro = (f"Bonjour, je suis l'assistant vocal automatise de {_prenom()}. "
             f"{message}")
    vr = VoiceResponse()
    vr.say(intro, voice="Polly.Lea-Neural", language="fr-FR")
    vr.record(max_length=int(reglage("appels.duree_max_message", 30)),
              play_beep=True, timeout=5, trim="trim-silence")
    vr.say("Merci, je transmets. Au revoir.", voice="Polly.Lea-Neural", language="fr-FR")
    return str(vr)


@outil(
    nom="call_with_message",
    description="Appelle un numero par telephone (Twilio), joue un message parle, "
                "enregistre la reponse et la transcrit. Pour 'appelle le resto et "
                "demande s'ils sont ouverts ce soir', 'appelle ce numero pour dire...'. "
                "Jarvis se presente comme assistant automatise. Confirmation requise.",
    parametres={
        "type": "object",
        "properties": {
            "numero": {"type": "string", "description": "Numero a appeler (06..., +33...)."},
            "message": {"type": "string",
                        "description": "Ce que Jarvis doit dire/demander (sans se presenter, "
                                       "la presentation est ajoutee automatiquement)."},
        },
        "required": ["numero", "message"],
    },
    confirmation=True,
    annonce=_annonce,
    lent=True,
    phrase_attente="Je passe l'appel, ca peut prendre une minute.",
    mcp_expose=False,
)
def call_with_message(numero: str, message: str) -> str:
    if not reglage("appels.actif", True):
        return "Les appels sont desactives dans la configuration."
    # Mode test : simule l'appel sans telephoner (appels.simulation dans config).
    if reglage("appels.simulation", False):
        import time
        time.sleep(4)
        return (f"(Mode test, aucun vrai appel) J'ai appele et transmis : "
                f"«{message}». Reponse simulee : c'est note, c'est bon.")
    if not _config_ok():
        return ("Twilio n'est pas configure (twilio.account_sid, auth_token et numero "
                "dans config.yaml). Voir docs/appels.md.")
    e164 = _normaliser(numero)
    if not e164 or len(e164) < 8:
        return f"Ce numero ne semble pas valide : {numero}."
    if _surtaxe(numero):
        return (f"Je n'appelle pas le {e164} : il ressemble a un numero surtaxe. "
                "Par securite je ne compose pas ce genre de numero.")

    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    try:
        from twilio.rest import Client
    except Exception as e:
        return f"La librairie Twilio n'est pas disponible ({e})."

    client = Client(reglage("twilio.account_sid", ""), reglage("twilio.auth_token", ""))
    try:
        appel = client.calls.create(
            to=e164, from_=reglage("twilio.numero", ""), twiml=_twiml(message))
    except Exception as e:
        LOG.exception("call_with_message: creation")
        return f"Je n'ai pas pu lancer l'appel ({e})."

    LOG.info("appel Twilio %s -> %s", appel.sid, e164)
    # Attend la fin de l'appel (sans webhook : on interroge le statut).
    statut = appel.status
    for _ in range(90):  # ~3 min max
        time.sleep(2)
        try:
            a = client.calls(appel.sid).fetch()
        except Exception:
            continue
        statut = a.status
        if statut in ("completed", "busy", "no-answer", "failed", "canceled"):
            duree = int(a.duration or 0)
            break
    else:
        duree = 0

    if statut in ("no-answer", "busy"):
        return f"Personne n'a decroche ({'occupe' if statut == 'busy' else 'pas de reponse'})."
    if statut in ("failed", "canceled"):
        return "L'appel n'a pas pu aboutir."

    minutes = max(duree / 60.0, 0.1)
    cout = _cout(minutes)
    compteur = _ajouter_compteur(minutes, cout)

    # Recupere l'enregistrement de la reponse (API REST).
    transcription = ""
    try:
        enregistrements = client.recordings.list(call_sid=appel.sid, limit=1)
        if enregistrements:
            transcription = _telecharger_et_transcrire(client, enregistrements[0], appel.sid)
    except Exception as e:
        LOG.exception("recuperation enregistrement")
        transcription = f"(je n'ai pas pu recuperer l'enregistrement : {e})"

    _journaliser(e164, message, transcription, duree, cout)
    resume_cout = (f"Duree {duree}s, cout estime {cout} euro. Ce mois : "
                   f"{compteur['appels']} appel(s), {compteur['cout']} euro.")
    if transcription and not transcription.startswith("("):
        return (f"Appel termine. L'interlocuteur a repondu : «{transcription}». "
                f"{resume_cout}")
    detail = transcription or "aucun enregistrement"
    return (f"Appel termine, mais je n'ai pas de reponse exploitable "
            f"({detail}). {resume_cout}")


def _telecharger_et_transcrire(client, enregistrement, sid):
    import requests
    dossier = _RACINE / (reglage("appels.dossier", "logs/calls"))
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = dossier / f"appel_{horodatage}.mp3"
    url = f"https://api.twilio.com{enregistrement.uri.replace('.json', '.mp3')}"
    r = requests.get(url, auth=(reglage("twilio.account_sid", ""),
                                reglage("twilio.auth_token", "")), timeout=20)
    chemin.write_bytes(r.content)
    return _transcrire(str(chemin))


def _journaliser(numero, message, transcription, duree, cout):
    dossier = _RACINE / (reglage("appels.dossier", "logs/calls"))
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    (dossier / f"appel_{horodatage}.txt").write_text(
        f"Date : {dt.datetime.now():%Y-%m-%d %H:%M}\nNumero : {numero}\n"
        f"Message envoye : {message}\nDuree : {duree}s\nCout estime : {cout} euro\n\n"
        f"Reponse transcrite :\n{transcription}\n", encoding="utf-8")


@outil(
    nom="cout_appels",
    description="Donne le compteur des appels telephoniques du mois (nombre, minutes, "
                "cout estime). Pour 'combien j'ai depense en appels', 'mes appels ce mois'.",
    mcp_expose=False,
)
def cout_appels() -> str:
    d = _lire_compteur()
    if d["appels"] == 0:
        return "Aucun appel passe ce mois-ci."
    return (f"Ce mois-ci : {d['appels']} appel(s), {round(d['minutes'])} minutes environ, "
            f"pour un cout estime de {d['cout']} euro.")
