"""Loopstr : classement absence/deadline et URL privee du flux jamais divulguee.

Aucun appel reseau : requests.get est remplace par un mock.
"""
import unittest
from unittest.mock import MagicMock, patch

import requests

from tools import loopstr

_URL = "https://loopstr.exemple/ical/JETON-FACTICE-123/loopstr.ics?key=CLE-FACTICE"
_SECRETS = ("JETON-FACTICE", "CLE-FACTICE", "loopstr.exemple", "/ical/")


def _reglage(cle, defaut=None):
    return _URL if cle == "loopstr.url" else defaut


class ClassementTests(unittest.TestCase):
    def test_mots_courants_restent_des_deadlines(self):
        for titre in ("Publication offre Black Friday", "Tournage coffret Noel",
                      "Brief disposition vitrine", "Livraison V1 Coffee brand",
                      "Publication offre partenaire", "Script office tour",
                      "Fermer le brief", "Repost story partenaire",
                      "Unboxing coffret cadeau", "Story offerte",
                      "Publication Instagram", "Tournage reel"):
            with self.subTest(titre=titre):
                self.assertEqual(loopstr._classer(titre, ""), "deadline")

    def test_vraies_absences(self):
        for titre in ("Vacances", "Congé", "Congés d'été", "Day off", "OFF",
                      "Off-day", "Indispo", "Indisponible", "Disponibilité",
                      "Dispo", "Absente", "Repos", "Fermé", "Holiday",
                      "Vacation", "Prise de congé"):
            with self.subTest(titre=titre):
                self.assertEqual(loopstr._classer(titre, ""), "absence")

    def test_categorie_d_absence(self):
        self.assertEqual(loopstr._classer("Semaine du 12", "VACANCES"), "absence")


class UrlPriveeTests(unittest.TestCase):
    def setUp(self):
        self._cache = (loopstr._CACHE_EV, loopstr._CACHE_T)
        loopstr._CACHE_EV = None

    def tearDown(self):
        loopstr._CACHE_EV, loopstr._CACHE_T = self._cache

    def _verifier_sans_secret(self, *textes):
        tout = "\n".join(textes)
        for secret in _SECRETS:
            self.assertNotIn(secret, tout)

    def test_erreur_reseau_ni_dans_la_reponse_ni_dans_le_journal(self):
        erreur = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='loopstr.exemple', port=443): Max retries "
            "exceeded with url: /ical/JETON-FACTICE-123/loopstr.ics?key=CLE-FACTICE")
        with patch.object(loopstr, "reglage", side_effect=_reglage), \
                patch("requests.get", side_effect=erreur), \
                self.assertLogs("jarvis", level="DEBUG") as journal:
            reponse = loopstr.get_deadlines("cette semaine")
        self._verifier_sans_secret(reponse, *journal.output)
        self.assertIn("flux injoignable", reponse)

    def test_refus_http_annonce_le_code_sans_l_url(self):
        reponse_http = MagicMock(status_code=403)
        reponse_http.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"403 Client Error: Forbidden for url: {_URL}", response=reponse_http)
        with patch.object(loopstr, "reglage", side_effect=_reglage), \
                patch("requests.get", return_value=reponse_http), \
                self.assertLogs("jarvis", level="DEBUG") as journal:
            reponse = loopstr.get_deadlines("cette semaine")
        self._verifier_sans_secret(reponse, *journal.output)
        self.assertIn("403", reponse)

    def test_charger_ne_rattache_pas_l_exception_d_origine(self):
        # Le tableau de bord et Signal Matin appellent _charger/_echeances : la
        # cause d'origine (message requests avec l'URL) ne doit pas suivre.
        erreur = requests.exceptions.ConnectionError(f"Max retries exceeded with url: {_URL}")
        with patch.object(loopstr, "reglage", side_effect=_reglage), \
                patch("requests.get", side_effect=erreur), \
                self.assertLogs("jarvis", level="DEBUG"):
            with self.assertRaises(loopstr.FluxIndisponible) as ctx:
                loopstr._charger()
        self._verifier_sans_secret(str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)
        self.assertIsInstance(ctx.exception, RuntimeError)


if __name__ == "__main__":
    unittest.main()
