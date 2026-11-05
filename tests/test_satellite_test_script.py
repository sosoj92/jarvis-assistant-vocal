"""scripts/satellite_test.py : la phrase de test ne passe plus dans -Command.

Panne : --texte "qu'est-ce que tu sais faire" fermait le litteral PowerShell
(erreur de syntaxe, CalledProcessError) ; un texte construit expres pouvait meme
executer du PowerShell. Le texte passe maintenant par l'entree standard.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("satellite_test_script_test",
                                               ROOT / "scripts" / "satellite_test.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


class GenererWavTest(unittest.TestCase):
    def _generer(self, texte, sortie):
        with patch.object(script.subprocess, "run") as lancer:
            self.assertEqual(script._generer_wav(texte, sortie), sortie)
        lancer.assert_called_once()
        return lancer.call_args

    def test_apostrophe_jamais_dans_la_commande(self):
        texte = "qu'est-ce que tu sais faire aujourd'hui ? l'été"
        sortie = r"C:\Users\l'essai\_sat_test_in.wav"
        appel = self._generer(texte, sortie)
        commande = appel.args[0]
        self.assertEqual(commande[:3], ["powershell", "-NoProfile", "-Command"])
        script_ps = commande[3]
        self.assertNotIn("qu'est", script_ps)
        self.assertNotIn("l'essai", script_ps)
        # Le texte arrive par stdin, en UTF-8 (accents compris), lu comme tel.
        self.assertEqual(appel.kwargs["input"], texte.encode("utf-8"))
        self.assertIn("[Console]::InputEncoding = [Text.Encoding]::UTF8", script_ps)
        self.assertIn("$s.Speak($t)", script_ps)
        # Le chemin de sortie passe par une variable d'environnement.
        self.assertEqual(appel.kwargs["env"]["JARVIS_SAT_TEST_WAV"], sortie)
        self.assertIn("$env:JARVIS_SAT_TEST_WAV", script_ps)
        self.assertTrue(appel.kwargs["check"])

    def test_texte_d_injection_reste_une_donnee(self):
        texte = "x'); Remove-Item C:\\important; ('"
        appel = self._generer(texte, "sortie.wav")
        self.assertNotIn("Remove-Item", appel.args[0][3])
        self.assertEqual(appel.kwargs["input"], texte.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
