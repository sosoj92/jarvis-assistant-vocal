"""Tests du pipeline Signal Matin, sans API ni impression reelle."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from pypdf import PdfReader

from core.signal_matin.mock_data import construire_demo
from core.signal_matin.models import DensityMode, MorningEdition
from core.signal_matin.normalizer import normaliser_edition
from core.signal_matin.pdf import generer_pdf, inspecter_html
from core.signal_matin.renderer import render_html
from core.signal_matin import automation


class SignalMatinModelTests(unittest.TestCase):
    def test_first_brief_print_marker_allows_only_one_attempt_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / ".signal_matin_impression"
            day = dt.date(2026, 9, 26)
            self.assertTrue(automation._reserver_impression_du_jour(day, marker))
            self.assertFalse(automation._reserver_impression_du_jour(day, marker))
            self.assertTrue(
                automation._reserver_impression_du_jour(day + dt.timedelta(days=1), marker)
            )

    def test_first_brief_print_requires_explicit_startup_mode(self):
        values = {
            "signal_matin.actif": True,
            "signal_matin.imprimer": True,
            "signal_matin.declenchement": "premier_demarrage",
        }
        with patch.object(automation, "reglage", side_effect=lambda key, default=None: values.get(key, default)):
            self.assertTrue(automation._premier_demarrage_actif())
            values["signal_matin.declenchement"] = "horaire"
            self.assertFalse(automation._premier_demarrage_actif())

    def test_first_brief_print_is_connected_to_daily_startup_scene(self):
        scene = (Path(__file__).resolve().parents[1] / "tools" / "scenes.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            scene.index("_marquer_fait()"),
            scene.index("lancer_impression_premier_brief_async()"),
        )

    def test_news_requires_a_source(self):
        raw = construire_demo(dt.date(2026, 9, 26)).model_dump(mode="json")
        del raw["news"]["lead"]["source"]
        with self.assertRaises(ValidationError):
            MorningEdition.model_validate(raw)

    def test_date_number_and_demo_marker(self):
        edition = construire_demo(dt.date(2026, 9, 26))
        html = render_html(edition)
        self.assertEqual(edition.edition.date, dt.date(2026, 9, 26))
        self.assertGreater(edition.edition.number, 0)
        self.assertIn("EDITION DE DEMONSTRATION", html)
        self.assertIn("Signal Matin", html)
        self.assertNotIn("Provenance", html)
        self.assertNotIn("Sources de cette edition", html)
        self.assertNotIn("Source absente", html)

    def test_technical_source_details_are_never_printed(self):
        edition = construire_demo(dt.date(2026, 9, 26))
        edition.sources[0].detail = "MARQUEUR_TECHNIQUE_API_FICHIER"
        html = render_html(edition)
        self.assertNotIn("MARQUEUR_TECHNIQUE_API_FICHIER", html)

    def test_social_and_discord_digest_are_editorial_not_technical(self):
        edition = construire_demo(dt.date(2026, 9, 26))
        html = render_html(edition)
        self.assertIn("Reseaux &amp; communaute", html)
        self.assertIn("Instagram, compte principal", html)
        self.assertIn("Discord, activite de la communaute", html)
        self.assertNotIn("access_token", html)

    def test_forced_density_modes_have_expected_pages(self):
        expected = {
            DensityMode.COMPACT: 4,
            DensityMode.STANDARD: 8,
            DensityMode.EXTENDED: 8,
        }
        demo = construire_demo(dt.date(2026, 9, 26))
        for mode, pages in expected.items():
            with self.subTest(mode=mode):
                edition = normaliser_edition(demo, mode=mode)
                self.assertEqual(render_html(edition).count('class="sheet '), pages)

    def test_front_briefs_get_a_dedicated_detail_page(self):
        edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="compact")
        html = render_html(edition)
        self.assertIn("En bref, en detail", html)
        self.assertIn("page-briefs-detail", html)
        for item in edition.news.all_secondary()[:3]:
            self.assertGreaterEqual(html.count(item.title), 2)

    def test_standard_has_two_dedicated_brief_pages(self):
        edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="standard")
        html = render_html(edition)
        self.assertEqual(html.count(" page-briefs-detail\""), 2)
        for item in edition.news.all_secondary()[:3]:
            self.assertGreaterEqual(html.count(item.title), 2)
        for item in edition.news.all_secondary()[3:6]:
            self.assertGreaterEqual(html.count(item.title), 1)

    def test_standard_has_tech_curiosity_and_learning_cahiers(self):
        edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="standard")
        html = render_html(edition)
        self.assertIn("page-tech", html)
        self.assertIn("page-curiosity", html)
        self.assertIn("page-learning", html)
        self.assertIn("Mots croises du jour", html)
        self.assertIn("Vocabulaire tech", html)
        self.assertIn("Mot francais", html)
        self.assertIn("Calcul mental", html)
        self.assertGreaterEqual(len(edition.learning.crossword.entries), 5)

    def test_windows_printer_does_not_add_driver_margins(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" /
                  "imprimer_image_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("PageBounds", script)
        self.assertNotIn("$event.MarginBounds", script)

    def test_windows_printer_supports_one_job_long_edge_duplex(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" /
                  "imprimer_image_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("DossierImages", script)
        self.assertIn("CanDuplex", script)
        self.assertIn("Duplex]::Vertical", script)
        self.assertIn("HasMorePages", script)

    def test_empty_sections_do_not_crash(self):
        demo = construire_demo(dt.date(2026, 9, 26)).model_dump(mode="json")
        for key in ("agenda", "priorities", "reminders", "tech", "watch",
                    "newsletter_digest", "recommendations"):
            demo[key] = []
        demo["weather"] = None
        demo["news"] = {}
        edition = normaliser_edition(demo, mode="compact")
        html = render_html(edition)
        self.assertIn("Aucune actualite", html)
        self.assertEqual(html.count('class="sheet '), 3)


class SignalMatinRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="extended")

    def test_no_major_overflow(self):
        expected = {
            DensityMode.COMPACT: 4,
            DensityMode.STANDARD: 8,
            DensityMode.EXTENDED: 8,
        }
        demo = construire_demo(dt.date(2026, 9, 26))
        for mode, page_count in expected.items():
            with self.subTest(mode=mode):
                edition = normaliser_edition(demo, mode=mode)
                layout = inspecter_html(render_html(edition))
                self.assertEqual(len(layout), page_count)
                self.assertFalse([page for page in layout if page["overflow"]], layout)

    def test_pdf_is_a4_and_page_count_is_reasonable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signal-matin.pdf"
            generer_pdf(self.edition, path)
            reader = PdfReader(str(path))
            self.assertEqual(len(reader.pages), 8)
            for page in reader.pages:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                self.assertAlmostEqual(width, 595.28, delta=1.0)
                self.assertAlmostEqual(height, 841.89, delta=1.0)
            self.assertGreater(path.stat().st_size, 20_000)


if __name__ == "__main__":
    unittest.main()
