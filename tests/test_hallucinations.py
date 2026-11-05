"""Filtre des hallucinations de Whisper : il ecarte le bruit, jamais une vraie demande."""
import unittest

from core.hallucinations import est_hallucination


class HallucinationsTest(unittest.TestCase):
    def test_hallucinations_connues_ecartees(self):
        for texte in (
            " Sous-titres réalisés par la communauté d'Amara.org",
            "Sous-titrage ST' 501",
            "Sous-titrage Société Radio-Canada",
            "Sous-titres.",
            "« Sous titres »",
            "Merci d'avoir regardé cette vidéo !",
            "Abonnez-vous à la chaîne !",
            "N'oubliez pas de vous abonner.",
            "À la prochaine vidéo.",
        ):
            with self.subTest(texte=texte):
                self.assertTrue(est_hallucination(texte))

    def test_vraies_demandes_avec_sous_titres_conservees(self):
        for texte in (
            "Active les sous-titres sur Netflix",
            "mets les sous titres en francais",
            "Jarvis, active les sous-titres.",
            "Désactive le sous-titrage",
            "Désactive le sous-titrage stp",
            "Ingère la chaîne avec les sous-titres",
            "Passe à la prochaine vidéo",
            "Allume la lumière du bureau.",
        ):
            with self.subTest(texte=texte):
                self.assertFalse(est_hallucination(texte))

    def test_texte_vide(self):
        self.assertFalse(est_hallucination(""))
        self.assertFalse(est_hallucination(None))


if __name__ == "__main__":
    unittest.main()
