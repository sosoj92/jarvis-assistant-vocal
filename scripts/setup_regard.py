"""Telecharge le modele officiel MediaPipe utilise par le test du regard.

    python scripts/setup_regard.py            # --force : retelecharge le modele
"""
import argparse
import sys
from pathlib import Path

# Meme telechargement atomique que les gestes (fichier .part, controle de taille) :
# une coupure ne laisse jamais de modele tronque sous le nom final.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_gestes import _modele_present, _telecharger  # noqa: E402


RACINE = Path(__file__).resolve().parent.parent
MODELE = RACINE / "gestes" / "models" / "face_landmarker.task"
URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
       "face_landmarker/float16/1/face_landmarker.task")
# Le vrai modele pese ~3,6 Mo : en dessous d'1 Mo, c'est un fichier tronque.
TAILLE_MIN_MODELE = 1_000_000


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Telecharge le modele facial MediaPipe du test du regard.")
    parser.add_argument("--force", action="store_true",
                        help="retelecharge le modele meme s'il est deja present")
    args = parser.parse_args(argv)

    MODELE.parent.mkdir(parents=True, exist_ok=True)
    if not args.force and _modele_present(MODELE, TAILLE_MIN_MODELE):
        print(f"Modele deja present : {MODELE}")
        return 0
    print("Telechargement du modele facial officiel MediaPipe (~4 Mo)...")
    try:
        _telecharger(URL, MODELE, taille_min=TAILLE_MIN_MODELE)
    except Exception as e:
        print(f"ECHEC du telechargement du modele ({type(e).__name__}: {e}).")
        print("Verifie la connexion puis relance : python scripts/setup_regard.py --force")
        return 1
    print(f"OK : {MODELE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
