"""Pages web ouvertes par Jarvis : Firefox si choisi et installe, sinon le navigateur par defaut."""
import unittest
from unittest.mock import patch

from core import ouvrir_web


def reglages(**valeurs):
    return lambda cle, defaut=None: valeurs.get(cle, defaut)


class OuvrirUrlTest(unittest.TestCase):
    def test_firefox_par_defaut_dans_un_nouvel_onglet(self):
        with patch.object(ouvrir_web, "reglage", reglages()), \
                patch.object(ouvrir_web, "firefox_exe", return_value=r"C:\ff\firefox.exe"), \
                patch.object(ouvrir_web.subprocess, "Popen") as lancement, \
                patch.object(ouvrir_web.webbrowser, "open_new_tab") as defaut:
            self.assertTrue(ouvrir_web.ouvrir_url("https://www.youtube.com"))
        self.assertEqual(lancement.call_args.args[0],
                         [r"C:\ff\firefox.exe", "-new-tab", "https://www.youtube.com"])
        defaut.assert_not_called()

    def test_sans_firefox_le_navigateur_par_defaut(self):
        with patch.object(ouvrir_web, "reglage", reglages()), \
                patch.object(ouvrir_web, "firefox_exe", return_value=None), \
                patch.object(ouvrir_web.subprocess, "Popen") as lancement, \
                patch.object(ouvrir_web.webbrowser, "open_new_tab", return_value=True) as defaut:
            self.assertTrue(ouvrir_web.ouvrir_url("https://example.org"))
        lancement.assert_not_called()
        defaut.assert_called_once_with("https://example.org")

    def test_reglage_systeme_n_utilise_jamais_firefox(self):
        with patch.object(ouvrir_web, "reglage", reglages(**{"navigateur.prefere": "systeme"})), \
                patch.object(ouvrir_web, "firefox_exe", return_value=r"C:\ff\firefox.exe"), \
                patch.object(ouvrir_web.subprocess, "Popen") as lancement, \
                patch.object(ouvrir_web.webbrowser, "open_new_tab", return_value=True):
            ouvrir_web.ouvrir_url("https://example.org")
        lancement.assert_not_called()


class BrowserOpenTest(unittest.TestCase):
    def test_ouvre_dans_firefox_sans_lancer_chrome(self):
        from tools import navigateur
        with patch("core.poste_distant.executer_principal", return_value=None), \
                patch.object(ouvrir_web, "reglage", reglages()), \
                patch.object(ouvrir_web, "firefox_exe", return_value=r"C:\ff\firefox.exe"), \
                patch.object(ouvrir_web.subprocess, "Popen") as lancement, \
                patch.object(navigateur, "_connexion") as chrome:
            reponse = navigateur.browser_open(url="netflix")
        self.assertIn("Firefox", reponse)
        self.assertEqual(lancement.call_args.args[0][-1], "https://www.netflix.com")
        chrome.assert_not_called()

    def test_avec_firefox_chrome_n_est_jamais_lance_pour_lire(self):
        from tools import navigateur
        with patch.object(ouvrir_web, "reglage", reglages()), \
                patch.object(navigateur, "_BROWSER", None), \
                patch.object(navigateur, "_tenter_cdp", return_value=None), \
                patch.object(navigateur, "_lancer_chrome") as lancement:
            self.assertIsNone(navigateur._connexion())
        lancement.assert_not_called()


if __name__ == "__main__":
    unittest.main()
