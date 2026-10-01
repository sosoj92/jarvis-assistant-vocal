import unittest

from tools.instagram import _erreur_sans_secret


class InstagramSecurityTests(unittest.TestCase):
    def test_erreur_instagram_masque_le_jeton_dans_une_url(self):
        secret = "jeton-tres-secret"
        erreur = (
            "HTTPSConnectionPool: /refresh_access_token?"
            f"grant_type=ig_refresh_token&access_token={secret}&limit=10"
        )

        nettoyee = _erreur_sans_secret(erreur)

        self.assertNotIn(secret, nettoyee)
        self.assertIn("access_token=<masque>", nettoyee)
        self.assertIn("limit=10", nettoyee)


if __name__ == "__main__":
    unittest.main()
