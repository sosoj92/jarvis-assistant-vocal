"""Tests sans réseau des bascules modèle/mode/voix du panneau local."""
import unittest
from unittest.mock import patch

from core import panneau


class PanneauSwitchTests(unittest.TestCase):
    def test_hybride_sans_modele_choisit_le_defaut_economique(self):
        def lire(cle, default=None):
            return "cle-factice" if cle == "openai.cle" else default

        with patch.object(panneau, "reglage", side_effect=lire), \
                patch.object(panneau, "definir") as ecrire, \
                patch("core.routage.definir_mode", return_value=True):
            resultat = panneau._definir_actif(
                "cloud", "", profil="hybride", fournisseur="openai")

        self.assertTrue(resultat["ok"])
        ecrire.assert_any_call("openai.modele", "gpt-5.6-luna")

    def test_gpt6_qualite_change_provider_mode_et_modele(self):
        def lire(cle, default=None):
            return "cle-factice" if cle == "openai.cle" else default

        with patch.object(panneau, "reglage", side_effect=lire), \
                patch.object(panneau, "definir") as ecrire, \
                patch("core.routage.definir_mode", return_value=True) as changer_mode:
            resultat = panneau._definir_actif(
                "cloud", "gpt-6-astra", profil="qualite", fournisseur="openai")

        self.assertTrue(resultat["ok"])
        ecrire.assert_any_call("cloud.fournisseur", "openai")
        ecrire.assert_any_call("openai.modele_qualite", "gpt-6-astra")
        changer_mode.assert_called_once_with("qualite", raison="panneau")

    def test_openai_sans_cle_est_refuse_sans_casser_le_mode_actuel(self):
        with patch.object(panneau, "reglage", return_value=""), \
                patch.object(panneau, "definir") as ecrire:
            resultat = panneau._definir_actif(
                "cloud", "gpt-5.6-terra", profil="hybride", fournisseur="openai")

        self.assertFalse(resultat["ok"])
        ecrire.assert_not_called()

    def test_switch_elevenlabs_reinitialise_le_tts(self):
        with patch("core.config.definir") as ecrire, \
                patch("core.tts.reinitialiser") as reinitialiser:
            resultat = panneau._definir_reglage("tts.moteur", "elevenlabs")

        self.assertTrue(resultat["ok"])
        ecrire.assert_called_once_with("tts.moteur", "elevenlabs")
        reinitialiser.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
