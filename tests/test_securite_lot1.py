"""Correctifs de l'audit de securite (lot 1) : pages locales, confirmations, MCP, fuites."""
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import http_local, panneau, registre

ROOT = Path(__file__).resolve().parents[1]
registre.charger_outils()


class RequeteLocaleTest(unittest.TestCase):
    def test_host_local_accepte(self):
        for host in ("127.0.0.1:8790", "localhost:8770", "[::1]:8790", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertTrue(http_local.requete_locale("127.0.0.1", {"host": host}))

    def test_dns_rebinding_refuse(self):
        # Un domaine externe qui pointe vers 127.0.0.1 : la socket est locale, pas le Host.
        for host in ("evil.example:8790", "127.0.0.1.evil.example", "", "localhost.evil:80"):
            with self.subTest(host=host):
                self.assertFalse(http_local.requete_locale("127.0.0.1", {"host": host}))

    def test_tunnel_et_reseau_refuses(self):
        self.assertFalse(http_local.requete_locale(
            "127.0.0.1", {"host": "127.0.0.1:8790", "x-forwarded-for": "1.2.3.4"}))
        self.assertFalse(http_local.requete_locale("192.168.1.42", {"host": "127.0.0.1:8790"}))

    def test_origine(self):
        self.assertTrue(http_local.origine_locale(None))
        self.assertTrue(http_local.origine_locale("http://127.0.0.1:8790"))
        self.assertFalse(http_local.origine_locale("https://evil.example"))
        self.assertFalse(http_local.origine_locale("null"))


def _client_panneau(base="http://127.0.0.1:8790"):
    app = FastAPI()
    panneau.monter_routes(app)
    return TestClient(app, base_url=base)


class PanneauTest(unittest.TestCase):
    def setUp(self):
        # Le client de test n'a pas d'adresse IP reelle : on l'assimile au poste local.
        self._adresses = patch.object(http_local, "_ADRESSES_LOCALES", {"127.0.0.1", "::1", "testclient"})
        self._adresses.start()

    def tearDown(self):
        self._adresses.stop()

    def _poster(self, client, entetes):
        with patch.object(panneau, "_whisper_supprimer", return_value={"ok": True}) as suppr:
            r = client.post("/api/panneau/whisper/supprimer", content=json.dumps({"nom": "small"}),
                            headers=entetes)
        return r, suppr

    def test_csrf_par_type_mime_deguise_refuse(self):
        r, suppr = self._poster(_client_panneau(), {"Content-Type": "text/plain; application/json",
                                                    "X-Jarvis-Panneau": "1"})
        self.assertEqual(r.status_code, 415)
        suppr.assert_not_called()

    def test_ecriture_sans_entete_panneau_ou_origine_externe_refusee(self):
        client = _client_panneau()
        r, suppr = self._poster(client, {"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 403)
        r, _ = self._poster(client, {"Content-Type": "application/json", "X-Jarvis-Panneau": "1",
                                     "Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        suppr.assert_not_called()

    def test_requete_legitime_acceptee(self):
        r, suppr = self._poster(_client_panneau(), {"Content-Type": "application/json",
                                                    "X-Jarvis-Panneau": "1",
                                                    "Origin": "http://127.0.0.1:8790"})
        self.assertEqual(r.status_code, 200)
        suppr.assert_called_once_with("small")

    def test_dns_rebinding_refuse_meme_en_lecture(self):
        r = _client_panneau("http://evil.example:8790").get("/api/panneau/modeles")
        self.assertEqual(r.status_code, 403)

    def test_suppression_whisper_jamais_hors_du_cache(self):
        with patch.object(panneau.shutil, "rmtree") as rmtree:
            for nom in ("x/../../../..", "..", "small/../..", "C:\\Users"):
                with self.subTest(nom=nom):
                    self.assertFalse(panneau._whisper_supprimer(nom)["ok"])
        rmtree.assert_not_called()

    def test_noms_de_modeles_valides(self):
        for nom in ("qwen2.5:7b", "hf.co/org/modele:Q4_K_M", "gpt-5.6-terra"):
            self.assertTrue(panneau._nom_valide(nom), nom)
        for nom in ("--help", "a b", "../x", "", "x" * 200, "a&calc"):
            self.assertFalse(panneau._nom_valide(nom), nom)

    def test_pages_non_integrables(self):
        with patch.object(panneau, "_HTML", MagicMock(exists=lambda: True, read_text=lambda **k: "<p>x</p>")):
            r = _client_panneau().get("/panneau")
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")


class ConfirmationsTest(unittest.TestCase):
    def test_tout_n3_demande_une_confirmation(self):
        for nom in registre._N3:
            outil = registre.get(nom)
            if outil is None:          # outil optionnel absent de cette machine
                continue
            with self.subTest(outil=nom):
                self.assertTrue(outil.confirmation, f"{nom} est N3 mais s'execute sans confirmation")
                self.assertEqual(registre.niveau(nom), "N3")

    def test_outils_sensibles_confirmes(self):
        for nom in ("book_appointment", "browser_interact", "start_stream", "start_record",
                    "ajouter_app", "controle_pc_astra"):
            with self.subTest(outil=nom):
                self.assertTrue(registre.get(nom).confirmation)
        self.assertFalse(registre.est_autorise("ajouter_app"))   # jamais « toujours »

    def test_annonces_completes(self):
        self.assertIn("C:\\jeu.exe", registre.get("ajouter_app").annonce({"nom": "jeu", "chemin": "C:\\jeu.exe"}))
        self.assertIn("ouvrir mes mails", registre.get("controle_pc_astra").annonce({"tache": "ouvrir mes mails"}))

    def test_ouvrir_application_ne_lance_jamais_un_nom_inconnu(self):
        from tools import systeme
        with patch("core.poste_distant.executer_principal", return_value=None), \
                patch.object(systeme.os, "startfile", create=True) as startfile, \
                patch("tools.apps.launch_app", return_value="inconnu") as launch:
            for nom in ("\\\\hote\\partage\\a.exe", "C:\\Users\\x\\Downloads\\a.exe", "ms-msdt:x"):
                with self.subTest(nom=nom):
                    systeme.ouvrir_application(nom)
            startfile.assert_not_called()
            self.assertEqual(launch.call_count, 3)

    def test_ajouter_app_refuse_un_partage_reseau(self):
        from tools import apps
        with patch.object(apps, "definir") as definir:
            self.assertIn("partage reseau", apps.ajouter_app("x", "\\\\hote\\s\\a.exe"))
        definir.assert_not_called()


class AstraTest(unittest.TestCase):
    def test_satellite_refuse_astra(self):
        from core import satellite
        from core.routage_intentions import Decision
        with patch("tools.astra_pc.executer_controle") as controle:
            reponse = satellite._executer_decision_prioritaire(
                MagicMock(historique=[]), Decision("astra", tache="ouvre le terminal"))
            self.assertIn("devant l'ordinateur", satellite._executer_outil("controle_pc_astra", {"tache": "x"}))
        controle.assert_not_called()
        self.assertFalse(reponse["attente_confirmation"])

    def test_poste_principal_confirme_astra(self):
        # jarvis14 est trop lourd a importer (micro, Whisper) : controle statique.
        source = (ROOT / "jarvis14.py").read_text(encoding="utf-8")
        self.assertIn('decision = Decision("outil", "controle_pc_astra", {"tache": decision.tache})', source)
        self.assertNotIn("texte = executer_controle(decision.tache)", source)


class McpTest(unittest.TestCase):
    def test_jamais_d_outil_a_confirmation_ni_interdit_par_la_doctrine(self):
        interdits = {"lumieres", "amaran", "alexa", "gestes", "modes", "obs", "finances", "factures"}
        for o in registre.exposes_mcp():
            with self.subTest(outil=o.nom):
                self.assertFalse(o.confirmation)
                self.assertFalse(registre.est_n3(o.nom))
                self.assertNotIn(o.fonction.__module__.split(".")[-1], interdits - {"obs"})
                if o.fonction.__module__.endswith("obs"):
                    self.assertEqual(o.nom, "stop_record")

    def test_serveur_mcp_sans_auto_confirmation(self):
        source = (ROOT / "jarvis" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertNotIn('k.pop("confirm"', source)


class PontIphoneTest(unittest.TestCase):
    def _client(self):
        from core import pont_iphone
        app = FastAPI()
        pont_iphone.monter_routes(app)
        return TestClient(app), pont_iphone

    def test_jeton_verifie_avant_de_lire_le_corps_et_taille_bornee(self):
        client, pont = self._client()
        with patch.object(pont, "reglage", lambda cle, defaut=None: {"pont_iphone.token": "bon"}.get(cle, defaut)):
            self.assertEqual(client.post("/api/inbox", content=b"x" * 10).status_code, 401)
            r = client.post("/api/inbox", content=b"x" * (pont._TAILLE_MAX_INBOX + 1),
                            headers={"X-Jarvis-Token": "bon"})
        self.assertEqual(r.status_code, 413)


class FuitesTest(unittest.TestCase):
    def test_jeton_instagram_masque(self):
        from tools import instagram
        erreur = Exception("HTTPSConnectionPool: /me?fields=x&access_token=SECRET123&y=1")
        self.assertNotIn("SECRET123", instagram._erreur_sans_secret(erreur))
        source = (ROOT / "tools" / "instagram.py").read_text(encoding="utf-8")
        self.assertNotIn('lecture impossible ({e})', source)

    def test_documentation_api_fermee_sur_le_serveur_public(self):
        source = (ROOT / "core" / "serveur.py").read_text(encoding="utf-8")
        self.assertIn("docs_url=None, redoc_url=None, openapi_url=None", source)

    def test_hud_verifie_le_host(self):
        source = (ROOT / "hud.py").read_text(encoding="utf-8")
        self.assertIn("requete_locale(self.client_address[0], self.headers)", source)
        self.assertIn("if not self._locale():\n            return\n        chemin = self.path", source)


if __name__ == "__main__":
    unittest.main()
