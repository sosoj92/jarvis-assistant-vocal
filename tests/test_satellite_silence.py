"""Satellites et agent : le silence ou le bruit ne deviennent jamais une phrase."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core import satellite
from core.hallucinations import est_hallucination

UNE_SECONDE = (np.ones(16000, dtype=np.int16) * 300).tobytes()


def _segment(texte, no_speech=0.0, logprob=-0.2):
    return SimpleNamespace(text=texte, no_speech_prob=no_speech, avg_logprob=logprob)


class _FauxWhisper:
    def __init__(self, segments):
        self.segments = segments
        self.options = {}

    def transcribe(self, audio, **options):
        self.options = options
        return iter(self.segments), None


class TranscriptionTest(unittest.TestCase):
    def _transcrire(self, segments):
        modele = _FauxWhisper(segments)
        with patch.object(satellite, "_whisper", return_value=modele):
            texte = satellite._transcrire(UNE_SECONDE)
        return texte, modele.options

    def test_la_detection_de_voix_est_activee(self):
        _, options = self._transcrire([_segment(" Allume la lumière.")])
        self.assertTrue(options.get("vad_filter"))

    def test_une_vraie_phrase_passe(self):
        texte, _ = self._transcrire([_segment(" Quelle heure est-il ?")])
        self.assertEqual(texte, "Quelle heure est-il ?")

    def test_hallucination_de_silence_rejetee(self):
        # Cas reel observe sur le poste : bruit de fond transcrit en sous-titres.
        texte, _ = self._transcrire([_segment(" Sous-titres réalisés par la communauté d'Amara.org")])
        self.assertEqual(texte, "")

    def test_segment_juge_sans_parole_ecarte(self):
        texte, _ = self._transcrire([_segment(" Merci beaucoup.", no_speech=0.9, logprob=-1.4)])
        self.assertEqual(texte, "")

    def test_un_vrai_merci_reste_possible(self):
        texte, _ = self._transcrire([_segment(" Merci beaucoup.", no_speech=0.1, logprob=-0.3)])
        self.assertEqual(texte, "Merci beaucoup.")


class IncomprisTest(unittest.TestCase):
    def test_apres_hey_jarvis_une_seule_phrase(self):
        sess = satellite._Session()
        self.assertEqual(satellite._incompris(sess, apres_reveil=True), "Je n'ai rien entendu.")

    def test_pendant_une_relance_le_silence(self):
        self.assertEqual(satellite._incompris(satellite._Session(), apres_reveil=False), "")

    def test_une_action_n3_en_attente_est_annulee(self):
        sess = satellite._Session()
        sess.en_attente = ("envoyer_mail", {})
        self.assertIn("j'annule", satellite._incompris(sess, apres_reveil=False))
        self.assertIsNone(sess.en_attente)

    def test_le_reveil_marque_la_phrase_suivante(self):
        sess = satellite._Session()
        self.assertFalse(sess.apres_reveil)
        sess.nouveau_reveil(2)
        self.assertTrue(sess.apres_reveil)


class HallucinationsPartageesTest(unittest.TestCase):
    def test_liste_commune(self):
        self.assertTrue(est_hallucination("Sous-titres réalisés par la communauté d'Amara.org"))
        self.assertFalse(est_hallucination("Allume la lumière du bureau."))


if __name__ == "__main__":
    unittest.main()
