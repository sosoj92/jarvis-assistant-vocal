"""Reconnaissance vocale : faster-whisper en local, repli cloud quand il est absent.

faster-whisper repose sur CTranslate2, qui n'existe pas sur toutes les plateformes
(notamment Windows ARM64 / Snapdragon). Dans ce cas, et seulement si la
configuration l'autorise, la transcription passe par l'API OpenAI avec la meme
interface que Whisper : ``modele.transcribe(audio, language="fr", ...)`` renvoie
``(segments, info)``, chaque segment ayant un attribut ``text``.

Regles du repli cloud :
  - ``stt.moteur`` : "auto" (defaut : local, sinon cloud), "local" (jamais de
    cloud) ou "openai" (cloud meme si Whisper local est installe) ;
  - jamais en mode de routage « local », qui promet zero appel d'API ;
  - il faut une cle ``openai.cle``. L'audio de la phrase part alors chez OpenAI ;
    le cout est compte dans le budget du jour.
"""
import io
import logging
import wave
from dataclasses import dataclass
from pathlib import Path

from core.config import reglage

LOG = logging.getLogger("jarvis.transcription")

TAUX = 16000
MESSAGE_INDISPONIBLE = (
    "Reconnaissance vocale indisponible : faster-whisper n'est pas installe sur cette "
    "machine (c'est le cas sur Windows ARM64) et le repli cloud n'est pas permis. "
    "Ajoute une cle openai.cle et garde stt.moteur sur auto, hors mode local.")


def whisper_local_disponible():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def moteur():
    choix = str(reglage("stt.moteur", "auto") or "auto").strip().lower()
    return choix if choix in {"auto", "local", "openai"} else "auto"


def cloud_autorise():
    """Vrai si l'audio peut partir chez OpenAI : moteur non local, routage non local, cle."""
    if moteur() == "local":
        return False
    try:
        from core.routage import mode_actuel
        if mode_actuel() == "local":
            return False
    except Exception:
        pass
    return bool(str(reglage("openai.cle", "") or "").strip())


@dataclass
class Segment:
    """Meme forme qu'un segment faster-whisper pour le code appelant."""
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0


def _en_wav(audio):
    """(octets WAV 16 bits mono, duree en secondes) depuis un tableau 16 kHz ou un fichier."""
    if isinstance(audio, (str, Path)):
        donnees = Path(audio).read_bytes()
        try:
            with wave.open(io.BytesIO(donnees), "rb") as f:
                return donnees, f.getnframes() / float(f.getframerate() or TAUX)
        except Exception:
            return donnees, 0.0
    import numpy as np
    echantillons = np.asarray(audio)
    if echantillons.dtype != np.int16:
        echantillons = (np.clip(echantillons.astype(np.float32), -1.0, 1.0) * 32767).astype(np.int16)
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(TAUX)
        f.writeframes(echantillons.tobytes())
    return tampon.getvalue(), echantillons.size / float(TAUX)


class TranscripteurCloud:
    """Transcription par l'API OpenAI, interchangeable avec un modele faster-whisper."""

    nom = "OpenAI"

    def __init__(self, modele=None):
        self.modele = modele or str(reglage("stt.modele_cloud", "gpt-4o-mini-transcribe"))

    def transcribe(self, audio, language="fr", **_options):
        if not cloud_autorise():
            # Le mode local a pu etre active depuis le chargement : rien ne part.
            LOG.warning("transcription cloud refusee (mode local, stt.moteur ou cle absente)")
            return [], None
        donnees, secondes = _en_wav(audio)
        if 0.0 < secondes < 0.3:
            return [], None
        from core import cloud
        client = cloud.client_openai()
        if client is None:
            return [], None
        reponse = client.audio.transcriptions.create(
            model=self.modele, file=("phrase.wav", donnees, "audio/wav"), language=language)
        texte = str(getattr(reponse, "text", "") or "").strip()
        try:
            from core import budget
            budget.enregistrer_stt(secondes, self.modele)
        except Exception:
            pass
        return ([Segment(texte)] if texte else []), None


def repli_cloud(raison=""):
    """Transcripteur cloud si le repli est permis, sinon None (avec un message clair)."""
    if moteur() != "local" and cloud_autorise():
        LOG.warning("Whisper local indisponible%s : transcription par OpenAI.",
                    f" ({raison})" if raison else "")
        return TranscripteurCloud()
    LOG.error(MESSAGE_INDISPONIBLE)
    return None


def charger(nom, device="cpu", compute_type="int8"):
    """Modele de transcription : faster-whisper si possible, sinon repli cloud, sinon None."""
    if moteur() == "openai" and cloud_autorise():
        return TranscripteurCloud()
    if not whisper_local_disponible():
        return repli_cloud("faster-whisper absent")
    from faster_whisper import WhisperModel
    return WhisperModel(nom, device=device, compute_type=compute_type)
