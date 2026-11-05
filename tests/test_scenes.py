"""Tests du brief quotidien déclenché par le poste principal."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.signal_matin import automation
from core.signal_matin.printer import WindowsRasterPrinter
from tools import scenes


def _reglage(cle, defaut=None):
    valeurs = {
        "scenes.au_demarrage_actif": True,
        "scenes.spotify": False,
    }
    return valeurs.get(cle, defaut)


class ScenesTests(unittest.TestCase):
    def setUp(self):
        # Garde : la scène appelle le vrai lanceur Signal Matin, qui lit le
        # config.yaml local. Aucun test de ce fichier ne doit pouvoir imprimer,
        # appeler le modèle ni consommer le marqueur d'impression du jour.
        interdit = AssertionError("impression réelle interdite en test")
        self.lanceur_impression = self._activer(patch.object(
            automation, "lancer_impression_premier_brief_async", return_value=False))
        self._activer(patch.object(
            automation, "_executer_impression", side_effect=interdit))
        self._activer(patch.object(
            WindowsRasterPrinter, "print_pdf", side_effect=interdit))
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self._activer(patch.object(
            automation, "_ETAT_IMPRESSION",
            Path(dossier.name) / ".signal_matin_impression"))

    def _activer(self, patcheur):
        objet = patcheur.start()
        self.addCleanup(patcheur.stop)
        return objet

    def test_garde_neutralise_l_impression_et_le_marqueur_reel(self):
        self.assertFalse(automation.lancer_impression_premier_brief_async())
        self.assertNotIn("notes", automation._ETAT_IMPRESSION.parts)
        with self.assertRaises(AssertionError):
            WindowsRasterPrinter().print_pdf(Path("brief.pdf"), execute=True)
        with self.assertRaises(AssertionError):
            automation._executer_impression()

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
        # La scène passe bien par le lanceur Signal Matin, ici neutralisé.
        self.lanceur_impression.assert_called_once_with()

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


class ExtinctionLumieresTests(unittest.TestCase):
    """« Lumières éteintes » seulement si le pont Hue a vraiment répondu."""

    def setUp(self):
        import sys
        from unittest.mock import MagicMock
        from core import config
        from tools import lumieres
        for patcheur in (
                patch.object(config, "_CONFIG", {}),     # jamais le config.yaml local
                patch.object(lumieres, "_hue_requete", side_effect=OSError("injoignable")),
                patch.dict(sys.modules, {"tools.obs": MagicMock(
                    _client=MagicMock(side_effect=ConnectionError()))})):
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def test_eteindre_tout_n_annonce_pas_des_lumieres_restees_allumees(self):
        hue = {"hue.pont": "192.0.2.1", "hue.cle": "cle-factice"}
        with patch("tools.scenes.reglage", lambda cle, defaut=None: hue.get(cle, defaut)), \
                patch("tools.scenes._touche_media", return_value=False):
            message = scenes.eteindre_tout()
        self.assertNotIn("lumières éteintes", message)
        self.assertIn("Hue injoignable", message)

    def test_eteindre_tout_sans_hue_saute_l_etape(self):
        with patch("tools.scenes.reglage", lambda cle, defaut=None: defaut), \
                patch("tools.scenes._touche_media", return_value=False), \
                patch("tools.modes.appliquer") as appliquer:
            message = scenes.eteindre_tout()
        appliquer.assert_not_called()
        self.assertNotIn("lumières", message)

    def _eteindre_pc(self, conf, appliquer=None):
        from unittest.mock import MagicMock
        from core import config
        from tools import systeme
        with patch.object(config, "_CONFIG", conf), \
                patch.object(systeme.subprocess, "run",
                             return_value=MagicMock(returncode=0)) as lancer:
            if appliquer is None:
                message = systeme.eteindre_pc()
            else:
                with patch("tools.modes.appliquer", return_value=appliquer):
                    message = systeme.eteindre_pc()
        self.assertEqual(lancer.call_args.args[0][:2], ["shutdown", "/s"])
        return message

    _HUE = {"pont": "192.0.2.1", "cle": "cle-factice"}

    def test_eteindre_pc_le_dit_mais_programme_quand_meme_l_arret(self):
        # Hue configure mais injoignable (le pont factice leve OSError).
        message = self._eteindre_pc({"hue": dict(self._HUE)})
        self.assertTrue(message.startswith("Lumieres non coupees (Hue injoignable)."))

    def test_eteindre_pc_sans_hue_ne_parle_pas_des_lumieres(self):
        message = self._eteindre_pc({})
        self.assertNotIn("Lumieres", message)
        self.assertNotIn("Hue", message)
        self.assertTrue(message.startswith("Le PC s'eteint"))

    def test_eteindre_pc_scene_inconnue_le_dit(self):
        message = self._eteindre_pc({"hue": dict(self._HUE),
                                     "assistant": {"scene_extinction": "dodo"}},
                                    appliquer=(None, []))
        self.assertTrue(message.startswith("Lumieres non coupees (scene d'extinction « dodo » inconnue)."))
        self.assertNotIn("injoignable", message)

    def test_eteindre_pc_cite_la_vraie_cause(self):
        message = self._eteindre_pc({"hue": dict(self._HUE)},
                                    appliquer=("off", ["Piece inconnue : grenier."]))
        self.assertTrue(message.startswith("Lumieres non coupees (Piece inconnue : grenier)."))
        self.assertNotIn("injoignable", message)

    def test_eteindre_pc_lumieres_coupees(self):
        message = self._eteindre_pc({"hue": dict(self._HUE)}, appliquer=("off", []))
        self.assertTrue(message.startswith("Lumieres coupees. Le PC s'eteint"))


if __name__ == "__main__":
    unittest.main()
