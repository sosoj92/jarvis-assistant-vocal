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
