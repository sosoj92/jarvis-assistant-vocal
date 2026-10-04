"""Suivi de colis : classement local des objets de mail, sans reseau."""
import datetime as dt
import unittest
from unittest.mock import patch

from tools import colis

MAINTENANT = dt.datetime(2026, 10, 4, 8, 0, tzinfo=dt.timezone.utc)


def mail(expediteur, sujet, heures_avant):
    return {"expediteur": expediteur, "sujet": sujet,
            "date": MAINTENANT - dt.timedelta(hours=heures_avant)}


class EtapeTest(unittest.TestCase):
    def test_etapes_reconnues(self):
        cas = {
            "Votre colis est en route": "expedie",
            "Expédié : votre commande 402-1234567-1234567": "expedie",
            "Votre colis est disponible en point relais, code de retrait": "relais",
            "Votre colis est en cours de livraison": "livraison",
            "Votre commande sera livrée aujourd'hui": "livraison",
            "Votre colis a été livré": "livre",
            "Commande livrée": "livre",
            "Your package was delivered": "livre",
        }
        for sujet, attendu in cas.items():
            with self.subTest(sujet=sujet):
                self.assertEqual(colis._etape(sujet), attendu)

    def test_publicites_et_mails_sans_colis_ignores(self):
        for sujet in ("Livraison offerte ce week-end !", "-30 % sur votre prochaine commande",
                      "Donnez votre avis sur votre colis livré", "Je suis en route, j'arrive",
                      "Votre commande de livre est confirmée", "Réunion demain"):
            with self.subTest(sujet=sujet):
                self.assertIsNone(colis._etape(sujet))

    def test_livraison_annoncee_n_est_pas_livree(self):
        self.assertNotEqual(colis._etape("Votre colis sera livré demain"), "livre")


class AnalyseTest(unittest.TestCase):
    def test_etape_la_plus_recente_par_colis(self):
        resultat = colis.analyser([
            mail("Amazon.fr <expedition@amazon.fr>", "Expédié : commande 402-1234567-1234567", 40),
            mail("Amazon.fr <expedition@amazon.fr>",
                 "En cours de livraison : commande 402-1234567-1234567", 2),
        ], MAINTENANT)
        self.assertEqual([(c["marchand"], c["etape"]) for c in resultat],
                         [("Amazon.fr", "livraison")])

    def test_livre_sans_numero_cloture_la_commande_numerotee(self):
        resultat = colis.analyser([
            mail("Amazon.fr <x@amazon.fr>", "Expédié : commande 402-1234567-1234567", 30),
            mail("Amazon.fr <x@amazon.fr>", "Livré : votre colis", 3),
        ], MAINTENANT)
        self.assertEqual([c["etape"] for c in resultat], ["livre"])

    def test_colis_livres_depuis_longtemps_oublies(self):
        resultat = colis.analyser([mail("Colissimo <noreply@laposte.fr>",
                                        "Votre colis a été livré", 72)], MAINTENANT)
        self.assertEqual(resultat, [])

    def test_marchand_lu_dans_le_domaine_si_nom_generique(self):
        self.assertEqual(colis._marchand("no-reply <no-reply@mondialrelay.fr>"), "Mondialrelay")
        self.assertEqual(colis._marchand("Vinted <no-reply@vinted.fr>"), "Vinted")

    def test_plusieurs_colis_tries_du_plus_avance(self):
        resultat = colis.analyser([
            mail("Zara <a@zara.com>", "Votre commande a été expédiée", 20),
            mail("Vinted <a@vinted.fr>", "Ton colis est disponible en point relais", 5),
        ], MAINTENANT)
        self.assertEqual([c["marchand"] for c in resultat], ["Vinted", "Zara"])


class BriefTest(unittest.TestCase):
    def test_phrase_du_brief(self):
        trouves = [{"marchand": "Vinted", "etape": "relais"},
                   {"marchand": "Zara", "etape": "expedie"}]
        with patch.object(colis.mail, "_mail_configure", return_value=True), \
                patch.object(colis, "colis_en_cours", return_value=trouves):
            self.assertEqual(colis.colis_du_brief(),
                             "Côté colis : Vinted t'attend en point relais et Zara est en route.")

    def test_rien_sans_messagerie_ni_colis(self):
        with patch.object(colis.mail, "_mail_configure", return_value=False):
            self.assertEqual(colis.colis_du_brief(), "")
        with patch.object(colis.mail, "_mail_configure", return_value=True), \
                patch.object(colis, "colis_en_cours", return_value=[]):
            self.assertEqual(colis.colis_du_brief(), "")

    def test_erreur_imap_ne_casse_pas_le_brief(self):
        with patch.object(colis.mail, "_mail_configure", return_value=True), \
                patch.object(colis, "colis_en_cours", side_effect=OSError("hors ligne")):
            self.assertEqual(colis.colis_du_brief(), "")


if __name__ == "__main__":
    unittest.main()
