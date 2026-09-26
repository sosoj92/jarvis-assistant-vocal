"""Schema valide et serialisable d'une edition de Signal Matin."""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Modele(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DensityMode(str, Enum):
    COMPACT = "compact"
    STANDARD = "standard"
    EXTENDED = "extended"


class Importance(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DataState(str, Enum):
    """Nature d'une source dans l'edition, visible pour le lecteur."""

    LIVE = "live"
    LOCAL = "local"
    FALLBACK = "fallback"
    SIMULATED = "simulated"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class DataSourceStatus(Modele):
    name: str = Field(min_length=1, max_length=80)
    state: DataState
    detail: str = Field(default="", max_length=240)
    item_count: int = Field(default=0, ge=0)


class SourceRef(Modele):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl | None = None
    published_at: dt.datetime | None = None


class Illustration(Modele):
    type: Literal["line_art", "engraving", "diagram", "image"] = "line_art"
    path: str | None = None
    alt: str = Field(default="", max_length=240)
    caption: str = Field(default="", max_length=300)


class EditionMeta(Modele):
    date: dt.date
    number: int = Field(ge=1)
    title: str = Field(default="Signal Matin", min_length=1, max_length=80)
    subtitle: str = Field(default="Le journal anti-scroll", max_length=120)
    motto: str = Field(default="Voir clair avant de voir l'ecran.", max_length=160)
    density: DensityMode = DensityMode.STANDARD


class WeatherBlock(Modele):
    location: str = Field(default="", max_length=120)
    condition: str = Field(default="Indisponible", max_length=120)
    temperature_c: float | None = None
    low_c: float | None = None
    high_c: float | None = None
    wind_kmh: float | None = None
    summary: str = Field(default="", max_length=420)
    advice: str = Field(default="", max_length=240)


class AgendaItem(Modele):
    title: str = Field(min_length=1, max_length=180)
    start: dt.datetime | None = None
    end: dt.datetime | None = None
    all_day: bool = False
    location: str = Field(default="", max_length=160)
    note: str = Field(default="", max_length=300)


class TaskItem(Modele):
    title: str = Field(min_length=1, max_length=220)
    importance: Importance = Importance.NORMAL
    due: dt.datetime | None = None
    context: str = Field(default="", max_length=160)
    done: bool = False


class NewsItem(Modele):
    title: str = Field(min_length=1, max_length=240)
    category: str = Field(default="Actualites", max_length=80)
    summary: str = Field(min_length=1, max_length=1600)
    expanded_summary: str = Field(default="", max_length=3200)
    source: SourceRef
    importance: Importance = Importance.NORMAL
    illustration: Illustration | None = None


class NewsBundle(Modele):
    lead: NewsItem | None = None
    world: list[NewsItem] = Field(default_factory=list, max_length=12)
    france: list[NewsItem] = Field(default_factory=list, max_length=12)
    economy: list[NewsItem] = Field(default_factory=list, max_length=12)
    society: list[NewsItem] = Field(default_factory=list, max_length=12)
    science: list[NewsItem] = Field(default_factory=list, max_length=12)
    culture: list[NewsItem] = Field(default_factory=list, max_length=12)

    def all_secondary(self) -> list[NewsItem]:
        return [
            *self.world, *self.france, *self.economy,
            *self.society, *self.science, *self.culture,
        ]


class DigestItem(Modele):
    title: str = Field(min_length=1, max_length=220)
    summary: str = Field(default="", max_length=900)
    source: SourceRef | None = None
    importance: Importance = Importance.NORMAL


class Recommendation(Modele):
    title: str = Field(min_length=1, max_length=180)
    kind: str = Field(default="A decouvrir", max_length=80)
    reason: str = Field(default="", max_length=500)
    source: SourceRef | None = None


class QuoteBlock(Modele):
    text: str = Field(min_length=1, max_length=420)
    author: str = Field(default="", max_length=120)


class WordOfTheDay(Modele):
    word: str = Field(min_length=1, max_length=80)
    definition: str = Field(min_length=1, max_length=420)
    example: str = Field(default="", max_length=300)


class QuizBlock(Modele):
    question: str = Field(min_length=1, max_length=360)
    answer: str = Field(min_length=1, max_length=240)


class CrosswordEntry(Modele):
    number: int = Field(ge=1, le=99)
    answer: str = Field(min_length=2, max_length=18, pattern=r"^[A-Z]+$")
    clue: str = Field(min_length=1, max_length=220)
    row: int = Field(ge=0, le=14)
    column: int = Field(ge=0, le=14)
    direction: Literal["across", "down"]


class CrosswordPuzzle(Modele):
    size: int = Field(default=13, ge=7, le=15)
    entries: list[CrosswordEntry] = Field(default_factory=list, max_length=12)


class MathChallenge(Modele):
    question: str = Field(min_length=1, max_length=220)
    answer: str = Field(min_length=1, max_length=120)
    hint: str = Field(default="", max_length=220)


class LearningPage(Modele):
    crossword: CrosswordPuzzle | None = None
    tech_word: WordOfTheDay | None = None
    french_word: WordOfTheDay | None = None
    math: MathChallenge | None = None


class Extras(Modele):
    quote: QuoteBlock | None = None
    word: WordOfTheDay | None = None
    stat_of_day: DigestItem | None = None
    quiz: QuizBlock | None = None
    reflection: str = Field(default="", max_length=420)


class PersonalBlock(Modele):
    greeting: str = Field(default="Bonjour.", max_length=160)
    note: str = Field(default="", max_length=600)
    free_window: str = Field(default="", max_length=240)


class MorningEdition(Modele):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: dt.datetime
    demo: bool = False
    edition: EditionMeta
    sources: list[DataSourceStatus] = Field(default_factory=list, max_length=16)
    weather: WeatherBlock | None = None
    agenda: list[AgendaItem] = Field(default_factory=list, max_length=24)
    priorities: list[TaskItem] = Field(default_factory=list, max_length=12)
    reminders: list[TaskItem] = Field(default_factory=list, max_length=16)
    news: NewsBundle = Field(default_factory=NewsBundle)
    tech: list[DigestItem] = Field(default_factory=list, max_length=16)
    tech_news: list[NewsItem] = Field(default_factory=list, max_length=12)
    curiosity_news: list[NewsItem] = Field(default_factory=list, max_length=8)
    watch: list[DigestItem] = Field(default_factory=list, max_length=16)
    newsletter_digest: list[DigestItem] = Field(default_factory=list, max_length=16)
    social_digest: list[DigestItem] = Field(default_factory=list, max_length=12)
    community_digest: list[DigestItem] = Field(default_factory=list, max_length=12)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=12)
    personal: PersonalBlock = Field(default_factory=PersonalBlock)
    extras: Extras = Field(default_factory=Extras)
    learning: LearningPage = Field(default_factory=LearningPage)

    @field_validator("generated_at")
    @classmethod
    def generated_at_timezone(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            return value.astimezone()
        return value

    def content_score(self) -> int:
        news = (1 if self.news.lead else 0) + len(self.news.all_secondary())
        extras = sum(bool(x) for x in (
            self.extras.quote, self.extras.word, self.extras.stat_of_day,
            self.extras.quiz, self.extras.reflection,
        ))
        return (
            len(self.agenda) * 2 + len(self.priorities) * 2 + len(self.reminders)
            + news * 2 + len(self.tech) * 2 + len(self.tech_news) * 2
            + len(self.curiosity_news) * 2 + len(self.watch)
            + len(self.newsletter_digest) + len(self.social_digest) * 2
            + len(self.community_digest) * 2
            + len(self.recommendations) + extras
        )
