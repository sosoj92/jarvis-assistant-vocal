"""Tests des profils cloud cout/qualite, sans appel reseau."""
import unittest
from unittest.mock import patch

from core import cloud


class CloudProfileTests(unittest.TestCase):
    def test_openai_hybride_utilise_luna_par_defaut(self):
        with patch.object(cloud, "fournisseur", return_value="openai"), \
                patch.object(cloud, "reglage", side_effect=lambda _k, default=None: default):
            self.assertEqual(cloud.modele(), "gpt-5.6-luna")

    def test_openai_qualite_reste_sur_astra(self):
        with patch.object(cloud, "fournisseur", return_value="openai"), \
                patch.object(cloud, "reglage", side_effect=lambda _k, default=None: default):
            self.assertEqual(cloud.modele(qualite=True), "gpt-6-astra")

    def test_claude_hybride_utilise_haiku_par_defaut(self):
        with patch.object(cloud, "fournisseur", return_value="anthropic"), \
                patch.object(cloud, "reglage", side_effect=lambda _k, default=None: default):
            self.assertEqual(cloud.modele(), "claude-haiku-4-5")

    def test_modele_explicitement_configure_reste_prioritaire(self):
        def lire(cle, default=None):
            return "gpt-5.6-terra" if cle == "openai.modele" else default

        with patch.object(cloud, "fournisseur", return_value="openai"), \
                patch.object(cloud, "reglage", side_effect=lire):
            self.assertEqual(cloud.modele(), "gpt-5.6-terra")


if __name__ == "__main__":
    unittest.main()
