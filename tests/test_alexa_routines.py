"""Choix de la routine Alexa et délai dépassé, sans connexion à Amazon."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools import alexa
from tools.alexa import _appareil, _resoudre_routine


class ResolutionRoutineTests(unittest.TestCase):
    def test_routine_de_sens_inverse_n_est_jamais_declenchee(self):
        nom, message = _resoudre_routine([{"name": "clim on"}], "clim", False)
        self.assertIsNone(nom)
        self.assertIn("clim on", message)
        self.assertIn("rien déclenché", message)
        self.assertIn("« clim off »", message)

        nom, message = _resoudre_routine([{"name": "clim off"}], "clim", True)
        self.assertIsNone(nom)
        self.assertIn("« clim on »", message)

    def test_lumiere_de_piece_avec_seulement_on(self):
        autos = [{"name": "lumiere salon on"}, {"name": "lumiere salon off"},
                 {"name": "lumiere chambre on"}]
        nom, message = _resoudre_routine(autos, "lumieres chambre", False)
        self.assertIsNone(nom)
        self.assertIn("lumiere chambre on", message)

    def test_paire_on_off_et_routine_neutre_inchangees(self):
        paire = [{"name": "clim on"}, {"name": "clim off"}]
        self.assertEqual(_resoudre_routine(paire, "clim", False), ("clim off", None))
        self.assertEqual(_resoudre_routine(paire, "clim", True), ("clim on", None))
        self.assertEqual(_resoudre_routine([{"name": "clim on"}], "clim", True),
                         ("clim on", None))
        # Routine neutre unique : elle reste utilisée dans les deux sens.
        self.assertEqual(_resoudre_routine([{"name": "Garage"}], "garage", False),
                         ("Garage", None))

    def test_eteindre_la_clim_ne_lance_pas_clim_on(self):
        api = MagicMock()
        api.run_routine = AsyncMock()
        with patch("tools.alexa._assurer_login", new=AsyncMock(return_value=object())), \
                patch("tools.alexa._automations",
                      new=AsyncMock(return_value=[{"name": "clim on"}])), \
                patch("tools.alexa._devices", new=AsyncMock(return_value=[{}])), \
                patch("tools.alexa._choisir", return_value={}), \
                patch("tools.alexa._api", return_value=api):
            message = asyncio.run(_appareil("clim", "eteindre"))

        api.run_routine.assert_not_called()
        self.assertNotIn("C'est fait", message)
        self.assertIn("rien déclenché", message)


class DelaiAlexaTests(unittest.TestCase):
    def test_delai_depasse_annule_la_coroutine(self):
        executees = []

        async def routine_lente():
            await asyncio.sleep(0.5)
            executees.append("routine")

        with self.assertRaises(TimeoutError) as erreur:
            alexa._run(routine_lente(), timeout=0.05)
        self.assertTrue(str(erreur.exception))
        time.sleep(0.8)
        self.assertEqual(executees, [])   # rien ne part après l'échec annoncé

    def test_message_de_delai_lisible(self):
        with patch("tools.alexa._configure", return_value=True), \
                patch("tools.alexa._run", side_effect=TimeoutError()) as run:
            message = alexa.alexa_appareil("clim", "eteindre")
        run.call_args.args[0].close()       # coroutine jamais attendue : on la ferme
        self.assertNotIn("()", message)
        self.assertIn("ne répond pas à temps", message)
        self.assertIn("vérifie avant de répéter", message)

    def test_erreur_sans_texte_garde_son_type(self):
        self.assertEqual(alexa._err(RuntimeError()), "Alexa a échoué (RuntimeError).")
        self.assertEqual(alexa._err(RuntimeError("hors ligne")),
                         "Alexa a échoué (hors ligne).")


if __name__ == "__main__":
    unittest.main()
