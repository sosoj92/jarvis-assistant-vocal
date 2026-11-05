"""Transactions locales : deduplication par rang d'occurrence et regles de
categorisation robustes aux motifs vides ou tres courts. Stockage en dossier temporaire."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import transactions as tx


def _t(libelle, montant, date="2026-10-12"):
    return {"date": date, "libelle": libelle, "montant": montant, "source": "csv"}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        dossier = Path(self._tmp.name)
        self._patches = [patch.object(tx, "_DOSSIER", dossier),
                         patch.object(tx, "_FICHIER", dossier / "transactions.jsonl"),
                         patch.object(tx, "_REGLES", dossier / "regles.yaml")]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class DeduplicationTest(_Base):
    def test_deux_operations_identiques_le_meme_jour(self):
        lot = [_t("NAVIGO", -2.15), _t("NAVIGO", -2.15), _t("CB BOULANGERIE", -1.2)]
        self.assertEqual(tx.ajouter(lot), 3)
        self.assertEqual(tx.ajouter(lot), 0)               # reimport idempotent
        self.assertEqual(tx.vue_mois("2026-10")["sorties"], 5.5)

    def test_releves_qui_se_chevauchent(self):
        self.assertEqual(tx.ajouter([_t("NAVIGO", -2.15)]), 1)
        self.assertEqual(tx.ajouter([_t("NAVIGO", -2.15), _t("NAVIGO", -2.15)]), 1)
        self.assertEqual(len(tx.charger()), 2)

    def test_ancien_id_sans_rang_reconnu(self):
        ancienne = dict(_t("NAVIGO", -2.15), categorie="Transport")
        ancienne["id"] = tx._id(ancienne)
        tx._FICHIER.write_text(json.dumps(ancienne) + "\n", encoding="utf-8")
        self.assertEqual(tx.ajouter([_t("NAVIGO", -2.15)]), 0)


class ReglesTest(_Base):
    def _lot(self):
        tx.ajouter([_t("VIR CAISSE ALLOCATIONS", 500, "2026-09-03"),
                    _t("VIR INST MARTIN", 80, "2026-09-04"),
                    _t("CB CASTORAMA", -40, "2026-09-05"),
                    _t("CB BP 1234", -60, "2026-09-06")])

    def test_motif_vide_refuse(self):
        for motif in ("", "   ", None):
            with self.subTest(motif=motif), self.assertRaises(ValueError):
                tx.memoriser_regle(motif, "Divers")
        self.assertFalse(tx._REGLES.exists())

    def test_motif_court_sur_mot_entier(self):
        self._lot()
        tx.memoriser_regle("ça", "Loisirs")
        tx.memoriser_regle("bp", "Carburant")
        cats = tx.vue_mois("2026-09")["par_categorie"]
        self.assertNotIn("Loisirs", cats)
        self.assertEqual(cats["Revenus"]["entrees"], 580)
        self.assertEqual(cats["Carburant"]["sorties"], 60)

    def test_regle_longue_reste_une_sous_chaine(self):
        self.assertEqual(tx.categoriser("CB MCDONALDS PARIS", -9), "Restauration")

    def test_outil_demande_de_preciser(self):
        from tools import finances
        self.assertIn("Précise", finances.corriger_categorie("  ", "Divers"))


if __name__ == "__main__":
    unittest.main()
