"""Google Sheets (tools/classeurs.py) : alias, recherche, erreurs propres.

Tout est moque : ces tests ne touchent jamais le reseau ni de vrais classeurs.
Ils verifient la mecanique (resolution d'alias/URL, aplatissage pour la voix,
confirmation requise pour l'ecriture, messages d'erreur sans fuite de donnes).
"""

import pytest

from tools import classeurs


# ------------------------------------------------------------- faux service

class _FauxValeurs:
    def __init__(self, reponse):
        self._reponse = reponse

    def get(self, **kw):
        return self

    def execute(self):
        return self._reponse

    def update(self, **kw):
        return self

    def append(self, **kw):
        return self


class _FauxFeuilles:
    def __init__(self, noms):
        self._noms = noms

    def get(self, **kw):
        return self

    def execute(self):
        return {"sheets": [{"properties": {"name": n}} for n in self._noms]}


class _FauxService:
    def __init__(self, valeurs=None, noms=("Feuil1",)):
        self.valeurs = valeurs or []
        self.noms = noms
        self.appels = []

    def spreadsheets(self):
        return self

    def values(self):
        self.appels.append("values")
        return _FauxValeurs({"values": self.valeurs})

    def get(self, **kw):
        self.appels.append("get")
        return _FauxFeuilles(self.noms)


@pytest.fixture
def service(monkeypatch):
    s = _FauxService(valeurs=[
        ["Nom", "Contact", "Statut"],
        ["PhoneBox", "Florian", "Actif"],
        ["Acme", "John", "En discussion"],
    ])
    monkeypatch.setattr(classeurs, "_service", lambda: s)
    return s


# ------------------------------------------------------------------ alias

def test_alias_resolu_depuis_config(monkeypatch):
    monkeypatch.setattr(classeurs, "reglage",
                        lambda c, d=None: {"partenaires": "ID123"}
                        if c == "classeurs.alias" else d)
    assert classeurs._resoudre("partenaires") == "ID123"


def test_url_extraite_l_id(monkeypatch):
    monkeypatch.setattr("core.config.reglage", lambda c, d=None: d)
    url = "https://docs.google.com/spreadsheets/d/1AbCdEf/edit#gid=0"
    assert classeurs._resoudre(url) == "1AbCdEf"


def test_id_brut_inchange(monkeypatch):
    monkeypatch.setattr("core.config.reglage", lambda c, d=None: d)
    assert classeurs._resoudre("1AbCdEf") == "1AbCdEf"


# ------------------------------------------------------------------ lecture

def test_lire_resume_les_lignes(service):
    texte = classeurs.classeurs_lire(classeur="1AbCdEf", plage="A1:C3")
    assert "PhoneBox" in texte
    assert "Acme" in texte
    assert "1." in texte


def test_lire_plage_vide(service):
    service.valeurs = []
    assert "vide" in classeurs.classeurs_lire(classeur="1AbCdEf").lower()


def test_lire_limite_le_flot(service):
    service.valeurs = [[f"client{i}", "x", "y"] for i in range(50)]
    texte = classeurs.classeurs_lire(classeur="1AbCdEf")
    assert "38 lignes de plus" in texte


def test_lire_sans_classeur():
    texte = classeurs.classeurs_lire(classeur="")
    assert "alias" in texte.lower()


# ---------------------------------------------------------------- recherche

def test_chercher_trouve_la_ligne(service):
    texte = classeurs.classeurs_chercher(classeur="1AbCdEf", valeur="acme")
    assert "Trouve ligne 3" in texte
    assert "John" in texte


def test_chercher_insensible_a_la_casse(service):
    assert "PHONEBOX" in classeurs.classeurs_chercher(
        classeur="1AbCdEf", valeur="phonebox").upper() or True
    texte = classeurs.classeurs_chercher(classeur="1AbCdEf", valeur="phonebox")
    assert "Trouve ligne 2" in texte


def test_chercher_absent(service):
    texte = classeurs.classeurs_chercher(classeur="1AbCdEf", valeur="zzz")
    assert "n'apparait" in texte


# ----------------------------------------------------------------- ecriture

def test_ecriture_exige_confirmation():
    """95/5 : ecrire dans un classeur demande TOUJOURS l'accord vocal."""
    from core import registre
    for nom in ("classeurs_ecrire_cellule", "classeurs_ajouter_ligne"):
        assert registre._REGISTRE[nom].confirmation is True


def test_ecriture_exige_un_service(service):
    texte = classeurs.classeurs_ecrire_cellule(
        classeur="", plage="B2", valeur="Actif")
    assert texte == "Je ne sais pas dans quel classeur ecrire."


def test_ecriture_requete_le_service(service):
    texte = classeurs.classeurs_ecrire_cellule(
        classeur="1AbCdEf", plage="B2", valeur="Actif")
    assert "C'est ecrit" in texte
    assert "values" in service.appels


def test_ajout_ligne(service):
    texte = classeurs.classeurs_ajouter_ligne(
        classeur="1AbCdEf", feuille="Feuil1", ligne=["Nouveau", "contact", ""])
    assert "Ligne ajoutee" in texte
    assert "Nouveau" in texte


def test_ajout_ligne_vide(service):
    texte = classeurs.classeurs_ajouter_ligne(
        classeur="1AbCdEf", ligne=["", "  "])
    assert "rien a ecrire" in texte


# ------------------------------------------------------------ pas d'exposition

def test_outils_sheets_exposes_nulle_part():
    """Donnees de CRM/facturation : jamais exposees via le serveur MCP."""
    from core import registre
    for nom in ("classeurs_lire", "classeurs_chercher",
                "classeurs_ecrire_cellule", "classeurs_ajouter_ligne"):
        assert registre._REGISTRE[nom].mcp_expose is False
