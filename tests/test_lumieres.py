"""Allumage automatique au démarrage, sans pont Hue réel."""
import unittest
from unittest.mock import patch

from tools import lumieres


class AllumageNuitTests(unittest.TestCase):
    def _allumer_si_nuit(self, reglages):
        with patch("tools.lumieres.reglage",
                   side_effect=lambda cle, defaut=None: reglages.get(cle, defaut)), \
                patch.object(lumieres, "HUE_PONT", "192.0.2.1"), \
                patch.object(lumieres, "HUE_CLE", "FACTICE"), \
                patch.object(lumieres, "PIECE_NUIT", "chambre"), \
                patch.dict(lumieres._PIECES_HUE, {"chambre": ("3", "Chambre")},
                           clear=True), \
                patch("tools.meteo.il_fait_nuit", return_value=True) as nuit, \
                patch("tools.lumieres._hue_requete",
                      return_value=[{"success": {}}]) as hue:
            lumieres.allumer_si_nuit()
        return hue, nuit

    def test_serveur_sans_peripheriques_n_allume_rien(self):
        hue, nuit = self._allumer_si_nuit({
            "poste_principal.actif": True,
            "poste_principal.serveur_sans_peripheriques": True,
        })
        hue.assert_not_called()
        nuit.assert_not_called()

    def test_poste_normal_allume_la_piece_de_nuit(self):
        hue, _ = self._allumer_si_nuit({})
        hue.assert_called_once_with("groups/3/action", "PUT", {"on": True})

    def test_poste_principal_avec_peripheriques_allume_toujours(self):
        hue, _ = self._allumer_si_nuit({
            "poste_principal.actif": True,
            "poste_principal.serveur_sans_peripheriques": False,
        })
        hue.assert_called_once_with("groups/3/action", "PUT", {"on": True})


if __name__ == "__main__":
    unittest.main()
