"""Tests hors reseau du journal papier du matin."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.journal_matin import construire_texte
from core.journal_pdf import generer_pdf


class JournalMatinTests(unittest.TestCase):
    def test_construit_un_journal_date_et_sections(self):
        moment = dt.datetime(2026, 9, 25, 7, 0)
        texte = construire_texte(
            maintenant=moment,
            sections=[("METEO", "A Yerres, il fait 18 degres."),
                      ("AGENDA DU JOUR", "A 10h reunion.")],
        )

        self.assertIn("SIGNAL MATIN - LE JOURNAL ANTI-SCROLL", texte)
        self.assertIn("vendredi 25 septembre 2026", texte)
        self.assertIn("A Yerres, il fait 18 degres.", texte)
        self.assertIn("AGENDA DU JOUR", texte)

    def test_wrappe_les_lignes_trop_longues(self):
        with patch("core.journal_matin.reglage", side_effect=lambda cle, defaut=None: (
            50 if cle == "journal_matin.largeur" else defaut
        )):
            texte = construire_texte(
                maintenant=dt.datetime(2026, 9, 25, 7, 0),
                sections=[("TEST", "mot " * 30)],
            )

        self.assertTrue(all(len(ligne) <= 50 for ligne in texte.splitlines()))

    def test_genere_un_pdf_a4(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = generer_pdf(
                Path(dossier) / "journal.pdf",
                dt.datetime(2026, 9, 25, 7, 0),
                [("METEO", "A Paris, il fait 18 degres."),
                 ("ACTUALITES", "Une breve importante ce matin.")],
            )
            self.assertTrue(chemin.exists())
            self.assertGreater(chemin.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
