"""Reconnexion du client satellite (Pi et audio de l'agent Windows), hors reseau.

Panne : un hello refuse (jeton renouvele sur le serveur, satellite retire)
sortait de la session sans exception, et la boucle se reconnectait aussitot,
sans pause : des dizaines de milliers de connexions et de lignes de journal par
seconde. Un refus doit espacer les tentatives ; une panne reseau garde 3 s.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import queue
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("jarvis_satellite_reconnexion_test",
                                               ROOT / "satellite_pi" / "jarvis_satellite.py")
sat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sat)

URL = "ws://192.0.2.10:8791/satellite"
PRET = json.dumps({"type": "pret", "piece": "test"})
REFUS = json.dumps({"type": "erreur", "message": "jeton invalide"})
_VRAI_SLEEP = asyncio.sleep


class Arret(BaseException):
    """Arrete la boucle infinie du test (BaseException : _boucle ne la rattrape pas)."""


class FausseConnexion:
    def __init__(self, messages, pause=False):
        self.messages = list(messages)
        self.pause = pause

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, _message):
        pass

    async def recv(self):
        if self.pause:
            await _VRAI_SLEEP(0)        # comme un vrai reseau : rend la main
        if not self.messages:
            raise ConnectionError("connexion fermee par le serveur")
        return self.messages.pop(0)


def _faux_websockets(scenarios, max_connexions=50, pause=False):
    """Chaque connexion consomme un scenario : liste de messages, ou exception."""
    connexions = []

    def connect(url, **_options):
        connexions.append(url)
        if len(connexions) > max_connexions:
            raise Arret("reconnexion sans fin")
        scenario = scenarios.pop(0) if scenarios else [REFUS]
        if isinstance(scenario, Exception):
            raise scenario
        return FausseConnexion(scenario, pause=pause)

    return SimpleNamespace(connect=connect), connexions


@contextlib.contextmanager
def _module_websockets(module):
    """Remplace seulement l'entree « websockets » de sys.modules (importe dans _session)."""
    ancien = sys.modules.get("websockets")
    sys.modules["websockets"] = module
    try:
        yield
    finally:
        if ancien is None:
            sys.modules.pop("websockets", None)
        else:
            sys.modules["websockets"] = ancien


def _boucle(micro=None):
    return sat._boucle(URL, "cuisine", "x", queue.Queue(), threading.Event(),
                       micro or MagicMock())


def _lancer(scenarios, sommeils_max=8):
    """Lance _boucle avec un faux reseau et un faux asyncio.sleep qui note les delais."""
    module, connexions = _faux_websockets(scenarios)
    delais = []

    async def faux_sleep(secondes, *a, **k):
        if secondes >= 1:               # l'emetteur dort 0,05 s : hors sujet ici
            delais.append(secondes)
            if len(delais) >= sommeils_max:
                raise Arret("assez de tentatives")
        await _VRAI_SLEEP(0)

    micro = MagicMock()
    sortie = io.StringIO()
    with _module_websockets(module), \
            patch.object(sat, "CONF", {}), \
            patch.object(sat.asyncio, "sleep", faux_sleep), \
            contextlib.redirect_stdout(sortie):
        try:
            asyncio.run(_boucle(micro))
        except Arret:
            pass
        else:
            raise AssertionError("la boucle de reconnexion ne doit jamais s'arreter seule")
    return delais, connexions, sortie.getvalue(), micro


class ReconnexionTest(unittest.TestCase):
    def test_jeton_refuse_recul_croissant_plafonne(self):
        delais, connexions, journal, micro = _lancer([], sommeils_max=8)
        self.assertEqual(delais, [3, 6, 12, 24, 48, 60, 60, 60])
        self.assertEqual(len(connexions), 8)        # une connexion par attente
        self.assertEqual(journal.count("refusé"), 1, journal)   # une ligne par serie
        self.assertIn("jeton invalide", journal)
        micro.fermer_relance.assert_called()

    def test_panne_reseau_garde_trois_secondes(self):
        delais, _, journal, _ = _lancer([OSError("hors ligne")] * 10, sommeils_max=4)
        self.assertEqual(delais, [3, 3, 3, 3])
        self.assertEqual(journal.count("[serveur] injoignable"), 1, journal)

    def test_connexion_acceptee_remet_le_recul_a_zero(self):
        # refus, refus, connexion acceptee puis coupee, refus : la serie repart a 3 s.
        delais, _, journal, _ = _lancer([[REFUS], [REFUS], [PRET], [REFUS]], sommeils_max=4)
        self.assertEqual(delais, [3, 6, 3, 3])
        self.assertEqual(journal.count("refusé"), 2, journal)

    def test_au_plus_une_connexion_par_demi_seconde_apres_un_refus(self):
        # Vrai asyncio.sleep : avant le correctif, des dizaines de milliers de connexions.
        module, connexions = _faux_websockets([], max_connexions=1_000_000, pause=True)

        async def une_demi_seconde():
            await asyncio.wait_for(_boucle(), 0.5)

        with _module_websockets(module), patch.object(sat, "CONF", {}), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(asyncio.TimeoutError):
                asyncio.run(une_demi_seconde())
        self.assertLessEqual(len(connexions), 2)


if __name__ == "__main__":
    unittest.main()
