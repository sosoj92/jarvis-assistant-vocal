"""Agent Windows : une connexion configuree en ws:// est signalee dans le journal.

En ws://, le jeton passe en clair et le serveur n'est pas authentifie : un
appareil du reseau qui se fait passer pour lui peut envoyer des commandes a ce
PC. Le client Pi avertissait deja, l'agent du bureau se connectait sans bruit.
"""
import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import config

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("jarvis_desktop_agent_ws_clair_test",
                                               ROOT / "desktop_agent" / "jarvis_desktop_agent.py")
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)

BASE = {"agent_id": "bureau", "token": "factice"}


def _demarrer(conf):
    """Lance main() sans reseau ni audio ; renvoie le journal et les appels simules."""
    sortie = io.StringIO()
    ancien_fichier, ancienne_config = config.FICHIER, config._CONFIG
    try:
        with patch.object(agent, "charger_config", return_value=conf), \
                patch.object(agent, "demarrer_audio") as audio, \
                patch.object(agent, "boucle", MagicMock(return_value=None)), \
                patch.object(agent.asyncio, "run") as lancer, \
                contextlib.redirect_stdout(sortie):
            agent.main()
    finally:
        config.FICHIER, config._CONFIG = ancien_fichier, ancienne_config
    return sortie.getvalue(), audio, lancer


class AvertissementClairTest(unittest.TestCase):
    def test_serveur_en_ws_averti_une_seule_fois_sans_refus(self):
        journal, audio, lancer = _demarrer(
            {**BASE, "serveur_url": "ws://192.0.2.10:8791/desktop-agent"})
        self.assertEqual(journal.count("[securite]"), 1, journal)
        self.assertIn("serveur_url en ws://", journal)
        self.assertIn("EN CLAIR", journal)
        self.assertIn("wss://", journal)
        # Avertissement seulement : l'agent demarre quand meme.
        audio.assert_called_once()
        lancer.assert_called_once()

    def test_serveur_en_wss_aucun_avertissement(self):
        journal, _, lancer = _demarrer(
            {**BASE, "serveur_url": "wss://192.0.2.10:8792/desktop-agent",
             "certificat": "jarvis-lan.crt"})
        self.assertNotIn("[securite]", journal)
        lancer.assert_called_once()

    def test_audio_actif_en_ws_averti_aussi(self):
        journal, _, _ = _demarrer({
            **BASE, "serveur_url": "wss://192.0.2.10:8792/desktop-agent",
            "audio": {"actif": True, "pc_url": "ws://192.0.2.10:8791/satellite"},
        })
        self.assertEqual(journal.count("[securite]"), 1, journal)
        self.assertIn("audio.pc_url en ws://", journal)

    def test_audio_inactif_ignore(self):
        messages = agent.avertissements_clair({
            **BASE, "serveur_url": "wss://192.0.2.10:8792/desktop-agent",
            "audio": {"actif": False, "pc_url": "ws://192.0.2.10:8791/satellite"},
        })
        self.assertEqual(messages, [])

    def test_les_deux_canaux_en_ws(self):
        messages = agent.avertissements_clair({
            **BASE, "serveur_url": " ws://192.0.2.10:8791/desktop-agent ",
            "audio": {"actif": True, "pc_url": "WS://192.0.2.10:8791/satellite"},
        })
        self.assertEqual(len(messages), 2)


if __name__ == "__main__":
    unittest.main()
