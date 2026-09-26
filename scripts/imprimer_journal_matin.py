"""Compatibilite de l'ancienne commande avec Signal Matin.

Exemples :
    uv run python scripts/imprimer_journal_matin.py --apercu
    uv run python scripts/imprimer_journal_matin.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Permet l'execution directe depuis le Planificateur de taches Windows.
RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from core.signal_matin.cli import main as signal_matin_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Genere ou imprime Signal Matin")
    parser.add_argument(
        "--apercu", action="store_true",
        help="genere le fichier sans l'envoyer a l'imprimante",
    )
    args = parser.parse_args()
    if args.apercu:
        return signal_matin_main(["preview"])
    print("Par securite, cette ancienne commande ne lance plus l'impression directement.")
    print("Utilise : uv run generate-morning-paper print --confirm")
    return signal_matin_main(["generate"])


if __name__ == "__main__":
    raise SystemExit(main())
