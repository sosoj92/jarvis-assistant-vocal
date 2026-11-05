"""Preparation du poste principal : chaque passage garde sa propre sauvegarde.

Le script reecrit config.yaml (sans ses commentaires) et desktop_agent/config.yaml :
un second passage ne doit jamais laisser sans copie ce qui a change entre-temps.
Tout se passe dans un dossier temporaire, sans reseau (--host est fourni).
"""
import importlib.util
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _charger_script():
    spec = importlib.util.spec_from_file_location(
        "preparer_poste_principal_test", ROOT / "scripts" / "preparer_poste_principal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SauvegardesTest(unittest.TestCase):
    def setUp(self):
        self.script = _charger_script()
        self.dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dossier, True)
        self.serveur = self.dossier / "config.yaml"
        self.agent = self.dossier / "desktop_agent" / "config.yaml"
        for nom, valeur in (("RACINE", self.dossier), ("CONFIG_SERVEUR", self.serveur),
                            ("CONFIG_AGENT", self.agent)):
            patch = mock.patch.object(self.script, nom, valeur)
            patch.start()
            self.addCleanup(patch.stop)

    def _lancer(self):
        sortie = io.StringIO()
        with mock.patch("sys.argv", ["preparer", "--host", "192.0.2.10"]), \
                mock.patch.object(self.script, "adresse_locale",
                                  side_effect=AssertionError("pas de reseau")), \
                redirect_stdout(sortie):
            self.script.main()
        return sortie.getvalue()

    def _copies(self, prefixe):
        return sorted((self.dossier / "logs").glob(f"{prefixe}-*.yaml"))

    def test_chaque_passage_garde_sa_copie(self):
        self.serveur.write_text("# commentaire d'origine\nmode: local\n", encoding="utf-8")
        sortie = self._lancer()
        self.assertIn("sans ses commentaires", sortie)
        premieres = self._copies("config-avant-poste-principal")
        self.assertEqual(len(premieres), 1)
        self.assertIn("# commentaire d'origine", premieres[0].read_text(encoding="utf-8"))
        self.assertEqual(self._copies("desktop-agent-config-avant-poste-principal"), [])

        # Changement fait entre deux passages : il doit se retrouver dans une copie.
        conf = yaml.safe_load(self.serveur.read_text(encoding="utf-8"))
        conf["nouvelle_cle"] = "modifiee entre deux passages"
        self.serveur.write_text(yaml.safe_dump(conf, allow_unicode=True), encoding="utf-8")
        self.agent.write_text("agent_id: ancien\n", encoding="utf-8")
        self._lancer()

        copies = self._copies("config-avant-poste-principal")
        self.assertEqual(len(copies), 2)
        self.assertTrue(any("modifiee entre deux passages" in c.read_text(encoding="utf-8")
                            for c in copies))
        copies_agent = self._copies("desktop-agent-config-avant-poste-principal")
        self.assertEqual(len(copies_agent), 1)
        self.assertEqual(copies_agent[0].read_text(encoding="utf-8"), "agent_id: ancien\n")

    def test_sans_config_existante_aucune_copie(self):
        sortie = self._lancer()
        self.assertNotIn("sans ses commentaires", sortie)
        self.assertEqual(self._copies("config-avant-poste-principal"), [])
        self.assertTrue(self.serveur.exists() and self.agent.exists())


if __name__ == "__main__":
    unittest.main()
