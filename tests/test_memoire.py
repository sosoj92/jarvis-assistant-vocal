"""Memoire long terme : un memory.json illisible ou un forget trop large ne perdent rien.

memory.json et l'ancien memoire.json sont rediriges vers un dossier temporaire :
la vraie memoire n'est ni lue ni ecrite.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core import memoire
from tools import memoire as outils

PLEINE = {
    "preferences": {"lumiere": "aime les lumieres chaudes le soir"},
    "people": {"soeur": "s'appelle Anna"},
    "projects": {"jarvis": "assistant vocal local"},
    "facts": ["habite a Lyon"],
}


class _Base(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.dossier = Path(self._dossier.name)
        self.sauve = (memoire.FICHIER, memoire.ANCIEN)
        memoire.FICHIER = self.dossier / "memory.json"
        memoire.ANCIEN = self.dossier / "memoire.json"

    def tearDown(self):
        memoire.FICHIER, memoire.ANCIEN = self.sauve
        self._dossier.cleanup()

    def ecrire(self, octets):
        memoire.FICHIER.write_bytes(octets)
        return octets

    def lire(self):
        return json.loads(memoire.FICHIER.read_text(encoding="utf-8"))

    def copies(self, motif):
        return sorted((self.dossier / "logs").glob(motif)) if (self.dossier / "logs").exists() else []

    def temporaires(self):
        return [p.name for p in self.dossier.iterdir() if p.name.endswith(".tmp")]


class FichierIllisibleTest(_Base):
    def test_virgule_finale_copie_conservee_avant_remember(self):
        texte = json.dumps(PLEINE, ensure_ascii=False)[:-1] + ",}"
        avant = self.ecrire(texte.encode("utf-8"))
        with self.assertLogs("jarvis", "WARNING"):
            self.assertEqual(outils.remember("preference", "aime le cafe", "cafe"), "C'est note.")
        copies = self.copies("memory.json.corrompu-*")
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), avant)     # rien n'est perdu
        self.assertEqual(self.lire()["preferences"], {"cafe": "aime le cafe"})
        self.assertEqual(self.temporaires(), [])

    def test_bom_windows_lu_normalement(self):
        self.ecrire(b"\xef\xbb\xbf" + json.dumps(PLEINE, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(memoire.charger()["people"], {"soeur": "s'appelle Anna"})
        outils.remember("fait", "travaille le soir")
        contenu = self.lire()
        self.assertEqual(contenu["people"], {"soeur": "s'appelle Anna"})
        self.assertIn("travaille le soir", contenu["facts"])
        self.assertEqual(self.copies("memory.json.corrompu-*"), [])

    def test_fichier_ansi_ne_fait_pas_planter_le_demarrage(self):
        self.ecrire('{"facts": ["caf\xe9"]}'.encode("cp1252"))
        with self.assertLogs("jarvis", "WARNING"):
            self.assertEqual(memoire.charger(), memoire._vide())

    def test_copie_impossible_rien_n_est_ecrase(self):
        avant = self.ecrire(b'{"facts": ["un", ]}')
        with patch.object(memoire.shutil, "copy2", side_effect=OSError("disque plein")), \
                self.assertLogs("jarvis", "WARNING"):
            with self.assertRaises(OSError):
                outils.remember("fait", "deux")
        self.assertEqual(memoire.FICHIER.read_bytes(), avant)


class EcritureTest(_Base):
    def test_echec_du_remplacement_laisse_l_original_intact(self):
        memoire.sauver(PLEINE)
        avant = memoire.FICHIER.read_bytes()
        with patch.object(memoire.os, "replace", side_effect=OSError("coupure")):
            with self.assertRaises(OSError):
                outils.remember("fait", "nouveau")
        self.assertEqual(memoire.FICHIER.read_bytes(), avant)
        self.assertEqual(self.temporaires(), [])

    def test_parcours_normal_inchange(self):
        memoire.sauver(PLEINE)
        self.assertEqual(outils.remember("personne", "joue du piano", "Paul"), "C'est note.")
        contenu = self.lire()
        self.assertEqual(contenu["people"]["Paul"], "joue du piano")
        self.assertEqual(contenu["projects"], PLEINE["projects"])
        self.assertEqual(self.copies("*"), [])          # aucune copie inutile

    def test_remember_simultanes_tous_conserves(self):
        memoire.sauver(PLEINE)

        def retenir(prefixe):
            for i in range(10):
                outils.remember("fait", f"{prefixe} {i}")

        fils = [threading.Thread(target=retenir, args=(p,)) for p in ("cuisine", "bureau")]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        faits = self.lire()["facts"]
        self.assertEqual(len(faits), 1 + 20)


class ForgetTest(_Base):
    def test_forget_garde_une_copie_avant_d_effacer(self):
        memoire.sauver(PLEINE)
        avant = memoire.FICHIER.read_bytes()
        self.assertEqual(outils.forget("a"), "Oublie : 4 element(s).")
        self.assertEqual(self.lire(), memoire._vide())
        copie = self.dossier / "logs" / "memory.json.bak"
        self.assertEqual(copie.read_bytes(), avant)     # tout reste recuperable
        self.assertFalse((self.dossier / "memory.json.bak").exists())   # jamais a la racine

    def test_forget_sans_correspondance_ne_copie_rien(self):
        memoire.sauver(PLEINE)
        self.assertEqual(outils.forget("zebre"), "Je n'ai rien la-dessus.")
        self.assertEqual(self.copies("*"), [])


if __name__ == "__main__":
    unittest.main()
