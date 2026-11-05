"""Agent du bureau : actions locales d'Astra et configuration visee (sans materiel).

keyboard, la souris et la config sont simules ; aucun clic, aucune frappe, aucune
ecriture de fichier de configuration.
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import config, registre

RACINE = Path(__file__).resolve().parents[1]
CHEMIN_AGENT = RACINE / "desktop_agent" / "jarvis_desktop_agent.py"
SPEC = importlib.util.spec_from_file_location("jarvis_desktop_agent_actions", CHEMIN_AGENT)
AGENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT)


class _ConfigIsolee(unittest.TestCase):
    def setUp(self):
        # _outil_local modifie l'etat global de core.config : on le restaure.
        patcheurs = (patch.object(config, "_CONFIG", config._CONFIG),
                     patch.object(config, "FICHIER", config.FICHIER))
        for p in patcheurs:
            p.start()
            self.addCleanup(p.stop)


class TaperTest(_ConfigIsolee):
    def test_caracteres_de_controle_retires(self):
        clavier = MagicMock()
        with patch.dict(sys.modules, {"keyboard": clavier}):
            ok, _ = AGENT.ActionsLocales({})._astra_action(
                {"action": "taper", "texte": "bonjour\nEnvoyer\r\tfin\x1b"})
        self.assertTrue(ok)
        clavier.write.assert_called_once_with("bonjourEnvoyerfin", delay=0.01)

    def test_texte_borne_a_500_caracteres(self):
        clavier = MagicMock()
        with patch.dict(sys.modules, {"keyboard": clavier}):
            AGENT.ActionsLocales({})._astra_action({"action": "taper", "texte": "a" * 900})
        self.assertEqual(len(clavier.write.call_args.args[0]), 500)


class CliquerTest(_ConfigIsolee):
    GEO_A = {"moniteur": {"left": 0, "top": 0, "width": 1920, "height": 1080},
             "largeur": 960, "hauteur": 540}
    GEO_B = {"moniteur": {"left": 1920, "top": 0, "width": 2560, "height": 1440},
             "largeur": 1280, "hauteur": 720}

    def _cliquer(self, geometrie):
        from tools import ecran, souris
        points = []
        with patch.object(ecran, "_DERNIERE", dict(self.GEO_B)), \
                patch.object(souris, "_placer_curseur",
                             side_effect=lambda x, y: points.append((x, y)) or True), \
                patch.object(souris, "_user32", MagicMock()), \
                patch("core.poste_distant.executer_outil_principal", return_value=None):
            args = {"action": "cliquer", "x": 480, "y": 270}
            if geometrie is not None:
                args["geometrie"] = geometrie
            ok, _ = AGENT.ActionsLocales({})._astra_action(args)
            derniere = ecran._DERNIERE
        return ok, points, derniere

    def test_clic_dans_le_repere_de_la_capture_vue_par_astra(self):
        # Capture A vue par Astra, puis une capture B plus recente (autre ecran).
        ok, points, derniere = self._cliquer(self.GEO_A)
        self.assertTrue(ok)
        self.assertEqual(points, [(960, 540)])          # centre de l'ecran A
        self.assertEqual(derniere, self.GEO_B)          # la plus recente est remise

    def test_sans_geometrie_comportement_historique(self):
        ok, points, _ = self._cliquer(None)
        self.assertTrue(ok)
        self.assertEqual(points, [(1920 + 960, 540)])   # derniere capture (B)

    def test_geometrie_invalide_ignoree(self):
        _, points, _ = self._cliquer({"forge": True})
        self.assertEqual(points, [(1920 + 960, 540)])


class ConfigAgentTest(_ConfigIsolee):
    def test_outil_local_ecrit_dans_la_config_de_l_agent(self):
        config.FICHIER = RACINE / "config.yaml"          # comme hors de main()
        appels = []

        def faux_outil(**args):
            appels.append(config.FICHIER)
            config.definir("overlay.actif", False)
            return "ok"

        outil = SimpleNamespace(fonction=faux_outil)
        nom = next(iter(AGENT.OUTILS_LOCAUX))
        with patch.object(registre, "charger_outils"), \
                patch.object(registre, "get", return_value=outil), \
                patch.object(config, "definir") as definir:
            ok, resultat = AGENT.ActionsLocales({"audio": {}})._outil_local(nom, {})
        self.assertTrue(ok)
        self.assertEqual(appels, [RACINE / "desktop_agent" / "config.yaml"])
        self.assertNotEqual(config.FICHIER, RACINE / "config.yaml")
        definir.assert_called_once()                    # simule : aucun fichier ecrit


if __name__ == "__main__":
    unittest.main()
