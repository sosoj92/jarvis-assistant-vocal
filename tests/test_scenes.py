"""Tests du brief quotidien déclenché par le poste principal."""
import unittest
from unittest.mock import patch

from tools import scenes


def _reglage(cle, defaut=None):
    valeurs = {
        "scenes.au_demarrage_actif": True,
        "scenes.spotify": False,
    }
    return valeurs.get(cle, defaut)


class ScenesTests(unittest.TestCase):
    @patch("tools.scenes._brief_hermes", return_value="Voici le brief du jour.")
    @patch("tools.scenes._lumieres_du_moment")
    @patch("tools.scenes._marquer_fait")
    @patch("tools.scenes._deja_fait_aujourdhui", return_value=False)
    @patch("tools.scenes.reglage", side_effect=_reglage)
    def test_premiere_connexion_prepare_le_brief_et_marque_la_date(
            self, _cfg, _deja, marquer, lumieres, _brief):
        statut, texte = scenes._preparer_scene_au_demarrage()

        self.assertEqual(statut, "Scène de démarrage jouée.")
        self.assertEqual(texte, "Voici le brief du jour.")
        marquer.assert_called_once_with()
        lumieres.assert_called_once_with()

    @patch("tools.scenes._marquer_fait")
    @patch("tools.scenes._deja_fait_aujourdhui", return_value=True)
    def test_reconnexion_du_meme_jour_ne_rejoue_rien(self, _deja, marquer):
        statut, texte = scenes._preparer_scene_au_demarrage()

        self.assertIn("déjà jouée aujourd'hui", statut)
        self.assertIsNone(texte)
        marquer.assert_not_called()

    def test_touche_media_est_envoyee_au_nouveau_pc(self):
        with patch("core.poste_distant.executer_principal",
                   return_value="Commande pause envoyée.") as distant:
            self.assertTrue(scenes._touche_media("play/pause media"))

        distant.assert_called_once_with(
            "controler_media", {"action": "pause"})


if __name__ == "__main__":
    unittest.main()
