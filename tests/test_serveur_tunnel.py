"""Tunnel ngrok : il doit viser l'adresse IPv4 sur laquelle le serveur ecoute, et
seulement quand c'est NOTRE serveur qui ecoute."""
from __future__ import annotations

import contextlib
import io
import sys
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

from core import serveur


def _faux_pyngrok():
    faux_ngrok = MagicMock()
    faux_ngrok.connect.return_value = MagicMock(public_url="https://exemple.ngrok-free.dev")
    module = types.ModuleType("pyngrok")
    module.ngrok = faux_ngrok
    return faux_ngrok, {"pyngrok": module, "pyngrok.ngrok": faux_ngrok}


_REGLAGES = {"serveur.ngrok_authtoken": "jeton-factice", "serveur.ngrok_domaine": ""}


def _lire(cle, defaut=None):
    return _REGLAGES.get(cle, defaut)


class TunnelTest(unittest.TestCase):
    def test_le_tunnel_vise_127_0_0_1_et_non_localhost(self):
        # Regression : un port seul devenait « localhost:8790 », resolu en ::1 sous
        # Windows alors que le serveur n'ecoute qu'en 127.0.0.1 -> ERR_NGROK_8012.
        faux_ngrok, modules = _faux_pyngrok()
        with patch.dict(sys.modules, modules), \
                patch.object(serveur, "reglage", _lire), \
                patch.object(serveur, "_port", return_value=8790), \
                patch.object(serveur, "_ecoute", return_value=True), \
                patch.object(serveur, "_URL", None), \
                contextlib.redirect_stdout(io.StringIO()):
            serveur._ouvrir_tunnel()
        adresse = faux_ngrok.connect.call_args.args[0]
        self.assertEqual(adresse, "127.0.0.1:8790")

    def test_pas_de_tunnel_si_notre_serveur_n_ecoute_pas(self):
        # Le port peut etre tenu par un autre processus : ne jamais le publier,
        # y compris par l'appel paresseux de url_publique() (appels Twilio).
        faux_ngrok, modules = _faux_pyngrok()
        with patch.dict(sys.modules, modules), \
                patch.object(serveur, "reglage", _lire), \
                patch.object(serveur, "_ecoute", return_value=False), \
                patch.object(serveur, "_URL", None):
            serveur._ouvrir_tunnel()
            self.assertEqual(serveur.url_publique(), "")
        faux_ngrok.connect.assert_not_called()

    def test_un_echec_n_efface_pas_une_url_ouverte_entre_temps(self):
        # Un autre thread ouvre le tunnel pendant que celui-ci echoue (ERR_NGROK_334) :
        # la branche d'erreur ne doit pas remettre _URL a None.
        faux_ngrok, modules = _faux_pyngrok()

        def connect(*_a, **_k):
            serveur._URL = "https://exemple.ngrok-free.dev"
            raise RuntimeError("ERR_NGROK_334 (simule)")

        faux_ngrok.connect.side_effect = connect
        with patch.dict(sys.modules, modules), \
                patch.object(serveur, "reglage", _lire), \
                patch.object(serveur, "_port", return_value=8790), \
                patch.object(serveur, "_ecoute", return_value=True), \
                patch.object(serveur, "_URL", None), \
                patch.object(serveur, "LOG"), \
                contextlib.redirect_stdout(io.StringIO()):
            serveur._ouvrir_tunnel()
            url = serveur._URL
        self.assertEqual(url, "https://exemple.ngrok-free.dev")

    def test_deux_ouvertures_simultanees_un_seul_connect(self):
        # Demarrage et url_publique() en meme temps : le second attend le premier et
        # reutilise son URL au lieu de rappeler ngrok (qui refuserait le domaine).
        faux_ngrok, modules = _faux_pyngrok()
        entre, libere = threading.Event(), threading.Event()
        appels = []

        def connect(*_a, **_k):
            appels.append(1)
            if len(appels) == 1:
                entre.set()
                libere.wait(2)
                return MagicMock(public_url="https://exemple.ngrok-free.dev")
            raise RuntimeError("ERR_NGROK_334 (simule)")

        faux_ngrok.connect.side_effect = connect
        with patch.dict(sys.modules, modules), \
                patch.object(serveur, "reglage", _lire), \
                patch.object(serveur, "_port", return_value=8790), \
                patch.object(serveur, "_ecoute", return_value=True), \
                patch.object(serveur, "_URL", None), \
                patch.object(serveur, "LOG"), \
                contextlib.redirect_stdout(io.StringIO()):
            a = threading.Thread(target=serveur._ouvrir_tunnel)
            a.start()
            self.assertTrue(entre.wait(2))
            b = threading.Thread(target=serveur._ouvrir_tunnel)
            b.start()
            b.join(0.3)
            libere.set()
            a.join(2)
            b.join(2)
            url = serveur._URL
        self.assertEqual(url, "https://exemple.ngrok-free.dev")
        self.assertEqual(len(appels), 1)


class DemarrageTest(unittest.TestCase):
    """serveur.demarrer() sans vrai uvicorn : uvicorn.Server est remplace."""

    def _demarrer(self, classe_serveur):
        faux_ngrok, modules = _faux_pyngrok()
        faux_satellite = types.ModuleType("core.satellite")
        faux_satellite.demarrer_lan = MagicMock()
        modules = dict(modules, **{"core.satellite": faux_satellite})
        sortie = io.StringIO()
        with patch.dict(sys.modules, modules), \
                patch("uvicorn.Server", classe_serveur), \
                patch("uvicorn.Config"), \
                patch.object(serveur, "app", return_value=object()), \
                patch.object(serveur, "reglage", _lire), \
                patch.object(serveur, "_port", return_value=8790), \
                patch.object(serveur, "_SERVEUR", None), \
                patch.object(serveur, "_UVICORN", None), \
                patch.object(serveur, "_URL", None), \
                contextlib.redirect_stdout(sortie), \
                self.assertLogs("jarvis", level="INFO") as journal:
            serveur.demarrer()
            thread = serveur._SERVEUR
            url_apres = serveur.url_publique()
        return faux_ngrok, faux_satellite, sortie.getvalue(), journal.output, thread, url_apres

    def test_port_deja_pris_ni_tunnel_ni_message_de_succes(self):
        # uvicorn fait sys.exit(STARTUP_FAILURE) quand le port est pris : ce SystemExit
        # doit etre journalise, et rien ne doit publier le processus qui tient le port.
        class ServeurPortPris:
            def __init__(self, config):
                self.started = False

            def run(self):
                sys.exit(3)

        ngrok, satellite, sortie, journal, thread, url = self._demarrer(ServeurPortPris)
        ngrok.connect.assert_not_called()
        self.assertEqual(url, "")
        satellite.demarrer_lan.assert_called_once_with()   # listener LAN independant
        self.assertNotIn("Serveur web : port", sortie)
        self.assertIn("NON demarre", sortie)
        self.assertTrue(any("n'a pas pu ecouter" in ligne for ligne in journal))
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_demarrage_nominal_ouvre_le_tunnel(self):
        fin = threading.Event()

        class ServeurQuiEcoute:
            def __init__(self, config):
                self.started = False

            def run(self):
                self.started = True
                fin.wait(5)

        try:
            ngrok, satellite, sortie, _journal, thread, url = self._demarrer(ServeurQuiEcoute)
        finally:
            fin.set()
        ngrok.connect.assert_called_once()
        self.assertEqual(url, "https://exemple.ngrok-free.dev")
        satellite.demarrer_lan.assert_called_once_with()
        self.assertIn("Serveur web : port 8790", sortie)
        thread.join(2)


if __name__ == "__main__":
    unittest.main()
