"""Route /desktop-agent : elle doit vraiment accepter une connexion WebSocket.

Regression : avec « from __future__ import annotations », FastAPI ne resolvait pas
le type WebSocket de la route et refusait toute connexion (HTTP 403).
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import poste_distant


def _client():
    app = FastAPI()
    # Le client de test n'a pas d'adresse IP : on considere l'origine comme le LAN.
    with patch("core.satellite._origine_locale_ou_lan", return_value=True):
        poste_distant.monter_routes(app)
    return TestClient(app)


class RouteDesktopAgentTest(unittest.TestCase):
    def test_la_connexion_est_acceptee_et_un_jeton_faux_refuse_proprement(self):
        reglages = {"desktop_agents": [{"id": "bureau", "token": "bon-jeton"}]}
        with patch.object(poste_distant, "reglage", lambda cle, defaut=None: reglages.get(cle, defaut)), \
                _client().websocket_connect("/desktop-agent") as ws:
            ws.send_text(json.dumps({"type": "hello", "agent": "bureau", "token": "mauvais"}))
            self.assertEqual(json.loads(ws.receive_text())["type"], "erreur")

    def test_le_bon_jeton_ouvre_la_session(self):
        reglages = {"desktop_agents": [{"id": "bureau", "token": "bon-jeton"}]}
        with patch.object(poste_distant, "reglage", lambda cle, defaut=None: reglages.get(cle, defaut)), \
                _client().websocket_connect("/desktop-agent") as ws:
            ws.send_text(json.dumps({"type": "hello", "agent": "bureau", "token": "bon-jeton",
                                     "capabilities": ["launch_app", "commande_inconnue"]}))
            reponse = json.loads(ws.receive_text())
        self.assertEqual(reponse["type"], "pret")
        self.assertEqual(reponse["agent"], "bureau")

    def test_le_module_ne_differe_pas_ses_annotations(self):
        # « from __future__ import annotations » laisse le nom `annotations` dans le module.
        self.assertNotIn("annotations", vars(poste_distant))


if __name__ == "__main__":
    unittest.main()
