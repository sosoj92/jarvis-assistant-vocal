"""Overlay de réponses, sans Tk ni thread : on observe la file de commandes `_Q`."""
import queue
import unittest

import overlay


def _vider():
    while True:
        try:
            overlay._Q.get_nowait()
        except queue.Empty:
            return


class OverlayFileTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(overlay._CFG)
        self._derniere = dict(overlay._DERNIERE)
        _vider()

    def tearDown(self):
        _vider()
        overlay._CFG.clear()
        overlay._CFG.update(self._cfg)
        overlay._DERNIERE.clear()
        overlay._DERNIERE.update(self._derniere)

    def actions(self):
        return [action for action, _ in list(overlay._Q.queue)]

    def test_affiche_le_est_une_surcharge_ponctuelle(self):
        overlay.set_actif(False)                 # « masque les réponses »
        overlay.memoriser("Adresse : 12 rue X", "reponse")
        _vider()
        self.assertTrue(overlay.reafficher())    # « affiche-le »
        self.assertFalse(overlay.est_actif())
        file = list(overlay._Q.queue)
        self.assertEqual([a for a, _ in file], ["afficher"])
        self.assertEqual(file[0][1]["texte"], "Adresse : 12 rue X")
        overlay.afficher("réponse suivante")     # reste masquée
        self.assertEqual(self.actions(), ["afficher"])

    def test_reafficher_sans_reponse_memorisee(self):
        overlay.memoriser("")
        self.assertFalse(overlay.reafficher())
        self.assertEqual(self.actions(), [])

    def test_set_actif(self):
        overlay.set_actif(False)
        self.assertFalse(overlay.est_actif())
        self.assertEqual(self.actions(), ["masquer"])
        overlay.afficher("ignorée")
        self.assertEqual(self.actions(), ["masquer"])
        overlay.set_actif(True)
        overlay.afficher("visible")
        self.assertEqual(self.actions(), ["masquer", "afficher"])

    def test_texte_vide_jamais_affiche(self):
        overlay.set_actif(True)
        overlay.afficher("")
        overlay.afficher(None)
        self.assertEqual(self.actions(), [])


if __name__ == "__main__":
    unittest.main()
