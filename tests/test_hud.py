"""Le HUD est la seule interface visuelle sur macOS : son echec doit se VOIR.

Avant, `_hud()` avalait toutes les exceptions — y compris celle du demarrage.
Le HUD ne s'ouvrait pas, aucune trace, et l'utilisateur n'avait aucun moyen de
savoir pourquoi. C'est exactement ce qui est arrive au premier essai sur Mac.
"""
import pytest

jarvis14 = pytest.importorskip("jarvis14")


@pytest.fixture
def _hud_muet(monkeypatch):
    """Neutralise la config pour que les tests ne dependent pas de config.yaml."""
    monkeypatch.setattr(jarvis14.config, "reglage",
                        lambda chemin, defaut=None: defaut)


class _FauxHud:
    PORT = 8770

    def __init__(self, erreur=None):
        self.erreur, self.appels = erreur, []

    def demarrer(self, ouvrir=True):
        self.appels.append(ouvrir)
        if self.erreur:
            raise self.erreur


def test_port_occupe_est_annonce(monkeypatch, capsys, _hud_muet):
    monkeypatch.setattr(jarvis14, "hud", _FauxHud(OSError("Address already in use")))
    jarvis14._demarrer_hud()
    texte = capsys.readouterr().out
    assert "8770" in texte and "deja pris" in texte


def test_import_rate_est_annonce(monkeypatch, capsys, _hud_muet):
    monkeypatch.setattr(jarvis14, "hud", None)
    monkeypatch.setattr(jarvis14, "_ERREUR_HUD", ImportError("pas de module hud"))
    jarvis14._demarrer_hud()
    assert "HUD indisponible" in capsys.readouterr().out


def test_erreur_inattendue_est_annoncee(monkeypatch, capsys, _hud_muet):
    monkeypatch.setattr(jarvis14, "hud", _FauxHud(RuntimeError("boum")))
    jarvis14._demarrer_hud()
    texte = capsys.readouterr().out
    assert "RuntimeError" in texte and "boum" in texte


def test_demarrage_normal_ne_dit_rien(monkeypatch, capsys, _hud_muet):
    faux = _FauxHud()
    monkeypatch.setattr(jarvis14, "hud", faux)
    jarvis14._demarrer_hud()
    assert faux.appels == [True]
    assert capsys.readouterr().out == ""


def test_hud_desactivable(monkeypatch, capsys):
    faux = _FauxHud()
    monkeypatch.setattr(jarvis14, "hud", faux)
    monkeypatch.setattr(jarvis14.config, "reglage",
                        lambda chemin, defaut=None:
                        False if chemin == "hud.actif" else defaut)
    jarvis14._demarrer_hud()
    assert faux.appels == []


def test_ouverture_navigateur_desactivable(monkeypatch):
    faux = _FauxHud()
    monkeypatch.setattr(jarvis14, "hud", faux)
    monkeypatch.setattr(jarvis14.config, "reglage",
                        lambda chemin, defaut=None:
                        False if chemin == "hud.ouvrir_navigateur" else defaut)
    jarvis14._demarrer_hud()
    assert faux.appels == [False]
