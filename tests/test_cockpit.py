"""Cockpit Finances : échéances, montants saisis à la main et alerte « montant changé ».

Sans réseau ni vraie donnée : finances/ est redirigé vers un dossier temporaire.
"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import cockpit

D = dt.date


class EcheanceTests(unittest.TestCase):
    def test_ancre_en_fin_de_mois_ne_derive_plus_vers_le_28(self):
        cas = [
            ({"periodicite": "mensuel", "date": "2026-01-31"}, D(2026, 10, 29), D(2026, 10, 31)),
            ({"periodicite": "mensuel", "date": "2026-01-31"}, D(2026, 10, 30), D(2026, 10, 31)),
            ({"periodicite": "mensuel", "date": "2026-01-31"}, D(2026, 11, 1), D(2026, 11, 30)),
            ({"periodicite": "trimestriel", "date": "2026-01-31"}, D(2026, 10, 29), D(2026, 10, 31)),
            ({"periodicite": "trimestriel", "date": "2026-03-31"}, D(2026, 7, 1), D(2026, 9, 30)),
            ({"periodicite": "semestriel", "date": "2026-08-31"}, D(2027, 3, 1), D(2027, 8, 31)),
            ({"periodicite": "annuel", "date": "2024-02-29"}, D(2028, 2, 1), D(2028, 2, 29)),
            ({"periodicite": "annuel", "date": "2024-02-29"}, D(2025, 3, 1), D(2026, 2, 28)),
        ]
        for abo, auj, attendu in cas:
            with self.subTest(abo=abo, auj=auj):
                self.assertEqual(cockpit._prochaine_echeance(abo, auj), attendu)

    def test_ancre_du_jour_et_ancre_future_inchangees(self):
        auj = D(2026, 10, 29)
        self.assertEqual(cockpit._prochaine_echeance(
            {"periodicite": "mensuel", "date": "2026-10-29"}, auj), auj)
        self.assertEqual(cockpit._prochaine_echeance(
            {"periodicite": "annuel", "date": "2027-03-15"}, auj), D(2027, 3, 15))
        self.assertEqual(cockpit._prochaine_echeance(
            {"periodicite": "hebdomadaire", "date": "2026-11-05"}, auj), D(2026, 11, 5))

    def test_hebdomadaire_avance_par_semaine_depuis_l_ancre(self):
        auj = D(2026, 10, 29)                       # un jeudi
        cas = [
            ({"periodicite": "hebdomadaire", "date": "2026-10-01"}, D(2026, 10, 29)),
            ({"periodicite": "hebdo", "date": "2026-10-22"}, D(2026, 10, 29)),
            ({"periodicite": "semaine", "date": "2026-10-23"}, D(2026, 10, 30)),
            ({"periodicite": "Hebdomadaire", "date": "2026-10-28"}, D(2026, 11, 4)),
        ]
        for abo, attendu in cas:
            with self.subTest(abo=abo):
                self.assertEqual(cockpit._prochaine_echeance(abo, auj), attendu)

    def test_chemin_jour_inchange(self):
        auj = D(2026, 10, 29)
        self.assertEqual(cockpit._prochaine_echeance({"jour": 5}, auj), D(2026, 11, 5))
        self.assertEqual(cockpit._prochaine_echeance({"jour": 30}, auj), D(2026, 11, 28))
        self.assertEqual(cockpit._prochaine_echeance({"jour": "29"}, D(2026, 10, 2)),
                         D(2026, 10, 28))
        # date illisible : repli sur le jour du mois
        self.assertEqual(cockpit._prochaine_echeance(
            {"date": "31/01/2026", "jour": 5}, auj), D(2026, 11, 5))

    def test_jour_illisible_leve_une_erreur_explicite(self):
        with self.assertRaises(ValueError):
            cockpit._prochaine_echeance({"jour": "le 10"}, D(2026, 10, 29))


class MontantTests(unittest.TestCase):
    def test_saisies_a_la_francaise(self):
        self.assertEqual(cockpit._montant("9,99"), 9.99)
        self.assertEqual(cockpit._montant("9,99 €"), 9.99)
        self.assertEqual(cockpit._montant(" 12.5€ "), 12.5)
        self.assertEqual(cockpit._montant("1" + chr(0xA0) + "234,50"), 1234.5)  # insécable
        self.assertEqual(cockpit._montant(13), 13.0)
        self.assertEqual(cockpit._montant(None), 0.0)
        self.assertEqual(cockpit._montant(""), 0.0)

    def test_valeur_illisible_refusee(self):
        for valeur in ("douze", "9,99 EUR", "nan", "inf", [9.99]):
            with self.subTest(valeur=valeur), self.assertRaises((ValueError, TypeError)):
                cockpit._montant(valeur)


class _DossierFinances(unittest.TestCase):
    """finances/ redirigé vers un dossier temporaire, jamais le vrai."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        dossier = Path(self._tmp.name) / "finances"
        dossier.mkdir()
        self.abonnements = dossier / "abonnements.yaml"
        self.etat = dossier / ".etat_abonnements.json"
        for nom, valeur in (("_DOSSIER", dossier), ("_ABONNEMENTS", self.abonnements),
                            ("_ETAT_ABO", self.etat)):
            p = patch.object(cockpit, nom, valeur)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def ecrire(self, texte):
        self.abonnements.write_text(texte, encoding="utf-8")


class FinancesRobustesTests(_DossierFinances):
    def test_une_ligne_illisible_ne_fait_plus_tomber_tout_le_volet(self):
        self.ecrire(
            "- service: Netflix\n  montant: 13.49\n  jour: 5\n"
            "- service: Box\n  montant: 9,99\n  jour: 12\n"
            "- service: Musique\n  montant: 10,99 €\n  jour: 3\n"
            "- service: Bizarre\n  montant: douze\n  jour: 1\n"
            "- service: Salle\n  montant: 30\n  jour: le 10\n")
        d = cockpit._finances(D(2026, 10, 29))
        self.assertEqual(d["fichier"], "ok")
        self.assertEqual(d["nb"], 3)
        self.assertEqual(d["total_mensuel"], 34.47)
        self.assertEqual({a["service"] for a in d["abonnements"]}, {"Netflix", "Box", "Musique"})
        self.assertIn("Ligne ignorée : Bizarre, montant illisible", d["alertes"])
        self.assertIn("Ligne ignorée : Salle, jour illisible", d["alertes"])
        json.dumps(d, allow_nan=False)              # réponse sérialisable telle quelle

    def test_fichier_absent_et_fichier_invalide_distingues(self):
        d = cockpit._finances(D(2026, 10, 29))
        self.assertEqual((d["fichier"], d["nb"]), ("absent", 0))
        self.assertFalse(self.etat.exists())        # rien à mémoriser : aucun fichier créé
        self.ecrire("- service: Netflix\n  montant: [13.49\n")
        d = cockpit._finances(D(2026, 10, 29))
        self.assertEqual((d["fichier"], d["nb"]), ("invalide", 0))
        self.assertTrue(any("illisible" in a for a in d["alertes"]))
        self.ecrire("service: Netflix\nmontant: 13.49\n")   # pas une liste
        self.assertEqual(cockpit._finances(D(2026, 10, 29))["fichier"], "invalide")

    def test_yaml_invalide_conserve_l_etat_et_la_hausse_est_signalee(self):
        self.ecrire("- service: Netflix\n  montant: 13.49\n")
        cockpit._finances(D(2026, 10, 1))
        avant = self.etat.read_text(encoding="utf-8")
        self.ecrire("- service: Netflix\n  montant: [15.99\n")   # édition en cours
        cockpit._finances(D(2026, 10, 2))
        self.assertEqual(self.etat.read_text(encoding="utf-8"), avant)
        self.ecrire("- service: Netflix\n  montant: 15.99\n")
        d = cockpit._finances(D(2026, 10, 3))
        self.assertIn("Montant changé : Netflix 13.49 € → 15.99 €", d["alertes"])

    def test_ligne_illisible_garde_l_ancien_montant(self):
        self.ecrire("- service: Netflix\n  montant: 13.49\n")
        cockpit._finances(D(2026, 10, 1))
        self.ecrire("- service: Netflix\n  montant: 15.99 EUR\n")
        d = cockpit._finances(D(2026, 10, 2))
        self.assertFalse(any(a.startswith("Montant changé") for a in d["alertes"]))
        self.ecrire("- service: Netflix\n  montant: 15,99\n")
        d = cockpit._finances(D(2026, 10, 3))
        self.assertIn("Montant changé : Netflix 13.49 € → 15.99 €", d["alertes"])


class RouteFinancesTests(_DossierFinances):
    def client(self, hote):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        cockpit.monter_routes(app)
        return TestClient(app, client=(hote, 50000), base_url="http://127.0.0.1")

    def test_montant_a_virgule_ne_renvoie_plus_500(self):
        self.ecrire("- service: Box\n  montant: 9,99\n  jour: 12\n")
        r = self.client("127.0.0.1").get("/api/cockpit/finances")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total_mensuel"], 9.99)

    def test_route_reste_locale(self):
        self.ecrire("- service: Box\n  montant: 9.99\n")
        r = self.client("192.168.1.20").get("/api/cockpit/finances")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.etat.exists())


class AlerteMontantChangeTests(_DossierFinances):
    def test_l_alerte_survit_aux_rafraichissements_puis_expire(self):
        self.ecrire("- service: Netflix\n  montant: 13.49\n")
        self.assertEqual(cockpit._finances(D(2026, 10, 1))["alertes"], [])
        self.ecrire("- service: Netflix\n  montant: 15.99\n")
        alerte = "Montant changé : Netflix 13.49 € → 15.99 €"
        for jour in (2, 2, 2, 5, 8):                  # rafraîchissements successifs
            with self.subTest(jour=jour):
                self.assertIn(alerte, cockpit._finances(D(2026, 10, jour))["alertes"])
        self.assertNotIn(alerte, cockpit._finances(D(2026, 10, 9))["alertes"])
        etat = json.loads(self.etat.read_text(encoding="utf-8"))
        self.assertEqual(etat, {"montants": {"Netflix": 15.99}, "changements": []})

    def test_get_sans_changement_ne_reecrit_pas_l_etat(self):
        self.ecrire("- service: Netflix\n  montant: 13.49\n")
        cockpit._finances(D(2026, 10, 1))
        with patch.object(Path, "write_text") as ecrire:
            cockpit._finances(D(2026, 10, 1))
        ecrire.assert_not_called()

    def test_ancien_format_plat_relu_puis_migre(self):
        self.etat.write_text(json.dumps({"Netflix": 13.49}), encoding="utf-8")
        self.ecrire("- service: Netflix\n  montant: 15.99\n")
        d = cockpit._finances(D(2026, 10, 2))
        self.assertIn("Montant changé : Netflix 13.49 € → 15.99 €", d["alertes"])
        etat = json.loads(self.etat.read_text(encoding="utf-8"))
        self.assertEqual(etat["montants"], {"Netflix": 15.99})
        self.assertEqual(etat["changements"], [
            {"service": "Netflix", "avant": 13.49, "apres": 15.99, "depuis": "2026-10-02"}])

    def test_etat_corrompu_ne_fait_pas_planter(self):
        self.etat.write_text(json.dumps({"montants": {"Netflix": "n/a"},
                                         "changements": ["x", {"service": "Box"}]}),
                             encoding="utf-8")
        self.ecrire("- service: Netflix\n  montant: 15.99\n")
        d = cockpit._finances(D(2026, 10, 2))
        self.assertEqual(d["nb"], 1)
        self.assertFalse(any(a.startswith("Montant changé") for a in d["alertes"]))

    def test_abonnement_retire_n_est_plus_signale(self):
        self.ecrire("- service: Netflix\n  montant: 13.49\n- service: Box\n  montant: 30\n")
        cockpit._finances(D(2026, 10, 1))
        self.ecrire("- service: Netflix\n  montant: 15.99\n- service: Box\n  montant: 30\n")
        self.assertIn("Montant changé : Netflix 13.49 € → 15.99 €",
                      cockpit._finances(D(2026, 10, 2))["alertes"])
        self.ecrire("- service: Box\n  montant: 30\n")
        d = cockpit._finances(D(2026, 10, 3))
        self.assertFalse(any(a.startswith("Montant changé") for a in d["alertes"]))

    def test_alerte_toujours_affichee_si_le_yaml_devient_invalide(self):
        self.ecrire("- service: Netflix\n  montant: 13.49\n")
        cockpit._finances(D(2026, 10, 1))
        self.ecrire("- service: Netflix\n  montant: 15.99\n")
        cockpit._finances(D(2026, 10, 2))
        self.ecrire("- service: Netflix\n  montant: [15.99\n")
        d = cockpit._finances(D(2026, 10, 3))
        self.assertIn("Montant changé : Netflix 13.49 € → 15.99 €", d["alertes"])


if __name__ == "__main__":
    unittest.main()
