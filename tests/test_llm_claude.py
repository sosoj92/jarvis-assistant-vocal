"""Tests sans reseau de l'adaptateur Claude (API Anthropic)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import llm
from core.llm import Bloc, ClaudeProvider


class _Messages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(stop_reason="end_turn", content=[], usage=None)


def _provider():
    p = ClaudeProvider.__new__(ClaudeProvider)
    p.modele = "claude-haiku-4-5"
    p.client = SimpleNamespace(messages=_Messages())
    return p


# Tour precedent : « Quel temps fait-il demain ? » a declenche un outil.
HISTORIQUE_AVEC_OUTIL = [
    {"role": "user", "content": "Quel temps fait-il demain ?"},
    {"role": "assistant", "content": [
        Bloc("tool_use", id="toolu_1", name="meteo", input={"ville": "Lyon"})]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Soleil, 21 degres."}]},
    {"role": "assistant", "content": [Bloc("text", text="Demain, soleil et 21 degres.")]},
    {"role": "user", "content": "Merci !"},
]


class OutilsDansHistoriqueTest(unittest.TestCase):
    def test_phrase_sans_outil_apres_un_appel_d_outil(self):
        p = _provider()
        p.repondre("Tu es Jarvis.", HISTORIQUE_AVEC_OUTIL, [])
        envoi = p.client.messages.kwargs
        self.assertEqual([o["name"] for o in envoi["tools"]], ["meteo"])
        self.assertEqual(envoi["tool_choice"], {"type": "none"})    # aucun outil ne s'execute

    def test_schema_du_registre_repris_quand_il_existe(self):
        schema = {"name": "meteo", "description": "Meteo",
                  "input_schema": {"type": "object", "properties": {"ville": {"type": "string"}}}}
        p = _provider()
        with patch("core.registre.schemas_api", return_value=[schema]):
            p.repondre("Tu es Jarvis.", HISTORIQUE_AVEC_OUTIL, [])
        self.assertEqual(p.client.messages.kwargs["tools"], [schema])

    def test_blocs_au_format_dictionnaire(self):
        historique = [
            {"role": "user", "content": "Quelle heure est-il ?"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_2", "name": "heure", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_2", "content": "14h05"}]},
            {"role": "user", "content": "Super"},
        ]
        p = _provider()
        p.repondre("Tu es Jarvis.", historique, [])
        self.assertEqual([o["name"] for o in p.client.messages.kwargs["tools"]], ["heure"])

    def test_conversation_simple_sans_catalogue(self):
        p = _provider()
        p.repondre("Tu es Jarvis.", [{"role": "user", "content": "Bonjour"}], [])
        self.assertNotIn("tools", p.client.messages.kwargs)
        self.assertNotIn("tool_choice", p.client.messages.kwargs)

    def test_catalogue_filtre_transmis_tel_quel(self):
        outils = [{"name": "allumer_lumiere", "description": "Lumiere",
                   "input_schema": {"type": "object", "properties": {}}}]
        p = _provider()
        p.repondre("Tu es Jarvis.", HISTORIQUE_AVEC_OUTIL, outils)
        self.assertIs(p.client.messages.kwargs["tools"], outils)
        self.assertNotIn("tool_choice", p.client.messages.kwargs)


class DelaisClientTest(unittest.TestCase):
    def _client(self, valeurs):
        with patch.object(llm, "reglage", lambda cle, defaut=None: valeurs.get(cle, defaut)):
            return ClaudeProvider().client

    def test_delai_et_reessais_bornes_par_defaut(self):
        client = self._client({"anthropic.cle": "cle-factice"})
        self.assertEqual(getattr(client.timeout, "read", client.timeout), 90.0)
        self.assertEqual(client.max_retries, 1)

    def test_delai_reglable(self):
        client = self._client({"anthropic.cle": "cle-factice", "anthropic.timeout": 30,
                               "anthropic.max_retries": 0})
        self.assertEqual(getattr(client.timeout, "read", client.timeout), 30.0)
        self.assertEqual(client.max_retries, 0)

    def test_sans_cle_pas_de_client(self):
        self.assertIsNone(self._client({}))


if __name__ == "__main__":
    unittest.main()
