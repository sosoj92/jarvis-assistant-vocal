"""Couleurs de la lumière vidéo amaran, sans ESP32 réel."""
import unittest
from unittest.mock import call, patch

from tools import amaran


class CouleursAmaranTests(unittest.TestCase):
    def setUp(self):
        configure = patch("tools.amaran._configure", return_value=True)
        configure.start()
        self.addCleanup(configure.stop)
        post = patch("tools.amaran._post")     # aucune requête vers l'ESP32
        self.post = post.start()
        self.addCleanup(post.stop)

    def test_formes_feminines_reconnues(self):
        cas = {"bleue": 220, "Verte": 120, "violette": 275}
        for couleur, teinte in cas.items():
            with self.subTest(couleur=couleur):
                self.post.reset_mock()
                message = amaran.controler_amaran(couleur=couleur)
                self.post.assert_called_once_with(
                    "/lights/all/hsi", {"intensity": 80, "hue": teinte, "sat": 100})
                self.assertEqual(message, f"C'est fait : key light couleur {couleur}.")

    def test_couleur_inconnue_n_envoie_rien(self):
        message = amaran.controler_amaran(couleur="bleu ciel")
        self.post.assert_not_called()
        self.assertTrue(message.startswith("Je ne connais pas la couleur « bleu ciel »"))
        self.assertNotIn("C'est fait", message)

    def test_couleur_inconnue_avec_temperature_reste_en_kelvin(self):
        message = amaran.controler_amaran(couleur="blanc chaud", temperature=3200)
        self.post.assert_called_once_with(
            "/lights/all/cct", {"intensity": 80, "kelvin": 3200, "gm": 0})
        self.assertEqual(message, "C'est fait : key light 3200 kelvin.")

    def test_couleur_connue_inchangee(self):
        amaran.controler_amaran(couleur="Bleu", intensite=50)
        self.post.assert_called_once_with(
            "/lights/all/hsi", {"intensity": 50, "hue": 220, "sat": 100})

    def test_blanche_avec_temperature_passe_en_cct(self):
        message = amaran.controler_amaran(couleur="blanche", temperature=5600)
        self.assertEqual(self.post.call_args_list, [
            call("/lights/all/cct", {"intensity": 80, "kelvin": 5600, "gm": 0})])
        self.assertEqual(message, "C'est fait : key light 5600 kelvin.")

    def test_blanc_sans_temperature_repasse_en_cct(self):
        for couleur in ("blanc", "blanche"):
            with self.subTest(couleur=couleur):
                self.post.reset_mock()
                message = amaran.controler_amaran(couleur=couleur)
                # Jamais /lights/all/on seul : la lampe resterait de sa couleur.
                self.assertEqual(self.post.call_args_list, [
                    call("/lights/all/cct", {"intensity": 80, "kelvin": 5600, "gm": 0})])
                self.assertEqual(message, "C'est fait : key light couleur blanc.")

    def test_blanc_avec_intensite_change_aussi_la_teinte(self):
        amaran.controler_amaran(couleur="blanc", intensite=40)
        self.post.assert_called_once_with(
            "/lights/all/cct", {"intensity": 40, "kelvin": 5600, "gm": 0})


if __name__ == "__main__":
    unittest.main()
