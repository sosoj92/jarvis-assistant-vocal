"""Navigateur pilote : reconnexion quand Chrome a ete ferme, et annonce de
fermeture d'onglets fidele a l'action. Aucun Chrome reel."""
import unittest
from unittest.mock import MagicMock, patch

from core import registre

registre.charger_outils()

from tools import navigateur  # noqa: E402


class ConnexionTest(unittest.TestCase):
    def setUp(self):
        self._ancien = navigateur._BROWSER

    def tearDown(self):
        navigateur._BROWSER = self._ancien

    def test_navigateur_deconnecte_remplace(self):
        mort = MagicMock()
        mort.is_connected.return_value = False
        neuf = MagicMock()
        navigateur._BROWSER = mort

        def tenter(_port):
            navigateur._BROWSER = neuf
            return neuf

        with patch.object(navigateur, "_tenter_cdp", side_effect=tenter) as tenter_cdp, \
                patch.object(navigateur, "_lancer_chrome") as lancer:
            self.assertIs(navigateur._connexion(auto=False), neuf)
        tenter_cdp.assert_called_once()
        lancer.assert_not_called()
        mort.close.assert_called_once()
        self.assertIs(navigateur._BROWSER, neuf)

    def test_navigateur_vivant_garde(self):
        vivant = MagicMock()
        vivant.is_connected.return_value = True
        navigateur._BROWSER = vivant
        with patch.object(navigateur, "_tenter_cdp") as tenter_cdp:
            self.assertIs(navigateur._connexion(auto=False), vivant)
        tenter_cdp.assert_not_called()

    def test_deconnecte_sans_chrome_renvoie_none(self):
        mort = MagicMock()
        mort.is_connected.side_effect = RuntimeError("canal ferme")
        navigateur._BROWSER = mort
        with patch.object(navigateur, "_tenter_cdp", return_value=None):
            self.assertIsNone(navigateur._connexion(auto=False))
        self.assertIsNone(navigateur._BROWSER)


class AnnonceFermetureTest(unittest.TestCase):
    def test_annonce_sans_interroger_le_navigateur(self):
        annonce = registre.get("browser_close_tabs").annonce
        with patch.object(navigateur, "_connexion", side_effect=AssertionError("pas de navigateur")):
            self.assertEqual(annonce({}), "Je ferme l'onglet actif.")
            self.assertEqual(annonce({"filtre": "  "}), "Je ferme l'onglet actif.")
            self.assertEqual(annonce({"filtre": "YouTube"}),
                             "Je ferme les onglets qui contiennent « YouTube ».")


if __name__ == "__main__":
    unittest.main()
