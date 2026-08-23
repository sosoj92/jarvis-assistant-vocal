"""Tests de la couche d'abstraction système (core/plateforme.py).

Ces tests tournent sur les trois systèmes. Ceux qui touchent réellement au
matériel (volume, extinction, touches) sont marqués et sautés par défaut : voir
scripts/test_mac.py pour la vérification manuelle sur un vrai Mac.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core import plateforme


# ------------------------------------------------------------- identification

def test_un_seul_systeme_est_vrai():
    """Les trois drapeaux sont mutuellement exclusifs, et un seul est vrai."""
    assert sum([plateforme.EST_WINDOWS, plateforme.EST_MAC,
                plateforme.EST_LINUX]) == 1


def test_nom_systeme_coherent():
    assert plateforme.SYSTEME in ("windows", "macos", "linux")
    attendu = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    assert plateforme.SYSTEME == attendu


def test_apple_silicon_implique_mac():
    assert not plateforme.est_apple_silicon() or plateforme.EST_MAC


def test_nom_machine_non_vide():
    assert plateforme.nom_machine().strip()


# ------------------------------------------------------------------- chemins

def test_racine_disque_existe():
    """La racine sert à psutil.disk_usage : elle doit exister réellement."""
    assert Path(plateforme.racine_disque()).exists()


def test_dossier_donnees_absolu_et_sous_le_home():
    chemin = plateforme.dossier_donnees("ChromeJarvis")
    assert chemin.is_absolute()
    assert chemin.name == "ChromeJarvis"
    # Aucun chemin en dur : toujours dérivé du dossier personnel de l'utilisateur.
    assert str(Path.home()) in str(chemin) or plateforme.EST_LINUX


def test_dossier_donnees_par_os():
    chemin = str(plateforme.dossier_donnees("X"))
    if plateforme.EST_MAC:
        assert "Library/Application Support" in chemin
    elif plateforme.EST_WINDOWS:
        assert "AppData" in chemin or "Local" in chemin


def test_bash_exe_est_un_chemin():
    assert plateforme.bash_exe()


def test_python_systeme_est_executable():
    py = plateforme.python_systeme()
    assert py
    # Si c'est un chemin absolu, il doit pointer sur quelque chose d'exécutable.
    if Path(py).is_absolute():
        assert Path(py).exists()


def test_chrome_exe_est_none_ou_existant():
    exe = plateforme.chrome_exe()
    assert exe is None or Path(exe).exists()


# ------------------------------------------------------------ sous-processus

def test_sans_fenetre_utilisable_par_subprocess():
    """Le dict doit pouvoir être déplié directement dans subprocess.run()."""
    kw = plateforme.sans_fenetre()
    assert isinstance(kw, dict)
    r = subprocess.run([sys.executable, "-c", "print(1)"],
                       capture_output=True, text=True, **kw)
    assert r.stdout.strip() == "1"


def test_detache_utilisable_par_subprocess():
    kw = plateforme.detache()
    assert isinstance(kw, dict)
    p = subprocess.Popen([sys.executable, "-c", "pass"], **kw)
    assert p.wait(timeout=30) == 0


def test_sans_fenetre_vide_hors_windows():
    if not plateforme.EST_WINDOWS:
        assert plateforme.sans_fenetre() == {}


# ------------------------------------------------------------------- réseau

sans_ping = pytest.mark.skipif(shutil.which("ping") is None,
                               reason="la commande ping n'est pas installée ici")


@sans_ping
def test_ping_localhost():
    """127.0.0.1 répond toujours : valide la commande ping ET l'analyse du TTL.

    C'est le test qui attrape l'erreur classique du portage : sur macOS, -W est
    en millisecondes, sur Linux en secondes, et Windows veut -n au lieu de -c.
    """
    assert plateforme.ping("127.0.0.1", timeout_ms=1500) is True


@sans_ping
def test_ping_ip_injoignable_est_faux():
    assert plateforme.ping("192.0.2.1", timeout_ms=300) is False   # TEST-NET-1


def test_ping_ip_vide_est_faux():
    """Sans IP configurée, aucun sous-processus ne doit être lancé."""
    assert plateforme.ping("", timeout_ms=200) is False
    assert plateforme.ping(None, timeout_ms=200) is False


# ---------------------------------------------------------------- audio / IA

def test_micro_defaut_par_os():
    defaut = plateforme.micro_defaut()
    assert defaut == (1 if plateforme.EST_WINDOWS else None)


@pytest.mark.parametrize("brut, attendu", [
    (None, None), ("", None), (3, 3), ("3", 3), ("-1", -1),
    ("Micro externe", "Micro externe"),
])
def test_peripherique_audio_normalise(brut, attendu):
    assert plateforme.peripherique_audio(brut) == attendu


def test_accelerateur_whisper():
    device, precision = plateforme.accelerateur_whisper()
    assert device in ("cpu", "cuda")
    # CTranslate2 n'a pas de backend Metal : sur Mac, ce doit être le CPU.
    if plateforme.EST_MAC:
        assert device == "cpu"
        assert precision == "int8"


# --------------------------------------------------------------------- voix

def test_nom_voix_systeme_mentionne_le_bon_moteur():
    nom = plateforme.nom_voix_systeme()
    if plateforme.EST_MAC:
        assert "say" in nom
    elif plateforme.EST_WINDOWS:
        assert "SAPI" in nom


def test_voix_systeme_disponible_renvoie_un_booleen():
    assert isinstance(plateforme.voix_systeme_disponible(), bool)


# ------------------------------------------------- garde-fous multiplateformes

def test_osascript_refuse_hors_mac():
    if not plateforme.EST_MAC:
        with pytest.raises(RuntimeError):
            plateforme.osascript("beep")


def test_volume_ajuster_refuse_un_sens_invalide():
    with pytest.raises(ValueError):
        plateforme.volume_ajuster("de_travers")


def test_media_action_inconnue_est_fausse():
    assert plateforme.media("teleportation") is False


def test_envoyer_touches_vide_est_faux():
    assert plateforme.envoyer_touches("") is False
    assert plateforme.envoyer_touches(None) is False


def test_fenetre_active_renvoie_deux_chaines():
    titre, proc = plateforme.fenetre_active()
    assert isinstance(titre, str) and isinstance(proc, str)


def test_moniteurs_renvoie_des_rectangles():
    for rect in plateforme.moniteurs():
        assert len(rect) == 4
        gauche, haut, droite, bas = rect
        assert droite > gauche and bas > haut


def test_annuler_extinction_sans_extinction_programmee():
    """Sans arrêt programmé, l'annulation doit dire non — pas planter."""
    assert plateforme.annuler_extinction() is False


def test_infos_gpu_est_une_chaine():
    assert isinstance(plateforme.infos_gpu(), str)
