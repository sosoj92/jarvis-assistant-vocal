"""Calibration interactive des gestes (à faire à l'arrivée de la webcam).

    python scripts/gestes_calibrer.py

Ouvre la webcam avec les landmarks + les métriques en direct. Ajuste les seuils au
clavier (+/- pincement, t/T durée de maintien), 's' sauvegarde vers
gestes/calibration.json (prioritaire sur config.yaml), 'q' quitte. Aucune image
n'est enregistrée. Voir docs/gestes.md.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from core.config import reglage  # noqa: E402

from core import plateforme  # noqa: E402

PY = plateforme.python_venv(RACINE / "gestes" / ".venv-tracker")


def main():
    if not PY.exists():
        print("Environnement gestes absent — lance d'abord : python scripts/setup_gestes.py")
        return 1
    conf = {
        "device": int(reglage("gestes.device", 0)),
        "fps": int(reglage("gestes.fps", 24)),
        "largeur": int(reglage("gestes.largeur", 640)),
        "hauteur": int(reglage("gestes.hauteur", 480)),
        "seuils": reglage("gestes.seuils", {}) or {},
        "armement": reglage("gestes.armement", {"actif": False}) or {"actif": False},
        "url": "", "token": "",
        "model_path": str(RACINE / "gestes" / "models" / "hand_landmarker.task"),
    }
    env = dict(os.environ, GESTES_CONF=json.dumps(conf))
    print("Calibration : +/- (pincement)  t/T (maintien)  s (sauver)  q (quitter)")
    subprocess.run([str(PY), str(RACINE / "gestes" / "tracker.py"), "--calibrate"],
                   env=env, cwd=str(RACINE))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
