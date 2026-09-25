"""Normalise sans l'afficher le fichier local d'authentification Hermes."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: normalize_hermes_api_env.py <fichier>")

    path = Path(sys.argv[1]).resolve()
    text = path.read_bytes().decode("utf-8-sig").strip()
    name, separator, value = text.partition("=")
    if separator != "=" or name != "API_SERVER_KEY" or len(value) < 8:
        raise SystemExit("format de cle Hermes invalide")
    if any(character.isspace() for character in value):
        raise SystemExit("la cle Hermes contient un espace interdit")

    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(f"API_SERVER_KEY={value}\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()

    print("HERMES_API_ENV_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
