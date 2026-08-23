"""Conversion des coordonnees vues par Claude vers l'ecran reel.

C'est LE calcul qui decide si Jarvis clique au bon endroit. Entre l'image que
Claude voit et l'ecran, il y a deux transformations :

  1. Retina : mss capture en PIXELS (2x les points sur un ecran Retina)
  2. redimensionnement a 1568 px de large avant l'envoi a Claude

Raisonner en fractions du moniteur annule les deux d'un coup. Ces tests
verrouillent ce raisonnement, y compris sur un second ecran (origine non nulle),
ou une erreur donnerait un clic sur le mauvais ecran.
"""
import pytest

from tools import ecran, souris


@pytest.fixture
def capture(monkeypatch):
    """Installe une geometrie de capture arbitraire."""
    def poser(moniteur, largeur, hauteur):
        monkeypatch.setattr(ecran, "_DERNIERE_CAPTURE",
                            {"moniteur": moniteur, "largeur": largeur,
                             "hauteur": hauteur})
    return poser


def test_ecran_simple_sans_redimensionnement(capture):
    capture({"left": 0, "top": 0, "width": 1440, "height": 900}, 1440, 900)
    assert souris._vers_ecran(0, 0) == (0, 0)
    assert souris._vers_ecran(720, 450) == (720, 450)
    assert souris._vers_ecran(1440, 900) == (1440, 900)


def test_retina_plus_redimensionnement(capture):
    """Cas reel d'un Mac : moniteur 1920x1080 points, image reduite a 1568.

    Le centre de l'image doit tomber au centre de l'ecran — pas au double.
    """
    capture({"left": 0, "top": 0, "width": 1920, "height": 1080}, 1568, 882)
    assert souris._vers_ecran(784, 441) == (960, 540)          # centre
    assert souris._vers_ecran(0, 0) == (0, 0)
    assert souris._vers_ecran(1568, 882) == (1920, 1080)       # coin bas droit


def test_second_ecran_decale(capture):
    """Un moniteur a droite du principal : l'origine doit etre ajoutee."""
    capture({"left": 1920, "top": 0, "width": 2560, "height": 1440}, 1568, 882)
    assert souris._vers_ecran(0, 0) == (1920, 0)
    assert souris._vers_ecran(784, 441) == (1920 + 1280, 720)


def test_ecran_au_dessus_avec_origine_negative(capture):
    capture({"left": 0, "top": -1080, "width": 1920, "height": 1080}, 1568, 882)
    assert souris._vers_ecran(784, 441) == (960, -540)


def test_hors_image_refuse(capture):
    """Cliquer hors de l'image serait un clic au hasard : on refuse."""
    capture({"left": 0, "top": 0, "width": 1920, "height": 1080}, 1568, 882)
    for x, y in ((-1, 10), (10, -1), (1569, 10), (10, 883)):
        with pytest.raises(ValueError, match="hors-image"):
            souris._vers_ecran(x, y)


def test_sans_capture_refuse(monkeypatch):
    """Sans capture recente, on ne devine pas : l'outil demande une capture."""
    monkeypatch.setattr(ecran, "_DERNIERE_CAPTURE", {})
    with pytest.raises(ValueError, match="pas-de-capture"):
        souris._vers_ecran(10, 10)


# --------------------------------------------------------------- les outils

def test_cliquer_sans_capture_dit_quoi_faire(monkeypatch):
    monkeypatch.setattr(ecran, "_DERNIERE_CAPTURE", {})
    reponse = souris.cliquer_ecran(10, 10)
    assert "capture_screen" in reponse


def test_cliquer_hors_image_ne_bouge_pas_la_souris(capture, monkeypatch):
    capture({"left": 0, "top": 0, "width": 1920, "height": 1080}, 1568, 882)
    bouges = []
    monkeypatch.setattr(souris.plateforme, "souris_deplacer",
                        lambda x, y: bouges.append((x, y)) or True)
    reponse = souris.cliquer_ecran(5000, 5000)
    assert "hors de l'image" in reponse
    assert bouges == [], "la souris a bouge malgre des coordonnees invalides"


def test_cliquer_deplace_puis_clique(capture, monkeypatch):
    capture({"left": 0, "top": 0, "width": 1920, "height": 1080}, 1568, 882)
    faits = []
    monkeypatch.setattr(souris.plateforme, "souris_deplacer",
                        lambda x, y: faits.append(("deplacer", x, y)) or True)
    monkeypatch.setattr(souris.plateforme, "souris_cliquer",
                        lambda b, d: faits.append(("cliquer", b, d)) or True)
    souris.cliquer_ecran(784, 441, "droite", True)
    assert faits == [("deplacer", 960, 540), ("cliquer", "droite", True)]


def test_permission_refusee_est_expliquee(capture, monkeypatch):
    capture({"left": 0, "top": 0, "width": 1920, "height": 1080}, 1568, 882)
    monkeypatch.setattr(souris.plateforme, "souris_deplacer", lambda x, y: False)
    assert "Accessibilite" in souris.cliquer_ecran(100, 100)


@pytest.mark.parametrize("sens, attendu", [
    ("haut", (180, 0)), ("bas", (-180, 0)),
    ("gauche", (0, 180)), ("droite", (0, -180)),
])
def test_defilement_par_sens(monkeypatch, sens, attendu):
    vus = []
    monkeypatch.setattr(souris.plateforme, "souris_defiler",
                        lambda v, h: vus.append((v, h)) or True)
    souris.defiler_ecran(sens)
    assert vus == [attendu]


def test_defilement_sens_inconnu():
    assert "inconnu" in souris.defiler_ecran("diagonale")


def test_taper_texte_vide_refuse():
    assert "texte" in souris.taper_texte("   ").lower()
