"""Installateur interactif (scripts/setup.py), sans reseau ni ecriture de config.yaml.

- en mode cloud, une cle Claude saisie donne bien un Jarvis branche sur Claude ;
- aucune cle d'exemple (« sk-proj-... ») ne passe pour une vraie ;
- la cle Hue est lue masquee, comme les cles cloud ;
- Python trop ancien, uv sync ou pip en echec : arret net et message clair ;
- la relance dans le venv attend l'enfant (pas d'os.execv, qui detache sous Windows).
"""
import collections
import importlib.util
import io
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import core.config

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup.py"


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigCloudTest(unittest.TestCase):
    def setUp(self):
        self.setup = _charger("jarvis_setup_test", SETUP)
        self.doctor = _charger("jarvis_doctor_test", ROOT / "scripts" / "doctor.py")

    def _config_cloud(self, cles):
        conf = self.setup.charger_exemple()
        with mock.patch.object(self.setup, "lire_cle", side_effect=cles), \
                mock.patch.object(self.setup, "oui", return_value=False), \
                redirect_stdout(io.StringIO()):
            self.setup.config_cloud(conf)
        return conf

    def test_cle_claude_saisie_choisit_claude(self):
        conf = self._config_cloud(["cle-claude-de-test", ""])
        self.assertEqual(conf["anthropic"]["cle"], "cle-claude-de-test")
        self.assertEqual(conf["cloud"]["fournisseur"], "anthropic")
        self.assertEqual(conf["openai"]["cle"], "")   # plus de « sk-proj-... »
        with mock.patch.object(core.config, "_CONFIG", conf):
            from core import cloud
            self.assertEqual(cloud.fournisseur(), "anthropic")
            self.assertTrue(cloud.modele().startswith("claude"))
            sortie = io.StringIO()
            with redirect_stdout(sortie):
                self.doctor.v_llm()
        self.assertIn("cle Anthropic (Claude) presente", sortie.getvalue())
        self.assertEqual(self.doctor._scores["ko"], 0)

    def test_sans_cle_aucune_valeur_d_exemple_ne_reste(self):
        conf = self._config_cloud(["", ""])
        self.assertEqual(conf["openai"]["cle"], "")
        self.assertEqual(conf["anthropic"]["cle"], "")
        with mock.patch.object(core.config, "_CONFIG", conf):
            from core import cloud
            self.assertFalse(cloud.disponible())
            sortie = io.StringIO()
            with redirect_stdout(sortie):
                self.doctor.v_llm()
        self.assertIn("absente", sortie.getvalue())
        self.assertEqual(self.doctor._scores["ko"], 1)

    def test_cles_factices_reconnues_par_les_deux_scripts(self):
        for valeur, attendu in (("sk-proj-...", True), ("sk-ant-...", True),
                                ("ta-cle-hue", True), ("", False), (None, False),
                                ("sk-proj-AbCdEf0123456789", False),
                                ("sk-ant-api03-XXXaTON-b", False)):   # vraie cle possible
            with self.subTest(valeur=valeur):
                self.assertIs(self.setup.est_cle_factice(valeur), attendu)
                self.assertIs(self.doctor.est_cle_factice(valeur), attendu)


class SaisieHueTest(unittest.TestCase):
    def test_cle_hue_lue_sans_echo(self):
        setup = _charger("jarvis_setup_test_hue", SETUP)
        terminal = mock.Mock()
        terminal.isatty.return_value = True
        conf = {}
        with mock.patch.object(setup.sys, "stdin", terminal), \
                mock.patch("getpass.getpass", side_effect=["", "", "FAKEHUEKEY"]) as masque, \
                mock.patch("builtins.input", side_effect=["o", "10.0.0.1"]) as visible, \
                redirect_stdout(io.StringIO()):
            setup.config_cloud(conf)
        self.assertEqual(conf["hue"], {"pont": "10.0.0.1", "cle": "FAKEHUEKEY"})
        self.assertEqual(masque.call_count, 3)
        self.assertTrue(all("cle Hue" not in str(c) for c in visible.call_args_list))


class AmorcageTest(unittest.TestCase):
    def setUp(self):
        self.setup = _charger("jarvis_setup_test_amorcage", SETUP)

    def test_python_trop_ancien_refuse(self):
        V = collections.namedtuple("V", "major minor micro releaselevel serial")
        with mock.patch.object(self.setup.sys, "version_info", V(3, 11, 9, "final", 0)), \
                redirect_stdout(io.StringIO()) as sortie, \
                self.assertRaises(SystemExit) as fin:
            self.setup.main()
        self.assertEqual(fin.exception.code, 1)
        self.assertIn("3.13", sortie.getvalue())

    def _installer(self, uv, code):
        echec = subprocess.CompletedProcess([], code)
        with mock.patch.object(self.setup.shutil, "which", return_value=uv), \
                mock.patch.object(self.setup, "python_venv", return_value=Path("venv/python")), \
                mock.patch.object(self.setup.subprocess, "run", return_value=echec) as run, \
                redirect_stdout(io.StringIO()):
            self.setup.installer_dependances()
        return run

    def test_echec_de_pip_arrete_tout(self):
        with self.assertRaises(SystemExit) as fin:
            self._installer(None, 1)
        self.assertEqual(fin.exception.code, 1)

    def test_echec_de_uv_sync_arrete_tout(self):
        with self.assertRaises(SystemExit) as fin:
            self._installer("uv", 2)
        self.assertEqual(fin.exception.code, 1)

    def test_playwright_en_echec_reste_un_avertissement(self):
        resultats = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)]
        with mock.patch.object(self.setup.shutil, "which", return_value="uv"), \
                mock.patch.object(self.setup, "python_venv", return_value=Path("venv/python")), \
                mock.patch.object(self.setup.subprocess, "run", side_effect=resultats), \
                redirect_stdout(io.StringIO()) as sortie:
            self.setup.installer_dependances()
        self.assertIn("Chromium non installe", sortie.getvalue())

    def test_relance_dans_le_venv_attend_l_enfant(self):
        py = Path("C:/ailleurs/.venv/Scripts/python.exe")
        with mock.patch.object(self.setup, "python_venv", return_value=py), \
                mock.patch.object(self.setup.subprocess, "call", return_value=0) as appel, \
                redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as fin:
            self.setup.relancer_dans_venv()
        self.assertEqual(fin.exception.code, 0)
        self.assertEqual(appel.call_args[0][0], [str(py), str(SETUP.resolve()), "--suite"])
        self.assertNotIn("os.execv(", SETUP.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
