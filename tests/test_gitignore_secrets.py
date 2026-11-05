"""Filets .gitignore : une copie de config.yaml ne doit jamais partir sur GitHub.

sauvegarder_jarvis.bat fait un « git add -A » puis pousse sur le depot public :
seul .gitignore protege les copies faites a la main (Explorateur, .bak...).
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")


def _ignore(chemin):
    # --no-index : on teste les motifs eux-memes, que le fichier existe ou non.
    r = subprocess.run([GIT, "check-ignore", "--no-index", "-q", chemin], cwd=ROOT,
                       capture_output=True)
    if r.returncode not in (0, 1):
        raise AssertionError(f"git check-ignore a echoue : {r.stderr!r}")
    return r.returncode == 0


@unittest.skipUnless(GIT and (ROOT / ".git").exists(), "git ou depot absent")
class GitignoreSecretsTest(unittest.TestCase):
    def test_copies_de_secrets_ignorees(self):
        for chemin in (
                "config - Copie.yaml",                 # copie de l'Explorateur Windows
                "Copie de config.yaml",
                "config.yaml.bak", "config.yaml.old", "config.old.yaml",
                "config.backup.yaml", "config.yml",
                "desktop_agent/config - Copie.yaml", "desktop_agent/config.yaml.bak",
                "satellite_pi/config.yaml.bak",
                "memory.json.bak", "contenus.yaml.bak",
                ".config.yaml.ab12cd.tmp", ".memory.json.ab12cd.tmp",
                ".contenus.yaml.ab12cd.tmp", "memory.json.2026-10-29",
                "hermes-api.env", "jarvis-lan.crt", "CLAUDE.local.md",
                ".codex/agents/x.toml"):               # consignes locales d'agents
            with self.subTest(chemin=chemin):
                self.assertTrue(_ignore(chemin), f"{chemin} n'est pas ignore")

    def test_exemples_publics_restent_suivis(self):
        for chemin in ("config.example.yaml", "desktop_agent/config.example.yaml",
                       "satellite_pi/config.exemple.yaml",
                       "deploy/server/hermes-config.yaml", ".env.example",
                       "finances/abonnements.example.yaml"):
            with self.subTest(chemin=chemin):
                self.assertFalse(_ignore(chemin), f"{chemin} serait ignore")

    def test_aucun_fichier_suivi_nouvellement_ignore(self):
        r = subprocess.run([GIT, "ls-files", "-ci", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
