"""Ouverture du micro : echouer clairement plutot que par une trace PortAudio.

Sans peripherique d'entree, PortAudio leve « Error querying device -1 » — une
trace de 20 lignes pour dire « pas de micro ». Sur un Mac mini (aucun micro
integre) ou quand l'autorisation Microphone manque, c'est le cas nominal, pas
un bug : il doit se lire en une phrase.
"""
import pytest

jarvis14 = pytest.importorskip("jarvis14")


def test_aucune_entree_sort_proprement(monkeypatch, capsys):
    monkeypatch.setattr(jarvis14, "_entrees_audio", lambda: [])
    with pytest.raises(SystemExit) as sortie:
        jarvis14._ouvrir_micro()
    assert sortie.value.code == 1
    texte = capsys.readouterr().out
    assert "Aucun peripherique d'ENTREE audio" in texte
    assert "Traceback" not in texte


def test_message_mac_cite_permission_et_mac_mini(monkeypatch, capsys):
    """Les deux causes reelles sur Mac doivent etre nommees, pas devinees."""
    monkeypatch.setattr(jarvis14, "_entrees_audio", lambda: [])
    monkeypatch.setattr(jarvis14.plateforme, "EST_MAC", True)
    with pytest.raises(SystemExit):
        jarvis14._ouvrir_micro()
    texte = capsys.readouterr().out
    assert "Microphone" in texte           # autorisation macOS
    assert "Mac mini" in texte             # pas de micro integre


def test_index_invalide_liste_les_entrees(monkeypatch, capsys):
    """Mauvais audio.micro : on montre les index valides au lieu de planter."""
    monkeypatch.setattr(jarvis14, "_entrees_audio",
                        lambda: [(0, "Micro USB"), (3, "AirPods")])
    monkeypatch.setattr(jarvis14.sd, "InputStream",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("device 99")))
    monkeypatch.setattr(jarvis14, "MICRO", 99)
    with pytest.raises(SystemExit):
        jarvis14._ouvrir_micro()
    texte = capsys.readouterr().out
    assert "Micro USB" in texte and "AirPods" in texte
    assert "audio.micro" in texte


def test_entrees_audio_ne_leve_jamais(monkeypatch):
    """Si PortAudio explose, on veut une liste vide, pas une exception."""
    def explose():
        raise OSError("PortAudio library not found")
    monkeypatch.setattr(jarvis14.sd, "query_devices", explose)
    assert jarvis14._entrees_audio() == []


# ------------------------------------------- couper la parole (« stop »)

def test_seuil_assez_court_pour_un_mot_bref():
    """« stop » dure ~250 ms : exiger 400 ms de parole continue le rendait
    mathematiquement indetectable. C'etait le bug."""
    duree_bloc_ms = jarvis14.BLOC / jarvis14.TAUX * 1000
    requis_ms = jarvis14.BLOCS_AVANT_VERIF * duree_bloc_ms
    assert requis_ms <= 250, (
        f"{requis_ms:.0f} ms exiges : trop long pour un « stop » sec")


def test_tolerance_aux_micro_coupures():
    """La plosive de « stop » cree un creux qui remettait le compteur a zero."""
    assert jarvis14.BLOCS_CREUX_TOLERES >= 1


def test_mots_d_arret_reconnus():
    for mot in ("stop", "attends", "arrete", "pardon"):
        assert jarvis14.type_arret(mot) == "relance", mot
    for mot in ("tais-toi", "chut", "c'est bon"):
        assert jarvis14.type_arret(mot) == "fin", mot
    assert jarvis14.type_arret("allume la lumiere") is None


# ------------------------------------------------- ancrage temporel du prompt

def test_le_prompt_donne_la_date():
    """Sans date, le modele interprete « cette semaine » au hasard."""
    texte = jarvis14._ancrage_temporel()
    import datetime as _dt
    d = _dt.datetime.now().astimezone()
    assert str(d.year) in texte and str(d.day) in texte
    assert "cette semaine" in texte


def test_la_date_est_recalculee_a_chaque_appel(monkeypatch):
    """Jarvis tourne des jours d'affilee : une date figee serait pire que rien."""
    import datetime as _dt
    vus = []

    class _Faux(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            vus.append(1)
            return _dt.datetime(2026, 8, 23, 21).astimezone()

    monkeypatch.setattr(jarvis14.dt, "datetime", _Faux)
    jarvis14._ancrage_temporel()
    jarvis14._ancrage_temporel()
    assert len(vus) == 2, "la date n'est pas recalculee"


def test_systeme_courant_contient_la_date():
    assert "Date et heure actuelles" in jarvis14.systeme_courant()
