"""Boucle de détection de présence, sans ping réel ni lumière Hue."""
import unittest
from unittest import mock

from tools import presence


class _Arret(BaseException):
    """Sort de la boucle infinie au dernier time.sleep."""


REGLAGES = {
    "presence.ip": "192.0.2.1",          # plage TEST-NET, jamais pinguée ici
    "presence.intervalle": 60,
    "presence.seuil_absence": 600,
    "presence.mode_absence": "off",
    "presence.mode_retour": "retour",
}


def _pings(cycles):
    """Un tour joignable consomme un ping, un tour raté en consomme deux."""
    sortie = []
    for present in cycles:
        sortie.extend([True] if present else [False, False])
    return sortie


class BouclePresenceTests(unittest.TestCase):
    def setUp(self):
        etat_initial = {"actif": True, "present": None, "absent_depuis": None}
        presence._ETAT.update(etat_initial)
        self.addCleanup(presence._ETAT.update, dict(etat_initial))

    def _tourner(self, cycles, pings=None, reglages=None, activer=None):
        valeurs = dict(REGLAGES, **(reglages or {}))
        horloge = mock.Mock()
        horloge.time.side_effect = [60.0 * i for i in range(1, len(cycles) + 1)]
        horloge.sleep.side_effect = [None] * (len(cycles) - 1) + [_Arret()]
        if activer is None:
            activer = mock.Mock(side_effect=lambda mode: f"Mode {mode} active.")
        with mock.patch("tools.presence.reglage",
                        side_effect=lambda cle, defaut=None: valeurs.get(cle, defaut)), \
                mock.patch("tools.presence._joignable",
                           side_effect=pings if pings is not None else _pings(cycles)), \
                mock.patch("tools.presence.time", horloge), \
                mock.patch("tools.presence.LOG") as journal, \
                mock.patch("tools.modes.activer", activer):
            with self.assertRaises(_Arret):
                presence._boucle()
        self.assertEqual(horloge.sleep.call_count, len(cycles))
        return activer, journal

    def test_un_ping_manque_ne_rallume_rien(self):
        activer, _ = self._tourner([True, False, True])
        activer.assert_not_called()

    def test_absence_sous_le_seuil_ne_rallume_rien(self):
        activer, _ = self._tourner([True] + [False] * 5 + [True])
        activer.assert_not_called()

    def test_vraie_absence_puis_retour(self):
        activer, _ = self._tourner([True] + [False] * 12 + [True])
        self.assertEqual(activer.call_args_list, [mock.call("off"), mock.call("retour")])

    def test_sans_mode_retour_seul_off_est_applique(self):
        activer, _ = self._tourner([True] + [False] * 12 + [True],
                                   reglages={"presence.mode_retour": ""})
        activer.assert_called_once_with("off")

    def test_mode_qui_leve_ne_tue_pas_la_boucle(self):
        activer = mock.Mock(side_effect=RuntimeError("mode mal forme"))
        activer, journal = self._tourner([True] + [False] * 15, activer=activer)
        activer.assert_called_once_with("off")       # pas relancé toutes les minutes
        journal.exception.assert_called_once()
        self.assertIs(presence._ETAT["present"], False)

    def test_mode_mal_forme_dans_la_config_ne_tue_pas_la_boucle(self):
        # Vrai tools.modes.activer avec « modes.off: ['toutes'] » (étape non dict).
        with mock.patch("tools.modes.reglage",
                        side_effect=lambda cle, defaut=None:
                        {"off": ["toutes"]} if cle == "modes" else defaut), \
                mock.patch("tools.lumieres._hue_requete",
                           side_effect=AssertionError("aucun appel Hue en test")):
            from tools import modes
            _, journal = self._tourner([True] + [False] * 12, activer=modes.activer)
        journal.exception.assert_called_once()

    def test_erreur_imprevue_dans_un_tour_ne_tue_pas_la_boucle(self):
        _, journal = self._tourner(
            [True, True, True], pings=[True, RuntimeError("ping"), True])
        journal.exception.assert_called_once_with("presence: iteration")

    def test_echec_hue_est_journalise(self):
        activer = mock.Mock(return_value="Mode off non applique — Hue injoignable : x")
        _, journal = self._tourner([True] + [False] * 12, activer=activer)
        journal.warning.assert_called_once()
        self.assertIn("Hue injoignable", journal.warning.call_args.args[-1])


if __name__ == "__main__":
    unittest.main()
