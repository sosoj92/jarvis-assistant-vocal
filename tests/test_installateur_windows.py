"""Installateur Windows en un clic : ne telecharge que ce qui est prevu, garde config.yaml."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLEUR = (ROOT / "INSTALLER_JARVIS.bat").read_text(encoding="ascii")
LANCEUR = (ROOT / "lancer_jarvis.bat").read_text(encoding="ascii")


class InstallateurTest(unittest.TestCase):
    def test_seuls_les_paquets_winget_officiels_attendus(self):
        paquets = re.findall(r"winget install --id (\S+)", INSTALLEUR)
        self.assertEqual(sorted(paquets), ["Git.Git", "astral-sh.uv"])
        self.assertEqual(INSTALLEUR.count("--source winget"), 2)

    def test_aucun_telechargement_ni_execution_distante(self):
        for interdit in ("curl", "Invoke-WebRequest", "iwr ", "bitsadmin", "certutil",
                         "powershell", "pip install", "irm "):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit.lower(), INSTALLEUR.lower())

    def test_dependances_verrouillees_et_configuration_conservee(self):
        self.assertIn('"%UV%" sync', INSTALLEUR)
        self.assertIn("scripts\\setup.py --suite", INSTALLEUR)
        self.assertNotIn("config.yaml\"", INSTALLEUR.replace(" ", ""))  # jamais copie/ecrase ici

    def test_pc_arm_prevenu_mais_installe(self):
        self.assertIn('"%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARM64=1"', INSTALLEUR)
        self.assertIn('if "%ARM64%"=="1" call :note_arm64', INSTALLEUR)
        self.assertIn("openai.cle", INSTALLEUR)

    def test_lanceur_garde_la_mise_a_jour_et_uv(self):
        self.assertIn("git pull --ff-only", LANCEUR)
        self.assertIn('"%UV%" run python jarvis14.py', LANCEUR)

    def test_scripts_batch_en_ascii_et_crlf_imposes(self):
        attributs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat text eol=crlf", attributs)
        for nom in ("INSTALLER_JARVIS.bat", "lancer_jarvis.bat", "mettre_a_jour_jarvis.bat",
                    "scripts/trouver_uv.bat"):
            with self.subTest(nom=nom):
                (ROOT / nom).read_bytes().decode("ascii")   # cmd.exe : pas d'accents


if __name__ == "__main__":
    unittest.main()
