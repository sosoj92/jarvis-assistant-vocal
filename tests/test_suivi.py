"""Suivi de contenus : un contenus.yaml mal edite n'est jamais ecrase, et le
rapprochement des titres se fait sur des mots entiers.

Tout se passe dans un dossier temporaire ; tools.notes est remplace par un stub.
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from tools import suivi

_VALIDE = """\
- titre: Video A
  statut: script
  plateforme: instagram
  deadline: '2026-11-10'
  notes: ''
- titre: Video B
  statut: montage
"""
# Edition manuelle typique : « : » non protege dans une note.
_INVALIDE = _VALIDE.replace("notes: ''", "notes: pourquoi: oui")


class _Base(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.dossier = Path(dossier.name)
        self.fichier = self.dossier / "contenus.yaml"
        p = patch.object(suivi, "_fichier", return_value=self.fichier)
        p.start()
        self.addCleanup(p.stop)
        self.ajouter_note = MagicMock()
        notes = types.ModuleType("tools.notes")
        notes.ajouter_note = self.ajouter_note
        p = patch.dict(sys.modules, {"tools.notes": notes})
        p.start()
        self.addCleanup(p.stop)

    def ecrire(self, texte):
        self.fichier.write_text(texte, encoding="utf-8")

    def lire(self):
        return self.fichier.read_text(encoding="utf-8")


class FichierIllisibleTests(_Base):
    def test_nouvelle_idee_n_ecrase_pas_un_yaml_invalide(self):
        self.ecrire(_INVALIDE)
        with self.assertLogs("jarvis", level="WARNING"):
            reponse = suivi.nouvelle_idee_video("Video C")
        self.assertEqual(self.lire(), _INVALIDE)
        self.assertIn("illisible", reponse)
        self.assertIn("ligne 5", reponse)
        self.ajouter_note.assert_not_called()

    def test_document_qui_n_est_pas_une_liste_n_est_pas_ecrase(self):
        texte = "Video A:\n  statut: script\n"
        self.ecrire(texte)
        reponse = suivi.nouvelle_idee_video("Video C")
        self.assertEqual(self.lire(), texte)
        self.assertIn("pas une liste", reponse)

    def test_changer_statut_sur_fichier_invalide_n_ecrit_rien(self):
        self.ecrire(_INVALIDE)
        with self.assertLogs("jarvis", level="WARNING"):
            reponse = suivi.changer_statut_contenu("Video A", "tournage")
        self.assertEqual(self.lire(), _INVALIDE)
        self.assertIn("illisible", reponse)

    def test_cas_nominal_ajoute_l_idee(self):
        self.ecrire(_VALIDE)
        reponse = suivi.nouvelle_idee_video("Video C", plateforme="tiktok")
        self.assertIn("Nouvelle idee ajoutee", reponse)
        contenus = yaml.safe_load(self.lire())
        self.assertEqual([c["titre"] for c in contenus], ["Video A", "Video B", "Video C"])
        self.assertEqual(contenus[2]["statut"], "idee")
        self.ajouter_note.assert_called_once()
        self.assertEqual(sorted(p.name for p in self.dossier.iterdir()), ["contenus.yaml"])

    def test_fichier_absent_demarre_un_suivi(self):
        reponse = suivi.nouvelle_idee_video("Premiere idee")
        self.assertIn("Nouvelle idee ajoutee", reponse)
        self.assertEqual(yaml.safe_load(self.lire())[0]["titre"], "Premiere idee")

    def test_sauvegarde_interrompue_laisse_l_ancien_fichier_intact(self):
        self.ecrire(_VALIDE)
        with patch.object(suivi.yaml, "safe_dump", side_effect=RuntimeError("disque plein")):
            with self.assertRaises(RuntimeError):
                suivi._sauver([{"titre": "X"}])
        self.assertEqual(self.lire(), _VALIDE)
        self.assertEqual(sorted(p.name for p in self.dossier.iterdir()), ["contenus.yaml"])


class RapprochementTitresTests(_Base):
    def test_inclusion_sur_mots_entiers(self):
        contenus = [{"titre": "IA"}]
        self.assertIsNone(suivi._trouver(contenus, "Les médias sociaux"))
        self.assertEqual(suivi._trouver(contenus, "ia"), 0)
        recettes = [{"titre": "Recette pâtes"}, {"titre": "Recette pâtes carbonara"}]
        self.assertEqual(suivi._trouver(recettes, "carbonara"), 1)
        self.assertEqual(suivi._trouver([{"titre": "Mon vlog de Paris"}], "le vlog Paris"), 0)
        self.assertIsNone(suivi._trouver([{"titre": "Vie familiale"}], "ami"))
        # Les titres d'une serie restent distincts.
        self.assertIsNone(suivi._trouver([{"titre": "Video A"}], "Video C"))
        self.assertIsNone(suivi._trouver([{"titre": "Episode 1"}], "Episode 2"))

    def test_nouvelle_idee_proche_d_un_titre_court_est_acceptee(self):
        self.ecrire("- titre: IA\n  statut: idee\n")
        reponse = suivi.nouvelle_idee_video("les médias sociaux")
        self.assertIn("Nouvelle idee ajoutee", reponse)
        self.assertEqual(len(yaml.safe_load(self.lire())), 2)

    def test_changer_statut_ne_modifie_pas_la_mauvaise_video(self):
        self.ecrire("- titre: IA\n  statut: idee\n")
        reponse = suivi.changer_statut_contenu("les médias sociaux", "montage")
        self.assertIn("Je ne trouve pas", reponse)
        self.assertEqual(yaml.safe_load(self.lire())[0]["statut"], "idee")


if __name__ == "__main__":
    unittest.main()
