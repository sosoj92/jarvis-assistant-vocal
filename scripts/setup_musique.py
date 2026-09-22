"""Installe l'environnement ISOLÉ de la reconnaissance musicale (Python 3.12 + shazamio).

    python scripts/setup_musique.py

shazamio-core (moteur d'empreinte en Rust) n'a pas de wheel Python 3.13 sous
shazamio n'a pas de roue Python 3.13 : la reconnaissance tourne donc dans un
venv 3.12 séparé (musique/.venv-shazam), sur les trois systèmes.
Ce script le crée et y installe shazamio. Le process principal (3.13) capture
l'audio et appelle musique/reconnaisseur.py dedans. Voir docs/musique.md.
"""
import subprocess
import sys
from pathlib import Path

for _f in (sys.stdout, sys.stderr):          # console Windows cp1252 -> UTF-8
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RACINE = Path(__file__).resolve().parent.parent
VENV = RACINE / "musique" / ".venv-shazam"
PY = VENV / ("Scripts" if sys.platform == "win32" else "bin") / \
     ("python.exe" if sys.platform == "win32" else "python")


def _run(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main():
    (RACINE / "musique").mkdir(parents=True, exist_ok=True)
    try:
        if not PY.exists():
            print("== Création du venv isolé (Python 3.12) ==")
            _run(["uv", "venv", "--python", "3.12", str(VENV)])
        print("== Installation shazamio ==")
        _run(["uv", "pip", "install", "--python", str(PY), "shazamio"])
    except FileNotFoundError:
        print("ERREUR : 'uv' introuvable. Installe uv (https://docs.astral.sh/uv/) puis relance.")
        return 1
    except subprocess.CalledProcessError as e:
        print(f"ERREUR d'installation ({e}).")
        return 1

    _run([str(PY), "-c",
          "import shazamio, shazamio_core; print('OK — shazamio prêt')"])
    print("\n✅ Environnement musique prêt.")
    print('   Dis : « Jarvis, c\'est quoi cette musique ? » (micro) ')
    print('   ou : « c\'est quoi la musique de cette vidéo ? » (audio système).')
    if sys.platform == "darwin":
        print("\n   Note macOS : la capture de l'audio SYSTÈME demande un pilote")
        print("   virtuel (brew install blackhole-2ch) choisi comme sortie.")
        print("   Sans lui, la reconnaissance par le micro marche très bien.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
