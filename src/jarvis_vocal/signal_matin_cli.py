"""Pont package -> modules source pour la commande Signal Matin."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core.signal_matin.cli import main as run
    return run()
