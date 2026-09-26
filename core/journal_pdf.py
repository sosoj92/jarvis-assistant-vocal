"""Compatibilite de l'ancien journal vers le renderer Signal Matin.

Les nouveaux appels doivent utiliser ``core.signal_matin``. Cette facade garde
les scripts et tests historiques fonctionnels pendant la migration.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from core.signal_matin.models import (
    AgendaItem, EditionMeta, MorningEdition, NewsBundle, NewsItem,
    PersonalBlock, SourceRef, WeatherBlock,
)
from core.signal_matin.normalizer import normaliser_edition
from core.signal_matin.pdf import generer_pdf as generer_signal_matin


def _legacy_edition(
    maintenant: dt.datetime,
    sections: list[tuple[str, str]],
) -> MorningEdition:
    mapping = {name.upper(): str(content or "") for name, content in sections}
    news = []
    for line in mapping.get("ACTUALITES", "").splitlines():
        text = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if not text:
            continue
        source, _, title = text.partition(":")
        if not title:
            title, source = source, "Source locale"
        news.append(NewsItem(
            title=title.strip(),
            category="Actualites",
            summary="Titre collecte par l'ancien pipeline ; resume non disponible.",
            source=SourceRef(name=source.strip() or "Source locale"),
        ))
    first = dt.date(maintenant.year, 1, 1)
    edition = MorningEdition(
        generated_at=maintenant.astimezone(),
        edition=EditionMeta(
            date=maintenant.date(),
            number=(maintenant.date() - first).days + 1,
        ),
        weather=WeatherBlock(summary=mapping.get("METEO", ""), condition="Voir le resume"),
        agenda=([AgendaItem(title="Agenda du jour", note=mapping["AGENDA DU JOUR"])]
                if mapping.get("AGENDA DU JOUR") else []),
        news=NewsBundle(lead=news[0] if news else None, world=news[1:]),
        personal=PersonalBlock(
            greeting="Bonjour. Voici l'essentiel de la journee.",
            note=mapping.get("ECHEANCES", ""),
        ),
    )
    return normaliser_edition(edition, mode="auto")


def generer_pdf(
    chemin: Path,
    maintenant: dt.datetime,
    sections: list[tuple[str, str]],
) -> Path:
    return generer_signal_matin(_legacy_edition(maintenant, sections), Path(chemin))
