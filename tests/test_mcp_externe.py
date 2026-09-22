"""Client MCP externe : outils distants publies dans le registre de Jarvis.

La doctrine tient en une phrase : un outil distant demande TOUJOURS confirmation
sauf mention explicite. Ces outils touchent a de l'infra invisible, leurs effets
ne se devinent pas depuis leur nom, et une transcription approximative ne doit
jamais suffire a redemarrer un serveur.
"""
import pytest

from core import mcp_externe, registre


class _OutilDistant:
    """Un Tool tel que le SDK MCP v2 le rend."""

    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema


class _OutilDistantV1(_OutilDistant):
    """Le SDK v1 nommait le champ inputSchema. Les deux doivent marcher."""

    def __init__(self, name, description="", schema=None):
        super().__init__(name, description, None)
        self.inputSchema = schema


@pytest.fixture
def serveur():
    return {"nom": "yorkhost", "url": "http://x/mcp", "entetes": {},
            "sans_confirmation": {"statut_serveur"}, "prefixe": True}


@pytest.fixture(autouse=True)
def _registre_propre():
    """Retire les outils publies par les tests."""
    avant = set(registre._REGISTRE)
    yield
    for nom in set(registre._REGISTRE) - avant:
        registre._REGISTRE.pop(nom, None)


# ------------------------------------------------------------- confirmation

def test_outil_distant_demande_confirmation_par_defaut(serveur):
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("redemarrer_vps"))
    assert registre._REGISTRE[nom].confirmation is True


def test_liste_blanche_dispense_de_confirmation(serveur):
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut_serveur"))
    assert registre._REGISTRE[nom].confirmation is False


def test_outil_a_confirmation_a_une_annonce(serveur):
    """Sans annonce, la demande de confirmation serait muette."""
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("redemarrer_vps"))
    o = registre._REGISTRE[nom]
    assert o.annonce is not None
    assert "redemarrer_vps" in o.annonce({})


def test_outil_distant_jamais_re_expose(serveur):
    """Re-exposer un outil distant via notre propre serveur MCP ferait un pont
    invisible entre deux systemes de permissions."""
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut_serveur"))
    assert registre._REGISTRE[nom].mcp_expose is False


# ------------------------------------------------------------------ schema

def test_schema_v2_input_schema(serveur):
    schema = {"type": "object", "properties": {"nom": {"type": "string"}},
              "required": ["nom"]}
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut", input_schema=schema))
    assert registre._REGISTRE[nom].parametres == schema


def test_schema_v1_inputSchema(serveur):
    """Le SDK a renomme le champ : sans compatibilite, les outils arrivaient
    SANS parametres et le modele ne savait pas quoi passer."""
    schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    nom = mcp_externe._enregistrer(serveur, _OutilDistantV1("vps", schema=schema))
    assert registre._REGISTRE[nom].parametres == schema


def test_schema_absent_donne_un_objet_vide(serveur):
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("ping"))
    assert registre._REGISTRE[nom].parametres == {"type": "object", "properties": {}}


# ------------------------------------------------------------------ nommage

def test_prefixe_par_serveur(serveur):
    """Deux serveurs peuvent exposer un « statut » : le prefixe evite l'ecrasement."""
    assert mcp_externe._enregistrer(serveur, _OutilDistant("statut")) == "yorkhost_statut"


def test_prefixe_desactivable(serveur):
    serveur["prefixe"] = False
    assert mcp_externe._enregistrer(serveur, _OutilDistant("statut")) == "statut"


def test_description_indique_le_serveur(serveur):
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut", "Etat du serveur."))
    assert registre._REGISTRE[nom].description.startswith("[yorkhost]")


# ------------------------------------------------------------- configuration

def test_serveur_sans_url_ignore(monkeypatch):
    monkeypatch.setattr(mcp_externe, "reglage",
                        lambda c, d=None: [{"nom": "x"}, {"url": ""}] if c == "mcp_externes" else d)
    assert mcp_externe._serveurs() == []


def test_config_vide_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(mcp_externe, "reglage", lambda c, d=None: d)
    assert mcp_externe.charger() == ""


def test_serveur_injoignable_ne_bloque_pas_le_demarrage(monkeypatch):
    """Un serveur MCP mort ne doit jamais empecher Jarvis de demarrer."""
    monkeypatch.setattr(
        mcp_externe, "reglage",
        lambda c, d=None: ([{"nom": "mort", "url": "http://127.0.0.1:1/mcp"}]
                           if c == "mcp_externes" else d))
    monkeypatch.setattr(mcp_externe, "_executer",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("refus")))
    resume = mcp_externe.charger()
    assert "injoignable" in resume


# --------------------------------------------------------------- resultats

class _Bloc:
    def __init__(self, text):
        self.text = text


class _Resultat:
    def __init__(self, content=None, isError=False, structuredContent=None):
        self.content, self.isError = content or [], isError
        self.structuredContent = structuredContent


def test_resultat_texte():
    assert mcp_externe._texte_resultat(_Resultat([_Bloc("en ligne")])) == "en ligne"


def test_resultat_erreur_signale():
    r = _Resultat([_Bloc("acces refuse")], isError=True)
    assert "Erreur de l'outil distant" in mcp_externe._texte_resultat(r)


def test_resultat_structure_sans_texte():
    r = _Resultat(structuredContent={"charge": 12})
    assert "charge" in mcp_externe._texte_resultat(r)


def test_resultat_vide_reste_lisible():
    assert mcp_externe._texte_resultat(_Resultat()) == "(pas de reponse)"


# --------------------------------------------------------------- robustesse

def test_appel_sur_serveur_deconnecte(serveur, monkeypatch):
    """Session tombee : message clair, pas de trace."""
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut"))
    monkeypatch.setattr(mcp_externe, "_CLIENTS", {})
    assert "pas connecte" in registre._REGISTRE[nom].fonction()


class _FauxClient:
    """Client MCP minimal : call_tool renvoie une coroutine, comme le vrai."""

    async def call_tool(self, nom, arguments):
        return _Resultat([_Bloc("ok")])


def test_appel_en_timeout(serveur, monkeypatch):
    """Serveur qui ne repond pas : message clair avec le delai, pas de trace."""
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut"))
    monkeypatch.setattr(mcp_externe, "_CLIENTS", {"yorkhost": _FauxClient()})
    monkeypatch.setattr(mcp_externe, "_executer",
                        lambda coro, **k: coro.close() or (_ for _ in ()).throw(TimeoutError()))
    reponse = registre._REGISTRE[nom].fonction()
    assert "n'a pas repondu" in reponse and "yorkhost" in reponse


def test_appel_erreur_reseau_est_lisible(serveur, monkeypatch):
    nom = mcp_externe._enregistrer(serveur, _OutilDistant("statut"))
    monkeypatch.setattr(mcp_externe, "_CLIENTS", {"yorkhost": _FauxClient()})
    monkeypatch.setattr(
        mcp_externe, "_executer",
        lambda coro, **k: coro.close() or (_ for _ in ()).throw(OSError("connexion perdue")))
    reponse = registre._REGISTRE[nom].fonction()
    assert "Echec de l'outil statut" in reponse and "connexion perdue" in reponse
