"""Tests du pipeline Signal Matin, sans API ni impression reelle."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from core.signal_matin.daily_learning import construire_apprentissage_du_jour
from core.signal_matin.mock_data import construire_demo
from core.signal_matin.models import DensityMode, MorningEdition, WordOfTheDay
from core.signal_matin.normalizer import normaliser_edition
from core.signal_matin.pdf import (
    _fit_moderate_overflow,
    _launch_browser,
    _measure,
    _paginate_adaptive,
    generer_pdf,
    inspecter_html,
)
from core.signal_matin.renderer import render_html
from core.signal_matin import automation


class SignalMatinModelTests(unittest.TestCase):
    def test_learning_history_has_no_expiration_or_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "learning-history.json"
            start = dt.date(2026, 1, 1)

            def generate_word(_date, used):
                value = len(used)
                letters = ""
                while True:
                    letters = chr(ord("a") + value % 26) + letters
                    value = value // 26 - 1
                    if value < 0:
                        break
                return WordOfTheDay(
                    word=f"Neologisme{letters}",
                    definition="Mot de test produit apres epuisement du stock local.",
                    example="Cet exemple valide la memoire sans expiration.",
                )

            def generate_crossword_terms(_date, used):
                roots = ("ALPHA", "BETON", "GAMMA", "DELTA", "OMEGA", "IMAGE")
                terms = []
                for index in range(36):
                    value = len(used) + index
                    letters = ""
                    while True:
                        letters = chr(ord("A") + value % 26) + letters
                        value = value // 26 - 1
                        if value < 0:
                            break
                    terms.append((
                        roots[index % len(roots)] + letters,
                        f"Definition artificielle numero {index} pour le test.",
                    ))
                return terms

            pages = [
                construire_apprentissage_du_jour(
                    start + dt.timedelta(days=offset),
                    history_path=history_path,
                    word_generator=generate_word,
                    crossword_term_generator=generate_crossword_terms,
                )
                for offset in range(75)
            ]
            french_words = [page.french_word.word.casefold() for page in pages]
            math_questions = [page.math.question for page in pages]
            crossword_signatures = [
                tuple(sorted(
                    (entry.answer, entry.row, entry.column, entry.direction)
                    for entry in page.crossword.entries
                ))
                for page in pages
            ]
            self.assertEqual(len(set(french_words)), len(pages))
            self.assertEqual(len(set(math_questions)), len(pages))
            self.assertEqual(len(set(crossword_signatures)), len(pages))
            crossword_answers = [
                entry.answer
                for page in pages
                for entry in page.crossword.entries
            ]
            self.assertEqual(len(set(crossword_answers)), len(crossword_answers))

            # Regenerer une date rend exactement la meme page sans consommer un
            # nouveau mot ni modifier l'historique.
            again = construire_apprentissage_du_jour(
                start + dt.timedelta(days=42),
                history_path=history_path,
                word_generator=generate_word,
                crossword_term_generator=generate_crossword_terms,
            )
            self.assertEqual(again, pages[42])
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(history["days"]), 75)

    def test_learning_history_imports_already_generated_editions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "data"
            archive.mkdir()
            old_date = dt.date(2026, 9, 28)
            old_page = construire_apprentissage_du_jour(old_date)
            (archive / f"{old_date.isoformat()}-signal-matin.json").write_text(
                json.dumps({
                    "edition": {"date": old_date.isoformat()},
                    "learning": old_page.model_dump(mode="json"),
                }),
                encoding="utf-8",
            )
            history_path = root / "learning-history.json"
            new_page = construire_apprentissage_du_jour(
                old_date + dt.timedelta(days=1),
                history_path=history_path,
                archive_dir=archive,
            )
            self.assertNotEqual(new_page.french_word.word, old_page.french_word.word)
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertIn(old_date.isoformat(), history["days"])

    def test_learning_content_changes_every_day(self):
        start = dt.date(2026, 9, 1)
        pages = [
            construire_apprentissage_du_jour(start + dt.timedelta(days=offset))
            for offset in range(30)
        ]
        for previous, current in zip(pages, pages[1:]):
            self.assertNotEqual(previous.french_word.word, current.french_word.word)
            self.assertNotEqual(previous.math.question, current.math.question)
            previous_answers = {
                entry.answer for entry in previous.crossword.entries
            }
            current_answers = {
                entry.answer for entry in current.crossword.entries
            }
            self.assertTrue(previous_answers.isdisjoint(current_answers))
        self.assertGreaterEqual(len({page.french_word.word for page in pages}), 14)
        self.assertEqual(len({page.math.question for page in pages}), len(pages))
        crossword_signatures = {
            tuple(
                (entry.answer, entry.row, entry.column, entry.direction)
                for entry in page.crossword.entries
            )
            for page in pages
        }
        self.assertEqual(len(crossword_signatures), len(pages))
        self.assertTrue(all(len(page.crossword.entries) == 6 for page in pages))

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
            DensityMode.STANDARD: 7,
            DensityMode.EXTENDED: 7,
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

    def test_standard_combines_short_briefs_without_wasting_a_page(self):
        edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="standard")
        html = render_html(edition)
        self.assertEqual(html.count(" page-briefs-detail\""), 1)
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

    def test_tech_pagination_depends_on_text_volume(self):
        edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="standard")
        self.assertEqual(len(edition.tech_news), 5)
        html = render_html(edition)
        self.assertNotIn("tech-continuation-page", html)

        long_items = [
            item.model_copy(update={"expanded_summary": "Texte developpe. " * 70})
            for item in edition.tech_news
        ]
        html = render_html(edition.model_copy(update={"tech_news": long_items}))
        self.assertIn("Technologie &amp; IA - suite", html)
        self.assertIn("tech-continuation-page", html)

    def test_extra_news_tech_and_curiosity_create_pages_without_omission(self):
        edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="standard")
        source_item = edition.news.all_secondary()[0]
        news_items = [
            source_item.model_copy(update={"title": f"Sujet actualite unique {index}"})
            for index in range(20)
        ]
        tech_items = [
            edition.tech_news[index % len(edition.tech_news)].model_copy(
                update={"title": f"Sujet technologie unique {index}"}
            )
            for index in range(9)
        ]
        curiosity_items = [
            edition.curiosity_news[index % len(edition.curiosity_news)].model_copy(
                update={"title": f"Sujet curiosite unique {index}"}
            )
            for index in range(8)
        ]
        edition = edition.model_copy(update={
            "news": edition.news.model_copy(update={
                "world": news_items[:12],
                "france": news_items[12:],
                "economy": [], "society": [], "science": [], "culture": [],
            }),
            "tech_news": tech_items,
            "curiosity_news": curiosity_items,
        })
        html = render_html(edition)
        self.assertEqual(html.count('class="sheet '), 10)
        for item in [*news_items, *tech_items, *curiosity_items]:
            self.assertIn(item.title, html)
        self.assertIn("tech-continuation is-four", html)
        self.assertIn("curiosity-continuation is-four", html)
        self.assertNotIn("continuation is-single", html)

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

    def test_delayed_print_copies_the_real_action_instead_of_nesting_tasks(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" /
                  "programmer_impression_signal_matin.ps1").read_text(
                      encoding="utf-8")
        self.assertIn("$sourceAction.Execute", script)
        self.assertIn("$sourceAction.Arguments", script)
        self.assertIn("New-ScheduledTaskAction @actionParams", script)
        self.assertNotIn("Start-ScheduledTask -TaskName $TacheSource", script)

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
            DensityMode.STANDARD: 7,
            DensityMode.EXTENDED: 7,
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
            self.assertEqual(len(reader.pages), 7)
            for page in reader.pages:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                self.assertAlmostEqual(width, 595.28, delta=1.0)
                self.assertAlmostEqual(height, 841.89, delta=1.0)
            self.assertGreater(path.stat().st_size, 20_000)

    def test_large_daily_variation_creates_balanced_continuation_pages(self):
        css = (
            (Path(__file__).resolve().parents[1] / "web" / "signal_matin.css")
            .read_text(encoding="utf-8")
            + """
            .page-news .news-opening { min-height: 190mm; }
            .page-news .news-followups { min-height: 190mm; }
            .page-news .news-followups { columns: 1; }
            .page-news .news-followups .news-card {
              min-height: 90mm;
              padding-bottom: 8mm;
            }
            .page-news .news-followups .news-card p {
              font-size: 13pt;
              line-height: 1.65;
            }
            """
        )
        html = render_html(self.edition, css=css)
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_content(html, wait_until="load")
                page.evaluate("document.fonts.ready")
                result = _paginate_adaptive(page)
                layout = _measure(page)
                self.assertGreater(result["pages"], 7)
                self.assertEqual(result["unresolved"], 0)
                self.assertFalse([item for item in layout if item["overflow"]], layout)
                adaptive = [item for item in layout if item["adaptive"]]
                self.assertTrue(adaptive)
                self.assertTrue(all(
                    item["used_ratio"] >= 0.52 or item["sparse"]
                    for item in adaptive
                ), adaptive)
            finally:
                browser.close()

    def test_moderate_live_overflow_is_fitted_before_pdf(self):
        html = """
        <section class="sheet" data-page="1">
          <main class="page-content" style="height:100px;overflow:hidden">
            <div style="height:112px">Contenu live variable</div>
          </main>
        </section>
        """
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                page = browser.new_page(viewport={"width": 800, "height": 600})
                page.set_content(html)
                layout = _measure(page)
                self.assertTrue(layout[0]["overflow"])
                fitted = _fit_moderate_overflow(page, layout)
                self.assertFalse(fitted[0]["overflow"], fitted)
                scale = float(page.locator(".page-content").get_attribute("data-auto-fit"))
                self.assertGreaterEqual(scale, 0.85)
                self.assertLess(scale, 1.0)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
