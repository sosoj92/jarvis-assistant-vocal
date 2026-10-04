"""Tunnel ngrok : il doit viser l'adresse IPv4 sur laquelle le serveur ecoute."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from core import serveur


class TunnelTest(unittest.TestCase):
    def test_le_tunnel_vise_127_0_0_1_et_non_localhost(self):
        # Regression : un port seul devenait « localhost:8790 », resolu en ::1 sous
        # Windows alors que le serveur n'ecoute qu'en 127.0.0.1 -> ERR_NGROK_8012.
        faux_ngrok = MagicMock()
        faux_ngrok.connect.return_value = MagicMock(public_url="https://exemple.ngrok-free.dev")
        module = types.ModuleType("pyngrok")
        module.ngrok = faux_ngrok
        reglages = {"serveur.ngrok_authtoken": "jeton-factice", "serveur.ngrok_domaine": ""}
        with patch.dict(sys.modules, {"pyngrok": module, "pyngrok.ngrok": faux_ngrok}), \
                patch.object(serveur, "reglage", lambda cle, defaut=None: reglages.get(cle, defaut)), \
                patch.object(serveur, "_port", return_value=8790), \
                patch.object(serveur, "_URL", None):
            serveur._ouvrir_tunnel()
        adresse = faux_ngrok.connect.call_args.args[0]
        self.assertEqual(adresse, "127.0.0.1:8790")


if __name__ == "__main__":
    unittest.main()
