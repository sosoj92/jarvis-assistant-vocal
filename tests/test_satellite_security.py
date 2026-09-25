"""Tests de la frontière réseau du WebSocket satellite."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.satellite import (_Session, _adresse_a_alexa, _demande_veille, _satellites,
                            _origine_locale_ou_lan, _phrase_progression,
                            _progression_initiale)
from core.util import nettoyer_reponse_vocale


def _ws(hote, **entetes):
    return SimpleNamespace(client=SimpleNamespace(host=hote), headers=entetes)


class SatelliteSecurityTests(unittest.TestCase):
    def test_loopback_et_lan_prive_sont_acceptes(self):
        self.assertTrue(_origine_locale_ou_lan(_ws("127.0.0.1")))
        self.assertTrue(_origine_locale_ou_lan(_ws("192.168.1.42")))
        self.assertTrue(_origine_locale_ou_lan(_ws("10.0.0.8")))
        self.assertTrue(_origine_locale_ou_lan(_ws("100.90.80.70")))

    def test_adresse_publique_est_refusee(self):
        self.assertFalse(_origine_locale_ou_lan(_ws("8.8.8.8")))

    def test_reverse_proxy_est_refuse_meme_en_loopback(self):
        self.assertFalse(_origine_locale_ou_lan(
            _ws("127.0.0.1", **{"x-forwarded-for": "203.0.113.9"})))

    def test_client_sans_adresse_est_refuse(self):
        self.assertFalse(_origine_locale_ou_lan(_ws("")))

    def test_progression_est_liee_a_l_intention(self):
        self.assertEqual(_progression_initiale("Cherche les dernières nouvelles"),
                         "Je lance la recherche.")
        self.assertEqual(_phrase_progression("Cherche les dernières nouvelles"),
                         "Je vérifie les résultats.")
        self.assertEqual(_progression_initiale("C'est quoi mes mails ?"),
                         "Je regarde tes mails.")
        self.assertEqual(_progression_initiale("Cherche-moi une recette"),
                         "Je cherche une recette adaptée.")
        self.assertIsNone(_progression_initiale("Allume la lumière"))
        self.assertEqual(_phrase_progression("Allume la lumière"),
                         "La commande est en cours.")

    def test_questions_simples_sans_mots_inutiles(self):
        for phrase in ("Comment ça va ?", "Quelle heure est-il ?", "Merci Jarvis",
                       "Explique-moi la relativité", "C'est quoi une recette ?"):
            self.assertIsNone(_progression_initiale(phrase))
            self.assertIsNone(_phrase_progression(phrase))

    def test_amorces_parasites_retires_des_reponses_finales(self):
        self.assertEqual(
            nettoyer_reponse_vocale("Attends, je regarde ça. Je vais très bien."),
            "Je vais très bien.",
        )
        self.assertEqual(
            nettoyer_reponse_vocale("Un instant... Il est quinze heures."),
            "Il est quinze heures.",
        )
        self.assertEqual(
            nettoyer_reponse_vocale("Je vais bien, merci."),
            "Je vais bien, merci.",
        )

    def test_demande_de_veille_explicite(self):
        self.assertTrue(_demande_veille("Hey Jarvis, mets-toi en veille"))
        self.assertTrue(_demande_veille("Arrête de m'écouter"))
        self.assertTrue(_demande_veille("Dors"))
        self.assertTrue(_demande_veille("Retourne en veille"))
        self.assertTrue(_demande_veille("Ne m'écoute plus"))
        self.assertTrue(_demande_veille("Arrête de répondre"))
        self.assertTrue(_demande_veille("Retourne dormir"))

    def test_commandes_voisines_ne_declenchent_pas_la_veille(self):
        self.assertFalse(_demande_veille("Mets la lumière en veilleuse"))
        self.assertFalse(_demande_veille("Arrête la musique"))

    def test_alexa_en_debut_de_phrase_est_destinee_a_l_autre_assistant(self):
        self.assertTrue(_adresse_a_alexa("Alexa, éteins la lumière"))
        self.assertTrue(_adresse_a_alexa("Hey Alexa mets Spotify en pause"))
        self.assertTrue(_adresse_a_alexa("Alexa"))

    def test_mention_d_alexa_dans_une_question_reste_pour_jarvis(self):
        self.assertFalse(_adresse_a_alexa("Est-ce qu'Alexa est connectée ?"))
        self.assertFalse(_adresse_a_alexa("Passe par Alexa pour la lumière"))

    def test_conversation_suivie_a_un_nombre_borne_de_relances(self):
        session = _Session()
        session.nouveau_reveil(2)
        self.assertTrue(session.autoriser_relance())
        self.assertTrue(session.autoriser_relance())
        self.assertFalse(session.autoriser_relance())

        # Une confirmation sensible explicitement attendue n'est jamais coupée,
        # mais elle ne recrée pas de crédit de conversation ordinaire.
        self.assertTrue(session.autoriser_relance(obligatoire=True))
        self.assertFalse(session.autoriser_relance())

    def test_mise_en_veille_annule_les_relances_restantes(self):
        session = _Session()
        session.nouveau_reveil(4)
        session.mettre_en_veille()
        self.assertFalse(session.autoriser_relance())

    def test_brief_demarrage_est_une_permission_par_satellite(self):
        with patch("core.satellite.reglage", return_value=[{
                "id": "bureau", "piece": "bureau", "token": "secret",
                "brief_au_demarrage": True,
        }]):
            config = _satellites()

        self.assertTrue(config["bureau"]["brief_au_demarrage"])


if __name__ == "__main__":
    unittest.main()
