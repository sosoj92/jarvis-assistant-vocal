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


# Reponses entendues apres « Tu confirmes ? » qui ne sont pas un accord sans reserve.
_CONDITIONNELLES = (
    "Oui, mais mets Paul en copie", "envoie-le plutot demain", "envoie-le plutôt demain",
    "fais gaffe", "c'est bon ?", "oui oui ok sauf la piece jointe", "fais-le demain",
    "ok d'abord change l'objet", "je fais quoi", "qu'est-ce que tu fais", "tu fais quoi la",
    "fais voir le mail d'abord", "envoie-moi le brouillon d'abord", "oui avant ça mets Marie",
    "ok après le café", "pourquoi tu fais ça", "comment ça ok", "toujours le meme probleme",
    "c'est toujours pareil", "c'est toujours pareil avec toi", "envoie-le", "fais-le",
    # Condition ou demande sans connecteur restrictif, question sans « ? ».
    "Oui, et mets aussi Marie en copie", "Oui, mets Marie en copie",
    "oui si c'est moins de 50 euros", "est-ce que c'est bon", "oui c'est bon pour Paul",
)


class StrictN3Test(unittest.TestCase):
    """Mode strict (actions N3) : condition, question ou « toujours » seul annulent."""

    def test_conditions_questions_et_toujours_seul_annulent(self):
        for phrase in _CONDITIONNELLES:
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase, strict=True), NON)

    def test_mode_normal_inchange(self):
        # N1/N2 : aucune de ces phrases ne change de decision.
        attendus = {"toujours le meme probleme": TOUJOURS, "c'est toujours pareil": TOUJOURS,
                    "c'est toujours pareil avec toi": TOUJOURS}
        for phrase in _CONDITIONNELLES:
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase),
                                 attendus.get(phrase, OUI))

    def test_accords_explicites_restent_valides(self):
        for phrase in ("oui", "Oui.", "je confirme", "d'accord", "c'est bon", "ouais vas-y",
                       "OK", "bien sûr", "oui envoie-le", "vas-y fais-le",
                       # pas de plafond de longueur
                       "oui vas-y envoie-le maintenant s'il te plaît",
                       "Oui Jarvis, merci", "oui c'est ça", "ok tu peux"):
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase, strict=True), OUI)

    def test_toujours_avec_accord_explicite(self):
        self.assertEqual(interpreter_confirmation("oui, toujours", strict=True), TOUJOURS)
        self.assertEqual(interpreter_confirmation("Toujours.", strict=True), NON)
        self.assertEqual(interpreter_confirmation("non, toujours pas", strict=True), NON)

    def test_negations_toujours_prioritaires(self):
        for phrase in ("oui mais attends", "Non, ne le fais pas", "ok non", "plus tard"):
            with self.subTest(phrase=phrase):
                self.assertEqual(interpreter_confirmation(phrase, strict=True), NON)


class SatelliteTest(unittest.TestCase):
    def _session(self, outil="envoyer_mail"):
        # Satellite de la maison, autorise aux actions critiques (le cas « refuse »
        # est couvert par tests/test_securite_lot2.py).
        return SimpleNamespace(en_attente=(outil, {"a": "x"}), actions_critiques=True,
                               historique=[], piece="cuisine")

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
        executer.assert_called_once_with("envoyer_mail", {"a": "x"}, piece="cuisine")
        memoriser.assert_called_once_with("envoyer_mail")
        self.assertIn("action critique", reponse)

    def test_n3_oui_conditionnel_n_execute_rien(self):
        # « Je vais envoyer le mail a Paul... Tu confirmes ? » -> le mail ne part pas.
        for phrase in ("Oui, mais mets Marie en copie", "envoie-le plutôt demain",
                       "c'est toujours pareil avec toi", "qu'est-ce que tu fais ?"):
            with self.subTest(phrase=phrase), \
                    patch.object(satellite, "_executer_outil") as executer:
                reponse = satellite._resoudre_confirmation(self._session(), phrase)
            executer.assert_not_called()
            self.assertEqual(reponse, "D'accord, j'annule.")

    def test_n2_garde_la_regle_normale(self):
        # browser_close_tabs (N2) : « ok d'abord » reste un accord, comme avant.
        with patch.object(satellite, "_executer_outil", return_value="Fait.") as executer:
            satellite._resoudre_confirmation(self._session("browser_close_tabs"), "ok d'abord")
        executer.assert_called_once()

    def test_issue_dans_l_historique(self):
        session = self._session()
        with patch.object(satellite, "_executer_outil", return_value="Mail envoye."):
            satellite._resoudre_confirmation(session, "oui")
        self.assertEqual(session.historique, [{"role": "user", "content": "oui"},
                                              {"role": "assistant", "content": "Mail envoye."}])


class JarvisPrincipalTest(unittest.TestCase):
    def test_le_pc_utilise_la_regle_stricte(self):
        # jarvis14 est trop lourd a importer (micro, Whisper) : controle statique.
        # Le mode strict (N3) peut y etre passe en argument.
        source = (ROOT / "jarvis14.py").read_text(encoding="utf-8")
        self.assertRegex(source, r"interpreter_confirmation\(texte\b[^\n]*\) != NON")
        self.assertNotIn("MOTS_OUI", source)


if __name__ == "__main__":
    unittest.main()
