"""Tests hors réseau du corps Windows distant."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from core import config, registre
from core import poste_distant


CHEMIN_AGENT = (Path(__file__).resolve().parent.parent / "desktop_agent"
                / "jarvis_desktop_agent.py")
SPEC = importlib.util.spec_from_file_location("jarvis_desktop_agent_test", CHEMIN_AGENT)
AGENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT)


class PosteDistantTests(unittest.TestCase):
    def setUp(self):
        self.ancienne_config = config._CONFIG
        config._CONFIG = {}

    def tearDown(self):
        config._CONFIG = self.ancienne_config

    def test_routage_desactive_conserve_execution_locale(self):
        fonction = unittest.mock.Mock(return_value="local")
        outil = registre.Outil(
            fonction, "capture_screen", "", {}, False, False, None, None, False)
        self.assertEqual(registre.executer(outil, {}), "local")
        fonction.assert_called_once_with()

    def test_outil_pc_est_route_une_fois_active(self):
        config._CONFIG = {"poste_principal": {"actif": True, "agent": "bureau"}}
        fonction = unittest.mock.Mock(return_value="local")
        outil = registre.Outil(
            fonction, "capture_screen", "", {}, False, False, None, None, False)
        with patch("core.poste_distant.executer_outil_principal",
                   return_value={"image": {"data": "abc"}}) as distant:
            resultat = registre.executer(outil, {"ecran": 1})
        self.assertEqual(resultat["image"]["data"], "abc")
        distant.assert_called_once_with("capture_screen", {"ecran": 1})
        fonction.assert_not_called()

    def test_agent_refuse_schema_et_outil_non_autorises(self):
        actions = AGENT.ActionsLocales({})
        ok, _ = actions.executer("commande_shell", {"commande": "calc"})
        self.assertFalse(ok)
        ok, _ = actions.executer(
            "outil_local", {"outil": "envoyer_mail", "args": {}})
        self.assertFalse(ok)

    def test_agent_refuse_url_dangereuse(self):
        actions = AGENT.ActionsLocales({})
        for url in ("file:///C:/secret.txt", "javascript:alert(1)", "data:text/plain,x"):
            with self.subTest(url=url):
                ok, _ = actions.executer("browser_open", {"url": url})
                self.assertFalse(ok)

    def test_listes_d_outils_identiques_des_deux_cotes(self):
        self.assertEqual(poste_distant.OUTILS_POSTE, AGENT.OUTILS_LOCAUX)


if __name__ == "__main__":
    unittest.main()
