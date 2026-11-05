"""Appels V2 (call_and_book) : la duree et le cout entrent dans le compteur
mensuel, et la voix ElevenLabs dans le budget. Twilio, serveur et TTS simules."""
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

from core import config, registre

registre.charger_outils()

from tools import appel_direct, appels  # noqa: E402


def _config(dossier):
    return {"appels": {"actif": True, "simulation": False, "dossier": dossier,
                       "duree_max_appel": 1},
            "twilio": {"account_sid": "ACfactice", "auth_token": "factice",
                       "numero": "+33100000000"},
            "elevenlabs": {"cle": "factice"}}


class CompteurV2Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        serveur = types.ModuleType("core.serveur")
        serveur.demarrer = MagicMock()
        serveur.url_publique = MagicMock(return_value="https://x.example")
        truststore = types.ModuleType("truststore")
        truststore.inject_into_ssl = MagicMock()
        self.client = MagicMock()
        twilio_rest = types.ModuleType("twilio.rest")
        twilio_rest.Client = MagicMock(return_value=self.client)
        self._patches = [
            patch.object(config, "_CONFIG", _config(self._tmp.name)),
            patch.dict(sys.modules, {"core.serveur": serveur, "truststore": truststore,
                                     "twilio.rest": twilio_rest}),
            patch.object(appel_direct, "_twiml_stream", return_value="<Response/>"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _appel(self, statut, duree, echanges):
        sid = f"CA{statut}"
        self.client.calls.create.return_value = MagicMock(sid=sid)
        self.client.calls.return_value.fetch.return_value = MagicMock(status=statut, duration=duree)

        def conclure():
            # Comme Conversation.terminer : attend que l'appel soit enregistre.
            for _ in range(200):
                res = appel_direct._RESULTATS.get(sid)
                if res is not None:
                    res["echanges"] = echanges
                    res["statut"] = "conclu"
                    res["event"].set()
                    return
                time.sleep(0.01)

        fil = threading.Thread(target=conclure)
        fil.start()
        reponse = appel_direct.call_and_book("06 12 34 56 78", "table pour 2")
        fil.join()
        return reponse

    def _compteur(self):
        f = appels._fichier_compteur()
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def test_appel_abouti_compte(self):
        self._appel("completed", 120, [("jarvis", "Bonjour"), ("interlocuteur", "Oui")])
        compteur = self._compteur()
        self.assertEqual(compteur["appels"], 1)
        self.assertEqual(compteur["minutes"], 2.0)
        self.assertEqual(compteur["cout"], appels._cout(2.0))
        self.assertIn("1 appel(s)", appels.cout_appels())
        from core import budget
        self.assertGreater(budget._twilio_mois(), 0)

    def test_duree_pas_encore_connue_estimee(self):
        self._appel("in-progress", None, [("jarvis", "Bonjour")])
        compteur = self._compteur()
        self.assertEqual(compteur["appels"], 1)
        self.assertGreaterEqual(compteur["minutes"], 0.1)

    def test_pas_de_decrochage_rien_compte(self):
        self._appel("no-answer", 0, [])
        self.assertIsNone(self._compteur())


class TtsBudgetTest(unittest.TestCase):
    def test_tts_compte_les_caracteres(self):
        reponse = MagicMock(status_code=200, content=b"\xff" * 160)
        with patch.object(config, "_CONFIG", {"elevenlabs": {"cle": "factice"}}), \
                patch("requests.post", return_value=reponse), \
                patch("core.budget.enregistrer_tts") as enregistrer:
            self.assertEqual(appel_direct._tts_ulaw("Bonjour"), b"\xff" * 160)
        enregistrer.assert_called_once_with(7)

    def test_tts_en_echec_non_compte(self):
        reponse = MagicMock(status_code=401, content=b"")
        with patch.object(config, "_CONFIG", {"elevenlabs": {"cle": "factice"}}), \
                patch("requests.post", return_value=reponse), \
                patch("core.budget.enregistrer_tts") as enregistrer:
            self.assertEqual(appel_direct._tts_ulaw("Bonjour"), b"")
        enregistrer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
