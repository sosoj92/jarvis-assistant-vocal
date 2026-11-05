"""Installe l'environnement ISOLÉ du tracker de gestes (Python 3.11 + MediaPipe).

    python scripts/setup_gestes.py            # --force : retélécharge le modèle

MediaPipe n'a pas de wheel Python 3.13 → le tracking tourne dans un venv 3.11 séparé
(c'est aussi la frontière vie privée : aucune image ne sort de ce process). Ce script
crée gestes/.venv-tracker, y installe mediapipe/opencv/requests, et télécharge le
modèle hand_landmarker.task. Voir docs/gestes.md.
"""
import argparse
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
VENV = RACINE / "gestes" / ".venv-tracker"
PY = VENV / "Scripts" / "python.exe"
MODELE = RACINE / "gestes" / "models" / "hand_landmarker.task"
URL_MODELE = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
              "hand_landmarker/float16/1/hand_landmarker.task")
# Le vrai modèle pèse ~8 Mo : en dessous d'1 Mo, c'est un fichier tronqué.
TAILLE_MIN_MODELE = 1_000_000


def _run(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def _modele_present(cible, taille_min=TAILLE_MIN_MODELE):
    """Vrai si le modèle existe ET n'est pas un reste de téléchargement coupé."""
    try:
        return cible.is_file() and cible.stat().st_size >= taille_min
    except OSError:
        return False


def _telecharger(url, cible, taille_min=TAILLE_MIN_MODELE, timeout=60):
    """Téléchargement atomique : fichier .part, contrôle de taille, puis os.replace.

    Une coupure réseau ne laisse jamais de modèle tronqué sous le nom final :
    la relance suivante retente donc le téléchargement.
    """
    partiel = cible.with_name(cible.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as reponse:
            attendu = reponse.headers.get("Content-Length")
            lus = 0
            with open(partiel, "wb") as sortie:
                while True:
                    bloc = reponse.read(64 * 1024)
                    if not bloc:
                        break
                    sortie.write(bloc)
                    lus += len(bloc)
        if attendu is not None and lus != int(attendu):
            raise OSError(f"téléchargement incomplet ({lus}/{attendu} octets)")
        if lus < taille_min:
            raise OSError(f"fichier trop petit ({lus} octets)")
        os.replace(partiel, cible)
    except BaseException:
        try:
            partiel.unlink()
        except OSError:
            pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Installe l'environnement isolé du tracker de gestes.")
    parser.add_argument("--force", action="store_true",
                        help="retélécharge le modèle même s'il est déjà présent")
    args = parser.parse_args(argv)

    (RACINE / "gestes" / "models").mkdir(parents=True, exist_ok=True)
    try:
        if not PY.exists():
            print("== Création du venv isolé (Python 3.11) ==")
            _run(["uv", "venv", "--python", "3.11", str(VENV)])
        print("== Installation mediapipe + opencv + requests ==")
        _run(["uv", "pip", "install", "--python", str(PY),
              "mediapipe", "opencv-python", "requests"])
    except FileNotFoundError:
        print("ERREUR : 'uv' introuvable. Installe uv (https://docs.astral.sh/uv/) puis relance.")
        return 1
    except subprocess.CalledProcessError as e:
        print(f"ERREUR d'installation ({e}).")
        return 1

    if args.force or not _modele_present(MODELE):
        print("== Téléchargement du modèle hand_landmarker.task (~8 Mo) ==")
        try:
            _telecharger(URL_MODELE, MODELE)
        except Exception as e:
            print(f"ERREUR de téléchargement du modèle ({e}). Vérifie la connexion "
                  "puis relance ce script.")
            return 1

    _run([str(PY), "-c",
          "import mediapipe, cv2; print('OK — mediapipe', mediapipe.__version__, '| opencv', cv2.__version__)"])
    print("\n✅ Environnement gestes prêt.")
    print('   Active : « Jarvis, active les gestes »  (ou config gestes.actif: true)')
    print("   Calibration (à l'arrivée de la webcam) : python scripts/gestes_calibrer.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
