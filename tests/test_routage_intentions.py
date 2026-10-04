"""Tests du routeur partagé et du catalogue d'outils réduit."""
import unittest
from unittest.mock import patch

from core import registre
from core.routage_intentions import (decider_prioritaire,
                                     est_demande_vision_ecran,
                                     modules_pour_phrase)


class SelectionDomainesTests(unittest.TestCase):
    def test_conversation_simple_n_expose_aucun_outil(self):
        self.assertEqual(modules_pour_phrase("Comment ça va aujourd'hui ?"), set())

    def test_vision_ecran_reste_separee_du_domaine_web(self):
        modules = modules_pour_phrase("Lis cette erreur sur mon écran")
        self.assertIn("ecran", modules)
        self.assertIn("astra_pc", modules)
        self.assertNotIn("navigateur", modules)

    def test_lecture_ecran_prend_la_route_vision_pas_astra(self):
        self.assertTrue(est_demande_vision_ecran("Lis cette erreur sur mon écran"))
        decision = decider_prioritaire("Lis cette erreur sur mon écran")
        self.assertEqual(decision.type, "vision")
        self.assertFalse(est_demande_vision_ecran("Clique sur ce bouton à l'écran"))

    def test_plusieurs_domaines_peuvent_etre_combines(self):
        modules = modules_pour_phrase(
            "Regarde mon agenda puis lis mes mails et donne-moi la météo")
        self.assertTrue({"agenda", "mail", "meteo"}.issubset(modules))

    def test_lumiere_et_mode_visio_exposent_les_deux_outils(self):
        modules = modules_pour_phrase(
            "Allume la lumière du bureau et lance le mode visio")
        self.assertIn("amaran", modules)
        self.assertIn("gestes", modules)

    def test_action_inconnue_conserve_le_catalogue_complet(self):
        self.assertIsNone(modules_pour_phrase("Modifie ce réglage mystérieux"))
        self.assertIsNone(modules_pour_phrase("Affiche quelque chose de spécial"))

    def test_mode_et_sortie_audio_ont_leurs_outils(self):
        self.assertTrue({"budget", "modes"}.issubset(
            modules_pour_phrase("Passe en mode qualité")))
        self.assertIn("systeme", modules_pour_phrase("Change la sortie audio"))

    def test_demande_sans_verbe_connu_garde_tous_les_outils(self):
        # Cas reel : « je veux suivre... » partait sans aucun outil et le modele improvisait.
        self.assertIsNone(modules_pour_phrase("Je veux que tu t'occupes de mon truc"))
        self.assertIsNone(modules_pour_phrase("Tu peux regarder ça pour moi ?"))
        self.assertEqual(modules_pour_phrase("Je suis fatiguée ce soir"), set())

    def test_colis_routes_directement_vers_le_suivi(self):
        for phrase in ("Je veux suivre juste mes colis, tout mes colis.",
                       "Où en sont mes colis ?", "Ma commande arrive quand ?",
                       "J'ai des livraisons aujourd'hui ? mes livraisons"):
            with self.subTest(phrase=phrase):
                decision = decider_prioritaire(phrase)
                self.assertEqual((decision.type, decision.outil), ("outil", "suivi_colis"))
        for phrase in ("Envoie un colis à ma mère", "Allume la lumière du bureau"):
            with self.subTest(phrase=phrase):
                decision = decider_prioritaire(phrase)
                self.assertFalse(decision and decision.outil == "suivi_colis")
        self.assertIn("colis", modules_pour_phrase("Un paquet doit arriver ?"))

    def test_question_de_fond_expose_hermes_et_le_web(self):
        modules = modules_pour_phrase("Fais une recherche de fond et compare ces micros")
        self.assertTrue({"deleguer_a_hermes", "web"}.issubset(modules))


class RegistreFiltreTests(unittest.TestCase):
    def test_capture_screen_est_bien_la_fonction_enregistree(self):
        from tools import ecran
        self.assertIs(registre.get("capture_screen").fonction,
                      ecran.capture_screen)

    def test_schemas_api_filtre_par_module(self):
        def lire_mail_test():
            return "mail"

        def heure_test():
            return "heure"

        lire_mail_test.__module__ = "tools.mail"
        heure_test.__module__ = "tools.temps"

        with patch.dict(registre._REGISTRE, {}, clear=True):
            registre.outil("mail_test", "test mail")(lire_mail_test)
            registre.outil("heure_test", "test heure")(heure_test)
            noms = {s["name"] for s in registre.schemas_api(modules={"mail"})}
            self.assertEqual(noms, {"mail_test"})
            self.assertEqual(registre.schemas_api(modules=set()), [])


if __name__ == "__main__":
    unittest.main()
