"""Tests sans réseau du mode opérateur Astra."""
import unittest
from unittest.mock import patch

from core import registre
from tools import astra_pc


class AstraPcTests(unittest.TestCase):
    def test_extrait_les_deux_formulations_explicites(self):
        self.assertEqual(
            astra_pc.extraire_commande_explicite(
                "Jarvis, utilise Astra pour ouvrir les paramètres audio"),
            "ouvrir les paramètres audio")
        self.assertEqual(
            astra_pc.extraire_commande_explicite(
                "Prends le contrôle de mon PC pour ouvrir Spotify"),
            "ouvrir Spotify")
        self.assertIsNone(astra_pc.extraire_commande_explicite("Ouvre Spotify"))

    def test_invocation_sans_tache_est_reconnue(self):
        self.assertEqual(astra_pc.extraire_commande_explicite("Utilise Astra"), "")

    def test_variantes_explicites_astra(self):
        self.assertEqual(
            astra_pc.extraire_commande_explicite(
                "Passe par Astra pour ouvrir les paramètres audio"),
            "ouvrir les paramètres audio")
        self.assertEqual(
            astra_pc.extraire_commande_explicite(
                "Prends la main sur mon PC pour régler le volume"),
            "régler le volume")
        self.assertEqual(
            astra_pc.extraire_commande_explicite(
                "Ouvre les paramètres audio avec Astra"),
            "Ouvre les paramètres audio")

    def test_demandes_sensibles_sont_bloquees_avant_capture(self):
        for tache in (
                "achète ce produit", "tape mon mot de passe",
                "envoie un mail à Paul", "supprime ce dossier",
                "ouvre PowerShell et lance une commande"):
            with self.subTest(tache=tache):
                self.assertIsNotNone(astra_pc._raison_blocage(tache))
        self.assertIsNone(astra_pc._raison_blocage("ouvre les paramètres audio"))

    @patch("tools.astra_pc.time.sleep")
    @patch("tools.astra_pc._echap_presse", return_value=False)
    @patch("core.poste_distant.executer_principal", return_value=None)
    @patch("tools.astra_pc.cliquer_ecran", return_value="clic effectué")
    @patch("tools.astra_pc.capture_screen", return_value={
        "image": {"media_type": "image/jpeg", "data": "YWJj"}})
    @patch("tools.astra_pc.cloud.client_openai", return_value=object())
    @patch("tools.astra_pc.cloud.decider_action_vision")
    def test_boucle_utilise_astra_et_verifie_apres_action(
            self, decider, _client, _capture, cliquer, _distant, _echap, _sleep):
        decider.side_effect = [
            {"action": "cliquer", "x": 20, "y": 30},
            {"action": "termine", "message": "Réglage ouvert."},
        ]
        with patch("tools.astra_pc.reglage", side_effect=lambda cle, defaut=None: defaut):
            resultat = astra_pc.executer_controle("ouvre les paramètres audio")
        self.assertEqual(resultat, "Réglage ouvert.")
        self.assertEqual(decider.call_count, 2)
        cliquer.assert_called_once_with(20, 30, double=False)
        self.assertEqual(decider.call_args.kwargs["nom_modele"], "gpt-6-astra")
        self.assertTrue(decider.call_args.kwargs["qualite"])
        self.assertEqual(decider.call_args.kwargs["fournisseur_force"], "openai")

    def test_outil_est_n3_et_jamais_expose(self):
        outil = registre.get("controle_pc_astra")
        self.assertIsNotNone(outil)
        self.assertTrue(outil.confirmation)
        self.assertFalse(outil.mcp_expose)
        self.assertEqual(registre.niveau("controle_pc_astra"), "N3")


if __name__ == "__main__":
    unittest.main()
