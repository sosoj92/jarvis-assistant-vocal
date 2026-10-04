"""Releve envoye aux postes pour leur fenetre Jarvis : non sensible et tolerant aux pannes."""
import unittest
from unittest.mock import patch

from core import satellite


class StatutAffichageTest(unittest.TestCase):
    def test_releve_complet(self):
        etat_budget = {"total_jour": 0.4249, "plafond_jour": 3.0, "pct_jour": 0.14163}
        with patch("hud._libelle_modele_actif", return_value="OpenAI · gpt-5.6-terra"), \
                patch("core.routage.mode_actuel", return_value="hybride"), \
                patch("core.budget.etat", return_value=etat_budget), \
                patch("tools.deleguer_a_hermes.taches_en_cours", return_value=2), \
                patch("tools.deleguer_a_hermes._TOKENS", 5000):
            statut = satellite.statut_affichage()
        self.assertEqual(statut, {
            "modele": "OpenAI · gpt-5.6-terra", "routage": "hybride",
            "budget": {"cout": 0.42, "plafond": 3.0, "pct": 0.142},
            "hermes": {"taches": 2, "tokens": 5000}})

    def test_une_partie_en_panne_n_empeche_pas_les_autres(self):
        with patch("hud._libelle_modele_actif", side_effect=RuntimeError("cloud")), \
                patch("core.routage.mode_actuel", return_value="local"), \
                patch("core.budget.etat", side_effect=OSError("fichier")):
            statut = satellite.statut_affichage()
        self.assertEqual(statut["routage"], "local")
        self.assertNotIn("modele", statut)
        self.assertNotIn("budget", statut)

    def test_aucune_cle_ni_secret_dans_le_releve(self):
        statut = satellite.statut_affichage()
        texte = repr(statut).lower()
        for interdit in ("sk-", "api_key", "token\": \"", "mot_de_passe"):
            self.assertNotIn(interdit, texte)


if __name__ == "__main__":
    unittest.main()
