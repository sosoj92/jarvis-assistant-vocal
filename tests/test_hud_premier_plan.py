"""Fenetre du HUD au premier plan au « Hey Jarvis » : regles, garde-fous et repli."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import hud

ROOT = Path(__file__).resolve().parents[1]


class FenetreTest(unittest.TestCase):
    def setUp(self):
        self._mode = hud._MODE_FENETRE
        self._ouverture = hud._DERNIERE_OUVERTURE

    def tearDown(self):
        hud._MODE_FENETRE = self._mode
        hud._DERNIERE_OUVERTURE = self._ouverture

    def test_fenetre_dediee_sans_onglets(self):
        self.assertEqual(
            hud.commande_fenetre_app("msedge.exe"),
            ["msedge.exe", f"--app=http://127.0.0.1:{hud.PORT}/"],
        )

    def test_titre_cherche_est_celui_de_la_page(self):
        page = (ROOT / "hud.html").read_text(encoding="utf-8")
        self.assertIn(f"<title>{hud.TITRE_FENETRE}</title>", page)

    def test_hors_windows_rien_ne_se_passe(self):
        with patch.object(hud.sys, "platform", "linux"):
            self.assertFalse(hud.mettre_au_premier_plan())
            self.assertEqual(hud.trouver_fenetres(), [])

    def test_fenetre_fermee_rouverte_une_seule_fois_par_minute(self):
        hud._MODE_FENETRE = "app"
        hud._DERNIERE_OUVERTURE = 0.0

        def ouvrir():
            hud._DERNIERE_OUVERTURE = time.monotonic()

        with patch.object(hud.sys, "platform", "win32"), \
                patch.object(hud, "trouver_fenetres", return_value=[]), \
                patch.object(hud, "ouvrir_fenetre", side_effect=ouvrir) as ouverture:
            self.assertFalse(hud.mettre_au_premier_plan())
            self.assertFalse(hud.mettre_au_premier_plan())
        ouverture.assert_called_once()

    def test_en_mode_onglet_aucune_fenetre_n_est_rouverte(self):
        hud._MODE_FENETRE = "navigateur"
        hud._DERNIERE_OUVERTURE = 0.0
        with patch.object(hud.sys, "platform", "win32"), \
                patch.object(hud, "trouver_fenetres", return_value=[]), \
                patch.object(hud, "ouvrir_fenetre") as ouverture:
            hud.mettre_au_premier_plan()
        ouverture.assert_not_called()

    def test_jamais_par_dessus_un_plein_ecran(self):
        user32 = MagicMock()
        with patch.object(hud.sys, "platform", "win32"), \
                patch.object(hud, "trouver_fenetres", return_value=[1234]), \
                patch.object(hud, "_user32", return_value=user32), \
                patch.object(hud, "_plein_ecran_au_premier_plan", return_value=True):
            self.assertFalse(hud.mettre_au_premier_plan())
        user32.SetWindowPos.assert_not_called()

    def test_mise_devant_sans_activer_ni_epingler(self):
        user32 = MagicMock()
        user32.IsIconic.return_value = True
        with patch.object(hud.sys, "platform", "win32"), \
                patch.object(hud, "trouver_fenetres", return_value=[1234]), \
                patch.object(hud, "_user32", return_value=user32), \
                patch.object(hud, "_plein_ecran_au_premier_plan", return_value=False):
            self.assertTrue(hud.mettre_au_premier_plan())
        user32.ShowWindow.assert_called_once_with(1234, 4)          # restaure sans activer
        positions = [appel.args for appel in user32.SetWindowPos.call_args_list]
        self.assertEqual([p[1] for p in positions], [-1, -2])      # devant, puis non epinglee
        self.assertTrue(all(p[6] & 0x0010 for p in positions))     # SWP_NOACTIVATE

    def test_placement_sur_la_zone_utile_de_l_ecran_demande(self):
        user32 = MagicMock()
        user32.IsIconic.return_value = False
        zones = [(0, 0, 3440, 1400), (-1080, 0, 0, 1880), (875, -1080, 2795, -40)]
        with patch.object(hud, "zones_ecrans", return_value=zones), \
                patch.object(hud, "_user32", return_value=user32):
            self.assertTrue(hud.placer_sur_ecran(1234, 2))
            self.assertFalse(hud.placer_sur_ecran(1234, 7))      # ecran inexistant : rien
        args = user32.SetWindowPos.call_args.args
        self.assertEqual(args[2:6], (875, -1080, 1920, 1040))
        self.assertTrue(args[6] & 0x0010)                         # SWP_NOACTIVATE

    def test_ecran_memorise_au_demarrage(self):
        ancien_serveur, ancien_ecran = hud._SERVEUR, hud._ECRAN
        try:
            hud._SERVEUR = None
            with patch.object(hud, "_Serveur"), patch.object(hud.threading, "Thread"):
                hud.demarrer(ouvrir=False, fenetre="app", ecran="2")
            self.assertEqual(hud._ECRAN, 2)
        finally:
            hud._SERVEUR, hud._ECRAN = ancien_serveur, ancien_ecran

    @unittest.skipUnless(sys.platform == "win32", "API des fenetres Windows")
    def test_recherche_reelle_en_lecture_seule(self):
        self.assertEqual(hud.trouver_fenetres("titre-improbable-signal-xyz-0001"), [])


class JarvisPrincipalTest(unittest.TestCase):
    def test_le_mot_d_activation_declenche_la_mise_devant(self):
        # jarvis14 est trop lourd a importer (micro, Whisper) : controle statique.
        source = (ROOT / "jarvis14.py").read_text(encoding="utf-8")
        self.assertIn('config.reglage("hud.premier_plan_au_reveil", True)', source)
        self.assertIn('args=("mettre_au_premier_plan",)', source)
        self.assertIn('config.reglage("hud.fenetre", "app")', source)


if __name__ == "__main__":
    unittest.main()
