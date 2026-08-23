"""Lisibilite des dates d'agenda : le bug « lundi 3 » un 23 aout.

Demander « cette semaine » rendait des jours qui semblaient hors periode. La
periode etait pourtant juste : c'est l'AFFICHAGE qui trompait. Un evenement de
plusieurs jours affiche sa date de DEBUT, donc des vacances commencees le 3 aout
apparaissaient en « lundi 3 » au milieu d'une semaine du 17 au 24.
"""
import datetime as dt

import pytest

from tools import agenda


def _local(annee, mois, jour, heure=0):
    return dt.datetime(annee, mois, jour, heure).astimezone()


@pytest.fixture
def le_23_aout(monkeypatch):
    """Fige « maintenant » au dimanche 23 aout 2026, 21h — le cas rapporte."""
    fige = _local(2026, 8, 23, 21)

    class _FauxDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fige if tz is None else fige.astimezone(tz)

    monkeypatch.setattr(agenda.dt, "datetime", _FauxDatetime)
    return fige


def test_cette_semaine_part_bien_du_lundi(le_23_aout):
    """23 aout 2026 est un dimanche : la semaine va du lundi 17 au lundi 24."""
    debut, fin, libelle = agenda._periode("cette semaine")
    assert (debut.day, debut.month) == (17, 8)
    assert (fin.day, fin.month) == (24, 8)
    assert libelle == "cette semaine"


def test_semaine_prochaine_ne_recouvre_pas_cette_semaine(le_23_aout):
    debut, fin, _ = agenda._periode("la semaine prochaine")
    assert (debut.day, debut.month) == (24, 8)
    assert (fin.day, fin.month) == (31, 8)


def test_jour_proche_reste_court(le_23_aout):
    """Dans la semaine, « mardi 18 » suffit — inutile d'alourdir."""
    assert agenda._jour_fr(_local(2026, 8, 18)) == "mardi 18"


def test_jour_lointain_precise_le_mois(le_23_aout):
    """C'est le cas qui trompait : « lundi 3 » devient « lundi 3 aout »."""
    assert agenda._jour_fr(_local(2026, 8, 3)) == "lundi 3 aout"


def test_hors_fenetre_precise_le_mois_meme_si_proche(le_23_aout):
    """Un evenement commence avant la periode interrogee doit etre date."""
    fenetre = (_local(2026, 8, 17), _local(2026, 8, 24))
    assert agenda._jour_fr(_local(2026, 8, 20), fenetre) == "jeudi 20"
    assert agenda._jour_fr(_local(2026, 8, 14), fenetre) == "vendredi 14 aout"


def test_aujourd_hui_demain_hier(le_23_aout):
    assert agenda._jour_fr(_local(2026, 8, 23)) == "aujourd'hui"
    assert agenda._jour_fr(_local(2026, 8, 24)) == "demain"
    assert agenda._jour_fr(_local(2026, 8, 22)) == "hier"


def test_evenement_deja_commence_est_signale(le_23_aout):
    """Sans cette mention, un evenement en cours passe pour une erreur."""
    fenetre = (_local(2026, 8, 17), _local(2026, 8, 24))
    evenements = [
        (_local(2026, 8, 3), True, "Vacances Nathan", "perso"),
        (_local(2026, 8, 18, 11), False, "Materiel a recuperer", "perso"),
    ]
    texte = agenda._formuler(evenements, "cette semaine", fenetre=fenetre)
    assert "deja en cours" in texte
    assert "lundi 3 aout" in texte, "le mois manque : c'est ce qui trompait"
    assert "mardi 18" in texte


def test_evenement_dans_la_fenetre_non_marque(le_23_aout):
    fenetre = (_local(2026, 8, 17), _local(2026, 8, 24))
    texte = agenda._formuler(
        [(_local(2026, 8, 18, 11), False, "Materiel", "perso")],
        "cette semaine", fenetre=fenetre)
    assert "deja en cours" not in texte
