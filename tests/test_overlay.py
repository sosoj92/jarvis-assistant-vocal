"""L'overlay ne doit JAMAIS faire tomber l'assistant.

Sur macOS, Cocoa impose que toute NSWindow naisse sur le thread principal. Tk
appelé depuis le thread daemon de l'overlay y lève une exception OBJECTIVE-C
— pas une exception Python : elle avorte le processus (code 134) et emporte
tout Jarvis, sans qu'aucun try/except puisse l'attraper.

C'est arrivé au premier lancement reel sur Mac. Ces tests verrouillent le fait
que l'overlay refuse de demarrer plutot que de tuer l'assistant.
"""
import pytest

import overlay


@pytest.fixture(autouse=True)
def _overlay_neuf(monkeypatch):
    """Repart d'un overlay non demarre, sans toucher a l'etat du module."""
    monkeypatch.setattr(overlay, "_THREAD", None)
    monkeypatch.setattr(overlay, "_CFG", dict(overlay._CFG))
    yield


def test_pas_de_thread_tk_sur_macos(monkeypatch):
    """Le seul test qui compte : aucun thread ne doit etre cree sur Mac."""
    monkeypatch.setattr(overlay, "_MAC", True)
    overlay.demarrer({"actif": True})
    assert overlay._THREAD is None


def test_macos_se_declare_indisponible(monkeypatch):
    monkeypatch.setattr(overlay, "_MAC", True)
    assert overlay.disponible() is False
    overlay.demarrer({"actif": True})
    # est_actif() passe a False : les outils repondent « indisponible »
    # au lieu d'envoyer dans une file que personne ne lit.
    assert overlay.est_actif() is False


def test_macos_le_dit_a_l_utilisateur(monkeypatch, capsys):
    monkeypatch.setattr(overlay, "_MAC", True)
    overlay.demarrer({"actif": True})
    texte = capsys.readouterr().out
    assert "macOS" in texte and "panneau web" in texte


def test_afficher_apres_refus_ne_leve_pas(monkeypatch):
    """Jarvis appelle afficher() a chaque reponse : ca doit rester inoffensif."""
    monkeypatch.setattr(overlay, "_MAC", True)
    overlay.demarrer({"actif": True})
    overlay.afficher("une reponse")
    overlay.masquer()
    overlay.memoriser("une reponse")


def test_boucle_sort_immediatement_sur_macos(monkeypatch):
    """Garde-fou : meme appelee directement, _boucle ne touche pas a Tk."""
    monkeypatch.setattr(overlay, "_MAC", True)
    appels = []
    monkeypatch.setitem(__import__("sys").modules, "tkinter",
                        type("_Piege", (), {"Tk": lambda *a: appels.append(1)})())
    overlay._boucle()
    assert appels == []


def test_demarre_bien_hors_macos(monkeypatch):
    """Windows et Linux ne doivent pas etre penalises par le correctif."""
    monkeypatch.setattr(overlay, "_MAC", False)
    lances = []
    monkeypatch.setattr(overlay.threading, "Thread",
                        lambda **kw: type("_F", (), {"start": lambda s: lances.append(kw)})())
    overlay.demarrer({"actif": True})
    assert len(lances) == 1 and lances[0]["daemon"] is True
