"""Tests sans réseau du mode opérateur Astra."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import registre
from tools import astra_pc, ecran

# Repère de la capture plein écran vue par Astra (1600x900 réduit à 1568x882).
_GEO_ASTRA = {"moniteur": {"left": 0, "top": 0, "width": 1600, "height": 900},
              "largeur": 1568, "hauteur": 882}
# Repère d'une lecture de la fenêtre active faite entre-temps.
_GEO_FENETRE = {"moniteur": {"left": 100, "top": 100, "width": 1200, "height": 800},
                "largeur": 1200, "hauteur": 800}


def _faux_mss():
    """Module mss simulé : un écran 1600x900, aucune vraie capture."""
    module = MagicMock()
    sct = module.mss.return_value.__enter__.return_value
    sct.monitors = [dict(_GEO_ASTRA["moniteur"]), dict(_GEO_ASTRA["moniteur"])]
    sct.grab.side_effect = lambda zone: SimpleNamespace(
        size=(zone["width"], zone["height"]),
        rgb=bytes(zone["width"] * zone["height"] * 3))
    return module


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

    def test_paraphrases_sensibles_sont_bloquees(self):
        for tache in (
                "paie la facture", "paye la facture",
                "réserve une table chez Luigi", "reserve une table chez Luigi",
                "réponds à Marie sur WhatsApp que j’arrive",
                "commande-moi une pizza sur Uber Eats",
                "valide le panier Amazon", "valide la commande",
                "vide la corbeille",
                "désactive l’antivirus Windows Defender",
                "désactive le pare-feu Windows",
                "ouvre le terminal Windows", "lance cmd",
                "ouvre le terminal et tape shutdown /s /t 0",
                "éteins l'ordinateur", "mets mon numéro de carte",
                "partage ce document avec Paul",
                "envoie-lui un message WhatsApp", "réponds au mail de Paul",
                "lance setup.exe"):
            with self.subTest(tache=tache):
                self.assertIsNotNone(astra_pc._raison_blocage(tache))

    def test_taches_legitimes_restent_acceptees(self):
        for tache in (
                "ouvre les paramètres audio", "régler le volume",
                "ouvre la vidéo YouTube", "appaire mes écouteurs Bluetooth",
                "ouvre les paramètres de la carte graphique",
                "lis mes messages Discord", "ouvre Spotify",
                "ouvre OBS sur le deuxième écran"):
            with self.subTest(tache=tache):
                self.assertIsNone(astra_pc._raison_blocage(tache))

    @patch("tools.astra_pc.cloud.decider_action_vision")
    @patch("tools.astra_pc.capture_screen")
    @patch("tools.astra_pc.cloud.client_openai", return_value=object())
    @patch("core.routage.mode_actuel", return_value="local")
    def test_mode_local_refuse_avant_toute_capture(
            self, _mode, _client, capture, decider):
        with patch("tools.astra_pc.reglage", side_effect=lambda cle, defaut=None: defaut):
            resultat = astra_pc.executer_controle("ouvre mes mails")
        self.assertIn("besoin du cloud", resultat)
        capture.assert_not_called()
        decider.assert_not_called()

    def test_prompt_traite_le_texte_affiche_comme_non_fiable(self):
        prompt = astra_pc._SYSTEME_OPERATEUR.lower()
        self.assertIn("non fiable", prompt)
        self.assertIn("adresse web", prompt)

    def test_taper_retire_les_caracteres_de_controle(self):
        faux_clavier = MagicMock()
        with patch.dict(sys.modules, {"keyboard": faux_clavier}):
            astra_pc._taper("https://site.invalid/?d=secret\n\b\rfin")
        texte = faux_clavier.write.call_args.args[0]
        self.assertEqual(texte, "https://site.invalid/?d=secretfin")
        self.assertFalse(any(ord(c) < 32 for c in texte))

    def test_ecran_secondaire_est_selectionne_explicitement(self):
        self.assertEqual(astra_pc._ecran_cible("ouvre OBS sur le deuxième écran"), 2)
        self.assertEqual(astra_pc._ecran_cible("regarde l'écran secondaire"), 2)
        self.assertEqual(astra_pc._ecran_cible("ouvre Spotify"), 0)

    @patch("core.routage.mode_actuel", return_value="hybride")
    @patch("tools.astra_pc.time.sleep")
    @patch("tools.astra_pc._echap_presse", return_value=False)
    @patch("core.poste_distant.executer_principal", return_value=None)
    @patch("tools.astra_pc.cliquer_ecran", return_value="clic effectué")
    @patch("tools.astra_pc.capture_screen", return_value={
        "image": {"media_type": "image/jpeg", "data": "YWJj"}})
    @patch("tools.astra_pc.cloud.client_openai", return_value=object())
    @patch("tools.astra_pc.cloud.decider_action_vision")
    def test_boucle_utilise_astra_et_verifie_apres_action(
            self, decider, _client, _capture, cliquer, _distant, _echap, _sleep,
            _mode):
        decider.side_effect = [
            {"action": "cliquer", "x": 20, "y": 30},
            {"action": "termine", "message": "Réglage ouvert."},
        ]
        with patch("tools.astra_pc.reglage", side_effect=lambda cle, defaut=None: defaut):
            resultat = astra_pc.executer_controle("ouvre les paramètres audio")
        self.assertEqual(resultat, "Réglage ouvert.")
        self.assertEqual(decider.call_count, 2)
        cliquer.assert_called_once_with(20, 30, double=False)
        _capture.assert_called_with(ecran=0)
        self.assertEqual(decider.call_args.kwargs["nom_modele"], "gpt-6-astra")
        self.assertTrue(decider.call_args.kwargs["qualite"])
        self.assertEqual(decider.call_args.kwargs["fournisseur_force"], "openai")

    def test_capture_renvoie_son_repere_et_le_clic_peut_le_figer(self):
        from tools import souris
        ancienne = ecran._DERNIERE
        try:
            with (patch.dict(sys.modules, {"mss": _faux_mss()}),
                  patch("core.poste_distant.executer_outil_principal",
                        return_value=None),
                  patch.object(ecran, "_fenetre_active",
                               return_value=dict(_GEO_FENETRE["moniteur"]))):
                plein = ecran.capture_screen()
                # Lecture d'écran concurrente (autre pièce) pendant la réflexion.
                ecran.capture_screen(cible="fenetre_active")
            self.assertEqual(plein["geometrie"], _GEO_ASTRA)
            self.assertEqual(ecran.derniere_capture(), _GEO_FENETRE)
            # Sans repère figé, le clic suivrait la dernière capture.
            self.assertEqual(souris._vers_ecran(800, 400), (900, 500))
            with ecran.geometrie_figee(plein["geometrie"]):
                self.assertEqual(souris._vers_ecran(800, 400), (816, 408))
            # La capture la plus récente reste la référence ensuite.
            self.assertEqual(ecran.derniere_capture(), _GEO_FENETRE)
            # Une géométrie invalide ne change rien.
            with ecran.geometrie_figee({"moniteur": {}, "largeur": 0}):
                self.assertEqual(ecran.derniere_capture(), _GEO_FENETRE)
        finally:
            ecran._DERNIERE = ancienne

    @patch("core.routage.mode_actuel", return_value="hybride")
    @patch("tools.astra_pc.time.sleep")
    @patch("tools.astra_pc._echap_presse", return_value=False)
    @patch("core.poste_distant.executer_principal", return_value=None)
    @patch("tools.astra_pc.capture_screen", return_value={
        "image": {"media_type": "image/jpeg", "data": "YWJj"},
        "geometrie": _GEO_ASTRA})
    @patch("tools.astra_pc.cloud.client_openai", return_value=object())
    @patch("tools.astra_pc.cloud.decider_action_vision")
    def test_clic_astra_utilise_sa_capture_malgre_une_capture_concurrente(
            self, decider, _client, _capture, _distant, _echap, _sleep, _mode):
        decider.side_effect = [
            {"action": "cliquer", "x": 800, "y": 400},
            {"action": "termine", "message": "Fait."},
        ]
        vus = []

        def cliquer(x, y, double=False):
            vus.append(ecran.derniere_capture())
            return "clic effectué"

        ancienne = ecran._DERNIERE
        ecran._DERNIERE = dict(_GEO_FENETRE)
        try:
            with (patch("tools.astra_pc.cliquer_ecran", side_effect=cliquer),
                  patch("tools.astra_pc.reglage",
                        side_effect=lambda cle, defaut=None: defaut)):
                self.assertEqual(astra_pc.executer_controle(
                    "ouvre les paramètres audio"), "Fait.")
            self.assertEqual(vus, [_GEO_ASTRA])
            self.assertEqual(ecran.derniere_capture(), _GEO_FENETRE)
        finally:
            ecran._DERNIERE = ancienne

    def test_action_distante_porte_le_repere_de_la_capture(self):
        with patch("core.poste_distant.executer_principal",
                   return_value="clic distant") as distant:
            resultat = astra_pc._executer_action(
                {"action": "cliquer", "x": 1, "y": 2,
                 "geometrie": {"forge": True}}, _GEO_ASTRA)
        self.assertEqual(resultat, "clic distant")
        charge = distant.call_args.args[1]
        self.assertEqual(charge["geometrie"], _GEO_ASTRA)
        with patch("core.poste_distant.executer_principal",
                   return_value="ok") as distant:
            astra_pc._executer_action({"action": "attendre",
                                       "geometrie": {"forge": True}})
        self.assertNotIn("geometrie", distant.call_args.args[1])

    def test_outil_est_n3_et_jamais_expose(self):
        outil = registre.get("controle_pc_astra")
        self.assertIsNotNone(outil)
        self.assertTrue(outil.confirmation)
        self.assertFalse(outil.mcp_expose)
        self.assertEqual(registre.niveau("controle_pc_astra"), "N3")


if __name__ == "__main__":
    unittest.main()
