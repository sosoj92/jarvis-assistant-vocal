"""Calibration du wake word : meme choix de micro que le satellite.

Panne : avec « micro: ["Micro USB B"] » (forme recommandee, liste de noms par
ordre de preference), calibrer_wake.py passait la liste telle quelle a
sounddevice, qui levait une exception avant toute mesure. Avec deux noms,
sounddevice la lisait comme une paire entree/sortie et ne mesurait pas le micro
que le satellite ouvrirait. Aucun materiel : sounddevice et openWakeWord simules.
"""
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
_DOSSIER = str(ROOT / "satellite_pi")
# Comme sur le Pi (python calibrer_wake.py) : le dossier du script est dans sys.path.
sys.path.insert(0, _DOSSIER)
try:
    _spec = importlib.util.spec_from_file_location("calibrer_wake_test",
                                                   ROOT / "satellite_pi" / "calibrer_wake.py")
    calib = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(calib)
finally:
    sys.path.remove(_DOSSIER)
satellite = sys.modules[calib._resoudre_micro.__module__]

MME, WASAPI = 0, 1
APPAREILS = [
    {"name": "Mappeur de sons Microsoft - Input", "hostapi": MME, "max_input_channels": 2, "default_samplerate": 44100},
    {"name": "Microphone sur casque (Enceinte", "hostapi": MME, "max_input_channels": 1, "default_samplerate": 16000},
    {"name": "Microphone (Micro USB A)", "hostapi": MME, "max_input_channels": 1, "default_samplerate": 16000},
    {"name": "Micro USB B Virtual Output (Mar", "hostapi": MME, "max_input_channels": 2, "default_samplerate": 16000},
    {"name": "Micro USB B Virtual Output (Marque Micro USB B)", "hostapi": WASAPI, "max_input_channels": 2, "default_samplerate": 48000},
    {"name": "Haut-parleurs (Enceinte BT)", "hostapi": MME, "max_input_channels": 0, "default_samplerate": 44100},
]


class FluxFactice:
    def __init__(self, **options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        return np.zeros((n, 1), dtype=np.float32), False


class ModeleFactice:
    def __init__(self, **_options):
        pass

    def predict(self, _pcm):
        return {"hey_jarvis": 0.0}


def _faux_sd(flux_ouverts, infos_demandees):
    def query_devices(device=None, kind=None):
        if device is None and kind is None:
            return APPAREILS
        infos_demandees.append(device)
        if isinstance(device, (list, tuple)):
            raise ValueError(f"Only single values and pairs are allowed, not {device}")
        if device is None:
            return {"name": "defaut", "default_samplerate": 16000}
        return APPAREILS[device]

    def input_stream(**options):
        flux = FluxFactice(**options)
        flux_ouverts.append(flux)
        return flux

    return SimpleNamespace(query_devices=query_devices, default=SimpleNamespace(hostapi=MME),
                           InputStream=input_stream)


def _calibrer(micro, muets=()):
    """Lance calibrer_wake.main() avec un config.yaml temporaire ; renvoie le device ouvert."""
    flux_ouverts, infos_demandees = [], []
    faux = _faux_sd(flux_ouverts, infos_demandees)
    with tempfile.TemporaryDirectory() as dossier:
        conf = {} if micro is None else {"micro": micro}
        (Path(dossier) / "config.yaml").write_text(yaml.safe_dump(conf), encoding="utf-8")
        with patch.object(calib, "RACINE", Path(dossier)), \
                patch.object(calib, "sd", faux), \
                patch.object(calib, "Model", ModeleFactice), \
                patch.object(satellite, "sd", faux), \
                patch.object(satellite, "_silence_numerique", side_effect=lambda i: i in muets), \
                patch.object(sys, "argv", ["calibrer_wake.py", "--secondes", "0.16", "--gains", "1"]), \
                contextlib.redirect_stdout(io.StringIO()) as journal:
            calib.main()
    assert len(flux_ouverts) == 1, flux_ouverts
    return flux_ouverts[0].options["device"], infos_demandees, journal.getvalue()


class CalibrationMicroTest(unittest.TestCase):
    def test_liste_d_un_seul_nom(self):
        device, infos, journal = _calibrer(["Micro USB B"])
        self.assertEqual(device, 3)                     # entree MME, comme le satellite
        self.assertEqual(infos, [3])
        self.assertIn("RESULTAT gain=1", journal)

    def test_deux_noms_premier_muet_le_second_est_mesure(self):
        device, _, _ = _calibrer(["Micro USB B", "Micro USB A"], muets={3})
        self.assertEqual(device, 2)

    def test_nom_seul_et_index_inchanges(self):
        self.assertEqual(_calibrer("Micro USB B")[0], 3)
        self.assertEqual(_calibrer(2)[0], 2)

    def test_sans_micro_configure_micro_par_defaut(self):
        device, infos, _ = _calibrer(None)
        self.assertIsNone(device)
        self.assertEqual(infos, [None])


if __name__ == "__main__":
    unittest.main()
