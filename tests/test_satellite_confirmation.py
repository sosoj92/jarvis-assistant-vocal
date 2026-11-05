"""Confirmation vocale sur un satellite : fenetre bornee, boucle WebSocket libre et
historique LLM valide apres une action en attente (hors reseau, sans outil reel)."""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import satellite
from core.llm import OpenAIProvider


# ------------------------------------------------------------ route /satellite

class _RouteSatellite(unittest.TestCase):
    """La route /satellite avec le client de test FastAPI (pas de vraie socket)."""

    def setUp(self):
        self.phrases = []
        self.executes = []
        self.dans_la_boucle = []
        self.traites = []
        reglages = {"satellite_lan.accuse_reveil_vocal": False,
                    "satellite_lan.accuse_immediat": False}

        def traiter(session, phrase):
            # La premiere demande pose une action critique a confirmer, comme le LLM.
            self.traites.append(phrase)
            if len(self.traites) == 1:
                session.en_attente = ("envoyer_mail", {"a": "Paul"})
                return {"reponse": "J'envoie le mail a Paul. Tu confirmes ?",
                        "attente_confirmation": True}
            return {"reponse": "C'est fait.", "attente_confirmation": False}

        def executer(nom, args, piece=None):
            try:
                asyncio.get_running_loop()
                self.dans_la_boucle.append(True)
            except RuntimeError:
                self.dans_la_boucle.append(False)
            self.executes.append(nom)
            return "Mail envoye."

        correctifs = [
            patch.object(satellite, "_origine_locale_ou_lan", return_value=True),
            patch.object(satellite, "_satellites", return_value={"cuisine": {
                "piece": "cuisine", "token": "jeton-factice", "wake": "appareil",
                "priorite_micro": 1.0, "brief_au_demarrage": False,
                "actions_critiques": True, "tableau": False}}),
            patch.object(satellite, "statut_affichage", return_value={}),
            patch.object(satellite, "reglage", lambda cle, defaut=None: reglages.get(cle, defaut)),
            patch.object(satellite, "_tts_pcm", return_value=(b"", 0)),
            patch.object(satellite, "_tts_pcm_court", return_value=(b"", 0)),
            patch.object(satellite, "_transcrire", side_effect=lambda _audio: self.phrases.pop(0)),
            patch.object(satellite, "traiter_texte", side_effect=traiter),
            patch.object(satellite, "_executer_outil", side_effect=executer),
            patch("core.arbitrage_micro.reserver_reveil", return_value=True),
        ]
        for c in correctifs:
            c.start()
            self.addCleanup(c.stop)
        app = FastAPI()
        satellite.monter_routes(app)
        self.client = TestClient(app, client=("192.168.1.20", 50000))

    @staticmethod
    def _jusqua(ws, type_, etat=None):
        while True:
            m = json.loads(ws.receive_text())
            if m.get("type") == type_ and (etat is None or m.get("etat") == etat):
                return m

    def _demander_mail(self, ws):
        """hello, « Hey Jarvis, envoie un mail a Paul » -> question + relance 12 s."""
        ws.send_text(json.dumps({"type": "hello", "satellite": "cuisine",
                                 "token": "jeton-factice"}))
        self._jusqua(ws, "etat", "veille")
        self._reveil(ws)
        self.phrases.append("envoie un mail a Paul pour dire que j'arrive")
        ws.send_text(json.dumps({"type": "fin_parole"}))
        self.assertEqual(self._jusqua(ws, "relance")["secondes"], 12.0)

    def _reveil(self, ws):
        ws.send_text(json.dumps({"type": "reveil", "score": 1.0, "id": "r"}))
        self._jusqua(ws, "reveil_accepte")

    def _dire(self, ws, phrase):
        self.phrases.append(phrase)
        ws.send_text(json.dumps({"type": "fin_parole"}))
        texte = self._jusqua(ws, "texte")["texte"]
        self._jusqua(ws, "etat", "veille")
        return texte


class FenetreConfirmationTests(_RouteSatellite):
    def test_oui_dans_la_fenetre_execute_hors_de_la_boucle(self):
        with self.client.websocket_connect("wss://testserver/satellite") as ws:
            self._demander_mail(ws)
            texte = self._dire(ws, "oui")
        self.assertEqual(self.executes, ["envoyer_mail"])
        self.assertEqual(texte, "Mail envoye.")
        # Un outil du poste principal attend une reponse de cette meme boucle :
        # il ne doit jamais s'executer dedans (gel jusqu'a 91 s sinon).
        self.assertEqual(self.dans_la_boucle, [False])

    def test_un_nouveau_hey_jarvis_abandonne_l_action(self):
        # Personne ne repond, la fenetre du poste expire sans rien envoyer ; plus tard :
        # « Hey Jarvis, ok mets de la musique » ne doit pas envoyer le mail.
        with self.client.websocket_connect("wss://testserver/satellite") as ws:
            self._demander_mail(ws)
            self._reveil(ws)
            self._dire(ws, "ok, mets de la musique")
        self.assertEqual(self.executes, [])
        self.assertEqual(self.traites[-1], "ok, mets de la musique")

    def test_hey_jarvis_sans_suite_abandonne_l_action(self):
        with self.client.websocket_connect("wss://testserver/satellite") as ws:
            self._demander_mail(ws)
            ws.send_text(json.dumps({"type": "reveil_sans_suite"}))
            self._jusqua(ws, "etat", "veille")
            self._dire(ws, "ok, mets de la musique")
        self.assertEqual(self.executes, [])
        self.assertEqual(self.traites[-1], "ok, mets de la musique")

    def test_reponse_hors_delai_traitee_comme_une_demande(self):
        with patch.object(satellite, "_DELAI_CONFIRMATION", -1.0), \
                self.client.websocket_connect("wss://testserver/satellite") as ws:
            self._demander_mail(ws)
            self._dire(ws, "oui")
        self.assertEqual(self.executes, [])
        self.assertEqual(self.traites[-1], "oui")


# ------------------------------------------------------------ historique LLM

def _outil(nom, confirmation=False):
    return SimpleNamespace(nom=nom, confirmation=confirmation, annonce=None)


_OUTILS = {"allumer_lumiere": _outil("allumer_lumiere"),
           "browser_close_tabs": _outil("browser_close_tabs", confirmation=True),
           "envoyer_mail": _outil("envoyer_mail", confirmation=True)}


def _appel(id_, nom):
    return SimpleNamespace(type="tool_use", id=id_, name=nom, input={})


def _outils(*blocs):
    return SimpleNamespace(stop_reason="tool_use", content=list(blocs))


def _texte(texte):
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=texte)])


def _verifier_appariement(historique):
    """Regle des API Messages/Responses : chaque tool_use recoit son tool_result
    dans le message utilisateur suivant, et l'historique commence par l'utilisateur."""
    if historique and not (historique[0]["role"] == "user"
                           and isinstance(historique[0]["content"], str)):
        raise ValueError("400 premier message non utilisateur")
    for i, message in enumerate(historique):
        contenu = message["content"]
        if message["role"] != "assistant" or isinstance(contenu, str):
            continue
        ids = {b.id for b in contenu if getattr(b, "type", None) == "tool_use"}
        suivant = historique[i + 1] if i + 1 < len(historique) else None
        recus = set()
        if suivant and suivant["role"] == "user" and isinstance(suivant["content"], list):
            recus = {r.get("tool_use_id") for r in suivant["content"]
                     if isinstance(r, dict) and r.get("type") == "tool_result"}
        if not ids <= recus:
            raise ValueError(f"400 tool_use ids were found without tool_result: {ids - recus}")
    # Meme controle cote OpenAI : aucun function_call sans function_call_output.
    items = OpenAIProvider._traduire(None, historique)
    appels = {i["call_id"] for i in items if i.get("type") == "function_call"}
    sorties = {i["call_id"] for i in items if i.get("type") == "function_call_output"}
    if appels - sorties:
        raise ValueError(f"400 No tool output found for function call {appels - sorties}")


class _FauxCerveau:
    nom = "Claude"

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.recus = []

    def disponible(self):
        return True

    def repondre(self, systeme, historique, outils):
        _verifier_appariement(historique)
        self.recus.append(len(historique))
        return self.reponses.pop(0)


class HistoriqueTests(unittest.TestCase):
    def setUp(self):
        self.reglages = {}
        self.executer = MagicMock(return_value="Fait.")
        correctifs = [
            patch.object(satellite, "reglage",
                         lambda cle, defaut=None: self.reglages.get(cle, defaut)),
            patch.object(satellite, "_executer_outil", self.executer),
            patch("core.routage_intentions.decider_prioritaire", return_value=None),
            patch("core.routage_intentions.modules_pour_phrase", return_value=None),
            patch("core.registre.get", side_effect=_OUTILS.get),
            patch("core.registre.confirmation_requise",
                  side_effect=lambda nom, externe=False: _OUTILS[nom].confirmation),
            patch("core.registre.niveau",
                  side_effect=lambda nom: "N3" if nom == "envoyer_mail" else "N2"),
            patch("core.registre.schemas_api", return_value=[]),
            # Jamais le vrai budget.json (ni Hermes, ni config.yaml) depuis un test.
            patch("core.routage.verifier_nouveau_jour"),
            patch("core.registre.autorisations", return_value=[]),
        ]
        for c in correctifs:
            c.start()
            self.addCleanup(c.stop)
        self.session = satellite._Session()
        self.session.satellite, self.session.piece = "cuisine", "cuisine"
        self.session.actions_critiques = True

    def _cerveau(self, *reponses):
        cerveau = _FauxCerveau(reponses)
        correctif = patch("core.llm.llm", return_value=cerveau)
        correctif.start()
        self.addCleanup(correctif.stop)
        return cerveau

    def test_confirmation_puis_nouvelle_demande(self):
        for reponse in ("oui", "non"):
            with self.subTest(reponse=reponse):
                self.session.historique = []
                # Trois outils : le 1er s'execute, le 2e attend, le 3e n'est pas fait.
                self._cerveau(_outils(_appel("t1", "allumer_lumiere"),
                                      _appel("t2", "browser_close_tabs"),
                                      _appel("t3", "allumer_lumiere")),
                              _texte("Il est midi."))
                r = satellite.traiter_texte(self.session, "ferme les onglets inutiles")
                self.assertTrue(r["attente_confirmation"])
                satellite._resoudre_confirmation(self.session, reponse)
                r = satellite.traiter_texte(self.session, "quelle heure est-il ?")
                self.assertEqual(r["reponse"], "Il est midi.")
                resultats = self.session.historique[2]["content"]
                self.assertEqual([x["tool_use_id"] for x in resultats], ["t1", "t2", "t3"])
                self.assertEqual(resultats[0]["content"], "Fait.")
                self.assertIn("En attente", resultats[1]["content"])
                self.assertEqual(resultats[2]["content"], "Non exécuté.")

    def test_limite_d_outils(self):
        self.reglages["assistant.max_appels_outils"] = 1
        self._cerveau(_outils(_appel("t1", "allumer_lumiere"), _appel("t2", "allumer_lumiere")),
                      _texte("Il est midi."))
        r = satellite.traiter_texte(self.session, "allume tout")
        self.assertIn("boucle d'actions", r["reponse"])
        self.executer.assert_not_called()
        r = satellite.traiter_texte(self.session, "quelle heure est-il ?")
        self.assertEqual(r["reponse"], "Il est midi.")

    def test_historique_borne(self):
        for i in range(100):
            self.session.historique += [
                {"role": "user", "content": f"demande {i}"},
                {"role": "assistant", "content": [_appel(f"t{i}", "allumer_lumiere")]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                                              "content": "Fait."}]},
                {"role": "assistant", "content": "C'est fait."},
            ]
        cerveau = self._cerveau(_texte("Il est midi."))
        r = satellite.traiter_texte(self.session, "quelle heure est-il ?")
        self.assertEqual(r["reponse"], "Il est midi.")
        self.assertLessEqual(cerveau.recus[0], 40)
        premier = self.session.historique[0]
        self.assertEqual(premier["role"], "user")
        self.assertIsInstance(premier["content"], str)

    def test_tronquer_ne_coupe_jamais_une_paire(self):
        historique = []
        for i in range(30):
            historique += [
                {"role": "user", "content": f"demande {i}"},
                {"role": "assistant", "content": [_appel(f"t{i}", "allumer_lumiere")]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                                              "content": "Fait."}]},
            ]
        satellite._tronquer_historique(historique)
        self.assertLessEqual(len(historique), 40)
        _verifier_appariement(historique)


# ------------------------------------------------------------ journal des outils

class JournalOutilsTests(unittest.TestCase):
    def test_nom_piece_duree_issue_sans_arguments_ni_resultat(self):
        with patch("core.registre.get", return_value=_outil("envoyer_mail")), \
                patch("core.registre.executer", return_value="Mail envoye a paul@exemple.fr"), \
                self.assertLogs("jarvis.satellite", "INFO") as journal:
            resultat = satellite._executer_outil("envoyer_mail", {"a": "secret@exemple.fr"},
                                                 piece="cuisine")
        self.assertEqual(resultat, "Mail envoye a paul@exemple.fr")
        ligne = "\n".join(journal.output)
        self.assertIn("envoyer_mail", ligne)
        self.assertIn("cuisine", ligne)
        self.assertIn("ok", ligne)
        self.assertNotIn("secret@exemple.fr", ligne)
        self.assertNotIn("paul@exemple.fr", ligne)

    def test_erreur_journalisee(self):
        with patch("core.registre.get", return_value=_outil("allumer_lumiere")), \
                patch("core.registre.executer", side_effect=RuntimeError("panne")), \
                self.assertLogs("jarvis.satellite", "INFO") as journal:
            resultat = satellite._executer_outil("allumer_lumiere", {}, piece="bureau")
        self.assertEqual(resultat, "Erreur pendant l'action.")
        self.assertTrue(any("allumer_lumiere -> erreur" in l and "bureau" in l
                            for l in journal.output))


if __name__ == "__main__":
    unittest.main()
