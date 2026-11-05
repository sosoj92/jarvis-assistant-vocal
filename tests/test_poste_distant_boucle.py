"""Commandes vers le poste distant : jamais d'envoi en retard (sans reseau).

Le websocket est simule ; aucune commande ne quitte le processus.
"""
import asyncio
import threading
import time
import unittest

from core import poste_distant


class _FauxWebSocket:
    def __init__(self):
        self.envois = []

    async def send_text(self, texte):
        self.envois.append(texte)


class BoucleDuPosteTest(unittest.TestCase):
    def tearDown(self):
        with poste_distant._VERROU:
            poste_distant._CONNEXIONS.pop("bureau-test", None)

    def test_appel_depuis_la_boucle_du_poste_refuse_tout_de_suite(self):
        ws = _FauxWebSocket()

        async def scenario():
            connexion = poste_distant._Connexion(
                websocket=ws, boucle=asyncio.get_running_loop(), capacites=set())
            with poste_distant._VERROU:
                poste_distant._CONNEXIONS["bureau-test"] = connexion
            debut = time.monotonic()
            resultat = poste_distant.executer_resultat(
                "capture_screen", {}, identifiant="bureau-test", timeout=0.2)
            duree = time.monotonic() - debut
            await asyncio.sleep(0.3)          # laisse une chance a un envoi tardif
            return resultat, duree

        resultat, duree = asyncio.run(scenario())
        self.assertIn("ne répond pas", resultat)
        self.assertLess(duree, 0.2)
        self.assertEqual(ws.envois, [])

    def test_commande_expiree_annulee_avant_de_partir(self):
        ws = _FauxWebSocket()
        boucle = asyncio.new_event_loop()
        fil = threading.Thread(target=boucle.run_forever, daemon=True)
        fil.start()
        try:
            connexion = poste_distant._Connexion(websocket=ws, boucle=boucle, capacites=set())
            # L'envoi reste bloque derriere le verrou (autre commande en cours).
            asyncio.run_coroutine_threadsafe(connexion.verrou_envoi.acquire(), boucle).result(2)
            with poste_distant._VERROU:
                poste_distant._CONNEXIONS["bureau-test"] = connexion
            resultat = poste_distant.executer_resultat(
                "capture_screen", {}, identifiant="bureau-test", timeout=0.05)
            self.assertIn("ne répond pas", resultat)
            boucle.call_soon_threadsafe(connexion.verrou_envoi.release)
            time.sleep(0.2)
            self.assertEqual(ws.envois, [])   # jamais envoyee apres l'echec annonce
        finally:
            boucle.call_soon_threadsafe(boucle.stop)
            fil.join(2)
            boucle.close()


if __name__ == "__main__":
    unittest.main()
