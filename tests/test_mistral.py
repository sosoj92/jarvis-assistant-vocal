"""Traduction Anthropic <-> Mistral dans core/llm.MistralProvider.

L'assistant parle le format Anthropic (blocs text / tool_use / tool_result).
Le provider Mistral traduit vers le format chat completions OpenAI-compatible
et relit la reponse. Ces tests ne touchent jamais au reseau : ils verifient
la forme des messages construits, l'elagage des schemas et le parsing.
"""
import json

import pytest

from core import cloud, llm


# ---------------------------------------------------------------- fabrique cloud

def test_fournisseur_mistral_reconnu(monkeypatch):
    monkeypatch.setattr(cloud, "reglage",
                        lambda chemin, defaut=None:
                        "mistral" if chemin == "cloud.fournisseur" else defaut)
    assert cloud.fournisseur() == "mistral"


def test_modeles_mistral_par_defaut(monkeypatch):
    monkeypatch.setattr(cloud, "reglage", lambda chemin, defaut=None: defaut)
    monkeypatch.setattr(cloud, "fournisseur", lambda: "mistral")
    assert cloud.modele() == "mistral-small-latest"
    assert cloud.modele(qualite=True) == "mistral-large-latest"


def test_surcharge_de_modele_incompatible_ignoree(monkeypatch):
    """Une ancienne config reservation.modele=claude-... ne doit pas casser."""
    monkeypatch.setattr(cloud, "fournisseur", lambda: "mistral")
    assert cloud.modele(surcharge="claude-haiku-4-5") == "mistral-small-latest"
    assert cloud.modele(surcharge="mistral-medium-latest") == "mistral-medium-latest"


# ---------------------------------------------------------------- provider llm

@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(llm, "reglage", lambda chemin, defaut=None: defaut)
    prov = llm.MistralProvider(modele="mistral-small-latest")
    prov.client = type("ClientFaux", (), {"chat": None})()
    return prov


def test_elagage_des_schemas_refuses(provider):
    """Mistral rejette additionalProperties sur l'appel entier : on elague."""
    sale = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "nom": {"type": "string", "additionalProperties": False},
            "liste": {"type": "array",
                      "items": {"type": "object", "additionalProperties": False}},
        },
    }
    propre = provider._elaguer_schema(sale)
    assert "additionalProperties" not in json.dumps(propre)
    assert propre["properties"]["nom"]["type"] == "string"


def test_outils_au_format_function(provider):
    outils = provider._outils([{
        "name": "heure",
        "description": "donne l'heure",
        "input_schema": {"type": "object", "properties": {},
                         "additionalProperties": False},
    }])
    assert outils == [{"type": "function", "function": {
        "name": "heure", "description": "donne l'heure",
        "parameters": {"type": "object", "properties": {}}}}]


def test_historique_texte_simple(provider):
    messages = provider._traduire([
        {"role": "user", "content": "salut"},
        {"role": "assistant", "content": "bonjour"},
    ])
    assert messages == [
        {"role": "user", "content": "salut"},
        {"role": "assistant", "content": "bonjour"},
    ]


def test_appel_outil_puis_resultat(provider):
    """tool_use cote assistant -> tool_calls ; tool_result -> role tool."""
    from core.llm import Bloc
    messages = provider._traduire([
        {"role": "assistant", "content": [
            Bloc("text", text="je regarde"),
            Bloc("tool_use", id="app1", name="meteo", input={"ville": "Paris"}),
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "app1", "content": "il pleut"},
        ]},
    ])
    assistant = messages[0]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "je regarde"
    appel = assistant["tool_calls"][0]
    assert appel["id"] == "app1"
    assert appel["function"]["name"] == "meteo"
    assert json.loads(appel["function"]["arguments"]) == {"ville": "Paris"}
    resultat = messages[1]
    assert resultat["role"] == "tool"
    assert resultat["tool_call_id"] == "app1"
    assert resultat["content"] == "il pleut"


def test_resultat_image_remplacee_par_texte(provider):
    """Mistral ne recoit pas d'image dans un tool_result : texte de repli."""
    messages = provider._traduire([
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "app1",
             "content": [{"type": "text", "text": "capture"},
                         {"type": "image",
                          "source": {"type": "base64", "data": "abc"}}]},
        ]},
    ])
    assert "capture d'ecran" in messages[0]["content"]


def test_resultat_texte_sans_image_conserve(provider):
    """Sans image, le contenu texte passe tel quel."""
    messages = provider._traduire([
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "app1",
             "content": [{"type": "text", "text": "il pleut"}]},
        ]},
    ])
    assert messages[0]["content"] == "il pleut"


def test_reponse_avec_appel_outil(provider, monkeypatch):
    """Une reponse chat.completions avec tool_calls devient des Blocs Anthropic."""

    class Fonction:
        name = "meteo"
        arguments = '{"ville": "Paris"}'

    class Appel:
        id = "app1"
        function = Fonction()

    class Message:
        content = "je regarde"
        tool_calls = [Appel()]

    class Choix:
        message = Message()

    class Rep:
        choices = [Choix()]
        usage = None

    monkeypatch.setattr(
        provider.client, "chat",
        type("ChatFaux", (), {"completions": type("CompFaux", (), {"create": staticmethod(lambda **k: Rep())})()})())
    rep = provider.repondre("tu es Jarvis", [
        {"role": "user", "content": "meteo ?"}], [])
    assert rep.stop_reason == "tool_use"
    assert rep.content[0].type == "text"
    assert rep.content[1].type == "tool_use"
    assert rep.content[1].name == "meteo"
    assert rep.content[1].input == {"ville": "Paris"}
    assert rep.content[1].id == "app1"


def test_reponse_texte_simple(provider, monkeypatch):
    class Message:
        content = "bonjour"
        tool_calls = None

    class Choix:
        message = Message()

    class Rep:
        choices = [Choix()]
        usage = None

    monkeypatch.setattr(
        provider.client, "chat",
        type("ChatFaux", (), {"completions": type("CompFaux", (), {"create": staticmethod(lambda **k: Rep())})()})())
    rep = provider.repondre("tu es Jarvis", [
        {"role": "user", "content": "salut"}], [])
    assert rep.stop_reason == "end"
    assert rep.content[0].text == "bonjour"
