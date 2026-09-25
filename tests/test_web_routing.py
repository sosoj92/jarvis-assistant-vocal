"""Tests du routage déterministe site web / application en mode local."""
import unittest
from unittest.mock import patch

from core import registre
from tools import apps, navigateur, systeme


class WebRoutingTests(unittest.TestCase):
    def test_browser_open_reste_expose_au_modele_local(self):
        noms = {schema["name"] for schema in registre.schemas_api(local_seulement=True)}
        self.assertIn("browser_open", noms)
        self.assertNotIn("browser_interact", noms)

    def test_noms_et_domaines_connus_sont_normalises(self):
        self.assertEqual(navigateur._resoudre_cible("Netflix"),
                         "https://www.netflix.com")
        self.assertEqual(navigateur._resoudre_cible("netflix.com"),
                         "https://netflix.com")
        self.assertEqual(navigateur._resoudre_cible("ouvre YouTube"),
                         "https://www.youtube.com")

    def test_ouvrir_application_reroute_netflix(self):
        with patch("tools.navigateur.browser_open", return_value="Netflix ouvert.") as ouvrir, \
                patch.object(systeme.os, "startfile") as startfile:
            resultat = systeme.ouvrir_application("netflix")

        self.assertEqual(resultat, "Netflix ouvert.")
        ouvrir.assert_called_once_with(url="netflix")
        startfile.assert_not_called()

    def test_utilitaire_windows_reste_une_application(self):
        with patch("core.poste_distant.executer_principal", return_value=None), \
                patch.object(systeme.os, "startfile") as startfile:
            resultat = systeme.ouvrir_application("calculatrice")

        self.assertEqual(resultat, "calculatrice lance.")
        startfile.assert_called_once_with("calc")

    def test_ouvertures_simples_contournent_astra(self):
        with patch("tools.apps._apps", return_value={"spotify": "spotify:"}):
            self.assertEqual(
                apps.router_ouverture_simple("Hey Jarvis, ouvre Spotify"),
                ("lancer_spotify", {}),
            )
        self.assertEqual(
            apps.router_ouverture_simple("Ouvre Netflix s'il te plaît"),
            ("browser_open", {"url": "netflix"}),
        )
        self.assertEqual(
            apps.router_ouverture_simple("Lance la calculatrice sur mon PC"),
            ("ouvrir_application", {"nom": "calculatrice"}),
        )
        self.assertEqual(
            apps.router_ouverture_simple("Tu peux m'ouvrir Spotify ?"),
            ("lancer_spotify", {}),
        )
        self.assertEqual(
            apps.router_ouverture_simple("Lance Spotify", piece="cuisine"),
            ("lancer_spotify", {"piece": "cuisine"}),
        )

    def test_variantes_naturelles_d_ouverture_simple(self):
        cas = {
            "Tu pourrais ouvrir Netflix": ("browser_open", {"url": "netflix"}),
            "Je veux que tu affiches YouTube": (
                "browser_open", {"url": "youtube"}),
            "Accède à Netflix": ("browser_open", {"url": "netflix"}),
            "Va sur YouTube": ("browser_open", {"url": "youtube"}),
            "Fais-moi démarrer la calculatrice": (
                "ouvrir_application", {"nom": "calculatrice"}),
        }
        for phrase, attendu in cas.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(apps.router_ouverture_simple(phrase), attendu)

    def test_ouverture_inconnue_utilise_le_lanceur_pas_astra(self):
        with patch("tools.apps._apps", return_value={}):
            self.assertEqual(
                apps.router_ouverture_simple("ouvre mon logiciel de montage"),
                ("launch_app", {"nom": "mon logiciel de montage"}),
            )

    def test_demandes_complexes_ou_non_imperatives_restent_au_modele(self):
        for phrase in (
                "Ouvre Spotify et cherche ma playlist",
                "Ouvre Netflix puis lance ma série",
                "Est-ce que Spotify est ouvert ?",
                "Ouvre ce fichier",
                "Va dormir"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(apps.router_ouverture_simple(phrase))


if __name__ == "__main__":
    unittest.main()
