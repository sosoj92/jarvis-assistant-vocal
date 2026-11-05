"""Reservation web : pas de validation armee en douce, et coordonnees saisies
uniquement sur le site de depart. Navigateur et modele cloud simules."""
import unittest
from unittest.mock import MagicMock, patch

from core import config, registre

registre.charger_outils()

from tools import reservation  # noqa: E402


def _page(url):
    page = MagicMock()
    page.url = url
    return page


class _Base(unittest.TestCase):
    def setUp(self):
        self._config = patch.object(config, "_CONFIG", {})
        self._config.start()
        self._distant = patch("core.poste_distant.executer_outil_principal", return_value=None)
        self._distant.start()
        registre.annuler_confirme()
        self._etat = (reservation._SITE_DEPART[0], reservation._DEPART_RECHERCHE[0],
                      reservation._RESUME_RESA, reservation._PAGE)

    def tearDown(self):
        (reservation._SITE_DEPART[0], reservation._DEPART_RECHERCHE[0],
         reservation._RESUME_RESA, reservation._PAGE) = self._etat
        registre.annuler_confirme()
        self._distant.stop()
        self._config.stop()


class ValidationNonArmeeTest(_Base):
    def test_book_appointment_ne_laisse_aucune_attente(self):
        page = _page("https://www.lebistrot.fr/reserver")
        action = {"action": "pret_a_confirmer", "resume": "table pour 2 vendredi 20h"}
        with patch.object(reservation, "_demarrer_navigateur", return_value=page), \
                patch.object(reservation, "_paiement_present", return_value=False), \
                patch.object(reservation, "_demander_action", return_value=action):
            registre.mettre_en_attente(registre.get("book_appointment"),
                                       {"site": "https://www.lebistrot.fr", "quoi": "table",
                                        "quand": "vendredi 20h"})
            resultat = registre.executer_confirme()
        self.assertIn("Formulaire pret", resultat)
        self.assertIsNone(registre.nom_en_attente())
        self.assertIsNone(registre.annonce_en_attente())

    def test_confirmer_reservation_reste_n3(self):
        self.assertEqual(registre.niveau("confirmer_reservation"), "N3")


class ResumePerimeTest(_Base):
    def test_resume_d_une_reservation_precedente_efface(self):
        # A validee ou preparee, puis B bloque : « valide quand meme » ne doit ni
        # annoncer A ni cliquer sur la page de B.
        reservation._RESUME_RESA = "A : table pour 2 vendredi 20h"
        page = _page("https://www.lebistrot.fr/reserver")
        with patch.object(reservation, "_demarrer_navigateur", return_value=page), \
                patch.object(reservation, "_paiement_present", return_value=False), \
                patch.object(reservation, "_demander_action",
                             return_value={"action": "bloque", "raison": "complet"}):
            reservation.book_appointment("https://www.lebistrot.fr", "B", "samedi")
        self.assertEqual(reservation._RESUME_RESA, "")
        self.assertNotIn("A : table", reservation._annonce_validation({}))
        reservation._PAGE = page
        with patch.object(reservation, "_paiement_present", return_value=False), \
                patch.object(reservation, "_demander_action") as demander, \
                patch.object(reservation, "_executer_action") as executer:
            resultat = reservation.confirmer_reservation()
        demander.assert_not_called()
        executer.assert_not_called()
        self.assertIn("rien de pret a valider", resultat)

    def test_resume_efface_apres_validation(self):
        reservation._SITE_DEPART[0] = "https://www.lebistrot.fr"
        reservation._RESUME_RESA = "table pour 2 vendredi 20h"
        reservation._PAGE = _page("https://www.lebistrot.fr/reserver")
        with patch.object(reservation, "_paiement_present", return_value=False), \
                patch.object(reservation, "_demander_action",
                             return_value={"action": "cliquer", "index": 1}), \
                patch.object(reservation, "_executer_action") as executer:
            resultat = reservation.confirmer_reservation()
        executer.assert_called_once()
        self.assertIn("Reservation validee : table pour 2 vendredi 20h", resultat)
        self.assertEqual(reservation._RESUME_RESA, "")


class MemeSiteTest(_Base):
    def test_suffixes_a_deux_labels(self):
        self.assertFalse(reservation._meme_site("https://evil.co.uk/x", "https://www.resto.co.uk/"))
        self.assertFalse(reservation._meme_site("https://phish.gouv.fr/x",
                                                "https://www.service-public.gouv.fr/"))
        self.assertTrue(reservation._meme_site("https://book.resto.co.uk/x", "https://www.resto.co.uk/"))
        self.assertTrue(reservation._meme_site("https://www.doctolib.fr/rdv", "https://doctolib.fr"))

    def test_taper_refuse_hors_du_site(self):
        reservation._SITE_DEPART[0] = "https://www.doctolib.fr"
        reservation._DEPART_RECHERCHE[0] = False
        page = _page("https://formulaire.evil.example/")
        resultat = reservation._executer_action(page, {"action": "taper", "index": 4,
                                                        "texte": "0600000000"})
        page.fill.assert_not_called()
        self.assertIn("refusee", resultat)

    def test_choisir_refuse_hors_du_site(self):
        reservation._SITE_DEPART[0] = "https://www.doctolib.fr"
        reservation._DEPART_RECHERCHE[0] = False
        page = _page("https://formulaire.evil.example/")
        resultat = reservation._executer_action(page, {"action": "choisir", "index": 2,
                                                        "texte": "2"})
        page.select_option.assert_not_called()
        self.assertIn("refusee", resultat)

    def test_taper_autorise_sur_le_site(self):
        reservation._SITE_DEPART[0] = "https://www.doctolib.fr"
        page = _page("https://partners.doctolib.fr/rdv")
        page.query_selector.return_value = None
        reservation._executer_action(page, {"action": "taper", "index": 1, "texte": "Martin"})
        page.fill.assert_called_once()

    def test_pret_a_confirmer_refuse_hors_du_site(self):
        page = _page("https://formulaire.evil.example/")
        action = {"action": "pret_a_confirmer", "resume": "table pour 2"}
        with patch.object(reservation, "_demarrer_navigateur", return_value=page), \
                patch.object(reservation, "_paiement_present", return_value=False), \
                patch.object(reservation, "_demander_action", return_value=action):
            resultat = reservation.book_appointment("https://www.lebistrot.fr", "table", "vendredi")
        self.assertIn("Je bloque", resultat)
        self.assertEqual(reservation._RESUME_RESA, "")

    def test_confirmer_reservation_refuse_hors_du_site(self):
        reservation._SITE_DEPART[0] = "https://www.lebistrot.fr"
        reservation._PAGE = _page("https://formulaire.evil.example/")
        with patch.object(reservation, "_demander_action") as demander:
            resultat = reservation.confirmer_reservation()
        demander.assert_not_called()
        self.assertIn("ne valide pas", resultat)


class DepartRechercheTest(_Base):
    def test_le_site_est_epingle_apres_google(self):
        page = _page("https://www.google.com/search?q=le+bistrot")
        actions = iter([
            {"action": "aller", "texte": "https://www.lebistrot.fr/"},
            {"action": "cliquer", "index": 3},
            {"action": "taper", "index": 1, "texte": "Martin"},
            {"action": "bloque", "raison": "fin du test"},
        ])

        def goto(url, **_):
            page.url = url

        def clic(*_a, **_k):
            if page.url.startswith("https://www.lebistrot.fr"):
                page.url = "https://formulaire.evil.example/"

        page.goto.side_effect = goto
        page.click.side_effect = clic
        page.query_selector.return_value = None
        resultats = []
        reel = reservation._executer_action

        def espion(p, act):
            r = reel(p, act)
            resultats.append(r)
            return r

        with patch.object(reservation, "_demarrer_navigateur", return_value=page), \
                patch.object(reservation, "_paiement_present", return_value=False), \
                patch.object(reservation, "_demander_action", side_effect=lambda *a: next(actions)), \
                patch.object(reservation, "_executer_action", side_effect=espion):
            reservation.book_appointment("le bistrot", "table", "vendredi")
        self.assertEqual(reservation._site(reservation._SITE_DEPART[0]), "lebistrot.fr")
        self.assertIn("navigue vers https://www.lebistrot.fr/", resultats[0])
        # Le clic a quitte le site epingle : la saisie est refusee.
        self.assertIn("refusee", resultats[2])
        page.fill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
