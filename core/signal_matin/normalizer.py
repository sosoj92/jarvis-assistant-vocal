"""Validation, choix de densite et persistence du JSON d'edition."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DensityMode, MorningEdition


def choisir_densite(edition: MorningEdition) -> DensityMode:
    score = edition.content_score()
    if score <= 14:
        return DensityMode.COMPACT
    if score <= 38:
        return DensityMode.STANDARD
    return DensityMode.EXTENDED


def normaliser_edition(
    donnees: MorningEdition | dict[str, Any],
    mode: str | DensityMode = "auto",
) -> MorningEdition:
    edition = donnees if isinstance(donnees, MorningEdition) else MorningEdition.model_validate(donnees)
    densite = choisir_densite(edition) if str(mode).lower() == "auto" else DensityMode(mode)
    if edition.edition.density != densite:
        edition = edition.model_copy(update={
            "edition": edition.edition.model_copy(update={"density": densite})
        })
    return edition


def charger_edition(chemin: Path, mode: str | DensityMode = "auto") -> MorningEdition:
    return normaliser_edition(json.loads(chemin.read_text(encoding="utf-8")), mode=mode)


def ecrire_edition(edition: MorningEdition, chemin: Path) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        edition.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    return chemin
