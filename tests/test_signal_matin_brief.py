"""Brief Tech & IA : verification des citations, repli, historique et rendu (hors ligne)."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.signal_matin import sources, tech_brief
from core.signal_matin.mock_data import construire_demo
from core.signal_matin.models import (
    BriefFact, BriefSource, NewsItem, SourceRef, TechBrief,
)
from core.signal_matin.normalizer import ecrire_edition, normaliser_edition
from core.signal_matin.renderer import render_html

NOW = dt.datetime(2026, 10, 1, 8, 0, tzinfo=dt.timezone.utc)
VERGE = (
    "Google is releasing Gemini 4 Argon, says chief AI architect Koray Kavukcuoglu, "
    "but the company is limiting access at first to a set of trusted cyber defenders "
    "while it studies the risks. " * 20
)
TECHCRUNCH = (
    "ElevenLabs doubled its valuation to $22 billion. The recent $300 million tender offer "
    "gave employees an opportunity to sell their shares, the company said. " * 20
)
NUMERAMA = (
    "La Commission européenne a ouvert une consultation sur le droit d'auteur et l'IA générative. "
    "Les ayants droit demandent une rémunération des œuvres utilisées pour l'entraînement. " * 20
)


def _sources() -> dict[int, dict]:
    return {
        1: {"media": "The Verge", "titre": "Gemini 4", "url": "https://www.theverge.com/a",
            "date": NOW, "role": "actualite", "texte": VERGE},
        2: {"media": "TechCrunch", "titre": "ElevenLabs", "url": "https://techcrunch.com/b",
            "date": NOW, "role": "actualite", "texte": TECHCRUNCH},
        3: {"media": "Numerama", "titre": "Droit d'auteur", "url": "https://www.numerama.com/c",
            "date": NOW, "role": "actualite", "texte": NUMERAMA},
    }


def _brief_json() -> dict:
    return {
        "essentiel": ["Google restreint Gemini 4 [1].", "ElevenLabs vaut 22 milliards [2]."],
        "informations": [
            {"fait": "Google limite l'accès à Gemini 4 [1].",
             "citation": "the company is limiting access at first to a set of trusted cyber defenders",
             "traduction": "l'entreprise limite d'abord l'accès", "source": 1,
             "pourquoi": "Un modèle jugé trop risqué pour le grand public [1]."},
            {"fait": "ElevenLabs double sa valorisation [2].",
             "citation": "The recent $300 million tender offer gave employees an opportunity",
             "traduction": "", "source": 2, "pourquoi": "Les salariés peuvent vendre [2]."},
            {"fait": "Bruxelles consulte sur le droit d'auteur [3].",
             "citation": "La Commission européenne a ouvert une consultation",
             "traduction": "", "source": 3, "pourquoi": "Enjeu de rémunération [3]."},
            # Paraphrase deguisee en citation (cas reel observe) : doit etre retiree.
            {"fait": "Google restreint Gemini 4.",
             "citation": "Google is limiting access at first to a set of trusted cyber defenders",
             "traduction": "", "source": 1, "pourquoi": ""},
        ],
        "analyses": [{
            "sujet": "Modèles à accès restreint",
            "faits": 'Google parle de « trusted cyber defenders » [1]. '
                     'Il aurait dit « we will never release it publicly » [1]. Autre phrase [9].',
            "contexte": "Contexte sourcé [3].", "geopolitique": "", "economie": "Valorisation [2].",
            "gagnants_perdants": "", "lectures_divergentes": "", "incertain": "Inconnu.",
            "confiance": "Moyen",
        }],
        "fil_rouge": [{"lien": "Sécurité et régulation avancent ensemble [1, 3].", "nature": "interprétation"}],
        "questions": ["Qui décide de l'accès ?"], "angles_morts": ["Peu de voix européennes."],
        "a_surveiller": ["Ouverture plus large de Gemini 4."], "non_etabli": ["Le prix."],
    }


class CitationTest(unittest.TestCase):
    def test_citation_exacte_malgre_la_typographie(self):
        self.assertTrue(tech_brief.citation_verifiee(
            "œuvres utilisées pour l’entraînement", NUMERAMA))
        self.assertTrue(tech_brief.citation_verifiee(
            "Les ayants droit demandent une rémunération", NUMERAMA.replace(" ", " ", 3)))
        self.assertTrue(tech_brief.citation_verifiee(
            "« gave employees an opportunity »", TECHCRUNCH))

    def test_paraphrase_deguisee_refusee(self):
        # Hermes avait remplace « the company » par « Google » entre guillemets.
        self.assertFalse(tech_brief.citation_verifiee(
            "Google is limiting access at first to a set of trusted cyber defenders", VERGE))

    def test_citation_trop_courte_ou_trop_longue_refusee(self):
        self.assertFalse(tech_brief.citation_verifiee("the company", VERGE))
        self.assertFalse(tech_brief.citation_verifiee(" ".join(VERGE.split()[:30]), VERGE))


class AssemblageTest(unittest.TestCase):
    def test_retire_les_fausses_citations_et_les_references_inconnues(self):
        retraits: list[str] = []
        brief, verifiees = tech_brief._assembler(_brief_json(), _sources(), NOW.date(), retraits)
        self.assertIsNotNone(brief)
        self.assertEqual(verifiees, 3)
        self.assertEqual(len(brief.facts), 3)
        self.assertTrue(any("citation introuvable dans [1]" in r for r in retraits))
        faits = brief.analyses[0].facts
        self.assertIn("trusted cyber defenders", faits)
        self.assertNotIn("never release it publicly", faits)
        self.assertNotIn("[9]", faits)
        self.assertEqual(brief.analyses[0].confidence, "moyen")
        self.assertEqual(brief.title, "Brief Tech & IA – 1er octobre 2026")
        self.assertEqual({s.id for s in brief.sources}, {1, 2, 3})

    def test_traduction_entre_parentheses_conservee(self):
        texte = 'Google évoque « a set of trusted cyber defenders » (« un groupe de défenseurs de confiance ») [1].'
        retraits: list[str] = []
        self.assertIn("défenseurs de confiance",
                      tech_brief._verifier_texte(texte, _sources(), retraits))
        self.assertEqual(retraits, [])

    def test_une_page_de_contexte_ne_devient_pas_une_information_du_jour(self):
        sources_ = _sources()
        sources_[2]["role"] = "contexte"
        retraits: list[str] = []
        brief, _ = tech_brief._assembler(_brief_json(), sources_, NOW.date(), retraits)
        self.assertNotIn(2, [f.source_id for f in brief.facts])
        self.assertTrue(any("page de contexte non datée [2]" in r for r in retraits))

    def test_moins_de_deux_informations_verifiees_donne_none(self):
        donnees = _brief_json()
        donnees["informations"] = donnees["informations"][3:]
        brief, _ = tech_brief._assembler(donnees, _sources(), NOW.date(), [])
        self.assertIsNone(brief)


class HistoriqueTest(unittest.TestCase):
    def test_le_jour_meme_est_ignore_et_les_jours_passes_exclus(self):
        historique = {"jours": {
            "2026-09-30": [{"sujet": "Hier", "url": "https://a"}],
            "2026-10-01": [{"sujet": "Aujourd'hui", "url": "https://b"}],
            "2026-09-01": [{"sujet": "Trop vieux", "url": "https://c"}],
        }}
        urls, sujets = tech_brief.deja_traites(historique, NOW.date(), 14)
        self.assertEqual(urls, {"https://a"})
        self.assertEqual(sujets, ["2026-09-30 : Hier"])


def _reglages(valeurs: dict):
    return lambda cle, defaut=None: valeurs.get(cle, defaut)


class ChaineCompleteTest(unittest.TestCase):
    def _candidats(self) -> list[NewsItem]:
        return [
            NewsItem(title=titre, summary="Résumé.", category="Tech",
                     source=SourceRef(name=media, url=url, published_at=NOW))
            for media, titre, url in (
                ("The Verge", "Gemini 4", "https://www.theverge.com/a"),
                ("TechCrunch", "ElevenLabs", "https://techcrunch.com/b"),
                ("Numerama", "Droit d'auteur", "https://www.numerama.com/c"),
                ("Wired", "Divertissement", "https://www.wired.com/d"),
            )
        ]

    def _cloud(self, appels: list[str]):
        def repondre(systeme, historique, max_tokens=500, nom_modele="", qualite=False):
            appels.append(nom_modele)
            if "chef d'édition" in systeme:
                return json.dumps({"articles": [0, 1, 2], "approfondir": [{"sujet": "Gemini 4", "recherche": "accès restreint"}]})
            return json.dumps(_brief_json(), ensure_ascii=False)
        return repondre

    def test_brief_construit_verifie_et_historise(self):
        textes = {"https://www.theverge.com/a": VERGE, "https://techcrunch.com/b": TECHCRUNCH,
                  "https://www.numerama.com/c": NUMERAMA}
        appels: list[str] = []
        reglages = {"signal_matin.brief_tech": True, "signal_matin.brief_contexte": "aucun",
                    "signal_matin.modele_brief": "gpt-5.6-terra"}
        with tempfile.TemporaryDirectory() as dossier, \
                patch.object(tech_brief, "reglage", _reglages(reglages)), \
                patch.object(tech_brief.cloud, "disponible", return_value=True), \
                patch.object(tech_brief.cloud, "repondre_texte", side_effect=self._cloud(appels)), \
                patch.object(tech_brief, "_article_text", side_effect=lambda url, **_: textes.get(url, "")):
            chemin = Path(dossier) / "historique.json"
            rapport: dict = {}
            brief = tech_brief.construire_brief(
                self._candidats(), NOW, allow_proxy=False, historique_path=chemin, rapport=rapport)
            self.assertIsNotNone(brief, rapport)
            self.assertEqual(rapport["etat"], "ok")
            self.assertEqual(len(brief.facts), 3)
            self.assertIn("gpt-5.6-terra", appels)  # redaction et relecture
            self.assertIn("3 citations retrouvées", brief.verification)
            historique = json.loads(chemin.read_text(encoding="utf-8"))
            self.assertIn("2026-10-01", historique["jours"])

            # Le lendemain, les articles deja utilises sont ecartes du tri.
            lendemain = NOW + dt.timedelta(days=1)
            vus = tech_brief.deja_traites(historique, lendemain.date(), 14)[0]
            self.assertIn("https://www.theverge.com/a", vus)

    def test_desactive_ou_sans_cloud_renvoie_none(self):
        with patch.object(tech_brief, "reglage", _reglages({"signal_matin.brief_tech": False})):
            self.assertIsNone(tech_brief.construire_brief(self._candidats(), NOW, allow_proxy=False))
        with patch.object(tech_brief, "reglage", _reglages({"signal_matin.brief_tech": True})), \
                patch.object(tech_brief.cloud, "disponible", return_value=False):
            self.assertIsNone(tech_brief.construire_brief(self._candidats(), NOW, allow_proxy=False))

    def test_echec_du_brief_rend_la_main_au_cahier_classique(self):
        with patch.object(sources, "construire_brief", side_effect=RuntimeError("panne")):
            brief, statut = sources._tech_brief(self._candidats(), NOW, True, allow_proxy=False)
        self.assertIsNone(brief)
        self.assertEqual(statut.state.value, "unavailable")
        self.assertIn("Cahier tech classique", statut.detail)


class ContexteWebTest(unittest.TestCase):
    def _faux_ddgs(self, requetes: list[str]):
        class FauxDDGS:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def text(self, requete, region="", max_results=0):
                requetes.append(requete)
                return [
                    {"href": "https://www.techcrunch.com/deja-lu", "title": "Deja lu"},
                    {"href": "https://www.reuters.com/a", "title": "Contexte A"},
                    {"href": "javascript:alert(1)", "title": "Piege"},
                    {"href": "https://arstechnica.com/b", "title": "Contexte B"},
                    {"href": "https://example.org/c", "title": "Contexte C"},
                    {"href": "https://seo-blog.example/d", "title": "Contexte D"},
                ]
        return type("M", (), {"DDGS": FauxDDGS})

    def test_le_modele_trie_les_sources_fiables(self):
        requetes: list[str] = []
        rapport: dict = {}
        with patch.dict("sys.modules", {"ddgs": self._faux_ddgs(requetes)}), \
                patch.object(tech_brief, "_cloud", return_value='{"choix": [1, 0]}'):
            pistes = tech_brief._pistes_web(
                [{"sujet": "Gemini 4", "recherche": "modeles a acces restreint"}],
                {"https://www.techcrunch.com/deja-lu"}, rapport)
        # Les deux requetes sont faites ; URL deja lue et lien piege ecartes avant le tri.
        self.assertEqual(requetes, ["modeles a acces restreint", "Gemini 4"])
        self.assertEqual([p["url"] for p in pistes],
                         ["https://arstechnica.com/b", "https://www.reuters.com/a"])
        self.assertEqual(pistes[1]["media"], "reuters.com")
        self.assertEqual(rapport["contexte"], {"source": "web", "candidats": 4, "pistes": 2})

    def test_tri_en_panne_garde_les_premiers_resultats(self):
        with patch.dict("sys.modules", {"ddgs": self._faux_ddgs([])}), \
                patch.object(tech_brief, "_cloud", side_effect=RuntimeError("cloud")):
            rapport: dict = {}
            pistes = tech_brief._pistes_web([{"sujet": "x"}], set(), rapport)
        self.assertEqual(len(pistes), 3)
        self.assertEqual(rapport["tri_contexte"], "repli sur l'ordre du moteur")

    def test_panne_de_recherche_ne_bloque_pas_le_brief(self):
        class EnPanne:
            def __enter__(self):
                raise RuntimeError("limite atteinte")

            def __exit__(self, *args):
                return False

        rapport: dict = {}
        with patch.dict("sys.modules", {"ddgs": type("M", (), {"DDGS": EnPanne})}):
            self.assertEqual(tech_brief._pistes_web([{"sujet": "x"}], set(), rapport), [])
        self.assertIn("indisponible", rapport["contexte"])


class RSSTest(unittest.TestCase):
    def test_un_resume_geant_ne_fait_plus_perdre_le_flux(self):
        flux = f"""<?xml version="1.0"?><rss><channel>
        <item><title>Normal</title><link>https://exemple.org/1</link><description>Court.</description></item>
        <item><title>Geant</title><link>https://exemple.org/2</link><description>{"x" * 3000}</description></item>
        </channel></rss>""".encode()

        class Reponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return flux

        with patch.object(sources.urllib.request, "urlopen", return_value=Reponse()):
            items, _ = sources._collect_rss(
                [{"nom": "Test", "url": "https://exemple.org/rss"}], NOW,
                limit=4, max_age_hours=72, status_name="Test",
                state=sources.DataState.LIVE, detail="test")
        self.assertEqual([i.title for i in items], ["Normal", "Geant"])
        self.assertEqual(len(items[1].summary), 1600)


class RenduTest(unittest.TestCase):
    def _edition(self):
        brief = TechBrief(
            title="Brief Tech & IA – 1er octobre 2026",
            essentials=["Google restreint Gemini 4 [1]."],
            facts=[BriefFact(fact="Google limite l'accès [1].", quote="limiting access at first",
                             translation="limite d'abord l'accès", source_id=1, why="Risque [1].")],
            sources=[BriefSource(id=1, name="The Verge", url="https://www.theverge.com/a", published_at=NOW)],
            verification="1 citation retrouvée.",
        )
        demo = construire_demo(dt.date(2026, 10, 1))
        return normaliser_edition(demo.model_copy(update={"tech_brief": brief}), mode="standard")

    def test_le_brief_remplace_le_cahier_tech_sans_url_imprimee(self):
        html = render_html(self._edition())
        self.assertIn("Brief Tech &amp; IA – 1er octobre 2026", html)
        self.assertIn("L'essentiel en 5 lignes", html)
        self.assertIn("« limiting access at first »", html)
        self.assertIn('<span class="tb-ref">The Verge</span>', html)
        self.assertNotIn("theverge.com", html)
        self.assertNotIn("Comprendre ce qui change vraiment", html)

    def test_sans_brief_le_cahier_tech_reste_et_le_json_ne_change_pas(self):
        demo = normaliser_edition(construire_demo(dt.date(2026, 10, 1)), mode="standard")
        self.assertIn("Technologie &amp; IA", render_html(demo))
        with tempfile.TemporaryDirectory() as dossier:
            chemin = ecrire_edition(demo, Path(dossier) / "edition.json")
            self.assertNotIn("tech_brief", json.loads(chemin.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
