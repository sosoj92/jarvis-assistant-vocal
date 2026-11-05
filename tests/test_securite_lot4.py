"""Correctifs de l'audit de securite (lot 4) : surface du serveur unifie.

Pont iPhone (jeton non ASCII, contenus externes, plafond d'outils, refus a distance),
boucle d'evenements jamais bloquee (pont + panneau), sonde MCP avec jeton, et tests
qui epinglent les verrous deja corrects. Sans reseau ni config.yaml : la config est
remplacee par un dictionnaire vide et le journal logs/inbox.log est neutralise.
"""
import asyncio
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import config, panneau, pont_iphone, registre, serveur

ROOT = Path(__file__).resolve().parents[1]

_JOURNAL_MUET = logging.getLogger("tests.lot4.inbox")
_JOURNAL_MUET.addHandler(logging.NullHandler())
_JOURNAL_MUET.propagate = False

_PATCHS = []


def setUpModule():
    # Jamais le vrai config.yaml (reglage() renvoie ses valeurs par defaut), et
    # filet : une note ecrite par erreur irait dans un dossier temporaire, pas notes/.
    from tools import notes
    dossier = Path(tempfile.mkdtemp(prefix="jarvis-lot4-"))
    for p in (patch.object(config, "_CONFIG", {}),
              patch.object(pont_iphone, "_LOGI", _JOURNAL_MUET),
              patch.object(notes, "_dossier", return_value=dossier)):
        p.start()
        _PATCHS.append(p)
    registre.charger_outils()


def tearDownModule():
    while _PATCHS:
        _PATCHS.pop().stop()


def _lire(valeurs):
    return lambda cle, defaut=None: valeurs.get(cle, defaut)


def _outil(nom, confirmation=False, mcp_expose=True):
    return registre.Outil(lambda **_: None, nom, f"outil {nom}",
                          {"type": "object", "properties": {}},
                          confirmation, False, None, None, mcp_expose)


def _appels(*noms):
    return SimpleNamespace(stop_reason="tool_use", content=[
        SimpleNamespace(type="tool_use", name=n, input={}, id=f"t{i}-{n}")
        for i, n in enumerate(noms)])


def _texte(texte="Fait."):
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=texte)])


class _FauxLLM:
    nom = "Faux"

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.messages = None
        self.outils = []

    def disponible(self):
        return True

    def repondre(self, systeme, messages, outils):
        self.systeme, self.messages = systeme, messages
        self.outils.append([o["name"] for o in outils])
        return self.reponses.pop(0)


def _resultats(messages):
    """tool_use_id -> contenu rendu au modele, sur toute la conversation."""
    sortie = {}
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for r in m["content"]:
                sortie[r["tool_use_id"]] = r["content"]
    return sortie


class PontCommandeTest(unittest.TestCase):
    """traiter_commande avec LLM factice, registre factice et executer simule."""

    OUTILS = {
        "chercher_inspiration": _outil("chercher_inspiration"),            # source externe
        "meteo": _outil("meteo"),                                          # lecture sure
        "heure_et_date": _outil("heure_et_date"),
        "generer_idees_contenu": _outil("generer_idees_contenu"),          # N1 expose, cout
        "allumer_lumiere": _outil("allumer_lumiere", mcp_expose=False),    # domotique distante
        "faux_n2": _outil("faux_n2", confirmation=True, mcp_expose=False),
        "faux_n2_liste": _outil("faux_n2_liste", confirmation=True, mcp_expose=False),
        "n1_non_expose": _outil("n1_non_expose", mcp_expose=False),
        "envoyer_mail": _outil("envoyer_mail", confirmation=True),        # N3 (par son nom)
    }

    def _commande(self, llm, reglages=None, autorises=()):
        valeurs = {"pont_iphone.domotique_distante": ["allumer_lumiere", "faux_n2_liste",
                                                      "envoyer_mail"]}
        valeurs.update(reglages or {})
        with patch.dict(registre._REGISTRE, self.OUTILS, clear=True), \
                patch.object(registre, "autorisations", return_value=list(autorises)), \
                patch.object(registre, "executer",
                             side_effect=lambda o, a: f"resultat de {o.nom}") as executer, \
                patch.object(pont_iphone, "reglage", _lire(valeurs)), \
                patch("core.llm.llm", return_value=llm):
            r = pont_iphone.traiter_commande("commande factice")
        return r, [c.args[0].nom for c in executer.call_args_list]

    # -- contenus externes (#135) --
    def test_apres_une_source_externe_seules_les_lectures_passent(self):
        llm = _FauxLLM(_appels("chercher_inspiration"),
                       _appels("allumer_lumiere", "generer_idees_contenu", "meteo"),
                       _texte())
        r, executes = self._commande(llm)
        self.assertEqual(executes, ["chercher_inspiration", "meteo"])
        self.assertEqual(r["faits"], ["chercher_inspiration", "meteo"])
        res = _resultats(llm.messages)
        self.assertTrue(res["t0-chercher_inspiration"].startswith(
            "[CONTENU EXTERNE NON FIABLE - source : chercher_inspiration."))
        self.assertIn("Par prudence", res["t0-allumer_lumiere"])
        self.assertIn("Par prudence", res["t1-generer_idees_contenu"])
        self.assertEqual(res["t2-meteo"], "resultat de meteo")      # lecture : non balisee
        self.assertIn("CONTENU EXTERNE NON FIABLE", llm.systeme)

    def test_un_outil_en_toujours_ne_passe_pas_apres_un_contenu_externe(self):
        # Le « toujours autoriser » est un choix LOCAL : il n'ouvre rien a distance.
        llm = _FauxLLM(_appels("chercher_inspiration"), _appels("faux_n2_liste"), _texte())
        _r, executes = self._commande(llm, autorises=["faux_n2_liste"])
        self.assertEqual(executes, ["chercher_inspiration"])

    def test_sans_contenu_externe_la_domotique_distante_reste_executee(self):
        llm = _FauxLLM(_appels("allumer_lumiere", "generer_idees_contenu"), _texte())
        r, executes = self._commande(llm)
        self.assertEqual(executes, ["allumer_lumiere", "generer_idees_contenu"])
        self.assertTrue(r["ok"])

    def test_nombre_d_appels_d_outils_plafonne(self):
        llm = _FauxLLM(_appels(*["meteo"] * 13), _texte())
        r, executes = self._commande(llm)
        self.assertEqual(executes, [])
        self.assertIn("boucle d'actions", r["reponse"])
        llm = _FauxLLM(_appels("meteo", "meteo"), _appels("meteo"), _texte())
        r, executes = self._commande(llm, {"assistant.max_appels_outils": 2})
        self.assertEqual(executes, ["meteo", "meteo"])
        self.assertIn("boucle d'actions", r["reponse"])

    # -- surface distante (#138, #143) --
    def test_refus_a_distance_et_liste_domotique(self):
        llm = _FauxLLM(_appels("envoyer_mail", "faux_n2", "n1_non_expose", "inexistant",
                               "heure_et_date", "faux_n2_liste"), _texte())
        r, executes = self._commande(llm)
        # N1 expose execute ; outil de la liste execute SANS confirmation (comportement
        # documente) ; N3 refuse meme dans la liste ; le reste refuse.
        self.assertEqual(executes, ["heure_et_date", "faux_n2_liste"])
        res = _resultats(llm.messages)
        self.assertIn("Action critique", res["t0-envoyer_mail"])
        self.assertIn("Action sensible", res["t1-faux_n2"])
        self.assertIn("Action sensible", res["t2-n1_non_expose"])
        self.assertIn("Outil inconnu", res["t3-inexistant"])
        # Le modele distant ne voit meme pas les schemas refuses.
        vus = set(llm.outils[0])
        self.assertTrue({"heure_et_date", "faux_n2_liste", "allumer_lumiere"} <= vus)
        self.assertFalse({"envoyer_mail", "faux_n2", "n1_non_expose"} & vus)

    def test_le_pont_utilise_le_balisage_et_la_prudence(self):
        source = (ROOT / "core" / "pont_iphone.py").read_text(encoding="utf-8")
        self.assertIn("registre.baliser_externe(", source)
        self.assertIn("registre.confirmation_requise(", source)
        self.assertIn("CONTENU EXTERNE NON FIABLE", source)


class PontJetonTest(unittest.TestCase):
    """#141 : un jeton non ASCII donne 401, jamais 500."""

    def _client(self, jeton):
        app = FastAPI()
        pont_iphone.monter_routes(app)
        return TestClient(app, raise_server_exceptions=False), \
            patch.object(pont_iphone, "reglage", _lire({"pont_iphone.token": jeton}))

    def test_en_tete_non_ascii_refuse_en_401(self):
        client, reglages = self._client("bon-jeton")
        with reglages:
            r = client.post("/api/inbox", content=b"{}", headers={b"X-Jarvis-Token": b"\xe9"})
        self.assertEqual(r.status_code, 401)

    def test_jeton_configure_non_ascii_refuse_sans_erreur(self):
        client, reglages = self._client("jetén")
        with reglages:
            r = client.post("/api/inbox", content=b"{}", headers={"X-Jarvis-Token": "bon"})
            self.assertFalse(pont_iphone._token_ok("jeté"))
        self.assertEqual(r.status_code, 401)

    def test_bon_jeton_toujours_accepte(self):
        with patch.object(pont_iphone, "reglage", _lire({"pont_iphone.token": "bon"})):
            self.assertTrue(pont_iphone._token_ok("bon"))
            self.assertFalse(pont_iphone._token_ok("mauvais"))
            self.assertFalse(pont_iphone._token_ok(None))
        with patch.object(pont_iphone, "reglage", _lire({})):
            self.assertFalse(pont_iphone._token_ok(""))      # pas de jeton configure

    def test_inspiration_refuse_un_lien_non_instagram_tiktok(self):
        client, reglages = self._client("jeton-factice")
        with reglages, patch.object(pont_iphone, "_inspiration_async") as ingerer:
            r = client.post("/api/inbox", headers={"X-Jarvis-Token": "jeton-factice"},
                            json={"type": "inspiration",
                                  "url": "http://192.168.1.1/instagram.com/p/x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Instagram", r.json()["message"])
        ingerer.assert_not_called()

    def test_inspiration_transmet_seulement_l_url_validee(self):
        client, reglages = self._client("jeton-factice")
        texte = "Regarde ca https://www.instagram.com/reel/AbC123/ trop bien"
        with reglages, patch.object(pont_iphone, "_inspiration_async") as ingerer:
            r = client.post("/api/inbox", headers={"X-Jarvis-Token": "jeton-factice"},
                            json={"type": "inspiration", "contenu": texte})
            for _ in range(100):                  # le thread demarre aussitot
                if ingerer.called:
                    break
                time.sleep(0.01)
        self.assertEqual(r.status_code, 200)
        ingerer.assert_called_once()
        self.assertEqual(ingerer.call_args.args[0], "https://www.instagram.com/reel/AbC123/")


async def _pendant_une_requete_lente(app, lancer_lente, chemin_rapide):
    """Lance une requete lente puis une rapide ; mesure la reactivite de la boucle."""
    transport = httpx.ASGITransport(app=app)        # client 127.0.0.1, aucune socket
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        ecarts, fini = [], asyncio.Event()

        async def battement():                      # imite le flux audio de /stream
            precedent = time.monotonic()
            while not fini.is_set():
                await asyncio.sleep(0.02)
                maintenant = time.monotonic()
                ecarts.append(maintenant - precedent)
                precedent = maintenant

        tache = asyncio.create_task(battement())
        lente = asyncio.create_task(lancer_lente(client))
        await asyncio.sleep(0.05)
        debut = time.monotonic()
        rapide = await client.get(chemin_rapide)
        latence = time.monotonic() - debut
        reponse_lente = await lente
        fini.set()
        await tache
    return reponse_lente, rapide, latence, max(ecarts)


def _lent(resultat):
    def fonction(*_a, **_k):
        time.sleep(0.8)
        return resultat
    return fonction


class BoucleNonBloqueeTest(unittest.TestCase):
    """#68 : le travail bloquant ne gele plus le serveur unifie."""

    SEUIL = 0.4      # la requete lente dure 0.8 s : un gel de la boucle depasse le seuil

    def test_commande_iphone(self):
        app = FastAPI()
        pont_iphone.monter_routes(app)

        def lente(client):
            return client.post("/api/inbox", json={"type": "commande", "contenu": "mode film"},
                               headers={"X-Jarvis-Token": "bon"})

        with patch.object(pont_iphone, "reglage", _lire({"pont_iphone.token": "bon"})), \
                patch.object(pont_iphone, "traiter_commande",
                             _lent({"ok": True, "reponse": "fait", "faits": []})):
            r, ping, latence, ecart = asyncio.run(
                _pendant_une_requete_lente(app, lente, "/api/ping"))
        self.assertEqual(r.json()["message"], "fait")
        self.assertEqual(ping.status_code, 200)
        self.assertLess(latence, self.SEUIL)
        self.assertLess(ecart, self.SEUIL)

    def test_note_iphone(self):
        def lente(client):
            return client.post("/api/inbox", json={"type": "note", "contenu": "test lot4"},
                               headers={"X-Jarvis-Token": "bon"})

        fausse_note = MagicMock(side_effect=_lent(("test_lot4", "ligne")))
        # monter_routes importe ajouter_note : le faux doit etre en place AVANT, sinon
        # le handler garderait la vraie fonction (ecriture dans notes/).
        with patch.object(pont_iphone, "reglage", _lire({"pont_iphone.token": "bon"})), \
                patch("tools.notes.ajouter_note", fausse_note):
            app = FastAPI()
            pont_iphone.monter_routes(app)
            r, ping, latence, ecart = asyncio.run(
                _pendant_une_requete_lente(app, lente, "/api/ping"))
        fausse_note.assert_called_once_with("test lot4", None, source="iPhone")
        self.assertEqual(r.json()["categorie"], "test_lot4")
        self.assertLess(latence, self.SEUIL)
        self.assertLess(ecart, self.SEUIL)

    def test_tester_un_modele_dans_le_panneau(self):
        app = FastAPI()
        panneau.monter_routes(app)

        def lente(client):
            return client.post("/api/panneau/ollama/tester", json={"nom": "qwen2.5:3b"},
                               headers={"X-Jarvis-Panneau": "1"})

        with patch.object(panneau, "_ollama_tester", _lent({"ok": True, "nom": "qwen2.5:3b"})):
            r, rapide, latence, ecart = asyncio.run(
                _pendant_une_requete_lente(app, lente, "/api/panneau/pull-status?nom=x"))
        self.assertTrue(r.json()["ok"])
        self.assertEqual(rapide.status_code, 200)
        self.assertLess(latence, self.SEUIL)
        self.assertLess(ecart, self.SEUIL)


class SondeMcpTest(unittest.TestCase):
    """#69 : la sonde MCP envoie le jeton, lit mcp.port, et 401 = vivant mais protege."""

    def _sonde(self, code=None, erreur=None, reglages=None, env=None):
        reponse = MagicMock(status_code=code)
        with patch.object(panneau, "reglage", _lire(reglages or {})), \
                patch.dict(os.environ, env or {}), \
                patch("requests.get", return_value=reponse, side_effect=erreur) as get:
            if not env:
                os.environ.pop("JARVIS_MCP_TOKEN", None)
            etat = panneau._mcp_repond()
        return etat, get

    def test_codes(self):
        for code, attendu in ((400, "ok"), (406, "ok"), (405, "ok"), (401, "jeton"),
                              (500, ""), (404, "")):
            with self.subTest(code=code):
                self.assertEqual(self._sonde(code)[0], attendu)
        self.assertEqual(self._sonde(erreur=ConnectionError("refuse"))[0], "")

    def test_jeton_envoye_seulement_s_il_existe(self):
        _etat, get = self._sonde(400)
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])
        _etat, get = self._sonde(400, reglages={"mcp.token": "jeton-factice"})
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer jeton-factice")
        _etat, get = self._sonde(400, env={"JARVIS_MCP_TOKEN": "jeton-env"})
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer jeton-env")

    def test_port_mcp_lu_dans_la_config(self):
        _etat, get = self._sonde(400, reglages={"mcp.port": 9123})
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:9123/mcp")

    def test_etat_utilise_les_vrais_ports(self):
        ports = []

        def ecoute(port):
            ports.append(port)
            return True

        with patch.object(panneau, "reglage", _lire({"mcp.port": 9123})), \
                patch.object(serveur, "port_effectif", return_value=8123), \
                patch.object(panneau, "_port_listen", side_effect=ecoute), \
                patch.object(panneau, "_mcp_repond", return_value="jeton"), \
                patch.object(panneau, "_docker_up", return_value=False), \
                patch.object(panneau, "_hermes_mcp_connecte", return_value=None):
            chaine = {c["cle"]: c for c in panneau._etat()["chaine"]}
        self.assertIn(8123, ports)
        self.assertIn(9123, ports)
        self.assertNotIn(8765, ports)
        self.assertTrue(chaine["mcp"]["up"])
        self.assertIn(":9123", chaine["mcp"]["nom"])
        self.assertIn("jeton", chaine["mcp"]["detail"])
        self.assertNotIn("jeton-", str(chaine))           # jamais la valeur du jeton

    def test_reconnecter_mcp_comportement_actuel(self):
        with patch.object(panneau.shutil, "which", return_value=None):
            self.assertIn("introuvable", panneau._reconnecter_mcp()["message"])
        with patch.object(panneau, "reglage", _lire({"mcp.port": 9123})), \
                patch.object(panneau.shutil, "which", return_value="hermes"), \
                patch.object(panneau.subprocess, "run",
                             return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
            r = panneau._reconnecter_mcp()
        self.assertTrue(r["ok"])
        self.assertEqual(run.call_args_list[0].args[0], ["hermes", "mcp", "remove", "jarvis"])
        self.assertEqual(run.call_args_list[1].args[0],
                         ["hermes", "mcp", "add", "jarvis", "--url", "http://127.0.0.1:9123/mcp"])


class VerrousActuelsTest(unittest.TestCase):
    """#143 : epingle les verrous deja corrects."""

    def test_autoriser_toujours_refuse_chaque_n3_sans_rien_ecrire(self):
        with patch("core.config.reglage", return_value=[]), \
                patch("core.config.definir") as ecrire:
            for nom in sorted(registre._N3):
                with self.subTest(outil=nom):
                    self.assertFalse(registre.autoriser_toujours(nom))
            ecrire.assert_not_called()
            # Temoin : un N2 est bien memorisable.
            with patch.dict(registre._REGISTRE, {"faux_n2": _outil("faux_n2", confirmation=True)}):
                self.assertTrue(registre.autoriser_toujours("faux_n2"))
            ecrire.assert_called_once_with("securite.toujours", ["faux_n2"])

    def test_n2_non_memorises_demandent_toujours_un_oui(self):
        n2 = [o.nom for o in registre.tous() if registre.niveau(o.nom) == "N2"][:6]
        self.assertTrue(n2)
        with patch.object(registre, "autorisations", return_value=[]):
            for nom in n2:
                with self.subTest(outil=nom):
                    self.assertTrue(registre.confirmation_requise(nom, apres_contenu_externe=False))
                    self.assertTrue(registre.confirmation_requise(nom, apres_contenu_externe=True))

    def test_regle_affichee_par_le_panneau_decrit_le_pont_reel(self):
        with patch.object(panneau, "reglage",
                          _lire({"pont_iphone.domotique_distante": ["allumer_lumiere"]})), \
                patch.object(panneau, "_hermes_config", return_value=ROOT / "absent.yaml"):
            regle = panneau._permissions()["regle_n3"]
        self.assertNotIn("ne declenche QUE des N1", regle)
        self.assertIn("domotique_distante", regle)
        self.assertIn("SANS confirmation", regle)
        self.assertIn("allumer_lumiere", regle)


if __name__ == "__main__":
    unittest.main()
