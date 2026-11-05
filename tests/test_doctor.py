"""Diagnostic (scripts/doctor.py) : micro par defaut et cles d'exemple.

sounddevice est remplace par un faux module aux memes regles (query_devices(None)
renvoie la LISTE, un tuple) : aucun acces au materiel.
"""
import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import core.config

ROOT = Path(__file__).resolve().parents[1]


def _charger_doctor():
    spec = importlib.util.spec_from_file_location("jarvis_doctor_test",
                                                  ROOT / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DeviceList(tuple):
    """Comme sounddevice.DeviceList : un tuple, donc liste["name"] -> TypeError."""


class _FauxSounddevice:
    def __init__(self, defaut="Micro USB"):
        self.defaut = defaut
        self.peripheriques = _DeviceList([
            {"name": "Haut-parleurs", "max_input_channels": 0},
            {"name": "Mix stereo (virtuel)", "max_input_channels": 2},
            {"name": "Micro USB", "max_input_channels": 1},
        ])

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return self.peripheriques
        if kind == "input":
            if self.defaut is None:
                raise Exception("Error querying device -1")
            return {"name": self.defaut, "max_input_channels": 1}
        return self.peripheriques[device]   # IndexError si hors limites


class MicroTest(unittest.TestCase):
    def _diagnostic(self, valeurs, sd=None):
        doctor = _charger_doctor()
        sortie = io.StringIO()
        with mock.patch.dict("sys.modules", {"sounddevice": sd or _FauxSounddevice()}), \
                mock.patch.object(doctor, "reglage",
                                  side_effect=lambda chemin, defaut=None:
                                  valeurs.get(chemin, defaut)), \
                redirect_stdout(sortie):
            doctor.v_micro()
        return sortie.getvalue(), doctor._scores

    def test_micro_null_de_l_exemple_sans_faux_avertissement(self):
        texte, scores = self._diagnostic({"audio.micro": None})
        self.assertNotIn("semble invalide", texte)
        self.assertIn("micro par defaut = Micro USB", texte)
        self.assertEqual(scores["warn"], 0)

    def test_cle_absente_meme_defaut_que_jarvis(self):
        texte, _ = self._diagnostic({})
        self.assertIn("micro par defaut", texte)
        self.assertNotIn("index 1", texte)

    def test_index_valide_affiche_son_nom(self):
        texte, scores = self._diagnostic({"audio.micro": 2})
        self.assertIn("index 2 = Micro USB", texte)
        self.assertEqual(scores["warn"], 0)

    def test_index_hors_limites_signale(self):
        texte, scores = self._diagnostic({"audio.micro": 9})
        self.assertIn("semble invalide", texte)
        self.assertEqual(scores["warn"], 1)

    def test_aucun_micro_par_defaut_signale(self):
        texte, scores = self._diagnostic({"audio.micro": None}, _FauxSounddevice(None))
        self.assertIn("aucun micro par defaut", texte)
        self.assertEqual(scores["warn"], 1)


class CleExempleTest(unittest.TestCase):
    def test_cle_d_exemple_n_est_pas_presente(self):
        doctor = _charger_doctor()
        conf = {"mode": "hybride", "cloud": {"fournisseur": "openai"},
                "openai": {"cle": "sk-proj-..."}}
        sortie = io.StringIO()
        with mock.patch.object(core.config, "_CONFIG", conf), redirect_stdout(sortie):
            doctor.v_llm()
        self.assertIn("valeur d'exemple", sortie.getvalue())
        self.assertNotIn("presente", sortie.getvalue())
        self.assertEqual(doctor._scores["ko"], 1)


if __name__ == "__main__":
    unittest.main()
