"""Frontiere reseau du satellite : Tailscale IPv6 hors de la maison, delai
d'authentification sur /satellite (hors reseau, client de test FastAPI)."""
from __future__ import annotations

import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core import satellite


def _ws(hote):
    return SimpleNamespace(client=SimpleNamespace(host=hote), headers={})


class TailscaleTests(unittest.TestCase):
    def test_tailscale_ipv6_vaut_hors_de_la_maison(self):
        # « N3 jamais a distance » tient aussi si le listener ecoute en IPv6.
        self.assertTrue(satellite._hors_maison(_ws("fd7a:115c:a1e0::1234")))
        self.assertTrue(satellite._hors_maison(_ws("fd7a:115c:a1e0:ab12:4843:cd96:6258:b240")))
        self.assertTrue(satellite._hors_maison(_ws("::ffff:100.101.102.103")))
        self.assertTrue(satellite._hors_maison(_ws("100.101.102.103")))

    def test_la_maison_reste_la_maison(self):
        for hote in ("192.168.1.42", "::ffff:192.168.1.5", "fe80::1", "fe80::1%12",
                     "127.0.0.1", "::1", "fd00::5"):
            with self.subTest(hote=hote):
                self.assertFalse(satellite._hors_maison(_ws(hote)))


class DelaiHelloTests(unittest.TestCase):
    def setUp(self):
        correctifs = [
            patch.object(satellite, "_origine_locale_ou_lan", return_value=True),
            patch.object(satellite, "_satellites", return_value={"cuisine": {
                "piece": "cuisine", "token": "jeton-factice", "wake": "appareil",
                "priorite_micro": 1.0, "brief_au_demarrage": False,
                "actions_critiques": True, "tableau": False}}),
            patch.object(satellite, "statut_affichage", return_value={}),
            patch.object(satellite, "_DELAI_HELLO", 0.3),
        ]
        for c in correctifs:
            c.start()
            self.addCleanup(c.stop)
        app = FastAPI()
        satellite.monter_routes(app)
        self.client = TestClient(app, client=("192.168.1.20", 50000))

    def _fermeture(self, ws):
        """Code de fermeture recu par le client (les ping ne prolongent rien)."""
        while True:
            try:
                message = ws.receive()
            except WebSocketDisconnect as e:
                return e.code
            if message.get("type") == "websocket.close":
                return message.get("code")

    def test_sans_hello_la_connexion_est_fermee(self):
        with self.client.websocket_connect("wss://testserver/satellite") as ws:
            ws.send_bytes(b"\x00" * 1000)
            ws.send_text(json.dumps({"type": "ping"}))
            self.assertEqual(self._fermeture(ws), 1008)

    def test_hello_immediat_inchange(self):
        with self.client.websocket_connect("wss://testserver/satellite") as ws:
            ws.send_text(json.dumps({"type": "hello", "satellite": "cuisine",
                                     "token": "jeton-factice"}))
            debut = [json.loads(ws.receive_text()) for _ in range(2)]
            # Authentifie : le delai ne s'applique plus.
            time.sleep(0.5)
            ws.send_text(json.dumps({"type": "ping"}))
            suivant = json.loads(ws.receive_text())
        self.assertEqual([m["type"] for m in debut], ["pret", "etat"])
        self.assertEqual(suivant["type"], "pong")


if __name__ == "__main__":
    unittest.main()
