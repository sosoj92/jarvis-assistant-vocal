"""Appels V2 : CONVERSATION temps reel via Twilio Media Streams.

call_and_book(numero, objectif, contraintes) : Jarvis appelle, se presente
honnetement, expose la demande, comprend les reponses (Whisper), repond (Claude,
phrases courtes), negocie dans les limites donnees, et conclut (ElevenLabs en
sortie ulaw 8 kHz, le format de Twilio).

Chaine audio :
  Twilio (mu-law 8kHz) --ws--> VAD/segmentation --> Whisper --> Claude --> ElevenLabs
  (ulaw_8000) --ws--> Twilio.

Twilio se connecte a un serveur websocket PUBLIC : soit twilio.public_url (que tu
exposes toi-meme), soit un tunnel ngrok automatique (twilio.ngrok_authtoken).

Ethique (comme la V1) : confirmation avant l'appel, presentation honnete en debut
d'appel, n'engage que ce qui a ete valide avant, transcription dans logs/calls/.
mcp_expose=False. Voir docs/appels.md.
"""
import asyncio
import audioop
import base64
import json
import logging
import secrets
import threading
import time
from pathlib import Path

from core.config import reglage
from core.registre import outil

# SÉCURITÉ : le WebSocket /stream est PUBLIC (exposé par le tunnel pour Twilio).
# On exige un secret partagé, glissé dans le TwiML (customParameter), donc connu
# de Twilio seul, et vérifié à l'event "start". Sans ça, n'importe qui connaissant
# le domaine ngrok pouvait ouvrir un tour LLM + TTS (drain de budget API).
_STREAM_SECRET = reglage("appel.stream_secret", "") or secrets.token_urlsafe(24)

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent

# Le serveur websocket est desormais le serveur unifie (core.serveur) : la route
# /stream y est montee par monter_ws(). Ici on ne garde que l'etat des appels.
_RESULTATS = {}        # callSid -> {"event": Event, "echanges": [...], "statut": str}

_TRANSCRIPTEUR = None   # np.float32 (16kHz) -> texte, fourni par jarvis14
_CLIENT = None


def definir_transcripteur_direct(fn):
    global _TRANSCRIPTEUR
    _TRANSCRIPTEUR = fn


# ------------------------------------------------------------------- audio

def _ulaw_vers_pcm16k(ulaw_bytes):
    """mu-law 8kHz -> PCM16 8kHz -> np.float32 16kHz (pour Whisper)."""
    import numpy as np
    pcm8 = audioop.ulaw2lin(ulaw_bytes, 2)
    pcm16, _ = audioop.ratecv(pcm8, 2, 1, 8000, 16000, None)
    return np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0


def _rms_ulaw(ulaw_bytes):
    return audioop.rms(audioop.ulaw2lin(ulaw_bytes, 2), 2)


def _transcrire(pcm8_bytes):
    import numpy as np
    if not pcm8_bytes:
        return ""
    pcm16, _ = audioop.ratecv(pcm8_bytes, 2, 1, 8000, 16000, None)
    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if _TRANSCRIPTEUR is not None:
        try:
            return (_TRANSCRIPTEUR(audio) or "").strip()
        except Exception:
            LOG.exception("transcription directe")
    return ""


def _tts_ulaw(texte):
    """ElevenLabs -> bytes mu-law 8kHz (format natif Twilio). '' si indispo."""
    import requests
    cle = reglage("elevenlabs.cle", "")
    if not cle or not texte:
        return b""
    voix = reglage("elevenlabs.voix", "") or "21m00Tcm4TlvDq8ikWAM"
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voix}"
           f"?output_format=ulaw_8000")
    try:
        r = requests.post(url, headers={"xi-api-key": cle,
            "content-type": "application/json"}, json={
                "text": texte,
                "model_id": reglage("elevenlabs.modele", "eleven_flash_v2_5")},
            timeout=30)
        return r.content if r.status_code == 200 else b""
    except Exception:
        LOG.exception("tts ulaw")
        return b""


# ------------------------------------------------------------------- Claude

def _client():
    global _CLIENT
    if _CLIENT is None:
        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:
            pass
        import anthropic
        cle = reglage("anthropic.cle", "")
        _CLIENT = anthropic.Anthropic(api_key=cle) if cle else None
    return _CLIENT


def _systeme(prenom, objectif, contraintes):
    return (
        f"Tu es l'assistant vocal automatise de {prenom}. Tu telephones a un "
        f"professionnel pour : {objectif}.\n"
        f"Contraintes a respecter absolument : {contraintes or 'aucune en plus de l objectif'}.\n"
        "Regles :\n"
        f"- Des le debut, presente-toi honnetement : \"Bonjour, je suis l'assistant "
        f"vocal automatise de {prenom}.\" Ne te fais JAMAIS passer pour un humain.\n"
        "- Phrases COURTES (tu es au telephone) : 1 a 2 phrases par tour.\n"
        f"- Tu ne peux confirmer QUE ce qui est dans l'objectif et les contraintes. "
        f"Tout imprevu (autre creneau, supplement, question hors sujet) : reponds "
        f"\"je dois verifier avec {prenom}, on vous rappelle\".\n"
        "- Jamais de donnees bancaires ni de mot de passe.\n"
        f"- Si on demande a parler a un humain, ou si la personne s'agace : excuse-toi, "
        f"propose que {prenom} rappelle, et termine poliment.\n"
        "- Repondeur : laisse un message court (qui tu es, l'objet, 'rappelez-nous') puis termine.\n"
        "- Quand l'echange est conclu : dis au revoir et termine ta reponse par le token [FIN].\n"
        "Reponds UNIQUEMENT par ce que tu dois dire a voix haute, en francais.")


def _repondre_claude(systeme, historique):
    client = _client()
    if client is None:
        return "Desole, je dois raccrocher. [FIN]"
    try:
        rep = client.messages.create(
            model=reglage("appels.modele", reglage("anthropic.modele", "claude-haiku-4-5")),
            max_tokens=150, system=systeme, messages=historique)
        return "".join(b.text for b in rep.content if getattr(b, "type", None) == "text").strip()
    except Exception:
        LOG.exception("claude appel direct")
        return "Desole, je rencontre un souci, on vous rappelle. [FIN]"


# ---------------------------------------------------------------- conversation

class Conversation:
    def __init__(self, ws, stream_sid, call_sid, params):
        self.ws = ws
        self.sid = stream_sid
        self.call_sid = call_sid
        prenom = params.get("prenom", "mon proprietaire")
        self.systeme = _systeme(prenom, params.get("objectif", ""), params.get("contraintes", ""))
        self.historique = []
        self.echanges = []          # transcript lisible
        self.buffer = bytearray()   # utterance mu-law en cours
        self.actif = False          # la personne parle-t-elle
        self.silence_ms = 0
        self.occupe = False         # un tour Jarvis est en cours
        self.fini = False
        self.debut = time.time()

    async def demarrer(self):
        # Jarvis parle en premier : presentation honnete + demande.
        self.historique.append({"role": "user", "content":
            "[L'appel vient de decrocher. Presente-toi honnetement et expose la demande.]"})
        await self._tour_jarvis()

    async def audio_entrant(self, payload_b64):
        if self.fini or self.occupe:
            return
        ulaw = base64.b64decode(payload_b64)
        cadre_ms = max(1, int(len(ulaw) / 8))   # 8 octets mu-law = 1 ms a 8kHz
        seuil = int(reglage("appels.seuil_voix", 400))
        if _rms_ulaw(ulaw) > seuil:
            self.buffer += audioop.ulaw2lin(ulaw, 2)
            self.silence_ms = 0
            self.actif = True
        elif self.actif:
            self.buffer += audioop.ulaw2lin(ulaw, 2)
            self.silence_ms += cadre_ms
            if self.silence_ms >= int(reglage("appels.silence_fin_ms", 700)):
                pcm = bytes(self.buffer)
                self.buffer = bytearray()
                self.actif = False
                self.silence_ms = 0
                await self._sur_utterance(pcm)
        if time.time() - self.debut > int(reglage("appels.duree_max_appel", 180)):
            await self.terminer("duree max")

    async def _sur_utterance(self, pcm8):
        texte = await asyncio.to_thread(_transcrire, pcm8)
        if not texte or len(texte) < 2:
            return  # silence / musique d'attente : on patiente
        self.echanges.append(("interlocuteur", texte))
        self.historique.append({"role": "user", "content": texte})
        await self._tour_jarvis()

    async def _tour_jarvis(self):
        if self.fini:
            return
        self.occupe = True
        try:
            reponse = await asyncio.to_thread(_repondre_claude, self.systeme, self.historique)
            fin = "[FIN]" in reponse
            texte = reponse.replace("[FIN]", "").strip()
            if texte:
                self.echanges.append(("jarvis", texte))
                self.historique.append({"role": "assistant", "content": texte})
                audio = await asyncio.to_thread(_tts_ulaw, texte)
                await self._jouer(audio)
            if fin:
                await self.terminer("conclu")
        finally:
            self.occupe = False

    async def _jouer(self, ulaw):
        # Envoie l'audio a Twilio par trames de 20 ms (160 octets mu-law).
        for i in range(0, len(ulaw), 160):
            if self.fini:
                break
            trame = ulaw[i:i + 160]
            try:
                await self.ws.send_text(json.dumps({"event": "media", "streamSid": self.sid,
                    "media": {"payload": base64.b64encode(trame).decode("ascii")}}))
            except Exception:
                # L'interlocuteur a raccroche pendant qu'on parlait : c'est normal.
                self.fini = True
                break
            await asyncio.sleep(0.018)

    async def terminer(self, statut="fin"):
        if self.fini:
            return
        self.fini = True
        res = _RESULTATS.get(self.call_sid)
        if res is not None:
            res["echanges"] = self.echanges
            res["statut"] = statut
            res["event"].set()
        # Raccroche cote Twilio (best-effort ; peut echouer en fin de vie du serveur).
        try:
            await asyncio.to_thread(_raccrocher, self.call_sid)
        except Exception:
            pass


def _raccrocher(call_sid):
    try:
        from twilio.rest import Client
        Client(reglage("twilio.account_sid", ""), reglage("twilio.auth_token", "")
               ).calls(call_sid).update(status="completed")
    except Exception:
        LOG.exception("raccrocher")


# --------------------------------------- route websocket sur le serveur unifie

def monter_ws(app):
    """Ajoute la route WebSocket /stream (Twilio Media Streams) au serveur unifie
    (core.serveur). Twilio s'y connecte via le <Stream> du TwiML."""
    from fastapi import WebSocket, WebSocketDisconnect

    @app.websocket("/stream")
    async def stream(ws: WebSocket):
        await ws.accept()
        conv = None
        try:
            while True:
                data = json.loads(await ws.receive_text())
                ev = data.get("event")
                if ev == "start":
                    info = data["start"]
                    params = info.get("customParameters", {}) or {}
                    # AUTH : refuse tout /stream sans le bon secret (voir _STREAM_SECRET).
                    if not secrets.compare_digest(str(params.get("secret", "")), _STREAM_SECRET):
                        LOG.warning("ws /stream : secret invalide -> fermeture")
                        await ws.close(code=1008)
                        return
                    conv = Conversation(ws, info["streamSid"], info["callSid"], params)
                    await conv.demarrer()
                elif ev == "media" and conv:
                    await conv.audio_entrant(data["media"]["payload"])
                elif ev == "stop":
                    if conv:
                        await conv.terminer("raccroche")
                    break
        except WebSocketDisconnect:
            if conv:
                await conv.terminer("raccroche")
        except Exception:
            LOG.exception("ws /stream")
            if conv:
                await conv.terminer("erreur")


# ------------------------------------------------------------------ l'outil

def _prenom():
    nom = (reglage("utilisateur.nom", "") or "").strip()
    return nom.split()[0] if nom else "mon proprietaire"


def _annonce(args):
    return (f"Je vais appeler le {args.get('numero','')} pour : "
            f"{args.get('objectif','')}. Je me presenterai comme ton assistant "
            "automatise et je n'engagerai que ce que tu as valide.")


def _twiml_stream(objectif, contraintes):
    from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
    from core.serveur import url_ws
    vr = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"{url_ws()}/stream")
    stream.parameter(name="objectif", value=objectif)
    stream.parameter(name="contraintes", value=contraintes or "")
    stream.parameter(name="prenom", value=_prenom())
    stream.parameter(name="secret", value=_STREAM_SECRET)      # auth du /stream
    connect.append(stream)
    vr.append(connect)
    return str(vr)


@outil(
    nom="call_and_book",
    description="Appelle un numero et MENE UNE VRAIE CONVERSATION pour atteindre un "
                "objectif (ex. reserver une table, prendre un rdv). Jarvis se presente, "
                "expose la demande, comprend les reponses et negocie dans les limites "
                "donnees. Pour 'appelle le resto et reserve une table pour 2 vendredi "
                "20h'. Confirmation requise. Necessite un serveur public (voir docs).",
    parametres={
        "type": "object",
        "properties": {
            "numero": {"type": "string", "description": "Numero a appeler."},
            "objectif": {"type": "string",
                         "description": "Le but de l'appel, precis (quoi reserver, quand, combien)."},
            "contraintes": {"type": "string",
                            "description": "Limites a ne pas depasser (creneaux acceptables, "
                                           "budget zero, nombre de personnes...)."},
        },
        "required": ["numero", "objectif"],
    },
    confirmation=True,
    annonce=_annonce,
    lent=True,
    phrase_attente="Je passe l'appel et je gere la conversation, ca peut prendre un moment.",
    mcp_expose=False,
)
def call_and_book(numero: str, objectif: str, contraintes: str = "") -> str:
    from tools.appels import _normaliser, _surtaxe, _config_ok, _journaliser
    if not reglage("appels.actif", True):
        return "Les appels sont desactives dans la configuration."
    # Mode test : on "fait comme si" l'appel etait passe et la reservation faite,
    # sans appeler personne (appels.simulation dans config.yaml). Le message dit
    # clairement que c'est une simulation.
    if reglage("appels.simulation", False):
        import time
        time.sleep(4)   # petit delai pour faire comme si on telephonait
        return (f"(Mode test, aucun vrai appel n'a ete passe) J'ai appele et c'est "
                f"regle : {objectif}. La reservation est confirmee.")
    if not _config_ok():
        return "Twilio n'est pas configure (voir docs/appels.md)."
    if not reglage("elevenlabs.cle", ""):
        return ("La V2 a besoin d'une voix ElevenLabs (elevenlabs.cle) pour parler "
                "pendant l'appel. Sans elle, utilise call_with_message (V1).")
    e164 = _normaliser(numero)
    if _surtaxe(numero):
        return f"Je n'appelle pas le {e164} : numero surtaxe."

    try:
        from core.serveur import demarrer, url_publique
        demarrer()
        url_publique()   # verifie qu'on a une URL publique (ngrok statique ou tunnel)
    except Exception as e:
        LOG.exception("preparation serveur/tunnel")
        return (f"Je n'ai pas pu preparer le serveur d'appel ({e}). Verifie "
                "serveur.public_url ou serveur.ngrok_authtoken (docs/appels.md).")

    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    from twilio.rest import Client
    client = Client(reglage("twilio.account_sid", ""), reglage("twilio.auth_token", ""))
    try:
        appel = client.calls.create(to=e164, from_=reglage("twilio.numero", ""),
                                    twiml=_twiml_stream(objectif, contraintes))
    except Exception as e:
        LOG.exception("call_and_book: creation")
        return f"Je n'ai pas pu lancer l'appel ({e})."

    _RESULTATS[appel.sid] = {"event": threading.Event(), "echanges": [], "statut": None}
    LOG.info("call_and_book %s -> %s", appel.sid, e164)

    duree_max = int(reglage("appels.duree_max_appel", 180))
    fini = _RESULTATS[appel.sid]["event"].wait(timeout=duree_max + 30)
    res = _RESULTATS.pop(appel.sid, {})
    echanges = res.get("echanges", [])

    # Journalise + resume
    transcript = "\n".join(f"{qui} : {txt}" for qui, txt in echanges)
    _journaliser(e164, f"[V2] {objectif}", transcript or "(pas d'echange capte)", 0, 0.0)

    if not fini and not echanges:
        return ("L'appel n'a pas abouti a une conversation (pas de decrochage, ou le "
                "serveur n'etait pas joignable). Rien n'a ete engage.")
    if not echanges:
        return "L'appel a eu lieu mais je n'ai pas capte d'echange exploitable."
    dernier = " ".join(t for q, t in echanges[-3:])
    return (f"Appel termine ({res.get('statut','fin')}). Voici comment ca s'est fini : "
            f"{dernier}. Le detail complet est dans logs/calls.")
