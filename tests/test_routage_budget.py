"""Bascule budget : la reprise « le lendemain » ne dépend plus d'une dépense cloud.

Tout est simulé en mémoire : ni budget.json, ni config.yaml, ni Hermes, ni voix.
"""
import unittest
from unittest.mock import patch

from core import routage


class NouveauJourTest(unittest.TestCase):
    def _patches(self, jour_change, mode="local", bascule=True, crons=("veille",),
                 depasse_mois=False):
        etat = {"bascule": bascule, "crons": list(crons)}
        return [
            patch("core.budget.jour_a_change", return_value=jour_change),
            patch("core.budget.reset_signaux"),
            patch("core.budget.etat", return_value={
                "depasse": depasse_mois, "depasse_jour": False,
                "depasse_mois": depasse_mois}),
            patch("core.budget.crons_suspendus", side_effect=lambda: list(etat["crons"])),
            patch("core.budget.memoriser_crons_suspendus",
                  side_effect=lambda noms: etat.__setitem__("crons", list(noms))),
            patch("core.budget.bascule_auto_active", side_effect=lambda: etat["bascule"]),
            patch("core.budget.effacer_bascule_auto",
                  side_effect=lambda: etat.__setitem__("bascule", False)),
            patch.object(routage, "mode_actuel", return_value=mode),
            patch.object(routage, "reglage", lambda cle, defaut=None: defaut),
        ], etat

    def _lancer(self, jour_change, **kw):
        patches, etat = self._patches(jour_change, **kw)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        with patch.object(routage, "definir_mode", return_value=True) as definir, \
                patch.object(routage, "reprendre_crons") as reprendre, \
                patch.object(routage, "_annoncer") as annoncer:
            routage.verifier_nouveau_jour()
        return definir, reprendre, annoncer, etat

    def test_lendemain_sans_depense_repasse_en_mode_normal(self):
        definir, reprendre, annoncer, etat = self._lancer(True)
        definir.assert_called_once()
        self.assertEqual(definir.call_args.args[0], "hybride")
        reprendre.assert_called_once_with(["veille"])
        self.assertEqual(etat["crons"], [])
        self.assertFalse(etat["bascule"])
        annoncer.assert_called_once()

    def test_meme_jour_ne_fait_rien(self):
        definir, reprendre, annoncer, _ = self._lancer(False)
        definir.assert_not_called()
        reprendre.assert_not_called()
        annoncer.assert_not_called()

    def test_local_choisi_par_l_utilisatrice_reste_local(self):
        definir, _, _, _ = self._lancer(True, bascule=False, crons=())
        definir.assert_not_called()

    def test_plafond_mensuel_depasse_reste_en_local(self):
        definir, reprendre, annoncer, etat = self._lancer(True, depasse_mois=True)
        definir.assert_not_called()
        reprendre.assert_not_called()
        annoncer.assert_not_called()
        self.assertEqual(etat["crons"], ["veille"])
        self.assertTrue(etat["bascule"])

    def test_ne_leve_jamais(self):
        with patch("core.budget.jour_a_change", side_effect=OSError("disque")):
            routage.verifier_nouveau_jour()       # aucune exception

    def test_appele_au_debut_de_chaque_tour(self):
        from pathlib import Path
        racine = Path(__file__).resolve().parents[1]
        for fichier in ("jarvis14.py", "core/satellite.py"):
            with self.subTest(fichier=fichier):
                source = (racine / fichier).read_text(encoding="utf-8")
                self.assertIn("verifier_nouveau_jour()", source)


_LISTE_CRONS = """
  a1 [active]
    Name:      veille
    Schedule:  0 8 * * *
  b2 \x1b[33m[paused]\x1b[0m
    Name:      revue perso
    Schedule:  0 9 * * *
  c3 [active]
    Name:      sauvegarde
    Schedule:  0 2 * * *
"""


class SuspensionCronsTest(unittest.TestCase):
    def _suspendre(self, sortie_pause="Paused job"):
        commandes = []

        def hermes(args, timeout=25):
            commandes.append(list(args))
            return _LISTE_CRONS if args == ["cron", "list"] else sortie_pause

        reglages = {"budget.crons_critiques": ["sauvegarde"]}
        with patch.object(routage, "_hermes", side_effect=hermes), \
                patch.object(routage, "reglage", lambda cle, defaut=None: reglages.get(cle, defaut)):
            suspendus = routage.suspendre_crons_non_critiques()
        return suspendus, commandes

    def test_cron_deja_en_pause_n_est_ni_suspendu_ni_memorise(self):
        suspendus, commandes = self._suspendre()
        self.assertEqual(suspendus, ["veille"])
        self.assertNotIn(["cron", "pause", "revue perso"], commandes)
        self.assertNotIn(["cron", "pause", "sauvegarde"], commandes)   # critique

    def test_pause_en_echec_non_memorisee(self):
        suspendus, _ = self._suspendre(sortie_pause="Failed to pause job: not found")
        self.assertEqual(suspendus, [])


if __name__ == "__main__":
    unittest.main()
