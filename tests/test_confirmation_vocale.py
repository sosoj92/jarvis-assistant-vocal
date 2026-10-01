"""Confirmation vocale stricte : une negation ou une hesitation n'execute jamais rien."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import satellite
from core.confirmation_vocale import NON, OUI, TOUJOURS, interpreter_confirmation

ROOT = Path(__file__).resolve().parents[1]


class InterpretationTest(unittest.TestCase):
    def test_refus_et_hesitations_annulent(self):
        # Chacune de ces phrases validait l'action avec l'ancienne recherche de sous-chaine.
        for phrase in (
            "Non, ne le fais pas", "non toujours pas", "toujours pas", "n'envoie pas",
            "Ne l'envoie surtout pas", "oui mais attends", "ok non", "pas maintenant",
            "laisse tomber", "plus tard", "je sais pas", "annule", "stop", "non merci",
            "nope", "je fais rien", "aucun", "Non, je ne veux pas", "fais pas ça",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase), NON)

    def test_silence_ou_reponse_vague_annule(self):
        for phrase in (None, "", "euh", "hmm je réfléchis", "Tokyo", "les faits sont clairs"):
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase), NON)

    def test_accords_explicites(self):
        for phrase in (
            "oui", "Oui.", "ouais vas-y", "Vas-y", "d'accord", "D’accord", "OK", "c'est bon",
            "envoie-le", "fais-le", "je confirme", "bien sûr", "Oui oui", "oui, pas de souci",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase), OUI)

    def test_toujours_memorise_seulement_sans_negation(self):
        self.assertEqual(interpreter_confirmation("oui, toujours"), TOUJOURS)
        self.assertEqual(interpreter_confirmation("Toujours."), TOUJOURS)
        self.assertEqual(interpreter_confirmation("non, toujours pas"), NON)


class SatelliteTest(unittest.TestCase):
    def _session(self):
        return SimpleNamespace(en_attente=("envoyer_mail", {"a": "x"}))

    def test_negation_sur_satellite_n_execute_rien(self):
        session = self._session()
        with patch.object(satellite, "_executer_outil") as executer:
            reponse = satellite._resoudre_confirmation(session, "Non, ne le fais pas")
        executer.assert_not_called()
        self.assertEqual(reponse, "D'accord, j'annule.")
        self.assertIsNone(session.en_attente)

    def test_oui_toujours_execute_et_demande_la_memorisation(self):
        with patch.object(satellite, "_executer_outil", return_value="Fait.") as executer, \
                patch("core.registre.autoriser_toujours", return_value=False) as memoriser:
            reponse = satellite._resoudre_confirmation(self._session(), "oui, toujours")
        executer.assert_called_once_with("envoyer_mail", {"a": "x"})
        memoriser.assert_called_once_with("envoyer_mail")
        self.assertIn("action critique", reponse)


class JarvisPrincipalTest(unittest.TestCase):
    def test_le_pc_utilise_la_regle_stricte(self):
        # jarvis14 est trop lourd a importer (micro, Whisper) : controle statique.
        source = (ROOT / "jarvis14.py").read_text(encoding="utf-8")
        self.assertIn("interpreter_confirmation(texte) != NON", source)
        self.assertNotIn("MOTS_OUI", source)


if __name__ == "__main__":
    unittest.main()
