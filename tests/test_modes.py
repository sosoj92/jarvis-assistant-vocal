"""Modes lumineux : compte rendu honnête et modes sur mesure, sans pont Hue réel."""
import unittest
from unittest.mock import patch

from tools import lumieres, modes


def _config_modes(sur_mesure):
    return lambda cle, defaut=None: sur_mesure if cle == "modes" else defaut


class CompteRenduModesTests(unittest.TestCase):
    def setUp(self):
        # Aucun mode sur mesure du config.yaml local, aucune pièce Hue réelle.
        for patcheur in (patch("tools.modes.reglage", side_effect=_config_modes({})),
                         patch.dict(lumieres._PIECES_HUE,
                                    {"salon": ("1", "Salon")}, clear=True)):
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def test_hue_injoignable_n_est_pas_annonce_comme_reussi(self):
        with patch("tools.lumieres._hue_requete",
                   side_effect=OSError("timeout simule")):
            message = modes.activer("off")
            cle, echecs = modes.appliquer("off")

        self.assertNotIn("active.", message)
        self.assertIn("non applique", message)
        self.assertIn("Hue injoignable", message)
        self.assertEqual(cle, "off")
        self.assertEqual(len(echecs), 1)
        self.assertTrue(echecs[0].startswith("Hue injoignable"))

    def test_echec_partiel_est_signale(self):
        with patch("tools.lumieres._hue_requete", return_value=[{"success": {}}]), \
                patch.dict(lumieres._PIECES_HUE, {}, clear=True):
            message = modes.activer("film")
        # « toutes » s'éteint, mais le salon est inconnu du pont.
        self.assertEqual(message, "Mode film partiellement applique — "
                                  "Piece inconnue : salon.")

    def test_chemin_nominal_inchange(self):
        with patch("tools.lumieres._hue_requete",
                   return_value=[{"success": {}}]) as hue:
            self.assertEqual(modes.activer("off"), "Mode off active.")
            self.assertEqual(modes.activer("film"), "Mode film active.")
            self.assertEqual(modes.appliquer("retour"), ("retour", []))
        self.assertEqual(hue.call_args_list[0].args,
                         ("groups/0/action", "PUT", {"on": False}))

    def test_mode_inconnu_inchange(self):
        cle, echecs = modes.appliquer("disco")
        self.assertIsNone(cle)
        self.assertEqual(echecs, [])
        self.assertTrue(modes.activer("disco").startswith("Mode inconnu : disco."))


class ModesSurMesureTests(unittest.TestCase):
    SUR_MESURE = {
        "office": [{"piece": "bureau", "allumer": True, "luminosite": 70}],
        "soirée cinéma rouge": [{"piece": "salon", "couleur": "rouge"}],
    }

    def setUp(self):
        patcheur = patch("tools.modes.reglage",
                         side_effect=_config_modes(self.SUR_MESURE))
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def test_mode_sur_mesure_n_est_pas_detourne_vers_un_preset(self):
        cas = {
            "office": "office",
            "mode office": "office",
            "Active le mode office": "office",
            "soirée cinéma rouge": "soirée cinéma rouge",
        }
        for phrase, attendu in cas.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(modes._resoudre(phrase), attendu)

    def test_intentions_libres_toujours_reconnues(self):
        cas = {
            "tout eteindre": "off",
            "je m'en vais": "off",
            "mode film": "film",
            "je suis rentree": "retour",
            "stream": "stream",
        }
        for phrase, attendu in cas.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(modes._resoudre(phrase), attendu)

    def test_activer_office_n_eteint_pas_la_maison(self):
        with patch("tools.lumieres.allumer_lumiere",
                   return_value="Bureau : lumiere allumee.") as allumer, \
                patch("tools.lumieres.regler_luminosite",
                      return_value="Bureau a 70 pour cent.") as luminosite:
            message = modes.activer("mode office")

        self.assertEqual(message, "Mode office active.")
        allumer.assert_called_once_with("bureau", True)
        luminosite.assert_called_once_with("bureau", 70)


if __name__ == "__main__":
    unittest.main()
