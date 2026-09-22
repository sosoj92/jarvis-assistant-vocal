"""Abstraction de la synthese vocale (TTS) : cloud ou local, meme interface.

Chaque provider expose `synthetiser(texte)` qui renvoie (audio_int16, frequence)
ou None. jarvis14 se charge de JOUER l'audio (avec sa gestion d'interruption) et
retombe sur la voix integree a l'OS si le provider renvoie None (SAPI sur
Windows, `say` sur macOS, espeak sur Linux — cf. core/plateforme).

  - PiperProvider      : local, 100% offline, voix francaise Piper (.onnx).
  - KokoroProvider     : local, kokoro-onnx (voix FR de qualite moyenne).
  - OSProvider         : demande le repli gere par jarvis14.dire().

Choix par config.yaml (`tts.moteur`) et par le mode local/hybride/qualite.
Sans modele Piper installe, on retombe proprement sur la voix integree de
l'OS (SAPI sur Windows, `say` sur macOS, espeak sur Linux).

Note honnete sur le TTS local francais : Piper est recommande (voix FR eprouvees
comme fr_FR-siwis / fr_FR-tom, tres leger, temps reel sur CPU). Kokoro (kokoro-onnx)
ne propose qu'une voix FR recente et de qualite moyenne ; Piper est un meilleur
choix pour le francais aujourd'hui.
"""
import logging
from pathlib import Path

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


class OSProvider(ProviderTTS):
    """Demande volontairement le repli OS gere par jarvis14.dire()."""
    nom = "OS"


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
                octets = getattr(bloc, "audio_int16_bytes", None)
                if octets is None:                       # repli : tableau float
                    arr = getattr(bloc, "audio_float_array", None)
                    if arr is not None:
                        octets = (np.asarray(arr) * 32767).astype(np.int16).tobytes()
                if octets:
                    morceaux.append(octets)
                if frequence is None:
                    frequence = getattr(bloc, "sample_rate", None)
            brut = b"".join(morceaux)
            if not brut:
                return None
            return (np.frombuffer(brut, dtype=np.int16),
                    frequence or getattr(self._voix.config, "sample_rate", 22050))

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

    ``tts.moteur`` peut valoir auto/piper/kokoro/os. Le mode local garde sa
    promesse de confidentialite : un moteur local est toujours choisi. En
    auto, on prend la voix locale installee, sinon le repli de l'OS.
    """
    global _TTS
    if _TTS is None:
        from core.routage import mode_actuel
        m = mode_actuel()
        moteur = (reglage("tts.moteur", "auto") or "auto").lower()
        if moteur == "auto" or moteur == "elevenlabs":
            # Valeur "elevenlabs" : ancienne config. On la traite comme auto.
            moteur = (reglage("voix_locale", "piper") or "piper").lower()
            local = _provider_local()
            if local.disponible():
                _TTS = local
            else:
                _TTS = OSProvider()
        elif moteur == "kokoro":
            _TTS = KokoroProvider()
        elif moteur == "piper":
            _TTS = PiperProvider()
        else:
            _TTS = OSProvider()
        LOG.info("provider TTS : %s (mode %s)", _TTS.nom, m)
    return _TTS


def reinitialiser():
    """Force la reconstruction du provider TTS au prochain tts() (switch de mode)."""
    global _TTS
    _TTS = None
