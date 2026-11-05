"""Connexion Alexa : le proxy (pages Amazon pre-remplies) n'ecoute qu'en local.

Tout est simule : ni proxy reel, ni compte Amazon, ni reseau.
"""
import asyncio
import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _charger_script():
    spec = importlib.util.spec_from_file_location("alexa_login_test",
                                                  ROOT / "scripts" / "alexa_login.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProxyLocalTest(unittest.TestCase):
    def test_proxy_ecoute_seulement_sur_la_boucle_locale(self):
        script = _charger_script()
        valeurs = {"alexa.email": "test@example.org", "alexa.password": "FAUX-MDP",
                   "alexa.proxy_port": 3000}
        proxy = mock.Mock()
        proxy.start_proxy = mock.AsyncMock()
        proxy.stop_proxy = mock.AsyncMock()
        proxy.access_url.return_value = "http://127.0.0.1:3000"
        # Login deja « connecte » : la boucle d'attente s'arrete au premier tour.
        login = SimpleNamespace(status={"login_successful": True}, access_token=None,
                                session=SimpleNamespace(cookie_jar=["cookie"]),
                                get_tokens=mock.AsyncMock(),
                                finalize_login=mock.AsyncMock(),
                                close=mock.AsyncMock())
        with mock.patch.object(script, "reglage",
                               side_effect=lambda chemin, defaut=None:
                               valeurs.get(chemin, defaut)), \
                mock.patch.object(script, "_activer_debug"), \
                mock.patch.object(script, "_nouveau_login", return_value=login), \
                mock.patch.object(script, "_proxy_totp_frais", return_value=proxy) as fabrique, \
                mock.patch.object(script, "_sauver_oauth"), \
                mock.patch.object(script, "_verifier", mock.AsyncMock(return_value=True)), \
                redirect_stdout(io.StringIO()):
            asyncio.run(script._login_navigateur())
        proxy.start_proxy.assert_awaited_once_with(host="127.0.0.1")
        self.assertEqual(fabrique.call_args[0][1], "http://127.0.0.1:3000")
        proxy.stop_proxy.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
