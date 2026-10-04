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

    def test_fenetre_desactivable(self):
        hud, audio = self._brancher({"actif": False})
        hud.demarrer.assert_not_called()
        self.assertNotIn("_evenement_callback", audio)


if __name__ == "__main__":
    unittest.main()
