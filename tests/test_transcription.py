"""Reconnaissance vocale : Whisper local, repli OpenAI (Windows ARM64), regles de confidentialite."""
import io
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from core import transcription

ROOT = Path(__file__).resolve().parents[1]


def reglages(**valeurs):
    return lambda cle, defaut=None: valeurs.get(cle, defaut)


AVEC_CLE = {"openai.cle": "cle-de-test"}


class ChoixMoteurTest(unittest.TestCase):
    def _choisir(self, valeurs, mode="hybride", local=True):
        with patch.object(transcription, "reglage", reglages(**valeurs)), \
                patch("core.routage.mode_actuel", return_value=mode), \
                patch.object(transcription, "whisper_local_disponible", return_value=local), \
                patch("faster_whisper.WhisperModel", create=True) as whisper:
            return transcription.charger("small"), whisper

    def test_whisper_local_prioritaire(self):
        modele, whisper = self._choisir(AVEC_CLE)
        whisper.assert_called_once_with("small", device="cpu", compute_type="int8")
        self.assertIs(modele, whisper.return_value)

    def test_sans_whisper_local_repli_openai(self):
        modele, _ = self._choisir(AVEC_CLE, local=False)
        self.assertIsInstance(modele, transcription.TranscripteurCloud)

    def test_jamais_de_cloud_en_mode_local(self):
        modele, _ = self._choisir(AVEC_CLE, mode="local", local=False)
        self.assertIsNone(modele)

    def test_jamais_de_cloud_si_stt_local(self):
        modele, _ = self._choisir({**AVEC_CLE, "stt.moteur": "local"}, local=False)
        self.assertIsNone(modele)

    def test_jamais_de_cloud_sans_cle(self):
        modele, _ = self._choisir({}, local=False)
        self.assertIsNone(modele)

    def test_openai_force_meme_avec_whisper_local(self):
        modele, whisper = self._choisir({**AVEC_CLE, "stt.moteur": "openai"})
        self.assertIsInstance(modele, transcription.TranscripteurCloud)
        whisper.assert_not_called()


class TranscripteurCloudTest(unittest.TestCase):
    def _transcrire(self, audio, mode="hybride", texte="Allume la lumière."):
        client = MagicMock()
        client.audio.transcriptions.create.return_value = MagicMock(text=texte)
        with patch.object(transcription, "reglage", reglages(**AVEC_CLE)), \
                patch("core.routage.mode_actuel", return_value=mode), \
                patch("core.cloud.client_openai", return_value=client), \
                patch("core.budget.enregistrer_stt") as budget:
            resultat = transcription.TranscripteurCloud().transcribe(audio, language="fr",
                                                                    beam_size=1, vad_filter=True)
        return resultat, client, budget

    def test_meme_interface_que_whisper(self):
        audio = np.zeros(transcription.TAUX, dtype=np.float32)
        (segments, info), client, budget = self._transcrire(audio)
        self.assertEqual([s.text for s in segments], ["Allume la lumière."])
        self.assertIsNone(info)
        envoi = client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(envoi["model"], "gpt-4o-mini-transcribe")
        self.assertEqual(envoi["language"], "fr")
        with wave.open(io.BytesIO(envoi["file"][1]), "rb") as f:     # vrai WAV 16 kHz mono
            self.assertEqual((f.getframerate(), f.getnchannels(), f.getnframes()),
                             (16000, 1, 16000))
        budget.assert_called_once_with(1.0, "gpt-4o-mini-transcribe")

    def test_rien_ne_part_si_le_mode_local_est_active_ensuite(self):
        (segments, _), client, _ = self._transcrire(np.zeros(16000, dtype=np.float32), mode="local")
        self.assertEqual(segments, [])
        client.audio.transcriptions.create.assert_not_called()

    def test_bruit_trop_court_non_envoye(self):
        (segments, _), client, _ = self._transcrire(np.zeros(1000, dtype=np.float32))
        self.assertEqual(segments, [])
        client.audio.transcriptions.create.assert_not_called()


class IntegrationTest(unittest.TestCase):
    def test_jarvis_ne_charge_plus_faster_whisper_au_demarrage(self):
        source = (ROOT / "jarvis14.py").read_text(encoding="utf-8")
        self.assertNotIn("\nfrom faster_whisper import WhisperModel\n", source.split("def ")[0])
        self.assertIn("transcription.repli_cloud(", source)

    def test_paquets_absents_sur_windows_arm64(self):
        projet = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        exclusion = "; sys_platform != 'win32' or platform_machine != 'ARM64'"
        for paquet in ("faster-whisper", "piper-tts", "miniaudio", "ddgs"):
            with self.subTest(paquet=paquet):
                self.assertRegex(projet, rf'"{paquet}>=[^"]*{exclusion}"')
        self.assertIn("cryptography==46.0.3 ; sys_platform == 'win32' and platform_machine == 'ARM64'",
                      projet)

    def test_requirements_exclut_brotli_sur_windows_arm64(self):
        # uv export ne propage pas l'exclusion par l'extra httpx[brotli] de ddgs :
        # sans cette correction, pip tenterait de compiler brotli sur Snapdragon.
        exigences = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for ligne in exigences.splitlines():
            if ligne.startswith(("brotli==", "brotlicffi==")):
                with self.subTest(ligne=ligne):
                    self.assertIn("platform_machine != 'ARM64' or sys_platform != 'win32'", ligne)


class ElevenLabsSansMiniaudioTest(unittest.TestCase):
    def test_pcm_brut_demande_quand_miniaudio_manque(self):
        from core import tts
        fournisseur = tts.ElevenLabsProvider.__new__(tts.ElevenLabsProvider)
        fournisseur.cle, fournisseur.voix, fournisseur.modele = "x", "voix", "eleven_flash_v2_5"
        fournisseur._voix_resolue = None
        reponse = MagicMock()
        reponse.__enter__.return_value.read.return_value = np.arange(5, dtype=np.int16).tobytes() + b"\x01"
        with patch.dict("sys.modules", {"miniaudio": None}), \
                patch.object(tts.urllib.request, "urlopen", return_value=reponse) as appel, \
                patch("core.budget.enregistrer_tts"):
            audio, taux = fournisseur.synthetiser("Bonjour")
        self.assertIn("output_format=pcm_24000", appel.call_args.args[0].full_url)
        self.assertEqual((audio.tolist(), taux), ([0, 1, 2, 3, 4], 24000))


if __name__ == "__main__":
    unittest.main()
