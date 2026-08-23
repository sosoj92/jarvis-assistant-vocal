"""Abstraction de la synthese vocale (TTS) : cloud ou local, meme interface.

Chaque provider expose `synthetiser(texte)` qui renvoie (audio_int16, frequence)
ou None. jarvis14 se charge de JOUER l'audio (avec sa gestion d'interruption) et
retombe sur la voix integree a l'OS si le provider renvoie None (SAPI sur
Windows, `say` sur macOS, espeak sur Linux — cf. core/plateforme).

  - ElevenLabsProvider : cloud (qualite max), voix configurable.
  - PiperProvider      : local, 100% offline, voix francaise Piper (.onnx).

Choix par config.yaml (mode: cloud | local). En local sans modele Piper, ou en
cloud sans cle ElevenLabs, on retombe proprement sur la voix de l'OS.

Note honnete sur le TTS local francais : Piper est recommande (voix FR eprouvees
comme fr_FR-siwis / fr_FR-tom, tres leger, temps reel sur CPU). Kokoro (kokoro-onnx)
ne propose qu'une voix FR recente et de qualite moyenne ; Piper est un meilleur
choix pour le francais aujourd'hui.
"""
import json
import logging
import urllib.request
from pathlib import Path

# Magasin de certificats du SYSTEME plutot que le bundle certifi (un antivirus qui
# intercepte le TLS ferait sinon echouer l'appel a ElevenLabs). truststore gere les
# trois OS : magasin Windows, Keychain macOS, magasin Linux.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from core import plateforme
from core.config import reglage

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent


class ProviderTTS:
    nom = "?"

    def disponible(self):
        return True

    def synthetiser(self, texte):
        """Renvoie (numpy int16 mono, frequence_hz) ou None si indisponible."""
        return None


# --------------------------------------------------------------- ElevenLabs

class ElevenLabsProvider(ProviderTTS):
    nom = "ElevenLabs"

    def __init__(self):
        self.cle = reglage("elevenlabs.cle", "")
        self.voix = reglage("elevenlabs.voix", "")
        self.modele = reglage("elevenlabs.modele", "eleven_flash_v2_5")
        self._voix_resolue = None

    def disponible(self):
        return bool(self.cle)

    def _resoudre_voix(self):
        if self.voix:
            return self.voix
        if self._voix_resolue:
            return self._voix_resolue
        try:
            requete = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": self.cle})
            with urllib.request.urlopen(requete, timeout=6) as reponse:
                d = json.loads(reponse.read().decode("utf-8"))
            self._voix_resolue = d["voices"][0]["voice_id"]
        except Exception:
            self._voix_resolue = "21m00Tcm4TlvDq8ikWAM"   # Rachel, par defaut
        return self._voix_resolue

    def synthetiser(self, texte):
        try:
            import miniaudio
            import numpy as np
        except ImportError:
            return None
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._resoudre_voix()}"
        charge = {"text": texte, "model_id": self.modele}
        # Flash/Turbo v2.5 acceptent language_code : on force le francais pour une
        # bonne prononciation des accents (e accent, c cedille...) quelle que soit
        # la voix (sinon la langue est auto-detectee et parfois lue en anglais).
        if any(x in self.modele for x in ("flash", "turbo")):
            charge["language_code"] = reglage("elevenlabs.langue", "fr")
        corps = json.dumps(charge).encode("utf-8")
        requete = urllib.request.Request(url, data=corps, method="POST", headers={
            "xi-api-key": self.cle, "Content-Type": "application/json",
            "Accept": "audio/mpeg"})
        try:
            with urllib.request.urlopen(requete, timeout=15) as reponse:
                mp3 = reponse.read()
            decode = miniaudio.decode(
                mp3, nchannels=1, sample_rate=24000,
                output_format=miniaudio.SampleFormat.SIGNED16)
            try:                                  # N12 : comptabilite voix (au caractere)
                from core import budget
                budget.enregistrer_tts(len(texte or ""))
            except Exception:
                pass
            return np.frombuffer(decode.samples, dtype=np.int16), 24000
        except Exception as e:
            print(f"  [ElevenLabs] indisponible ({e}), repli "
                  f"{plateforme.nom_voix_systeme()}.")
            return None


# --------------------------------------------------------------- Piper (local)

class PiperProvider(ProviderTTS):
    nom = "Piper"

    def __init__(self):
        self.modele = reglage("piper.modele", "")
        self._voix = None
        self._config = None

    def _synthese(self):
        """SynthesisConfig depuis config.yaml, ou None pour les defauts du modele.

        Les trois leviers qui rendent une voix Piper moins mecanique :
          vitesse      (length_scale) : >1 ralentit, <1 accelere
          expressivite (noise_scale)  : variation de l'intonation
          variation    (noise_w)      : variation de la duree des syllabes
        Piper part de 1.0 / 0.667 / 0.8 ; monter les deux derniers donne un
        debit moins regulier, donc plus humain.
        """
        if self._config is not None:
            return self._config or None
        try:
            from piper import SynthesisConfig
        except ImportError:
            self._config = False
            return None
        reglages = {
            "length_scale": reglage("piper.vitesse", None),
            "noise_scale": reglage("piper.expressivite", None),
            "noise_w_scale": reglage("piper.variation", None),
            "volume": reglage("piper.volume", None),
        }
        reglages = {k: float(v) for k, v in reglages.items() if v is not None}
        self._config = SynthesisConfig(**reglages) if reglages else False
        return self._config or None

    def _chemin(self):
        if not self.modele:
            # a defaut, prend le premier .onnx trouve dans voix/
            trouves = list((_RACINE / "voix").glob("*.onnx"))
            return trouves[0] if trouves else None
        p = Path(self.modele)
        return p if p.is_absolute() else (_RACINE / p)

    def disponible(self):
        c = self._chemin()
        return bool(c and c.exists())

    def _rendre(self, np, texte):
        """(audio int16, frequence) — gere les deux API de piper-tts.

        Depuis la 1.3, `synthesize(texte)` rend un flux d'AudioChunk (un par
        phrase) au lieu d'octets bruts ; `synthesize_stream_raw` a disparu. On
        garde les deux chemins pour ne pas casser une installation plus ancienne.
        """
        if hasattr(self._voix, "synthesize"):
            morceaux, frequence = [], None
            reglages = self._synthese()
            flux = (self._voix.synthesize(texte, reglages) if reglages
                    else self._voix.synthesize(texte))
            for bloc in flux:
                morceaux.append(bloc.audio_int16_bytes)
                if frequence is None:
                    frequence = bloc.sample_rate
            brut = b"".join(morceaux)
            if not brut:
                return None
            return (np.frombuffer(brut, dtype=np.int16),
                    frequence or self._voix.config.sample_rate)

        brut = b"".join(self._voix.synthesize_stream_raw(texte))    # piper < 1.3
        return np.frombuffer(brut, dtype=np.int16), self._voix.config.sample_rate

    def synthetiser(self, texte):
        try:
            import numpy as np
            from piper import PiperVoice
        except ImportError:
            print("  [Piper] librairie piper-tts absente.")
            return None
        chemin = self._chemin()
        if chemin is None or not chemin.exists():
            print("  [Piper] aucun modele de voix (.onnx) dans voix/. Voir docs.")
            return None
        try:
            if self._voix is None:
                self._voix = PiperVoice.load(str(chemin))
            return self._rendre(np, texte)
        except Exception as e:
            print(f"  [Piper] echec ({e}), repli "
                  f"{plateforme.nom_voix_systeme()}.")
            return None


# --------------------------------------------------------------- Kokoro (local)

class KokoroProvider(ProviderTTS):
    nom = "Kokoro"

    def __init__(self):
        self.modele = reglage("kokoro.modele", "")
        self.voix = reglage("kokoro.voix", "")
        self.voix_nom = reglage("kokoro.voix_nom", "ff_siwis")
        self._k = None

    def disponible(self):
        return bool(self.modele and Path(self.modele).exists())

    def synthetiser(self, texte):
        try:
            import numpy as np
            from kokoro_onnx import Kokoro
        except ImportError:
            print("  [Kokoro] librairie absente. Installe : uv add kokoro-onnx")
            return None
        if not (self.modele and Path(self.modele).exists()):
            print("  [Kokoro] modele introuvable (kokoro.modele). Voir docs/local.md.")
            return None
        try:
            if self._k is None:
                self._k = Kokoro(self.modele, self.voix)
            samples, freq = self._k.create(texte, voice=self.voix_nom, speed=1.0, lang="fr-fr")
            audio = (np.asarray(samples) * 32767).astype(np.int16)
            return audio, freq
        except Exception as e:
            print(f"  [Kokoro] echec ({e}), repli "
                  f"{plateforme.nom_voix_systeme()}.")
            return None


# --------------------------------------------------------------- fabrique

_TTS = None


def _provider_local():
    """Piper ou Kokoro, selon voix_locale."""
    moteur = (reglage("voix_locale", "piper") or "piper").lower()
    return KokoroProvider() if moteur == "kokoro" else PiperProvider()


def tts():
    """Provider TTS courant.

    - mode local              -> Piper/Kokoro (config voix_locale).
    - mode hybride/qualite    -> ElevenLabs.
    - hybride SANS cle ElevenLabs, mais avec une voix locale installee -> cette
      voix locale. Elle est bien meilleure que le repli de l'OS, et c'est le cas
      de figure de quiconque veut Claude sans payer un second service.
    """
    global _TTS
    if _TTS is None:
        from core.routage import mode_actuel
        m = mode_actuel()
        if m == "local":
            _TTS = _provider_local()
        else:
            cloud = ElevenLabsProvider()
            local = _provider_local()
            if not cloud.disponible() and local.disponible():
                _TTS = local
                LOG.info("pas de cle ElevenLabs : repli sur la voix locale %s", local.nom)
            else:
                _TTS = cloud
        LOG.info("provider TTS : %s (mode %s)", _TTS.nom, m)
    return _TTS


def reinitialiser():
    """Force la reconstruction du provider TTS au prochain tts() (switch de mode)."""
    global _TTS
    _TTS = None
