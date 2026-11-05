"""Tests du pipeline Signal Matin, sans API ni impression reelle."""
from __future__ import annotations

import datetime as dt
import email.message
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
import urllib.response
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from core.signal_matin import daily_learning, learning_generation, news_enrichment, renderer
from core.signal_matin.daily_learning import construire_apprentissage_du_jour
from core.signal_matin.mock_data import construire_demo
from core.signal_matin.models import (
    CrosswordEntry, CrosswordPuzzle, DensityMode, Illustration, LearningPage,
    MorningEdition, NewsItem, SourceRef, TaskItem, WordOfTheDay,
)
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
        # La tache ponctuelle herite de la duree maximale de la tache quotidienne.
        self.assertIn("$source.Settings.ExecutionTimeLimit", script)
        self.assertIn("-ExecutionTimeLimit $dureeMax", script)

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


# Mots courants, absents de la banque integree : reserve generee factice.
GENERATED_WORDS = (
    "MAISON", "SOLEIL", "ORANGE", "TABLEAU", "CRAYON", "JARDIN", "LUMIERE",
    "NUAGES", "RIVIERE", "MONTAGNE", "CHEMIN", "ETOILE", "PAPIER", "CANAPE",
    "LECTURE", "MUSIQUE", "CUISINE", "SALADE", "TOMATE", "CAROTTE", "BATEAU",
    "VOITURE", "AVION", "TRAIN", "CLAVIER", "SOURIS", "ECRAN", "CABLE",
    "PRISE", "LAMPE", "BUREAU", "CHAISE", "PORTE", "TAPIS", "MIROIR", "HORLOGE",
)


def _history_with_builtin_terms_used(path: Path) -> None:
    """Historique ou toute la banque integree de mots croises a deja ete imprimee."""
    answers = [term.answer for term in daily_learning.TERMS]
    days = {}
    for index in range(0, len(answers), 6):
        day = dt.date(2026, 1, 1) + dt.timedelta(days=index // 6)
        entries = [
            CrosswordEntry(number=number + 1, answer=answer, clue="Deja imprime.",
                           row=number, column=0, direction="across")
            for number, answer in enumerate(answers[index:index + 6])
        ]
        days[day.isoformat()] = LearningPage(
            crossword=CrosswordPuzzle(entries=entries)).model_dump(mode="json")
    path.write_text(json.dumps({"version": 1, "days": days}), encoding="utf-8")


class SignalMatinRobustnessTests(unittest.TestCase):
    """Cas limites des sources et du rendu, sans reseau ni impression."""

    def test_weather_with_a_single_bound_still_renders(self):
        demo = construire_demo(dt.date(2026, 9, 26))
        for update, expected in (
            ({}, "Min 9 / Max 18 deg"),
            ({"high_c": None}, "Min 9 deg"),
            ({"low_c": None}, "Max 18 deg"),
        ):
            with self.subTest(update=update):
                weather = demo.weather.model_copy(update=update)
                html = render_html(demo.model_copy(update={"weather": weather}))
                self.assertIn(expected, html)
        weather = demo.weather.model_copy(update={"low_c": None})
        self.assertNotIn("Min 9", render_html(demo.model_copy(update={"weather": weather})))

    def test_illustration_only_embeds_images_from_the_dedicated_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "illustrations"
            folder.mkdir()
            image = folder / "gravure.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nIMAGE-FACTICE")
            secret = root / "secret.yaml"
            secret.write_text("cle_api: FAUSSE-VALEUR-123", encoding="utf-8")
            note = folder / "notes.txt"
            note.write_text("note privee", encoding="utf-8")

            def block(path: Path) -> str:
                item = NewsItem(
                    title="Sujet", summary="Resume.", source=SourceRef(name="Test"),
                    illustration=Illustration(type="image", path=str(path), alt="Gravure"),
                )
                return renderer.illustration_block(item)

            with patch.object(renderer, "ILLUSTRATIONS_DIR", folder):
                self.assertIn("data:image/png;base64,", block(image))
                for refused in (secret, folder / ".." / "secret.yaml", note):
                    with self.subTest(path=refused):
                        html = block(refused)
                        self.assertNotIn("base64", html)
                        self.assertIn("<svg", html)
                with patch.object(renderer, "ILLUSTRATION_MAX_OCTETS", 4):
                    self.assertNotIn("base64", block(image))

    def test_expanded_summaries_only_for_articles_sent_to_the_model(self):
        items = [
            NewsItem(title=f"Sujet {index}", summary="Resume RSS.",
                     source=SourceRef(name="Test", url=f"https://exemple.org/{index}"))
            for index in range(7)
        ]
        readable = {"https://exemple.org/0", "https://exemple.org/2", "https://exemple.org/5"}

        def answer(system, messages, max_tokens=0, nom_modele=""):
            # Le modele renvoie aussi des id qui ne lui ont jamais ete envoyes.
            return json.dumps([
                {"id": index, "developpe": f"Synthese {index}."} for index in (0, 2, 5, 3, 6)
            ])

        with patch.object(news_enrichment.cloud, "disponible", return_value=True), \
                patch.object(news_enrichment.cloud, "repondre_texte", side_effect=answer), \
                patch.object(news_enrichment, "reglage", side_effect=lambda key, default=None: default), \
                patch.object(news_enrichment, "_article_text",
                             side_effect=lambda url, **_: "Texte source. " * 60 if url in readable else ""):
            result = news_enrichment.enrichir_actualites(items, limite=7)
        self.assertEqual(
            [bool(item.expanded_summary) for item in result],
            [True, False, True, False, False, True, False],
        )

    def test_only_public_addresses_pass_the_download_filter(self):
        def resolve(host, *args, **kwargs):
            return [(0, 0, 0, "", (host, 0))]

        with patch.object(news_enrichment.socket, "getaddrinfo", side_effect=resolve):
            for url in (
                "http://100.64.0.1/", "http://100.100.100.100/", "http://224.0.0.1/",
                "http://127.0.0.1/", "http://192.168.1.10/", "http://0.0.0.0/",
                "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::7f00:1]/",
                "http://[fd7a:115c:a1e0::1]/", "http://[ff02::1]/",
            ):
                with self.subTest(url=url):
                    self.assertFalse(news_enrichment._public_http_url(url))
            self.assertTrue(news_enrichment._public_http_url("https://93.184.215.14/article"))

    def test_redirections_to_a_private_address_are_refused(self):
        routes = {
            "http://93.184.215.14/vers-local": (302, "http://127.0.0.1:8765/interne"),
            "http://93.184.215.14/vers-public": (302, "http://93.184.215.15/suite"),
            "http://127.0.0.1:8765/interne": (200, "<article><p>SECRET local du reseau</p></article>"),
            "http://93.184.215.15/suite": (200, "<article><p>Contenu public lisible</p></article>"),
        }
        opened: list[str] = []

        def fake_http_open(handler, request):
            # Aucune connexion reelle : chaque URL a une reponse simulee.
            opened.append(request.full_url)
            code, value = routes[request.full_url]
            headers = email.message.Message()
            if code == 302:
                headers["Location"] = value
                body = b""
            else:
                headers["Content-Type"] = "text/html; charset=utf-8"
                body = value.encode("utf-8")
            response = urllib.response.addinfourl(io.BytesIO(body), headers, request.full_url, code)
            response.msg = "Found" if code == 302 else "OK"
            return response

        def resolve(host, *args, **kwargs):
            return [(0, 0, 0, "", (host, 0))]

        with patch.object(urllib.request.HTTPHandler, "http_open", fake_http_open), \
                patch.object(news_enrichment.socket, "getaddrinfo", side_effect=resolve):
            with self.assertRaises(urllib.error.URLError):
                news_enrichment._download("http://93.184.215.14/vers-local")
            self.assertNotIn("http://127.0.0.1:8765/interne", opened)
            self.assertIn("Contenu public", news_enrichment._download("http://93.184.215.14/vers-public"))

    def test_crossword_never_places_a_word_longer_than_the_grid(self):
        terms = [
            daily_learning._Term(word, "Definition de test.")
            for word in ("VIRTUALISATION", "AUTHENTIFICATION")
        ]
        self.assertEqual(daily_learning._crossword(dt.date(2026, 10, 29), 0, terms).entries, [])

    def test_long_generated_terms_are_ignored_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "learning-history.json"
            _history_with_builtin_terms_used(history_path)

            def generator(_date, _used):
                words = ("VIRTUALISATION", "AUTHENTIFICATION", "INTEROPERABILITE", *GENERATED_WORDS)
                return [(word, f"Definition de {word.lower()}.") for word in words]

            for offset in range(3):
                page = construire_apprentissage_du_jour(
                    dt.date(2026, 10, 1) + dt.timedelta(days=offset),
                    history_path=history_path,
                    crossword_term_generator=generator,
                )
                self.assertEqual(len(page.crossword.entries), 6)
                self.assertTrue(all(len(entry.answer) <= 13 for entry in page.crossword.entries))
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertTrue(all(len(row["answer"]) <= 13 for row in history["reserve"]))

    def test_generated_reserve_survives_a_generator_outage(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "learning-history.json"
            _history_with_builtin_terms_used(history_path)
            calls: list[dt.date] = []

            def generator(date, _used):
                calls.append(date)
                return [(word, f"Definition de {word.lower()}.") for word in GENERATED_WORDS]

            def broken(date, _used):
                calls.append(date)
                raise RuntimeError("Ollama absent, cloud en panne")

            first = construire_apprentissage_du_jour(
                dt.date(2026, 10, 1), history_path=history_path,
                crossword_term_generator=generator,
            )
            self.assertEqual(len(first.crossword.entries), 6)
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(history["reserve"]), len(GENERATED_WORDS) - 6)

            # Le lendemain, la reserve suffit : le modele n'est ni appele ni necessaire.
            second = construire_apprentissage_du_jour(
                dt.date(2026, 10, 2), history_path=history_path,
                crossword_term_generator=broken,
            )
            self.assertIsNotNone(second.crossword)
            self.assertEqual(len(second.crossword.entries), 6)
            self.assertEqual(calls, [dt.date(2026, 10, 1)])
            self.assertTrue(
                {entry.answer for entry in first.crossword.entries}.isdisjoint(
                    {entry.answer for entry in second.crossword.entries})
            )

    def test_generated_crossword_terms_fit_the_grid(self):
        payload = json.dumps({"terms": [
            {"answer": "Virtualisation", "clue": "Quatorze lettres."},
            {"answer": "Abstractions", "clue": "Douze lettres."},
            {"answer": "Interoperable", "clue": "Treize lettres."},
        ]})
        with patch.object(learning_generation, "_request_text", return_value=payload):
            terms = learning_generation.generer_termes_mots_croises(dt.date(2026, 10, 29), frozenset())
        self.assertEqual([answer for answer, _ in terms], ["ABSTRACTIONS", "INTEROPERABLE"])

    @unittest.skipUnless(os.name == "nt", "PowerShell Windows requis")
    def test_first_brief_mode_warns_about_an_existing_print_task(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "installer_journal_matin.ps1"

        def run(task: str) -> str:
            # Planificateur simule : la lecture renvoie une tache factice et toute
            # ecriture echouerait. Aucune tache reelle n'est lue ni modifiee.
            fakes = (
                "function Register-ScheduledTask { throw 'interdit' }; "
                "function Disable-ScheduledTask { throw 'interdit' }; "
                "function Unregister-ScheduledTask { throw 'interdit' }; "
                f"function Get-ScheduledTask {{ param($TaskName) {task} }}; "
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", fakes + f"& '{script}' -Mode premier_demarrage -NomTache 'Tache factice' 3>&1"],
                capture_output=True, text=True, errors="replace", timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        printing = ("[pscustomobject]@{ State = 'Ready'; Actions = @("
                    "[pscustomobject]@{ Arguments = '-File x.ps1 -Imprimer -RectoVerso' }) }")
        self.assertIn('Unregister-ScheduledTask -TaskName "Tache factice"', run(printing))
        self.assertNotIn("Unregister-ScheduledTask", run(printing.replace("Ready", "Disabled")))
        self.assertNotIn("Unregister-ScheduledTask", run(printing.replace(" -Imprimer", "")))
        absent = run("$null")
        self.assertNotIn("Unregister-ScheduledTask", absent)
        self.assertNotIn("une seule fois", absent)

    def test_daily_task_duration_is_a_parameter_with_the_previous_default(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" /
                  "installer_journal_matin.ps1").read_text(encoding="utf-8")
        self.assertIn("[int]$DureeMaxMinutes = 15", script)
        self.assertIn("-ExecutionTimeLimit (New-TimeSpan -Minutes $DureeMaxMinutes)", script)
        self.assertNotIn("New-TimeSpan -Minutes 15", script)


class SignalMatinRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edition = normaliser_edition(
            construire_demo(dt.date(2026, 9, 26)), mode="extended")

    def test_no_major_overflow(self):
        # EXTENDED : la rubrique tech de la demo remonte sur la page « Ta journee »
        # au lieu d'occuper une page peu remplie (regroupement des pages creuses).
        expected = {
            DensityMode.COMPACT: 4,
            DensityMode.STANDARD: 7,
            DensityMode.EXTENDED: 6,
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
            self.assertEqual(len(reader.pages), 6)
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
        normal_pages = len(inspecter_html(render_html(self.edition)))
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_content(html, wait_until="load")
                page.evaluate("document.fonts.ready")
                result = _paginate_adaptive(page)
                layout = _measure(page)
                # Un contenu bien plus long que d'habitude cree des pages de suite.
                self.assertGreater(result["pages"], normal_pages)
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

    def test_carnet_et_pages_creuses_ne_coutent_jamais_une_page(self):
        # Cas reel : journee sans agenda, huit rappels. Avant, la colonne agenda
        # restait vide et le carnet partait seul sur une page a moitie blanche.
        demo = construire_demo(dt.date(2026, 9, 26))
        rappels = [TaskItem(title=f"Rappel {numero}") for numero in range(8)]
        edition = normaliser_edition(
            demo.model_copy(update={"agenda": [], "reminders": rappels}), mode="extended")
        html = render_html(edition)
        self.assertIn("day-grid-tasks", html)
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_content(html, wait_until="load")
                page.evaluate("document.fonts.ready")
                result = _paginate_adaptive(page)
                self.assertEqual(result["unresolved"], 0)
                pages_sans_contenu = page.evaluate("""() => [...document.querySelectorAll('.sheet')]
                  .filter(sheet => ![...sheet.querySelectorAll(':scope > .page-content > *')].some(node =>
                    !node.hidden && !node.classList.contains('page-filler')
                    && !node.classList.contains('section-header')
                    && !node.classList.contains('adaptive-section-header'))).length""")
                self.assertEqual(pages_sans_contenu, 0)
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
