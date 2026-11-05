"""Bot Discord : un echec de connexion ne le desactive plus jusqu'au redemarrage.

Aucun reseau : le module `discord` est remplace par un faux module dont
Client.start leve l'erreur voulue. Aucun thread reel n'est lance.
"""
import asyncio
import logging
import sys
import types
import unittest
from unittest.mock import patch

from core import journal

# Pas de FileHandler vers logs/jarvis.log pendant les tests.
if journal._LOG is None:
    journal._LOG = logging.getLogger("jarvis")

from tools import discord_bot  # noqa: E402


class LoginFailure(Exception):
    pass


class _FauxClient:
    erreur = OSError(11001, "getaddrinfo failed")
    tentatives = 0

    def __init__(self, intents=None):
        self.ferme = False

    def event(self, fonction):
        return fonction

    def is_ready(self):
        return False

    def is_closed(self):
        return self.ferme

    async def close(self):
        self.ferme = True

    async def start(self, token):
        type(self).tentatives += 1
        raise type(self).erreur


def _faux_discord():
    module = types.ModuleType("discord")
    module.Intents = types.SimpleNamespace(default=lambda: types.SimpleNamespace())
    module.Client = _FauxClient
    module.LoginFailure = LoginFailure
    return module


class ReconnexionTests(unittest.TestCase):
    def setUp(self):
        _FauxClient.tentatives = 0
        _FauxClient.erreur = OSError(11001, "getaddrinfo failed")
        self.boucles = []
        vraie = asyncio.new_event_loop

        def creer_boucle():
            boucle = vraie()
            self.boucles.append(boucle)
            return boucle

        for p in (patch.dict(sys.modules, {"discord": _faux_discord()}),
                  patch.dict(discord_bot._BOT, {"loop": None, "client": None,
                                                "lance": False, "erreur": "",
                                                "fatal": False}),
                  patch.object(discord_bot, "_configure", return_value=True),
                  patch.object(discord_bot, "reglage",
                               side_effect=lambda cle, defaut=None: (
                                   "jeton-factice" if cle == "discord.token" else defaut)),
                  patch.object(discord_bot.asyncio, "new_event_loop",
                               side_effect=creer_boucle)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(asyncio.set_event_loop, None)

    def _lancer(self):
        discord_bot._BOT["lance"] = True          # comme demarrer_discord
        with self.assertLogs("jarvis", level="ERROR"):
            discord_bot._lancer()

    def test_echec_reseau_remet_le_bot_a_zero_et_ferme_la_boucle(self):
        self._lancer()
        self.assertFalse(discord_bot._BOT["lance"])
        self.assertIsNone(discord_bot._BOT["client"])
        self.assertIsNone(discord_bot._BOT["loop"])
        self.assertEqual(discord_bot._BOT["erreur"], "OSError")
        self.assertFalse(discord_bot._BOT["fatal"])
        self.assertTrue(self.boucles[0].is_closed())

        with patch.object(discord_bot.threading, "Thread") as thread:
            discord_bot.demarrer_discord()
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()

    def test_une_demande_vocale_relance_le_bot(self):
        self._lancer()
        with patch.object(discord_bot.threading, "Thread") as thread:
            messages, erreur = discord_bot._lancer_scan(lambda c: None)
        self.assertIsNone(messages)
        self.assertIn("reessaie dans un instant", erreur)
        thread.return_value.start.assert_called_once()

    def test_jeton_refuse_pas_de_relance(self):
        _FauxClient.erreur = LoginFailure("Improper token has been passed.")
        self._lancer()
        self.assertTrue(discord_bot._BOT["fatal"])
        self.assertFalse(discord_bot._BOT["lance"])
        with patch.object(discord_bot.threading, "Thread") as thread:
            discord_bot.demarrer_discord()
            messages, erreur = discord_bot._lancer_scan(lambda c: None)
        thread.assert_not_called()
        self.assertIn("jeton refuse", erreur)
        self.assertEqual(_FauxClient.tentatives, 1)

    def test_module_absent_ne_bloque_pas_l_etat(self):
        with patch.dict(sys.modules, {"discord": None}):
            self._lancer()
        self.assertFalse(discord_bot._BOT["lance"])
        self.assertEqual(self.boucles, [])


if __name__ == "__main__":
    unittest.main()
