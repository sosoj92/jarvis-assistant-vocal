"""Outil ouvrir_panneau : honnete sur l'endroit ou le panneau s'ouvre (sans reseau)."""
import unittest
from unittest.mock import patch

from core import serveur
from tools import panneau


def _reglages(valeurs):
    return lambda cle, defaut=None: valeurs.get(cle, defaut)


class OuvrirPanneauTest(unittest.TestCase):
    def _ouvrir(self, valeurs, port_ouvert=True):
        with patch.object(panneau, "reglage", _reglages(valeurs)), \
                patch.object(serveur, "_port", return_value=8790), \
                patch.object(serveur, "_port_ouvert", return_value=port_ouvert), \
                patch.object(panneau, "ouvrir_url", return_value=True) as ouvrir:
            return panneau.ouvrir_panneau(), ouvrir

    def test_serveur_sans_peripheriques_n_ouvre_rien_et_le_dit(self):
        # Topologie serveur H24 / PC-BUREAU : un navigateur ouvert sur le serveur ne montre rien a
        # personne, et l'URL localhost ne marche pas depuis le poste.
        reponse, ouvrir = self._ouvrir({"poste_principal.actif": True,
                                        "poste_principal.serveur_sans_peripheriques": True})
        ouvrir.assert_not_called()
        self.assertNotIn("J'ouvre", reponse)
        self.assertIn("sur le serveur", reponse)
        self.assertIn("127.0.0.1:8790", reponse)

    def test_poste_principal_sans_l_option_reste_nominal(self):
        reponse, ouvrir = self._ouvrir({"poste_principal.actif": True})
        ouvrir.assert_called_once_with("http://localhost:8790/panneau")
        self.assertIn("J'ouvre", reponse)

    def test_cas_nominal_ouvre_le_navigateur(self):
        reponse, ouvrir = self._ouvrir({})
        ouvrir.assert_called_once_with("http://localhost:8790/panneau")
        self.assertIn("J'ouvre le panneau de configuration", reponse)

    def test_serveur_local_eteint(self):
        reponse, ouvrir = self._ouvrir({}, port_ouvert=False)
        ouvrir.assert_not_called()
        self.assertIn("pas démarré", reponse)


if __name__ == "__main__":
    unittest.main()
