"""Le budget doit chiffrer les modeles Mistral, pas compter 0 $."""
from core import budget


def test_prix_mistral_small_par_defaut(monkeypatch):
    monkeypatch.setattr(budget, "reglage", lambda c, d=None: d)
    assert budget._prix("mistral-small-latest") == (0.10, 0.30)


def test_prix_mistral_large_par_defaut(monkeypatch):
    monkeypatch.setattr(budget, "reglage", lambda c, d=None: d)
    assert budget._prix("mistral-large-latest") == (0.50, 1.50)


def test_cout_mistral_non_nul(monkeypatch, tmp_path):
    monkeypatch.setattr(budget, "reglage", lambda c, d=None: d)
    monkeypatch.setattr(budget, "_fichier", lambda: tmp_path / "budget.json")
    budget.enregistrer("Mistral (Jarvis)", "mistral-small-latest",
                       tin=100_000, tout=20_000)
    lignes = budget.resume()["jour"]
    cle = next(k for k in lignes if "mistral" in k.lower())
    assert lignes[cle]["cout"] > 0
