"""config.yaml : une lecture ratee ou un cache perime ne doivent jamais effacer les secrets.

Tout se passe dans un dossier temporaire : config.FICHIER est redirige avant le
moindre appel, le vrai config.yaml n'est ni lu ni ecrit.
"""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from core import config

CONTENU_VALIDE = (
    "# commentaire\n"
    "openai:\n"
    "  cle: cle-factice-openai\n"
    "elevenlabs:\n"
    "  cle: cle-factice-eleven\n"
    "assistant:\n"
    "  duree_suite: 8\n"
)
# Ligne mal indentee : le YAML entier devient illisible.
CONTENU_CASSE = CONTENU_VALIDE + " mode: hybride\n  satellites: [a, b\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.dossier = Path(self._dossier.name)
        self.sauve = (config.FICHIER, config._CONFIG, config._ERREUR_CHARGEMENT)
        config.FICHIER = self.dossier / "config.yaml"
        config._CONFIG = None
        config._ERREUR_CHARGEMENT = None

    def tearDown(self):
        config.FICHIER, config._CONFIG, config._ERREUR_CHARGEMENT = self.sauve
        self._dossier.cleanup()

    def ecrire(self, texte):
        config.FICHIER.write_bytes(texte.encode("utf-8"))
        return config.FICHIER.read_bytes()

    def lire(self):
        return yaml.safe_load(config.FICHIER.read_text(encoding="utf-8"))

    def temporaires(self):
        return [p.name for p in self.dossier.iterdir() if p.name != "config.yaml"]


class LectureIllisibleTest(_Base):
    def test_yaml_invalide_definir_refuse_et_fichier_intact(self):
        avant = self.ecrire(CONTENU_CASSE)
        with self.assertLogs("jarvis", "ERROR") as journal:
            self.assertIsNone(config.reglage("openai.cle"))
        self.assertIn("ligne", config._ERREUR_CHARGEMENT)
        # Le journal donne la position, jamais le contenu (qui peut contenir une cle).
        self.assertNotIn("factice", "\n".join(journal.output))
        with self.assertRaises(config.ConfigIllisible):
            config.definir("mode", "local")
        self.assertEqual(config.FICHIER.read_bytes(), avant)
        self.assertEqual(self.temporaires(), [])

    def test_fichier_verrouille_au_demarrage_definir_refuse(self):
        avant = self.ecrire(CONTENU_VALIDE)
        with patch.object(Path, "read_text", side_effect=PermissionError("verrou")), \
                self.assertLogs("jarvis", "ERROR"):
            self.assertEqual(config.reglage("openai.cle", "<defaut>"), "<defaut>")
            with self.assertRaises(config.ConfigIllisible):
                config.definir("securite.toujours", ["x"])
        self.assertEqual(config.FICHIER.read_bytes(), avant)

    def test_lecture_ratee_puis_fichier_redevenu_lisible_rien_n_est_perdu(self):
        self.ecrire(CONTENU_VALIDE)
        with patch.object(Path, "read_text", side_effect=PermissionError("verrou")), \
                self.assertLogs("jarvis", "ERROR"):
            config.reglage("openai.cle")
        self.assertEqual(config._CONFIG, {})
        config.definir("mode", "local")         # le cache est vide, le disque fait foi
        contenu = self.lire()
        self.assertEqual(contenu["openai"]["cle"], "cle-factice-openai")
        self.assertEqual(contenu["elevenlabs"]["cle"], "cle-factice-eleven")
        self.assertEqual(contenu["mode"], "local")

    def test_racine_non_dictionnaire_refusee(self):
        avant = self.ecrire("- a\n- b\n")
        with self.assertLogs("jarvis", "ERROR"):
            self.assertIsNone(config.reglage("a"))
        with self.assertRaises(config.ConfigIllisible):
            config.definir("mode", "local")
        self.assertEqual(config.FICHIER.read_bytes(), avant)

    def test_yaml_casse_pendant_que_jarvis_tourne(self):
        self.ecrire(CONTENU_VALIDE)
        self.assertEqual(config.reglage("openai.cle"), "cle-factice-openai")
        avant = self.ecrire(CONTENU_CASSE)
        with self.assertRaises(config.ConfigIllisible):
            config.definir("assistant.duree_suite", 12)
        self.assertEqual(config.FICHIER.read_bytes(), avant)
        self.assertEqual(config.reglage("assistant.duree_suite"), 8)


class EcritureTest(_Base):
    def test_cle_imbriquee_ajoutee_et_autres_cles_conservees(self):
        self.ecrire(CONTENU_VALIDE)
        config.definir("tts.voix.nom", "Adam")
        contenu = self.lire()
        self.assertEqual(contenu["tts"]["voix"]["nom"], "Adam")
        self.assertEqual(contenu["openai"]["cle"], "cle-factice-openai")
        self.assertEqual(contenu["assistant"]["duree_suite"], 8)
        self.assertEqual(config.reglage("tts.voix.nom"), "Adam")
        self.assertEqual(self.temporaires(), [])

    def test_cle_ajoutee_sur_disque_apres_le_chargement_conservee(self):
        self.ecrire(CONTENU_VALIDE)
        self.assertEqual(config.reglage("assistant.duree_suite"), 8)
        with open(config.FICHIER, "a", encoding="utf-8") as f:
            f.write("twilio:\n  sid: sid-factice\n")
        config.definir("assistant.duree_suite", 12)
        contenu = self.lire()
        self.assertEqual(contenu["twilio"]["sid"], "sid-factice")
        self.assertEqual(contenu["assistant"]["duree_suite"], 12)

    def test_fichier_absent_cree(self):
        config.definir("mode", "local")
        self.assertEqual(self.lire(), {"mode": "local"})
        self.assertEqual(config.reglage("mode"), "local")

    def test_echec_du_remplacement_laisse_l_original_intact(self):
        avant = self.ecrire(CONTENU_VALIDE)
        config.reglage("mode")
        with patch.object(config.os, "replace", side_effect=OSError("disque plein")):
            with self.assertRaises(OSError):
                config.definir("mode", "local")
        self.assertEqual(config.FICHIER.read_bytes(), avant)
        self.assertEqual(self.temporaires(), [])
        self.assertIsNone(config.reglage("mode"))       # rien d'enregistre, rien en memoire

    def test_valeur_non_serialisable_ne_touche_pas_le_fichier(self):
        avant = self.ecrire(CONTENU_VALIDE)
        with self.assertRaises(yaml.YAMLError):
            config.definir("x", object())
        self.assertEqual(config.FICHIER.read_bytes(), avant)
        self.assertEqual(self.temporaires(), [])

    def test_lecteur_windows_qui_bloque_un_instant(self):
        self.ecrire(CONTENU_VALIDE)
        vrai_replace = config.os.replace
        essais = []

        def replace(source, cible):
            essais.append(1)
            if len(essais) < 3:
                raise PermissionError("fichier ouvert ailleurs")
            return vrai_replace(source, cible)

        with patch.object(config.os, "replace", side_effect=replace), \
                patch.object(config.time, "sleep"):
            config.definir("mode", "qualite")
        self.assertEqual(len(essais), 3)
        self.assertEqual(self.lire()["mode"], "qualite")
        self.assertEqual(self.temporaires(), [])

    def test_dictionnaire_partage_par_l_agent_mis_a_jour_en_place(self):
        self.ecrire("audio:\n  sortie: 3\n")
        partage = {"audio": {"sortie": 3}}
        config._CONFIG = partage                # comme desktop_agent
        config.definir("audio.sortie", 5)
        self.assertIs(config._CONFIG, partage)
        self.assertEqual(partage["audio"]["sortie"], 5)
        self.assertEqual(self.lire(), {"audio": {"sortie": 5}})

    def test_ecritures_simultanees_toutes_conservees(self):
        self.ecrire(CONTENU_VALIDE)
        erreurs = []

        def ecrire(prefixe):
            try:
                for i in range(15):
                    config.definir(f"{prefixe}.n{i}", i)
            except Exception as e:      # pragma: no cover - remonte dans le test
                erreurs.append(e)

        fils = [threading.Thread(target=ecrire, args=(p,)) for p in ("panneau", "budget")]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        self.assertEqual(erreurs, [])
        contenu = self.lire()
        self.assertEqual(len(contenu["panneau"]), 15)
        self.assertEqual(len(contenu["budget"]), 15)
        self.assertEqual(contenu["openai"]["cle"], "cle-factice-openai")


if __name__ == "__main__":
    unittest.main()
