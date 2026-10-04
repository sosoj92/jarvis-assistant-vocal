"""Agent Windows : fenetre Jarvis alimentee par le micro et le serveur."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, ROOT / chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


satellite = _charger("jarvis_satellite_test", "satellite_pi/jarvis_satellite.py")
agent = _charger("jarvis_desktop_agent_test", "desktop_agent/jarvis_desktop_agent.py")


class EvenementSatelliteTest(unittest.TestCase):
    def tearDown(self):
        satellite.CONF = {}

    def test_sans_recepteur_rien_ne_se_passe(self):
        satellite.CONF = {}
        satellite._evenement("reveil")  # comportement d'un Raspberry Pi : aucun effet

    def test_le_recepteur_recoit_les_evenements_et_ses_erreurs_sont_contenues(self):
        recus = []
        satellite.CONF = {"_evenement_callback": lambda nom, valeur=None: recus.append((nom, valeur))}
        satellite._evenement("transcription", "allume la lumiere")
        self.assertEqual(recus, [("transcription", "allume la lumiere")])
        satellite.CONF = {"_evenement_callback": MagicMock(side_effect=RuntimeError("affichage"))}
        satellite._evenement("reveil")  # l'audio ne doit jamais tomber a cause de l'affichage

    def test_veille_annoncee_pendant_la_conversation_suivie_reste_ecoute(self):
        # Bug reel : « VEILLE » affiche alors que le micro ecoutait encore la suite.
        micro = MagicMock()
        micro._relance_restante.return_value = 7.5
        self.assertEqual(satellite._etat_affiche("veille", micro), "ecoute")
        micro._relance_restante.return_value = 0.0
        self.assertEqual(satellite._etat_affiche("veille", micro), "veille")
        self.assertEqual(satellite._etat_affiche("parole", micro), "parole")

    def test_le_client_signale_ouverture_et_fin_de_l_ecoute_suivie(self):
        source = (ROOT / "satellite_pi" / "jarvis_satellite.py").read_text(encoding="utf-8")
        self.assertIn('micro.ouvrir_relance(d.get("secondes"))\n'
                      '                    occupe.clear()\n'
                      '                    _evenement("etat", "ecoute")', source)
        self.assertIn('_evenement("etat", "veille")', source)
        self.assertIn('_evenement("statut", d)', source)


class AffichageAgentTest(unittest.TestCase):
    def _brancher(self, reglages=None):
        hud = MagicMock()
        audio: dict = {}
        with patch.object(agent.threading, "Thread") as fil:
            fil.side_effect = lambda target, daemon=True: MagicMock(start=target)
            module = agent.brancher_affichage(audio, reglages or {}, hud_module=hud)
            if module is not None:
                evenement = audio["_evenement_callback"]
                for nom, valeur in (
                    ("reveil", None), ("niveau", 0.1), ("transcription", "quelle heure est-il"),
                    ("reponse", "Il est midi."), ("parole_debut", None), ("parole_fin", None),
                    ("etat", "inconnu"),
                ):
                    evenement(nom, valeur)
        return hud, audio

    def test_hey_jarvis_ouvre_et_met_la_fenetre_devant(self):
        hud, _ = self._brancher()
        hud.demarrer.assert_called_once_with(ouvrir=False, fenetre="app", ecran=None)
        hud.mettre_au_premier_plan.assert_called_once()
        hud.niveau.assert_called_once_with(0.5)
        hud.dire_vous.assert_called_once_with("quelle heure est-il")
        hud.dire_jarvis.assert_called_once_with("Il est midi.")
        etats = [appel.args[0] for appel in hud.etat.call_args_list]
        self.assertEqual(etats, ["ecoute", "reflexion", "parole", "veille"])  # « inconnu » ignore

    def test_ecran_transmis_au_hud(self):
        hud, _ = self._brancher({"ecran": 2})
        self.assertEqual(hud.demarrer.call_args.kwargs["ecran"], 2)

    def test_premier_plan_desactivable(self):
        hud, _ = self._brancher({"premier_plan_au_reveil": False})
        hud.mettre_au_premier_plan.assert_not_called()
        hud.etat.assert_any_call("ecoute")

    def test_releve_du_serveur_affiche_modele_routage_budget_hermes(self):
        hud, audio = self._brancher()
        audio["_evenement_callback"]("statut", {
            "type": "statut", "modele": "OpenAI · gpt-5.6-terra", "routage": "hybride",
            "budget": {"cout": 0.42, "plafond": 3.0, "pct": 0.14},
            "hermes": {"taches": 1, "tokens": 1200}})
        hud.config.assert_called_with("OpenAI · gpt-5.6-terra", "micro de ce PC")
        hud.routage.assert_called_once_with("hybride")
        hud.budget.assert_called_once_with(0.42, 3.0, 0.14)
        hud.hermes.assert_called_once_with(1, 1200)

    def test_releve_partiel_n_efface_rien(self):
        hud, audio = self._brancher()
        audio["_evenement_callback"]("statut", {"routage": "local"})
        hud.routage.assert_called_once_with("local")
        hud.budget.assert_not_called()
        hud.hermes.assert_not_called()

    def test_fenetre_desactivable(self):
        hud, audio = self._brancher({"actif": False})
        hud.demarrer.assert_not_called()
        self.assertNotIn("_evenement_callback", audio)


if __name__ == "__main__":
    unittest.main()
