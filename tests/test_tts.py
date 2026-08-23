"""Tests du TTS local (Piper), indépendants du système.

Piper est le moteur de voix recommandé hors ligne : s'il échoue, Jarvis retombe
sur la voix de l'OS sans le dire fort. Ces tests vérifient qu'on appelle bien
l'API réellement présente dans la version installée.
"""
import sys
from pathlib import Path

import pytest

from core import tts

RACINE = Path(__file__).resolve().parent.parent


class _Bloc:
    """Un AudioChunk de piper-tts >= 1.3 (un par phrase)."""

    def __init__(self, octets, frequence=22050):
        self.audio_int16_bytes = octets
        self.sample_rate = frequence


class _Config:
    sample_rate = 16000        # volontairement different, pour voir qui gagne


class _VoixModerne:
    """piper-tts >= 1.3 : synthesize() rend des AudioChunk."""

    config = _Config()

    def synthesize(self, texte, *a, **kw):
        return [_Bloc(b"\x01\x02" * 100), _Bloc(b"\x03\x04" * 50)]


class _VoixAncienne:
    """piper-tts < 1.3 : synthesize_stream_raw() rend des octets."""

    config = _Config()

    def synthesize_stream_raw(self, texte):
        return [b"\x01\x02" * 100]


def _numpy():
    return pytest.importorskip("numpy")


def test_api_moderne_concatene_les_phrases():
    """Chaque phrase est un bloc : il faut TOUS les joindre, pas seulement le 1er."""
    np = _numpy()
    p = tts.PiperProvider()
    p._voix = _VoixModerne()
    audio, freq = p._rendre(np, "Deux phrases. Vraiment deux.")
    assert audio.dtype == np.int16
    assert len(audio) == 150          # (200 + 100) octets / 2
    # La fréquence vient du bloc audio, pas de la config du modèle.
    assert freq == 22050


def test_api_ancienne_toujours_geree():
    """Une installation piper < 1.3 ne doit pas être cassée par le correctif."""
    np = _numpy()
    p = tts.PiperProvider()
    p._voix = _VoixAncienne()
    audio, freq = p._rendre(np, "Bonjour")
    assert len(audio) == 100 and freq == 16000


def test_audio_vide_rend_none():
    """Rien à jouer -> None, pour que jarvis14 bascule sur la voix de l'OS."""
    np = _numpy()

    class _Muette(_VoixModerne):
        def synthesize(self, texte, *a, **kw):
            return []

    p = tts.PiperProvider()
    p._voix = _Muette()
    assert p._rendre(np, "") is None


def test_methode_appelee_existe_vraiment():
    """Le garde-fou qui aurait attrapé le bug : piper 1.6 n'a plus
    synthesize_stream_raw, et l'échec était silencieux (repli sur la voix OS)."""
    piper = pytest.importorskip("piper")
    voix = piper.PiperVoice
    assert hasattr(voix, "synthesize") or hasattr(voix, "synthesize_stream_raw"), (
        "aucune des deux API de synthese n'est disponible dans piper-tts")


@pytest.mark.skipif(not list((RACINE / "voix").glob("*.onnx")),
                    reason="aucune voix Piper (.onnx) installee dans voix/")
def test_synthese_reelle_produit_de_la_parole():
    """Bout en bout avec le vrai modele, quand il est present."""
    np = _numpy()
    pytest.importorskip("piper")
    p = tts.PiperProvider()
    assert p.disponible()
    res = p.synthetiser("Bonjour, je suis Jarvis.")
    assert res is not None, "Piper n'a rien rendu"
    audio, freq = res
    assert audio.dtype == np.int16
    assert len(audio) > freq * 0.3, "audio trop court pour etre de la parole"
    assert int(abs(audio).max()) > 1000, "audio silencieux"


# ------------------------------------------------- choix du provider (fabrique)

@pytest.fixture(autouse=True)
def _tts_neuf():
    """Chaque test repart d'un provider non construit (le module le met en cache)."""
    tts.reinitialiser()
    yield
    tts.reinitialiser()


def _fabrique(monkeypatch, mode, cle_eleven, piper_dispo):
    monkeypatch.setattr("core.routage.mode_actuel", lambda: mode)
    monkeypatch.setattr(tts, "reglage",
                        lambda chemin, defaut=None:
                        cle_eleven if chemin == "elevenlabs.cle" else defaut)
    monkeypatch.setattr(tts.PiperProvider, "disponible", lambda self: piper_dispo)
    return tts.tts()


def test_mode_local_utilise_piper(monkeypatch):
    assert _fabrique(monkeypatch, "local", "", True).nom == "Piper"


def test_hybride_avec_cle_utilise_elevenlabs(monkeypatch):
    assert _fabrique(monkeypatch, "hybride", "cle-xyz", True).nom == "ElevenLabs"


def test_hybride_sans_cle_bascule_sur_piper(monkeypatch):
    """Claude sans payer ElevenLabs : la voix locale installee doit primer sur
    le repli de l'OS, nettement moins bon."""
    assert _fabrique(monkeypatch, "hybride", "", True).nom == "Piper"


def test_hybride_sans_cle_ni_piper_reste_sur_elevenlabs(monkeypatch):
    """Rien d'installe : on garde ElevenLabs, qui rendra None -> voix de l'OS."""
    assert _fabrique(monkeypatch, "hybride", "", False).nom == "ElevenLabs"


# ------------------------------------------------- reglages de voix (Piper)

def test_sans_reglage_on_garde_les_defauts_du_modele(monkeypatch):
    """Aucun SynthesisConfig si rien n'est configure : le .onnx decide."""
    monkeypatch.setattr(tts, "reglage", lambda chemin, defaut=None: defaut)
    assert tts.PiperProvider()._synthese() is None


def test_reglages_transmis_a_piper(monkeypatch):
    pytest.importorskip("piper")
    vals = {"piper.vitesse": 1.05, "piper.expressivite": 0.8,
            "piper.variation": 1.0, "piper.volume": 1.0}
    monkeypatch.setattr(tts, "reglage",
                        lambda chemin, defaut=None: vals.get(chemin, defaut))
    cfg = tts.PiperProvider()._synthese()
    assert cfg.length_scale == 1.05
    assert cfg.noise_scale == 0.8
    assert cfg.noise_w_scale == 1.0


def test_reglage_partiel_ne_force_pas_le_reste(monkeypatch):
    """Ne regler que la vitesse ne doit pas ecraser l'intonation du modele."""
    pytest.importorskip("piper")
    monkeypatch.setattr(tts, "reglage",
                        lambda chemin, defaut=None:
                        1.2 if chemin == "piper.vitesse" else defaut)
    cfg = tts.PiperProvider()._synthese()
    assert cfg.length_scale == 1.2
    assert cfg.noise_scale is None and cfg.noise_w_scale is None
