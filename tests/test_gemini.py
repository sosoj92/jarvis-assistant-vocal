"""Traduction Anthropic <-> Gemini dans core/llm.GeminiProvider.

Tout l'assistant parle le format Anthropic (blocs text / image / tool_use /
tool_result). Le provider Gemini traduit dans les deux sens ; c'est la que se
cachent les erreurs, pas dans l'appel reseau. Ces tests ne touchent jamais au
reseau : ils verifient la forme des `contents` construits et le parsing.
"""
import base64

import pytest

from core import llm

pytest.importorskip("google.genai")

# 1 pixel JPEG, pour les tests d'image.
IMAGE_B64 = base64.b64encode(b"\xff\xd8\xff\xd9").decode()


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(llm, "reglage", lambda chemin, defaut=None: defaut)
    return llm.GeminiProvider()


# --------------------------------------------------------------- les outils

def test_schema_nettoye_des_mots_cles_refuses(provider):
    """Gemini rejette TOUTE la requete si un schema contient additionalProperties.

    Ce n'est pas l'outil fautif qui echoue : c'est l'appel entier. D'ou
    l'elagage en profondeur.
    """
    sale = {
        "type": "object",
        "additionalProperties": False,
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Truc",
        "properties": {
            "nom": {"type": "string", "default": "x", "title": "Nom"},
            "liste": {"type": "array",
                      "items": {"type": "object", "additionalProperties": False,
                                "properties": {"a": {"type": "string"}}}},
        },
    }
    propre = provider._nettoyer_schema(sale)
    texte = str(propre)
    for interdit in ("additionalProperties", "$schema", "title", "default"):
        assert interdit not in texte, f"{interdit} non elague"
    # ce qui compte est conserve
    assert propre["properties"]["nom"]["type"] == "string"
    assert propre["properties"]["liste"]["items"]["properties"]["a"]["type"] == "string"


def test_outil_sans_parametre_recoit_un_objet_vide(provider):
    """Gemini refuse `parameters: None` : il faut un objet, meme vide."""
    tools = provider._outils([{"name": "heure", "description": "donne l'heure"}])
    decl = tools[0].function_declarations[0]
    assert decl.name == "heure"
    assert decl.parameters is not None


def test_aucun_outil_donne_none(provider):
    """Liste vide -> None, pas une Tool vide (que l'API rejette)."""
    assert provider._outils([]) is None


# ----------------------------------------------------------- l'historique

def test_message_texte_simple(provider):
    contents, _ = provider._traduire([{"role": "user", "content": "Bonjour"}])
    assert len(contents) == 1
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "Bonjour"


def test_role_assistant_devient_model(provider):
    """Anthropic dit « assistant », Gemini dit « model »."""
    contents, _ = provider._traduire([
        {"role": "user", "content": "salut"},
        {"role": "assistant", "content": "bonjour"},
    ])
    assert [c.role for c in contents] == ["user", "model"]


def test_appel_outil_puis_resultat(provider):
    """Le cas central : Gemini identifie la reponse par le NOM de la fonction,
    Anthropic par un identifiant. La correspondance doit etre retrouvee."""
    historique = [
        {"role": "user", "content": "allume le salon"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_42", "name": "allumer_lumiere",
             "input": {"piece": "salon"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_42", "content": "C'est fait."}]},
    ]
    contents, noms = provider._traduire(historique)
    assert noms == {"toolu_42": "allumer_lumiere"}

    appel = contents[1].parts[0].function_call
    assert appel.name == "allumer_lumiere"
    assert dict(appel.args) == {"piece": "salon"}

    reponse = contents[2].parts[0].function_response
    assert reponse.name == "allumer_lumiere", "le nom n'a pas ete retrouve via l'id"
    assert "C'est fait." in str(reponse.response)


def test_resultat_sans_appel_connu_ne_plante_pas(provider):
    """Historique tronque : on ne doit pas lever, juste nommer generiquement."""
    contents, _ = provider._traduire([
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "inconnu", "content": "ok"}]}])
    assert contents[0].parts[0].function_response.name == "outil"


def test_capture_ecran_transmet_l_image(provider):
    """La vision est LA raison de prendre Gemini plutot qu'Ollama en local :
    l'image d'une capture doit vraiment arriver, pas un texte de remplacement."""
    historique = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "capture_screen", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg",
                            "data": IMAGE_B64}}]}]},
    ]
    contents, _ = provider._traduire(historique)
    parts = contents[1].parts
    assert parts[0].function_response.name == "capture_screen"
    donnees = [p.inline_data for p in parts if getattr(p, "inline_data", None)]
    assert donnees, "aucune image transmise a Gemini"
    assert donnees[0].mime_type == "image/jpeg"


def test_image_directe_dans_un_message(provider):
    contents, _ = provider._traduire([{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": IMAGE_B64}},
        {"type": "text", "text": "c'est quoi ?"}]}])
    parts = contents[0].parts
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[1].text == "c'est quoi ?"


def test_message_vide_est_ignore(provider):
    """Un Content sans parts fait echouer l'API : il ne doit pas etre construit."""
    contents, _ = provider._traduire([{"role": "user", "content": ""},
                                      {"role": "user", "content": []}])
    assert contents == []


# ------------------------------------------------------------- la reponse

class _Appel:
    def __init__(self, name, args, id=None):
        self.name, self.args, self.id = name, args, id


class _Part:
    def __init__(self, text=None, function_call=None):
        self.text, self.function_call = text, function_call


class _Reponse:
    def __init__(self, parts):
        self.candidates = [type("C", (), {"content": type("D", (), {"parts": parts})()})()]


def test_parse_texte(provider):
    r = provider._parser(_Reponse([_Part(text="Bonjour Arturo.")]))
    assert r.stop_reason == "end"
    assert r.content[0].type == "text" and r.content[0].text == "Bonjour Arturo."


def test_parse_appel_outil(provider):
    r = provider._parser(_Reponse([
        _Part(text="J'allume."),
        _Part(function_call=_Appel("allumer_lumiere", {"piece": "salon"})),
    ]))
    assert r.stop_reason == "tool_use"
    assert [b.type for b in r.content] == ["text", "tool_use"]
    outil = r.content[1]
    assert outil.name == "allumer_lumiere"
    assert outil.input == {"piece": "salon"}
    assert outil.id, "un identifiant est requis pour rattacher le tool_result"


def test_parse_identifiants_uniques(provider):
    """Deux appels dans le meme tour ne doivent pas partager un identifiant."""
    r = provider._parser(_Reponse([
        _Part(function_call=_Appel("a", {})),
        _Part(function_call=_Appel("b", {})),
    ]))
    ids = [b.id for b in r.content if b.type == "tool_use"]
    assert len(set(ids)) == 2, f"identifiants dupliques : {ids}"


def test_parse_reponse_vide_ne_plante_pas(provider):
    r = provider._parser(_Reponse([]))
    assert r.stop_reason == "end" and r.content


def test_parse_sans_candidat(provider):
    """Reponse filtree par la securite : aucun candidat. Ne doit pas lever."""
    vide = type("R", (), {"candidates": []})()
    assert provider._parser(vide).stop_reason == "end"


# --------------------------------------------------------------- fabrique

def test_fournisseur_par_defaut_reste_claude(monkeypatch):
    monkeypatch.setattr(llm, "reglage", lambda chemin, defaut=None: defaut)
    assert llm._provider_cloud().nom == "Claude"


def test_fournisseur_gemini(monkeypatch):
    valeurs = {"fournisseur": "gemini", "gemini.modele": "gemini-2.5-flash"}
    monkeypatch.setattr(llm, "reglage",
                        lambda chemin, defaut=None: valeurs.get(chemin, defaut))
    p = llm._provider_cloud()
    assert p.nom == "Gemini" and p.modele == "gemini-2.5-flash"


def test_fournisseur_gemini_en_qualite(monkeypatch):
    valeurs = {"fournisseur": "gemini", "gemini.modele_qualite": "gemini-2.5-pro"}
    monkeypatch.setattr(llm, "reglage",
                        lambda chemin, defaut=None: valeurs.get(chemin, defaut))
    assert llm._provider_cloud(qualite=True).modele == "gemini-2.5-pro"


def test_gemini_indisponible_sans_cle(monkeypatch):
    monkeypatch.setattr(llm, "reglage", lambda chemin, defaut=None: defaut)
    assert llm.GeminiProvider().disponible() is False
