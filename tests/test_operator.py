"""Operator (core/operator.py) : journal, KPIs, validation locale uniquement.

Le CRM « AI Operator » ne cree AUCUN droit nouveau : la file « a valider »
reflete le mecanisme EXISTANT de confirmation vocale (registre._EN_ATTENTE),
et valider/refuser depuis la page equivaut au oui/non vocal. Les tests le
verifient, ainsi que le garde « local uniquement » et le journal borne.
"""

import json

import pytest

from core import operator, registre


@pytest.fixture(autouse=True)
def journal_isole(tmp_path, monkeypatch):
    """Journal dans un tmp : les tests ne touchent jamais le vrai fichier."""
    monkeypatch.setattr(operator, "_JOURNAL", tmp_path / "journal.json")
    monkeypatch.setattr(operator, "_ENTREES", None)
    yield
    registre.annuler_confirme()


def _un_outil(monkeypatch):
    """Un faux outil en attente, comme le fait la confirmation vocale."""
    outil = registre.Outil(
        lambda **k: "fait", "outil_test",
        "outil de test", {}, True, False, None,
        lambda a: f"Je vais faire {a.get('quoi')}.", False, "auto")
    registre.mettre_en_attente(outil, {"quoi": "le café"})
    return outil


# ------------------------------------------------------------------ journal

def test_journaliser_et_relire():
    operator.journaliser("mail", "3 mails triés", "boîte INBOX")
    etat = operator.etat()
    assert etat["journal"][0]["titre"] == "3 mails triés"
    assert etat["journal"][0]["categorie"] == "mail"


def test_journal_persiste_sur_disque():
    operator.journaliser("crm", "Client Acme ajouté")
    operator._ENTREES = None                      # force la relecture disque
    assert any("Acme" in e["titre"] for e in operator._charger())


def test_journal_borne_en_taille(monkeypatch):
    monkeypatch.setattr(operator, "_MAX_ENTREES", 5)
    for i in range(12):
        operator.journaliser("lecture", f"ligne {i}")
    assert len(operator._charger()) == 5
    assert operator._charger()[0]["titre"] == "ligne 11"


def test_journaliser_tronque_les_entrees():
    operator.journaliser("mail", "x" * 500, "y" * 1000)
    e = operator._charger()[0]
    assert len(e["titre"]) <= 160
    assert len(e["detail"]) <= 400


def test_journal_corrompu_repart_a_zero(tmp_path, monkeypatch):
    (tmp_path / "journal.json").write_text("{pas du json", encoding="utf-8")
    monkeypatch.setattr(operator, "_ENTREES", None)
    assert operator._charger() == []


# ---------------------------------------------------------------- KPIs 24 h

def test_kpis_comptent_les_dernieres_24h():
    import time
    operator.journaliser("mail", "vieux mail", "")
    operator._ENTREES[-1]["ts"] = time.time() - 3 * 24 * 3600   # hors fenetre
    operator.journaliser("mail", "mail récent")
    kpis = operator.etat()["kpis"]
    assert kpis["actions_24h"] == 1
    assert kpis["par_categorie"]["mail"] == 1


# ------------------------------------------------------------ file de validation

def test_file_vide_sans_action_en_attente():
    registre.annuler_confirme()
    assert operator.etat()["a_valider"] == []
    assert operator.etat()["kpis"]["en_attente"] == 0


def test_file_reflete_le_registre(monkeypatch):
    _un_outil(monkeypatch)
    file = operator.etat()["a_valider"]
    assert len(file) == 1
    assert file[0]["outil"] == "outil_test"
    assert file[0]["annonce"].startswith("Je vais faire")


# --------------------------------------------------------- valider / refuser

def test_valider_execute_l_action_en_attente(monkeypatch):
    _un_outil(monkeypatch)
    res = operator.valider()
    assert res["ok"] is True
    assert res["resultat"] == "fait"
    assert registre.nom_en_attente() is None      # file videe


def test_valider_sans_action_refuse():
    registre.annuler_confirme()
    assert operator.valider()["ok"] is False


def test_refuser_annule_sans_executer(monkeypatch):
    _un_outil(monkeypatch)
    res = operator.refuser()
    assert res["ok"] is True
    assert registre.nom_en_attente() is None


def test_validation_journallee(monkeypatch):
    _un_outil(monkeypatch)
    operator.valider()
    assert any(e["categorie"] == "validation" for e in operator._charger())


# ------------------------------------------------------------------- routes

class _Client:
    """Client bas niveau : host simulable pour tester le garde local."""

    def __init__(self, host="127.0.0.1", forwarded=False):
        self.host = host
        self.forwarded = forwarded


class _Req:
    def __init__(self, host="127.0.0.1", forwarded=False, method="GET"):
        import types
        self.client = _Client(host)
        self.headers = {"x-forwarded-for": "1.2.3.4"} if forwarded else {}
        self.method = method


def _app_routes():
    import types
    app = types.SimpleNamespace()
    app.routes = []
    app.get = lambda chemin: (lambda f: app.routes.append((chemin, f)) or f)
    app.post = lambda chemin: (lambda f: app.routes.append((chemin, f)) or f)
    operator.monter_routes(app)
    return app


def test_page_operator_refuse_le_tunnel():
    app = _app_routes()
    page = dict(app.routes)["/operator"]
    reponse = page(_Req(forwarded=True))
    assert reponse.status_code == 403


def test_api_refuse_le_lan():
    app = _app_routes()
    etat = dict(app.routes)["/api/operator/etat"]
    assert etat(_Req(host="192.168.1.5")).status_code == 403
    assert isinstance(etat(_Req()), dict)      # local : etat servi, pas un refus


def test_post_exige_json():
    app = _app_routes()
    valider = dict(app.routes)["/api/operator/valider"]
    req = _Req(method="POST")
    req.headers = {"content-type": "text/plain"}
    assert valider(req).status_code == 415


# --------------------------------------------------------- messagerie ecrite

def test_message_ecrit_file_et_reponse():
    operator.envoyer_message("lis mes mails")
    m = operator.message_suivant()
    assert m["texte"] == "lis mes mails"
    assert operator.message_suivant() is None      # file videe
    operator.reponse_message(m["id"], "Voici tes 3 mails.")
    assert operator.lire_reponse(m["id"]) == "Voici tes 3 mails."
    assert operator.lire_reponse(m["id"]) is None  # consommee une fois


def test_message_vide_ou_trop_long_refuse():
    assert operator.envoyer_message("  ")["ok"] is False
    assert operator.envoyer_message("x" * 700)["ok"] is False


def test_conversation_garde_les_derniers():
    for i in range(50):
        operator.envoyer_message(f"message {i}")
    assert len(operator.conversation()) <= 40
