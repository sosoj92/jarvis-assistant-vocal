"""Google Agenda : autorisation OAuth, messages d'erreur et dates relatives.

Aucun appel reseau ni navigateur : le flux OAuth, le client Google et le
service sont remplaces par des mocks ; les fichiers sont dans un dossier temporaire.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools import agenda

_SERVEUR = {"poste_principal.actif": True,
            "poste_principal.serveur_sans_peripheriques": True}


def _reglages(valeurs):
    return lambda cle, defaut=None: valeurs.get(cle, defaut)


class AutorisationTests(unittest.TestCase):
    """Sans jeton, identifiants presents : qui a le droit de lancer le flux OAuth ?"""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        racine = Path(dossier.name)
        ident = racine / "google_credentials.json"
        ident.write_text("{}", encoding="utf-8")
        self.jeton = racine / "google_token.json"          # jamais autorise
        chemins = {"agenda.credentials": ident, "agenda.token": self.jeton}
        for p in (patch.object(agenda, "_SERVICE", None),
                  patch.object(agenda, "_chemin",
                               side_effect=lambda cle, defaut: chemins[cle]),
                  patch("googleapiclient.discovery.build")):
            p.start()
            self.addCleanup(p.stop)
        flux = patch("google_auth_oauthlib.flow.InstalledAppFlow")
        self.flux = flux.start()
        self.addCleanup(flux.stop)
        self.flow = self.flux.from_client_secrets_file.return_value
        self.flow.run_local_server.return_value = MagicMock(
            to_json=MagicMock(return_value="{}"))

    def test_serveur_sans_peripheriques_ne_lance_jamais_le_navigateur(self):
        with patch.object(agenda, "reglage", side_effect=_reglages(_SERVEUR)), \
                self.assertLogs("jarvis", level="DEBUG"):
            reponse = agenda.get_events("demain")
            annonce = agenda._annonce_suppression({"recherche": "dentiste"})
        self.flow.run_local_server.assert_not_called()
        self.flux.from_client_secrets_file.assert_not_called()
        self.assertIn("non relie", reponse)
        self.assertIn("Je ne trouve aucun", annonce)
        self.assertFalse(self.jeton.exists())

    def test_serveur_message_coherent_sans_ecran(self):
        with patch.object(agenda, "reglage", side_effect=_reglages(_SERVEUR)), \
                self.assertLogs("jarvis", level="DEBUG"):
            reponse = agenda.get_events("demain")
        self.assertIn("poste avec ecran", reponse)
        self.assertIn("copie google_token.json sur le serveur", reponse)
        self.assertNotIn("sur ce poste", reponse)
        self.assertNotIn("Verifie les identifiants", reponse)

    def test_appel_non_interactif_explicite(self):
        with patch.object(agenda, "reglage", side_effect=_reglages({})):
            with self.assertRaises(FileNotFoundError):
                agenda._service(interactif=False)
        self.flow.run_local_server.assert_not_called()

    def test_bureau_garde_la_reconnexion_a_la_voix_avec_delai(self):
        with patch.object(agenda, "reglage", side_effect=_reglages({})):
            agenda._service()
        self.flow.run_local_server.assert_called_once_with(port=0, timeout_seconds=300)
        self.assertTrue(self.jeton.exists())

    def test_bureau_consentement_jamais_donne(self):
        from google_auth_oauthlib.flow import WSGITimeoutError
        self.flow.run_local_server.side_effect = WSGITimeoutError("Timed out")
        with patch.object(agenda, "reglage", side_effect=_reglages({})), \
                self.assertLogs("jarvis", level="DEBUG"):
            reponse = agenda.get_events("demain")
        self.assertIn("5 minutes", reponse)
        self.assertFalse(self.jeton.exists())


class ErreurApiTests(unittest.TestCase):
    def test_suppression_ratee_ne_cite_pas_l_uri_ni_l_adresse(self):
        import httplib2
        from googleapiclient.errors import HttpError
        erreur = HttpError(
            httplib2.Response({"status": 410, "reason": "Gone"}),
            b'{"error": {"message": "Resource has been deleted"}}',
            uri="https://www.googleapis.com/calendar/v3/calendars/"
                "prenom.factice%40gmail.com/events/abc123?")
        service = MagicMock()
        service.events.return_value.delete.return_value.execute.side_effect = erreur
        trouve = ("prenom.factice@gmail.com", {"id": "abc123", "summary": "Dentiste"},
                  "owner", "prenom.factice@gmail.com")
        with patch.object(agenda, "_service", return_value=service), \
                patch.object(agenda, "_trouver", return_value=[trouve]), \
                self.assertLogs("jarvis", level="DEBUG"):
            reponse = agenda.delete_event("dentiste")
        for interdit in ("%40", "@", "googleapis", "factice"):
            self.assertNotIn(interdit, reponse)
        self.assertIn("410", reponse)

    def test_creation_ratee_sans_detail_technique(self):
        service = MagicMock()
        service.events.return_value.insert.return_value.execute.side_effect = \
            RuntimeError("https://www.googleapis.com/calendar/v3/calendars/x%40gmail.com")
        with patch.object(agenda, "_service", return_value=service), \
                patch.object(agenda, "reglage", side_effect=_reglages({})), \
                self.assertLogs("jarvis", level="DEBUG"):
            reponse = agenda.create_event("Dentiste", "demain", "15h")
        self.assertNotIn("googleapis", reponse)
        self.assertIn("RuntimeError", reponse)


class DatesRelativesTests(unittest.TestCase):
    def test_apres_demain_avec_ou_sans_tiret(self):
        attendu = agenda._periode("après-demain")
        self.assertEqual(attendu[2], "apres-demain")
        for texte in ("après demain", "apres demain", "Après  demain",
                      "le surlendemain"):
            with self.subTest(texte=texte):
                self.assertEqual(agenda._periode(texte), attendu)
        self.assertEqual(agenda._periode("demain")[2], "demain")

    def test_combiner_apres_demain(self):
        aujourd_hui = dt.datetime.now().astimezone().date()
        for texte in ("après demain", "apres-demain", "Après  demain"):
            with self.subTest(texte=texte):
                d = agenda._combiner(texte, "15h")
                self.assertEqual(d.date(), aujourd_hui + dt.timedelta(days=2))
                self.assertEqual((d.hour, d.minute), (15, 0))
        self.assertEqual(agenda._combiner("demain", "15h").date(),
                         aujourd_hui + dt.timedelta(days=1))

    def test_combiner_midi_et_minuit(self):
        self.assertEqual(agenda._combiner("2026-10-31", "midi").hour, 12)
        self.assertEqual(agenda._combiner("2026-10-31", "à midi").hour, 12)
        self.assertEqual(agenda._combiner("2026-10-31", "minuit").hour, 0)
        self.assertEqual(agenda._combiner("2026-10-31", "12:00").hour, 12)
        self.assertEqual(agenda._combiner("2026-10-31", "15h30").minute, 30)
        # Heure incomprise : la valeur par defaut (9h) est conservee.
        self.assertEqual(agenda._combiner("2026-10-31", "vers le soir").hour, 9)


if __name__ == "__main__":
    unittest.main()
