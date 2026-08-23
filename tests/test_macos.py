"""Vérifie les BRANCHES macOS de core/plateforme depuis n'importe quel système.

On ne peut pas exécuter osascript ou `say` ailleurs que sur un Mac. On vérifie
donc ce qui est vérifiable partout : que les bonnes commandes sont construites,
avec les bons arguments. C'est là que se cachent les vraies erreurs de portage
(le `-W` de ping en millisecondes, le `-f -` de `say`, le `open -a`...).

Les tests forcent le module en mode macOS via monkeypatch et interceptent
subprocess. Aucun appel système réel n'est fait.
"""
import subprocess

import pytest

from core import plateforme


@pytest.fixture
def mac(monkeypatch):
    """Force core.plateforme en mode macOS pour la durée du test."""
    monkeypatch.setattr(plateforme, "EST_MAC", True)
    monkeypatch.setattr(plateforme, "EST_WINDOWS", False)
    monkeypatch.setattr(plateforme, "EST_LINUX", False)
    monkeypatch.setattr(plateforme, "SYSTEME", "macos")


@pytest.fixture
def commandes(monkeypatch):
    """Intercepte subprocess.run et enregistre les commandes construites."""
    vues = []

    def faux_run(cmd, *a, **kw):
        vues.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", faux_run)
    return vues


@pytest.fixture
def popens(monkeypatch):
    """Intercepte subprocess.Popen et enregistre les commandes construites."""
    vues = []

    class FauxPopen:
        def __init__(self, cmd, *a, **kw):
            vues.append(cmd)
            self.returncode = 0

        def communicate(self, input=None):
            return b"", b""

    monkeypatch.setattr(subprocess, "Popen", FauxPopen)
    return vues


# ------------------------------------------------------------------- ping

def test_ping_mac_utilise_des_millisecondes(mac, commandes):
    """Piège classique : -W est en ms sur macOS, en SECONDES sur Linux.

    Passer 800 « secondes » à un ping macOS le ferait attendre 13 minutes.
    """
    plateforme.ping("192.168.1.20", timeout_ms=800)
    assert commandes == [["ping", "-c", "1", "-W", "800", "192.168.1.20"]]


def test_ping_linux_convertit_en_secondes(monkeypatch, commandes):
    monkeypatch.setattr(plateforme, "EST_MAC", False)
    monkeypatch.setattr(plateforme, "EST_WINDOWS", False)
    plateforme.ping("192.168.1.20", timeout_ms=800)
    assert commandes == [["ping", "-c", "1", "-W", "1", "192.168.1.20"]]


def test_ping_windows_utilise_n_et_w(monkeypatch, commandes):
    monkeypatch.setattr(plateforme, "EST_WINDOWS", True)
    monkeypatch.setattr(plateforme, "EST_MAC", False)
    plateforme.ping("192.168.1.20", timeout_ms=800)
    assert commandes == [["ping", "-n", "1", "-w", "800", "192.168.1.20"]]


def test_ping_lit_le_ttl_quelle_que_soit_la_casse(mac, monkeypatch):
    """Windows écrit « TTL=64 », macOS et Linux « ttl=64 »."""
    for sortie in ("64 bytes from 127.0.0.1: icmp_seq=0 ttl=64 time=0.05 ms",
                   "Reponse de 127.0.0.1 : octets=32 temps<1ms TTL=128"):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, s=sortie, **kw: subprocess.CompletedProcess(a, 0, s, ""))
        assert plateforme.ping("127.0.0.1") is True


# ------------------------------------------------------------------ ouvrir

def test_ouvrir_url_passe_par_open(mac, commandes):
    plateforme.ouvrir("steam://rungameid/1234")
    assert commandes == [["open", "steam://rungameid/1234"]]


def test_ouvrir_application_par_nom(mac, commandes):
    """Un nom qui n'est pas un chemin existant -> `open -a`."""
    plateforme.ouvrir("OBS")
    assert commandes == [["open", "-a", "OBS"]]


def test_ouvrir_bundle_existant(mac, commandes, tmp_path):
    bundle = tmp_path / "Jeu.app"
    bundle.mkdir()
    plateforme.ouvrir(str(bundle))
    assert commandes == [["open", str(bundle)]]


def test_ouvrir_refuse_une_cible_vide(mac):
    with pytest.raises(ValueError):
        plateforme.ouvrir("   ")


# ------------------------------------------------------------------ volume

def test_volume_definir_utilise_osascript(mac, commandes):
    assert plateforme.volume_definir(42) is True
    assert commandes == [["osascript", "-e", "set volume output volume 42"]]


def test_volume_definir_borne_entre_0_et_100(mac, commandes):
    plateforme.volume_definir(250)
    plateforme.volume_definir(-30)
    assert commandes[0][-1].endswith(" 100")
    assert commandes[1][-1].endswith(" 0")


def test_volume_ajuster_lit_puis_ecrit(mac, monkeypatch):
    """2 % par cran, comme sur Windows : 40 % + 10 crans = 60 %."""
    ecrits = []
    monkeypatch.setattr(plateforme, "volume_actuel", lambda: 40)
    monkeypatch.setattr(plateforme, "volume_definir",
                        lambda pct: ecrits.append(pct) or True)
    monkeypatch.setattr(plateforme, "volume_muet", lambda etat=None: False)
    assert plateforme.volume_ajuster("monter", 10) == 60
    assert ecrits == [60]


def test_volume_ajuster_ne_descend_pas_sous_zero(mac, monkeypatch):
    monkeypatch.setattr(plateforme, "volume_actuel", lambda: 5)
    monkeypatch.setattr(plateforme, "volume_definir", lambda pct: True)
    monkeypatch.setattr(plateforme, "volume_muet", lambda etat=None: False)
    assert plateforme.volume_ajuster("baisser", 20) == 0


# -------------------------------------------------------------------- voix

def test_parler_systeme_mac_lit_sur_stdin(mac, monkeypatch, popens):
    """Le texte ne doit JAMAIS passer en argument : une apostrophe le casserait."""
    monkeypatch.setattr(plateforme.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(plateforme, "_voix_francaise_mac", lambda: "Thomas")
    plateforme.parler_systeme("Il n'y a qu'à demander")
    assert popens == [["say", "-v", "Thomas", "-f", "-"]]


def test_parler_systeme_mac_sans_voix_francaise(mac, monkeypatch, popens):
    monkeypatch.setattr(plateforme.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(plateforme, "_voix_francaise_mac", lambda: "")
    plateforme.parler_systeme("Bonjour")
    assert popens == [["say", "-f", "-"]]


def test_parler_systeme_sans_moteur_renvoie_none(mac, monkeypatch):
    monkeypatch.setattr(plateforme.shutil, "which", lambda n: None)
    assert plateforme.parler_systeme("Bonjour") is None


def test_voix_francaise_mac_choisit_une_voix_fr(mac, monkeypatch):
    sortie = ("Alex                en_US    # Most people recognize me\n"
              "Amelie              fr_CA    # Bonjour, je m'appelle Amelie.\n"
              "Thomas              fr_FR    # Bonjour, je m'appelle Thomas.\n")
    monkeypatch.setattr(plateforme, "_VOIX_SYSTEME", None)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, sortie, ""))
    assert plateforme._voix_francaise_mac() == "Amelie"


def test_nom_voix_systeme_mac(mac, monkeypatch):
    monkeypatch.setattr(plateforme, "_voix_francaise_mac", lambda: "Thomas")
    assert plateforme.nom_voix_systeme() == "voix macOS (say · Thomas)"


# ---------------------------------------------------------------- extinction

def test_extinction_mac_est_une_minuterie_annulable(mac, monkeypatch):
    """macOS n'a pas de `shutdown -h +N` sans sudo : Jarvis tient la minuterie."""
    monkeypatch.setattr(plateforme, "_MINUTERIE_EXTINCTION", None)
    ok, detail = plateforme.programmer_extinction(30)
    assert ok and detail == ""
    assert plateforme._MINUTERIE_EXTINCTION is not None
    # Une deuxième demande ne doit pas empiler deux arrêts.
    assert plateforme.programmer_extinction(30) == (False, "deja_en_cours")
    assert plateforme.annuler_extinction() is True
    assert plateforme._MINUTERIE_EXTINCTION is None
    assert plateforme.annuler_extinction() is False


def test_extinction_mac_respecte_le_delai_minimum(mac, monkeypatch):
    monkeypatch.setattr(plateforme, "_MINUTERIE_EXTINCTION", None)
    try:
        plateforme.programmer_extinction(1)
        assert plateforme._MINUTERIE_EXTINCTION.interval == 5
    finally:
        plateforme.annuler_extinction()


# ------------------------------------------------------------------ clavier

def test_alt_tab_devient_cmd_tab(mac, commandes):
    """Sur Mac, la bascule de fenêtres est Cmd+Tab, pas Alt+Tab."""
    assert plateforme.envoyer_touches("alt+tab") is True
    script = commandes[0][-1]
    assert "key code 48" in script and "command down" in script
    assert "option down" not in script


def test_touche_simple_utilise_keystroke(mac, commandes):
    plateforme.envoyer_touches("l")             # YouTube : avance de 10 s
    assert 'keystroke "l"' in commandes[0][-1]


def test_touche_nommee_utilise_un_key_code(mac, commandes):
    plateforme.envoyer_touches("right")
    assert "key code 124" in commandes[0][-1]


def test_touche_inconnue_est_refusee(mac, commandes):
    assert plateforme.envoyer_touches("f13") is False
    assert commandes == []


# ------------------------------------------------------------------ chemins

def test_dossier_donnees_mac(mac):
    chemin = plateforme.dossier_donnees("ChromeJarvis")
    assert chemin.parts[-3:] == ("Library", "Application Support", "ChromeJarvis")


def test_racine_disque_mac(mac):
    assert plateforme.racine_disque() == "/"


def test_micro_defaut_mac_est_none(mac):
    """L'index 1 désigne souvent une SORTIE sur macOS : on laisse PortAudio choisir."""
    assert plateforme.micro_defaut() is None


def test_accelerateur_whisper_mac_est_cpu(mac):
    assert plateforme.accelerateur_whisper() == ("cpu", "int8")
