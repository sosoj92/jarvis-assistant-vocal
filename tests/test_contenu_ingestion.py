"""Ingestion YouTube : l'annonce ne compte que les NOUVELLES transcriptions.

Aucun processus ni reseau : subprocess.run est simule, le thread s'execute de
facon synchrone, la voix est capturee et le projet Scripts est un dossier
temporaire.
"""
import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Pas de FileHandler vers logs/hub.log pendant les tests.
_JOURNAL_HUB = logging.getLogger("jarvis.hub")
if not _JOURNAL_HUB.handlers:
    _JOURNAL_HUB.addHandler(logging.NullHandler())
    _JOURNAL_HUB.propagate = False

from tools import contenu  # noqa: E402

_URL = "https://www.youtube.com/@createur-x"


class _ThreadSynchrone:
    def __init__(self, target=None, **_):
        self.target = target

    def start(self):
        self.target()


class IngestionYoutubeTests(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.scripts = Path(dossier.name)
        (self.scripts / "scripts").mkdir()
        (self.scripts / "scripts" / "ingest.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        self.clean = self.scripts / "sources" / "clean" / "createur-x"
        self.clean.mkdir(parents=True)
        for i in range(12):
            (self.clean / f"ancienne-{i}.md").write_text("ancien", encoding="utf-8")
        reglages = {"integrations.scripts": str(self.scripts), "integrations.bash": "bash"}
        self.parler = MagicMock()
        self.journal = MagicMock()
        for p in (patch.object(contenu, "reglage",
                               side_effect=lambda cle, defaut=None: reglages.get(cle, defaut)),
                  patch.object(contenu.voix, "parler", self.parler),
                  patch.object(contenu.threading, "Thread", _ThreadSynchrone),
                  patch.object(contenu.hub_contenu, "_LOGH", self.journal)):
            p.start()
            self.addCleanup(p.stop)

    def _lancer(self, code, nouveaux=(), reecrire=False, stderr=""):
        def faux_run(args, **_):
            if reecrire:
                for f in self.clean.glob("*.md"):
                    f.write_text("reecrit", encoding="utf-8")
            for nom in nouveaux:
                (self.clean / nom).write_text("nouveau", encoding="utf-8")
            return subprocess.CompletedProcess(args, code, "", stderr)

        with patch.object(contenu.subprocess, "run", side_effect=faux_run):
            contenu.lancer_ingestion_youtube(_URL, "createur-x")
        self.parler.assert_called_once()
        return self.parler.call_args.args[0]

    def test_echec_avec_anciennes_transcriptions_n_annonce_pas_de_succes(self):
        annonce = self._lancer(1, stderr="ERROR: yt-dlp casse")
        self.assertNotIn("terminee", annonce)
        self.assertIn("aucune nouvelle transcription", annonce)

    def test_anciennes_transcriptions_reecrites_ne_comptent_pas(self):
        annonce = self._lancer(0, reecrire=True)
        self.assertNotIn("terminee", annonce)
        self.assertIn("aucune transcription", annonce)

    def test_chaine_deja_ingeree_rien_de_nouveau_sans_faux_diagnostic(self):
        annonce = self._lancer(0, reecrire=True)
        self.assertIn("aucune nouvelle video", annonce)
        self.assertNotIn("chaine privee", annonce)

    def test_premiere_ingestion_vide_donne_les_causes_possibles(self):
        for f in self.clean.glob("*.md"):
            f.unlink()
        annonce = self._lancer(0)
        self.assertIn("chaine privee", annonce)
        self.assertNotIn("aucune nouvelle video", annonce)

    def test_seules_les_nouvelles_sont_comptees(self):
        annonce = self._lancer(0, nouveaux=("video-a.md", "video-b.md"), reecrire=True)
        self.assertEqual(annonce, "Ingestion YouTube terminee : 2 transcriptions pour createur-x.")

    def test_echec_journalise_sans_chemin_perso_ni_jeton(self):
        stderr = ("Traceback...\nFileNotFoundError: C:\\Users\\prenom\\cookies.txt "
                  "/c/Users/prenom/Scripts jeton=abcdefghijklmnopqrstuvwxyz0123456789ABCD")
        self._lancer(2, stderr=stderr)
        self.journal.warning.assert_called_once()
        journalise = " ".join(str(a) for a in self.journal.warning.call_args.args)
        self.assertNotIn("prenom", journalise)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789ABCD", journalise)
        self.assertIn("FileNotFoundError", journalise)


if __name__ == "__main__":
    unittest.main()
