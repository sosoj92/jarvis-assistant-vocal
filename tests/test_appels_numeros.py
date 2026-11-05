"""Appels : validation commune des numeros (V1 et V2) avant toute preparation,
surtaxes etrangers bloques. Twilio, serveur et tunnel simules : aucun appel reel."""
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from core import config, registre

registre.charger_outils()

from tools import appel_direct, appels  # noqa: E402


def _config(dossier):
    return {"appels": {"actif": True, "simulation": False, "dossier": dossier},
            "twilio": {"account_sid": "ACfactice", "auth_token": "factice",
                       "numero": "+33100000000"},
            "elevenlabs": {"cle": "factice"}}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patches = [patch.object(config, "_CONFIG", _config(self._tmp.name))]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class ValiderNumeroTest(_Base):
    def test_numeros_valides(self):
        self.assertEqual(appels._valider_numero("06 12 34 56 78"), ("+33612345678", None))
        self.assertEqual(appels._valider_numero("+33 (0)6 12 34 56 78"), ("+33612345678", None))
        self.assertEqual(appels._valider_numero("+44 20 7946 0000")[1], None)

    def test_numeros_refuses(self):
        cas = {"112": "pas valide", "06 12 34 56 78 poste 12": "pas valide",
               "3200": "surtaxe", "08 99 12 34 56": "surtaxe",
               "+44 909 879 0000": "surtaxe", "+882 1234 5678": "surtaxe",
               "+49 900 1234567": "surtaxe"}
        for numero, motif in cas.items():
            with self.subTest(numero=numero):
                erreur = appels._valider_numero(numero)[1]
                self.assertIsNotNone(erreur)
                self.assertIn("surtaxe" if motif == "surtaxe" else "ne semble pas valide", erreur)

    def test_annonce_v1_dit_le_numero_compose(self):
        annonce = registre.get("call_with_message").annonce(
            {"numero": "+33 (0)6 12 34 56 78", "message": "Bonjour"})
        self.assertIn("+33612345678", annonce)


class AvantPreparationTest(_Base):
    def test_v2_ne_demarre_pas_le_serveur_pour_un_numero_invalide(self):
        serveur = types.ModuleType("core.serveur")
        serveur.demarrer = MagicMock()
        serveur.url_publique = MagicMock()
        client = MagicMock()
        twilio_rest = types.ModuleType("twilio.rest")
        twilio_rest.Client = client
        with patch.dict(sys.modules, {"core.serveur": serveur, "twilio.rest": twilio_rest}):
            for numero in ("112", "+44 909 879 0000"):
                with self.subTest(numero=numero):
                    reponse = appel_direct.call_and_book(numero, "reserver une table")
                    self.assertTrue(reponse.startswith(("Ce numero", "Je n'appelle pas")))
        serveur.demarrer.assert_not_called()
        serveur.url_publique.assert_not_called()
        client.assert_not_called()

    def test_v1_refuse_un_surtaxe_etranger(self):
        client = MagicMock()
        twilio_rest = types.ModuleType("twilio.rest")
        twilio_rest.Client = client
        with patch.dict(sys.modules, {"twilio.rest": twilio_rest}):
            reponse = appels.call_with_message("+44 909 879 0000", "Bonjour")
        self.assertIn("surtaxe", reponse)
        client.assert_not_called()


class V1CompteurTest(_Base):
    def test_appel_v1_abouti_compte(self):
        appel = MagicMock(sid="CA1", status="queued")
        client = MagicMock()
        client.calls.create.return_value = appel
        client.calls.return_value.fetch.return_value = MagicMock(status="completed", duration=60)
        client.recordings.list.return_value = []
        twilio_rest = types.ModuleType("twilio.rest")
        twilio_rest.Client = MagicMock(return_value=client)
        truststore = types.ModuleType("truststore")
        truststore.inject_into_ssl = MagicMock()
        with patch.dict(sys.modules, {"twilio.rest": twilio_rest, "truststore": truststore}), \
                patch.object(appels.time, "sleep"):
            reponse = appels.call_with_message("06 12 34 56 78", "Bonjour")
        self.assertIn("Appel termine", reponse)
        compteur = json.loads(appels._fichier_compteur().read_text(encoding="utf-8"))
        self.assertEqual((compteur["appels"], compteur["minutes"]), (1, 1.0))


if __name__ == "__main__":
    unittest.main()
