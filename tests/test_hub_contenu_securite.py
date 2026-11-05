"""Hub de contenu : la garde SSRF de l'ingestion d'inspiration verifie l'hote.

Rien n'est telecharge : _ingerer_brut et indexer_fiche sont remplaces par des
mocks, le Vault est un dossier temporaire.
"""
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Pas de FileHandler vers logs/hub.log pendant les tests.
_JOURNAL_HUB = logging.getLogger("jarvis.hub")
if not _JOURNAL_HUB.handlers:
    _JOURNAL_HUB.addHandler(logging.NullHandler())
    _JOURNAL_HUB.propagate = False

from core import hub_contenu  # noqa: E402

_PIEGEES = (
    "http://192.0.2.10:8080/instagram.com/p/abc",
    "http://192.0.2.10:8080/api?x=instagram.com/p/abc",
    "http://169.254.169.254/latest/meta-data/?x=instagram.com/reel/abc",
    "https://evil.example/tiktok.com/@a/video/123",
    "http://127.0.0.1:8790/x?instagram.com/p/abc",
    "http://127.0.0.1:8790/x#instagram.com/p/a",
    "file:///C:/Windows/win.ini#instagram.com/p/a",
    "--exec=calc instagram.com/p/a",
    "https://instagram.com.evil.example/p/abc",
    "https://www.instagram.com@192.168.1.1/p/abc",
    "https://www.instagram.com/explore/",
    "https://example.com/",
    "",
)
_VALIDES = {
    "https://www.instagram.com/reel/C1a2B3c4D5/?igsh=xyz":
        "https://www.instagram.com/reel/C1a2B3c4D5/?igsh=xyz",
    "https://www.instagram.com/p/abc/": "https://www.instagram.com/p/abc/",
    "https://www.tiktok.com/@createur/video/7312345678901234567":
        "https://www.tiktok.com/@createur/video/7312345678901234567",
    "Regarde https://www.instagram.com/p/abc/ trop bien":
        "https://www.instagram.com/p/abc/",
    "Partage (https://www.instagram.com/reel/XyZ/).":
        "https://www.instagram.com/reel/XyZ/",
}


class ValidationUrlTests(unittest.TestCase):
    def test_urls_piegees_refusees(self):
        for url in _PIEGEES:
            with self.subTest(url=url):
                self.assertEqual(hub_contenu.url_inspiration_valide(url), "")

    def test_urls_instagram_tiktok_acceptees(self):
        for texte, attendu in _VALIDES.items():
            with self.subTest(texte=texte):
                self.assertEqual(hub_contenu.url_inspiration_valide(texte), attendu)


class IngestionTests(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        for p in (patch.object(hub_contenu, "_vault", return_value=Path(dossier.name)),):
            p.start()
            self.addCleanup(p.stop)

    def test_url_piegee_jamais_transmise_au_telechargeur(self):
        with patch.object(hub_contenu, "_ingerer_brut") as brut, \
                patch.object(hub_contenu, "indexer_fiche") as indexer:
            for url in _PIEGEES:
                with self.subTest(url=url):
                    res = hub_contenu.ingerer_inspiration(url)
                    self.assertFalse(res["ok"])
        brut.assert_not_called()
        indexer.assert_not_called()

    def test_seule_l_url_validee_part_au_telechargeur(self):
        fiche = Path("insta_abc.md")
        with patch.object(hub_contenu, "_ingerer_brut", return_value=fiche) as brut, \
                patch.object(hub_contenu, "indexer_fiche",
                             return_value={"ok": True, "message": "ok"}):
            res = hub_contenu.ingerer_inspiration(
                "Regarde https://www.instagram.com/p/abc/ trop bien\nhttp://127.0.0.1/x")
        self.assertTrue(res["ok"])
        self.assertEqual(brut.call_args.args[0], "https://www.instagram.com/p/abc/")
        self.assertEqual(res["url"], "https://www.instagram.com/p/abc/")


if __name__ == "__main__":
    unittest.main()
