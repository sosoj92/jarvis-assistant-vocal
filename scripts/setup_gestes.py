"""Installe l'environnement ISOLÉ du tracker de gestes (Python 3.11 + MediaPipe).

    python scripts/setup_gestes.py

MediaPipe n'a pas de wheel Python 3.13 → le tracking tourne dans un venv 3.11 séparé
(c'est aussi la frontière vie privée : aucune image ne sort de ce process). Ce script
crée gestes/.venv-tracker, y installe mediapipe/opencv/requests, et télécharge le
modèle hand_landmarker.task. Voir docs/gestes.md.
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
VENV = RACINE / "gestes" / ".venv-tracker"
PY = VENV / ("Scripts" if sys.platform == "win32" else "bin") / \
     ("python.exe" if sys.platform == "win32" else "python")
MODELE = RACINE / "gestes" / "models" / "hand_landmarker.task"
URL_MODELE = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
              "hand_landmarker/float16/1/hand_landmarker.task")


def _run(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main():
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

    if not MODELE.exists():
        print("== Téléchargement du modèle hand_landmarker.task (~8 Mo) ==")
        urllib.request.urlretrieve(URL_MODELE, MODELE)

    _run([str(PY), "-c",
          "import mediapipe, cv2; print('OK — mediapipe', mediapipe.__version__, '| opencv', cv2.__version__)"])
    print("\n✅ Environnement gestes prêt.")
    print('   Active : « Jarvis, active les gestes »  (ou config gestes.actif: true)')
    print("   Calibration (à l'arrivée de la webcam) : python scripts/gestes_calibrer.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
