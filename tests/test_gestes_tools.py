"""Tests des commandes vocales de gestes, sans ouvrir la webcam."""
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from core import gestes as gestes_core
from tools.gestes import (demande_calibration_gestes, demande_demo_gestes,
                           demande_mode_regard, demande_mode_visio,
                           lancer_calibration_gestes, lancer_demo_gestes,
                           lancer_mode_regard, quitter_mode_regard)


class GestesToolsTests(unittest.TestCase):
    def test_ordre_explicite_est_reconnu(self):
        self.assertTrue(demande_calibration_gestes(
            "Lance l'appli calibration geste"))
        self.assertTrue(demande_calibration_gestes(
            "Peux-tu ouvrir la calibration des gestes ?"))
        self.assertTrue(demande_calibration_gestes(
            "Teste la reconnaissance de mes mains"))

    def test_question_ou_discussion_n_ouvre_pas_la_camera(self):
        self.assertFalse(demande_calibration_gestes(
            "Est-ce que la calibration des gestes existe ?"))
        self.assertFalse(demande_calibration_gestes(
            "Je parle de la reconnaissance des mains dans ma vidéo"))

    def test_ordre_demo_visible_est_reconnu(self):
        self.assertTrue(demande_demo_gestes("Ouvre la démo des gestes"))
        self.assertTrue(demande_demo_gestes(
            "Lance les gestes visibles pour ma vidéo"))
        self.assertFalse(demande_demo_gestes(
            "Je parle des gestes dans ma vidéo"))

    def test_mode_visio_est_une_commande_directe(self):
        self.assertIs(demande_mode_visio(
            "Hey Jarvis, passe en mode visio"), True)
        self.assertIs(demande_mode_visio("Active le mode visio"), True)
        self.assertIs(demande_mode_visio(
            "Active le contrôle avec les yeux"), None)
        self.assertIs(demande_mode_visio("Quitte le mode visio"), False)
        self.assertIs(demande_mode_visio(
            "Coupe le contrôle du regard"), None)
        self.assertIs(demande_mode_visio("Je parle du mode visio"), None)

    def test_variantes_du_mode_vision(self):
        self.assertIs(demande_mode_visio("Passe en mode vision"), True)
        self.assertIs(demande_mode_visio(
            "Tu pourrais activer le contrôle gestuel"), True)
        self.assertIs(demande_mode_visio("Active les gestes"), True)
        self.assertIs(demande_mode_visio(
            "Je veux que tu actives les gestes"), True)
        self.assertIs(demande_mode_visio("Regarde mes mains"), True)
        self.assertIs(demande_mode_visio(
            "Arrête le contrôle par gestes"), False)
        self.assertIs(demande_mode_visio("Coupe le mode vision"), False)
        self.assertIs(demande_mode_visio("Coupe les gestes"), False)

    def test_mode_regard_est_separe_du_mode_visio(self):
        self.assertIs(demande_mode_regard(
            "Hey Jarvis, passe en mode regard"), True)
        self.assertIs(demande_mode_regard(
            "Active le contrôle avec les yeux"), True)
        self.assertIs(demande_mode_regard(
            "Coupe le contrôle du regard"), False)
        self.assertIs(demande_mode_regard(
            "Je parle du suivi des yeux"), None)

    def test_variantes_du_mode_regard(self):
        self.assertIs(demande_mode_regard(
            "Contrôle la souris avec mes yeux"), True)
        self.assertIs(demande_mode_regard(
            "Quitte le contrôle oculaire"), False)
        self.assertIs(demande_mode_regard(
            "Arrête le suivi des yeux"), False)

    def test_variantes_de_recalibrage(self):
        self.assertTrue(demande_calibration_gestes(
            "Refais la calibration de mes mains"))
        self.assertTrue(demande_calibration_gestes(
            "Recalibre les gestes de la webcam"))

    def test_commande_vocale_ouvre_la_calibration_locale(self):
        with patch("core.gestes.lancer_calibration",
                   return_value="Calibration ouverte.") as lancer:
            self.assertEqual(lancer_calibration_gestes(), "Calibration ouverte.")
        lancer.assert_called_once_with()

    def test_commande_vocale_ouvre_la_demo_active(self):
        with patch("core.gestes.demarrer_demo",
                   return_value="Démo active.") as lancer:
            self.assertEqual(lancer_demo_gestes(), "Démo active.")
        lancer.assert_called_once_with()

    def test_mode_visio_prepare_application_camera_avant_tracker(self):
        appels = Mock()
        appels.camera.return_value = (True, "")
        appels.tracker.return_value = "Démo active."
        with (patch.object(gestes_core, "actif", side_effect=[False, True]),
              patch.object(gestes_core, "_demarrer_application_camera",
                           new=appels.camera),
              patch.object(gestes_core, "_demarrer_tracker",
                           new=appels.tracker)):
            reponse = gestes_core.demarrer_demo()
        self.assertEqual(reponse, "Démo active.")
        self.assertEqual(appels.mock_calls,
                         [call.camera(), call.tracker(demo=True)])

    def test_mode_visio_ne_lance_pas_tracker_si_camera_absente(self):
        with (patch.object(gestes_core, "actif", return_value=False),
              patch.object(gestes_core, "_demarrer_application_camera",
                           return_value=(False, "Caméra absente.")),
              patch.object(gestes_core, "_demarrer_tracker") as tracker):
            reponse = gestes_core.demarrer_demo()
        self.assertEqual(reponse, "Caméra absente.")
        tracker.assert_not_called()

    def test_mode_regard_lance_le_regard(self):
        with patch("core.gestes.demarrer_regard",
                   return_value="Regard actif.") as lancer:
            self.assertEqual(lancer_mode_regard(), "Regard actif.")
        lancer.assert_called_once_with()

    def test_quitter_mode_regard_libere_la_camera(self):
        with patch("core.gestes.arreter_regard",
                   return_value="Regard coupé.") as arreter:
            self.assertEqual(quitter_mode_regard(), "Regard coupé.")
        arreter.assert_called_once_with()

    def test_mode_regard_demarre_avec_les_clics_actifs(self):
        ancien_regard = gestes_core._PROC_REGARD
        ancienne_calibration = gestes_core._PROC_CALIBRATION
        faux_processus = Mock(pid=1234)
        faux_processus.poll.return_value = None
        gestes_core._PROC_REGARD = None
        gestes_core._PROC_CALIBRATION = None
        try:
            with (patch.object(gestes_core, "_python_tracker",
                               return_value=Path("C:/faux/python.exe")),
                  patch.object(Path, "exists", return_value=True),
                  patch.object(gestes_core, "actif", return_value=False),
                  patch.object(gestes_core.subprocess, "Popen",
                               return_value=faux_processus) as popen):
                reponse = gestes_core.demarrer_regard()
            commande = popen.call_args.args[0]
            self.assertIn("--clics-actifs", commande)
            self.assertIn("clic par sourcils sera déjà actif", reponse)
        finally:
            gestes_core._PROC_REGARD = ancien_regard
            gestes_core._PROC_CALIBRATION = ancienne_calibration


if __name__ == "__main__":
    unittest.main()
