"""Repli « touche média » de lancer_spotify, sans Spotify ni poste réel."""
import unittest
from unittest.mock import patch

from tools import spotify, systeme  # noqa: F401  (charge tools.systeme pour le patch)

SUCCES = "Spotify est lancé et j'ai envoyé la commande lecture."
ECHEC = "Spotify est lancé, mais je n'ai pas pu démarrer la lecture."


class RepliToucheMediaTests(unittest.TestCase):
    def _lancer(self, **media):
        with patch("tools.spotify._configure", return_value=False), \
                patch("tools.spotify._ouvrir_application_spotify", return_value=None), \
                patch("tools.spotify.time.sleep"), \
                patch("tools.systeme.controler_media", **media) as controler:
            resultat = spotify.lancer_spotify()
        controler.assert_called_once_with("pause")
        return resultat

    def test_echec_du_poste_principal_n_est_pas_annonce_comme_lecture(self):
        for reponse in ("Le poste bureau ne répond pas.",
                        "Commande impossible sur le poste principal : x",
                        "Commande multimédia inconnue.",
                        "Le poste distant n'a pas pu exécuter la commande."):
            with self.subTest(reponse=reponse):
                self.assertEqual(self._lancer(return_value=reponse), ECHEC)

    def test_exception_reste_un_echec(self):
        self.assertEqual(self._lancer(side_effect=OSError("clavier")), ECHEC)

    def test_succes_local_ou_distant_garde_l_annonce(self):
        for reponse in ("Fait : pause.",
                        "Commande pause envoyée au poste principal."):
            with self.subTest(reponse=reponse):
                self.assertEqual(self._lancer(return_value=reponse), SUCCES)


if __name__ == "__main__":
    unittest.main()
