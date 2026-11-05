"""Google Home : un echec d'API ne renvoie jamais l'URL SDM brute (sans reseau)."""
import unittest
from unittest.mock import patch

import requests

from tools import google_home


def _erreur_http(code=403):
    reponse = requests.Response()
    reponse.status_code = code
    return requests.HTTPError(
        f"{code} for url https://smartdevicemanagement.googleapis.com/v1/enterprises/"
        "projet-secret/devices", response=reponse)


class GoogleHomeErreursTest(unittest.TestCase):
    def test_code_http_seulement(self):
        with patch.object(google_home, "_configure", return_value=True), \
                patch.object(google_home, "_appareils", side_effect=_erreur_http()), \
                patch.object(google_home.LOG, "exception"):
            for message in (google_home.google_home_etat(),
                            google_home.google_home_allumer("lampe", True)):
                with self.subTest(message=message):
                    self.assertIn("(403)", message)
                    self.assertNotIn("projet-secret", message)
                    self.assertNotIn("googleapis", message)

    def test_sans_reponse_le_type_d_erreur(self):
        with patch.object(google_home, "_configure", return_value=True), \
                patch.object(google_home, "_appareils",
                             side_effect=ConnectionError("https://x/enterprises/secret")), \
                patch.object(google_home.LOG, "exception"):
            message = google_home.google_home_etat()
        self.assertIn("(ConnectionError)", message)
        self.assertNotIn("secret", message)


if __name__ == "__main__":
    unittest.main()
