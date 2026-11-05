"""Instance Playwright partagee : tout le travail passe par UN thread dedie.

Sans Playwright reel : un faux demarreur reproduit ses deux contraintes (objet lie
au thread createur, refus de demarrer dans une boucle asyncio en cours)."""
import asyncio
import sys
import threading
import types
import unittest
from unittest.mock import patch

from core import playwright_partage as pp


class _FauxPlaywright:
    def __init__(self):
        self.thread = threading.current_thread()

    def utiliser(self):
        # Comme les greenlets de l'API sync : inutilisable hors du thread createur.
        if threading.current_thread() is not self.thread:
            raise RuntimeError("cannot switch to a different thread")
        return "ok"


class _FauxDemarreur:
    def start(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _FauxPlaywright()
        raise RuntimeError("It looks like you are using Playwright Sync API inside the asyncio loop.")


def _modules_factices():
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = _FauxDemarreur
    return {"playwright": types.ModuleType("playwright"), "playwright.sync_api": sync_api}


def _dans_un_thread(fn):
    """Lance fn dans un thread neuf (qui se termine ensuite) et renvoie son resultat."""
    sortie = {}

    def corps():
        try:
            sortie["valeur"] = fn()
        except BaseException as e:      # noqa: BLE001 - remonte dans le test
            sortie["erreur"] = e

    t = threading.Thread(target=corps)
    t.start()
    t.join(5)
    if t.is_alive():
        raise AssertionError("interblocage")
    if "erreur" in sortie:
        raise sortie["erreur"]
    return sortie["valeur"]


class PlaywrightPartageTest(unittest.TestCase):
    def setUp(self):
        for patcheur in (patch.dict(sys.modules, _modules_factices()),
                         patch.object(pp, "_PW", None),
                         patch.object(pp, "_THREAD_PW", None)):
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def test_le_travail_tourne_toujours_sur_le_meme_thread_dedie(self):
        t1 = _dans_un_thread(lambda: pp.executer(threading.current_thread))
        t2 = _dans_un_thread(lambda: pp.executer(threading.current_thread))
        self.assertIs(t1, t2)
        self.assertTrue(t1.name.startswith("playwright"))

    def test_deux_threads_successifs_partagent_l_instance(self):
        # Reproduction du defaut : instance creee par le thread A (termine), puis
        # utilisee par le thread B -> « cannot switch to a different thread ».
        self.assertEqual(_dans_un_thread(lambda: pp.executer(lambda: pp.obtenir().utiliser())), "ok")
        self.assertEqual(_dans_un_thread(lambda: pp.executer(lambda: pp.obtenir().utiliser())), "ok")
        self.assertIs(pp.executer(pp.obtenir), pp.executer(pp.obtenir))

    def test_depuis_une_boucle_asyncio_en_cours(self):
        # Confirmation d'un satellite : executee sur le thread de la boucle uvicorn.
        async def coroutine():
            return pp.executer(lambda: pp.obtenir().utiliser())
        self.assertEqual(asyncio.run(coroutine()), "ok")

    def test_appel_reentrant_sans_interblocage(self):
        self.assertEqual(_dans_un_thread(lambda: pp.executer(lambda: pp.executer(lambda: 42))), 42)

    def test_les_erreurs_remontent_a_l_appelant(self):
        with self.assertRaises(ZeroDivisionError):
            pp.executer(lambda: 1 / 0)

    def test_obtenir_hors_du_thread_createur_leve_une_erreur_claire(self):
        pp.executer(pp.obtenir)
        with self.assertRaises(RuntimeError) as erreur:
            pp.obtenir()
        self.assertIn("executer", str(erreur.exception))

    def test_meme_thread_sans_executeur_reste_possible(self):
        # Compatibilite : un appelant qui reste sur un seul thread continue de marcher.
        self.assertIs(pp.obtenir(), pp.obtenir())


class OutilsSurThreadDedieTest(unittest.TestCase):
    """Les outils navigateur, reservation et factures ne touchent Playwright que sur
    le thread dedie, quel que soit le thread qui les appelle (sans navigateur reel)."""

    def _thread_du_corps(self, module, nom_corps, appel):
        vu = []

        def corps(*_a, **_k):
            vu.append(pp.sur_thread_dedie())
            return "ok"

        with patch.object(module, nom_corps, side_effect=corps):
            self.assertEqual(_dans_un_thread(appel), "ok")
        self.assertEqual(vu, [True])

    def test_outils_navigateur(self):
        from tools import navigateur
        for nom_corps, appel in (
                ("_browser_current_page", navigateur.browser_current_page),
                ("_browser_tabs", lambda: navigateur.browser_tabs("lister")),
                ("_browser_close_tabs", lambda: navigateur.browser_close_tabs("x")),
                ("_browser_interact", lambda: navigateur.browser_interact("pause"))):
            with self.subTest(outil=nom_corps):
                self._thread_du_corps(navigateur, nom_corps, appel)

    def test_reservation(self):
        from tools import reservation
        self._thread_du_corps(reservation, "_book_appointment",
                              lambda: reservation.book_appointment("site", "table", "vendredi"))
        self._thread_du_corps(reservation, "_confirmer_reservation",
                              reservation.confirmer_reservation)

    def test_connexion_chrome_sur_le_thread_dedie(self):
        from tools import navigateur
        vu = []

        def connexion(*_a, **_k):
            vu.append(pp.sur_thread_dedie())
            return None                        # Chrome absent : message d'absence

        with patch.object(navigateur, "_connexion", side_effect=connexion):
            _dans_un_thread(navigateur.browser_current_page)
        self.assertEqual(vu, [True])


if __name__ == "__main__":
    unittest.main()
