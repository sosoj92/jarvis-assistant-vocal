"""Tests sans réseau du téléchargement du modèle de gestes (scripts/setup_gestes.py)."""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "setup_gestes.py"
_spec = importlib.util.spec_from_file_location("setup_gestes_teste", _SCRIPT)
setup_gestes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_gestes)

TAILLE = 2_000_000


class _FausseReponse:
    """Réponse HTTP simulée, éventuellement coupée après `coupure` octets."""

    def __init__(self, total=TAILLE, coupure=None, annonce=None):
        self.headers = {"Content-Length": str(annonce or total)}
        self.total = total
        self.coupure = coupure
        self.lus = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        if self.coupure is not None and self.lus >= self.coupure:
            raise ConnectionResetError("coupure simulée")
        taille = min(n, self.total - self.lus)
        self.lus += taille
        return b"\0" * taille


class TelechargementModeleTests(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        racine = Path(self._dossier.name)
        self.modele = racine / "gestes" / "models" / "hand_landmarker.task"
        for nom, valeur in (("RACINE", racine), ("MODELE", self.modele),
                            ("PY", racine / "python.exe"), ("_run", MagicMock())):
            correctif = patch.object(setup_gestes, nom, valeur)
            correctif.start()
            self.addCleanup(correctif.stop)
        self.addCleanup(self._dossier.cleanup)

    def _lancer(self, *reponses, argv=()):
        with (patch("urllib.request.urlopen", side_effect=list(reponses)) as ouvrir,
              contextlib.redirect_stdout(io.StringIO())):
            code = setup_gestes.main(list(argv))
        return code, ouvrir

    def _part(self):
        return self.modele.with_name(self.modele.name + ".part")

    def test_coupure_ne_laisse_aucun_modele_tronque_et_la_relance_retente(self):
        code, _ = self._lancer(_FausseReponse(coupure=64 * 1024))
        self.assertEqual(code, 1)
        self.assertFalse(self.modele.exists())
        self.assertFalse(self._part().exists())

        code, ouvrir = self._lancer(_FausseReponse())
        self.assertEqual(code, 0)
        ouvrir.assert_called_once()
        self.assertEqual(self.modele.stat().st_size, TAILLE)
        self.assertFalse(self._part().exists())

    def test_reponse_plus_courte_que_annoncee_est_refusee(self):
        code, _ = self._lancer(_FausseReponse(total=TAILLE, annonce=TAILLE + 10))
        self.assertEqual(code, 1)
        self.assertFalse(self.modele.exists())
        self.assertFalse(self._part().exists())

    def test_modele_tronque_existant_est_retelecharge(self):
        self.modele.parent.mkdir(parents=True)
        self.modele.write_bytes(b"\0" * 65536)
        code, ouvrir = self._lancer(_FausseReponse())
        self.assertEqual(code, 0)
        ouvrir.assert_called_once()
        self.assertEqual(self.modele.stat().st_size, TAILLE)

    def test_modele_complet_n_est_retelecharge_qu_avec_force(self):
        self.modele.parent.mkdir(parents=True)
        self.modele.write_bytes(b"\0" * TAILLE)
        code, ouvrir = self._lancer()
        self.assertEqual(code, 0)
        ouvrir.assert_not_called()

        code, ouvrir = self._lancer(_FausseReponse(total=TAILLE + 1),
                                    argv=["--force"])
        self.assertEqual(code, 0)
        ouvrir.assert_called_once()
        self.assertEqual(self.modele.stat().st_size, TAILLE + 1)


_SCRIPT_REGARD = _SCRIPT.parent / "setup_regard.py"
_spec_regard = importlib.util.spec_from_file_location("setup_regard_teste", _SCRIPT_REGARD)
setup_regard = importlib.util.module_from_spec(_spec_regard)
_spec_regard.loader.exec_module(setup_regard)


class SetupRegardTest(unittest.TestCase):
    """Même téléchargement atomique pour le modèle du regard (sans réseau)."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.modele = Path(dossier.name) / "models" / "face_landmarker.task"

    def _lancer(self, reponse=None, argv=()):
        ouvrir = MagicMock(return_value=reponse or _FausseReponse())
        with patch.object(setup_regard, "MODELE", self.modele), \
                patch("urllib.request.urlopen", ouvrir), \
                contextlib.redirect_stdout(io.StringIO()):
            code = setup_regard.main(list(argv))
        return code, ouvrir

    def test_telechargement_atomique(self):
        code, ouvrir = self._lancer()
        self.assertEqual(code, 0)
        ouvrir.assert_called_once()
        self.assertEqual(self.modele.stat().st_size, TAILLE)

    def test_coupure_code_1_sans_modele_tronque(self):
        code, _ = self._lancer(_FausseReponse(coupure=100_000))
        self.assertEqual(code, 1)
        self.assertFalse(self.modele.exists())

    def test_present_n_est_retelecharge_qu_avec_force(self):
        self.modele.parent.mkdir(parents=True)
        self.modele.write_bytes(b"\0" * TAILLE)
        code, ouvrir = self._lancer()
        self.assertEqual(code, 0)
        ouvrir.assert_not_called()
        code, ouvrir = self._lancer(argv=["--force"])
        self.assertEqual(code, 0)
        ouvrir.assert_called_once()


if __name__ == "__main__":
    unittest.main()
