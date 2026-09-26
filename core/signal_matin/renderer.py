"""Composants HTML semantiques de Signal Matin.

Ce module ne connait ni API, ni credentials, ni configuration Jarvis. Il recoit
uniquement un ``MorningEdition`` valide et produit un document autonome.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import mimetypes
from pathlib import Path

from .models import (
    AgendaItem, DensityMode, DigestItem, MorningEdition, NewsItem,
    Recommendation, TaskItem,
)

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / "web" / "signal_matin.css"
WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
          "aout", "septembre", "octobre", "novembre", "decembre")
FRONT_BRIEF_LIMIT = 3
BRIEF_DETAIL_PAGE_LIMIT = 3
NEWS_PAGE_LIMIT = 9


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _truncate(value: str, limit: int) -> str:
    value = " ".join(str(value or "").split())
    if len(value) <= limit:
        return value
    short = value[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return short + "..."


def _date_fr(value: dt.date) -> str:
    return f"{WEEKDAYS[value.weekday()]} {value.day} {MONTHS[value.month - 1]} {value.year}"


def _time(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    return f"{value.hour:02d} h {value.minute:02d}" if value.minute else f"{value.hour:02d} h"


def _due(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    local = value.astimezone()
    if local.hour == 0 and local.minute == 0:
        return f"{local.day} {MONTHS[local.month - 1][:4]}."
    if local.date() == dt.date.today():
        return _time(local)
    return f"{local.day} {MONTHS[local.month - 1][:4]}. · {_time(local)}"


def section_header(title: str, eyebrow: str = "") -> str:
    meta = f'<span class="section-eyebrow">{_e(eyebrow)}</span>' if eyebrow else ""
    return f'<header class="section-header">{meta}<h2>{_e(title)}</h2></header>'


def illustration_block(item: NewsItem) -> str:
    illustration = item.illustration
    if not illustration:
        return ""
    image = ""
    if illustration.path:
        path = Path(illustration.path)
        path = path if path.is_absolute() else ROOT / path
        if path.is_file():
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            image = f'<img src="data:{mime};base64,{encoded}" alt="{_e(illustration.alt)}">'
    if not image:
        image = """
        <svg viewBox="0 0 720 270" role="img" aria-label="Nature morte matinale dessinee au trait">
          <rect x="0" y="0" width="720" height="270" fill="#efeee8"/>
          <g fill="none" stroke="#1b1b1a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M44 222 H680" stroke="#777772" stroke-width="1.5"/>
            <path d="M68 206 L246 157 L424 198 L243 244 Z" fill="#f8f7f2"/>
            <path d="M246 157 L245 232 M90 204 L242 172 M273 169 L401 200 M116 211 L224 183 M278 184 L374 207" stroke="#8a8983" stroke-width="1.4"/>
            <path d="M468 108 C470 92 576 92 578 108 L566 194 C563 216 488 216 482 194 Z" fill="#f8f7f2"/>
            <ellipse cx="523" cy="108" rx="55" ry="16" fill="#fbfaf6"/>
            <ellipse cx="523" cy="108" rx="43" ry="10" stroke="#777772"/>
            <path d="M575 126 C626 112 636 183 574 184"/>
            <path d="M484 218 H608 M493 226 H599" stroke="#777772" stroke-width="1.4"/>
            <path d="M142 164 C130 122 135 78 163 35 M163 35 C181 56 187 78 181 101 M164 53 C145 62 130 77 122 94 M170 72 C194 75 211 88 222 108"/>
            <path d="M162 37 C141 28 123 35 115 53 C136 56 151 50 162 37 Z" fill="#d7d6d0"/>
            <path d="M181 99 C205 91 224 99 235 119 C211 123 193 116 181 99 Z" fill="#d7d6d0"/>
            <path d="M132 124 C112 116 94 122 83 140 C104 146 121 140 132 124 Z" fill="#d7d6d0"/>
            <path d="M631 49 H679 M655 25 V74 M637 31 L672 67 M674 31 L638 67" stroke="#8a8983" stroke-width="1.5"/>
          </g>
        </svg>"""
    caption = f'<figcaption>{_e(illustration.caption)}</figcaption>' if illustration.caption else ""
    return f'<figure class="illustration">{image}{caption}</figure>'


def edition_meta(edition: MorningEdition) -> str:
    meta = edition.edition
    demo = '<span class="demo-mark">EDITION DE DEMONSTRATION</span>' if edition.demo else ""
    return f"""
    <div class="edition-meta">
      <span>NO {meta.number:04d}</span>
      <span>{_e(_date_fr(meta.date).upper())}</span>
      <span>{_e(meta.density.value.upper())}</span>
    </div>{demo}
    """


def masthead(edition: MorningEdition) -> str:
    meta = edition.edition
    first, _, second = meta.title.partition(" ")
    wordmark = (
        f'<span>{_e(first)}</span><em>{_e(second)}</em>'
        if second else f'<span>{_e(first)}</span>'
    )
    return f"""
    <header class="masthead">
      <div class="masthead-rule"></div>
      <div class="masthead-overline"><span>LE QUOTIDIEN PERSONNEL</span><span>{_e(meta.subtitle)}</span></div>
      <h1>{wordmark}</h1>
      <p class="masthead-motto">{_e(meta.motto)}</p>
      {edition_meta(edition)}
    </header>
    """


def weather_block(edition: MorningEdition) -> str:
    weather = edition.weather
    if weather is None:
        return ""
    temp = "--" if weather.temperature_c is None else f"{weather.temperature_c:g}°"
    range_text = ""
    if weather.low_c is not None or weather.high_c is not None:
        range_text = f"Min {weather.low_c:g} / Max {weather.high_c:g} deg"
    return f"""
    <section class="weather-block ruled-block">
      {section_header("Meteo", weather.location)}
      <div class="weather-line">
        <svg class="weather-symbol" viewBox="0 0 64 48" aria-hidden="true">
          <circle cx="22" cy="18" r="9" fill="none" stroke="currentColor" stroke-width="2"/>
          <path d="M22 2v7M22 27v7M6 18h7M31 18h7M10 6l5 5M29 25l5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <path d="M21 39h28c7 0 10-10 4-14-3-2-7-2-10 0-2-8-15-8-17 1-8-1-12 13-5 13Z" fill="#fbfaf6" stroke="currentColor" stroke-width="2"/>
        </svg>
        <strong>{_e(temp)}</strong><span>{_e(weather.condition)}</span>
      </div>
      <p>{_e(_truncate(weather.summary, 220))}</p>
      <p class="utility">{_e(range_text)}</p>
      {f'<p class="weather-advice">{_e(weather.advice)}</p>' if weather.advice else ''}
    </section>
    """


def agenda_block(items: list[AgendaItem], limit: int = 6) -> str:
    if not items:
        return ""
    rows = []
    for item in items[:limit]:
        when = "Journee" if item.all_day else (_time(item.start) or "A caler")
        detail = item.location or item.note
        rows.append(f"""
        <li><time>{_e(when)}</time><div><strong>{_e(item.title)}</strong>
        {f'<small>{_e(_truncate(detail, 150))}</small>' if detail else ''}</div></li>""")
    return f'<section class="agenda-block">{section_header("Agenda", "Aujourd hui")}<ol class="timeline">{"".join(rows)}</ol></section>'


def task_list(title: str, items: list[TaskItem], limit: int = 6) -> str:
    active = [item for item in items if not item.done][:limit]
    if not active:
        return ""
    rows = []
    for index, item in enumerate(active, 1):
        context = f'<small>{_e(item.context)}</small>' if item.context else ""
        due = f'<small>{_e(_due(item.due))}</small>' if item.due else ""
        rows.append(f'<li data-importance="{item.importance.value}"><span>{index:02d}</span><div>{_e(item.title)}{context}{due}</div></li>')
    return f'<section class="task-block">{section_header(title)}<ol class="numbered-list">{"".join(rows)}</ol></section>'


def _source_line(item: NewsItem) -> str:
    source = item.source
    published = source.published_at.astimezone().strftime("%H:%M") if source.published_at else ""
    bits = [item.category.upper(), source.name]
    if published:
        bits.append(published)
    return " / ".join(_e(bit) for bit in bits if bit)


def news_lead(item: NewsItem | None, summary_limit: int = 520) -> str:
    if item is None:
        return ""
    return f"""
    <article class="news-lead">
      <p class="article-meta">{_source_line(item)}</p>
      <h2>{_e(_truncate(item.title, 150))}</h2>
      {illustration_block(item)}
      <p class="standfirst">{_e(_truncate(item.summary, summary_limit))}</p>
    </article>
    """


def news_card(item: NewsItem, summary_limit: int = 280, compact: bool = False) -> str:
    summary = "" if compact else f'<p>{_e(_truncate(item.summary, summary_limit))}</p>'
    return f"""
    <article class="news-card" data-importance="{item.importance.value}">
      <p class="article-meta">{_source_line(item)}</p>
      <h3>{_e(_truncate(item.title, 120))}</h3>
      {summary}
    </article>
    """


def news_feature(item: NewsItem, summary_limit: int = 420) -> str:
    return f"""
    <article class="news-feature" data-importance="{item.importance.value}">
      <p class="article-meta">{_source_line(item)}</p>
      <h2>{_e(_truncate(item.title, 150))}</h2>
      <p class="feature-summary">{_e(_truncate(item.summary, summary_limit))}</p>
    </article>
    """


def news_opening(items: list[NewsItem], *, compact: bool = False) -> str:
    if not items:
        return ""
    feature_limit = 250 if compact else 440
    side_limit = 0 if compact else 125
    side_cards = []
    for item in items[1:3]:
        side_cards.append(
            news_card(item, compact=compact, summary_limit=side_limit)
        )
    side = f'<aside class="news-side">{"".join(side_cards)}</aside>' if side_cards else ""
    return f'<div class="news-opening">{news_feature(items[0], feature_limit)}{side}</div>'


def news_followups(
    items: list[NewsItem], *, summary_limit: int = 220, compact: bool = False,
) -> str:
    if not items:
        return ""
    return '<div class="news-followups">' + "".join(
        news_card(item, summary_limit=summary_limit, compact=compact)
        for item in items
    ) + "</div>"


def news_grid(
    items: list[NewsItem],
    limit: int = 8,
    summary_limit: int = 280,
) -> str:
    return '<div class="news-grid">' + "".join(
        news_card(item, summary_limit=summary_limit) for item in items[:limit]
    ) + "</div>"


def news_briefs(items: list[NewsItem], limit: int = 5) -> str:
    if not items:
        return ""
    return f'<section class="briefs">{section_header("En bref")}<div class="brief-list">' + "".join(
        news_card(item, summary_limit=105) for item in items[:limit]
    ) + "</div></section>"


def detailed_brief(item: NewsItem, *, featured: bool = False) -> str:
    title_tag = "h2" if featured else "h3"
    detail = item.expanded_summary or item.summary
    paragraphs = "".join(
        f'<p>{_e(_truncate(paragraph, 1500))}</p>'
        for paragraph in detail.split("\n\n") if paragraph.strip()
    ) or f'<p>{_e(_truncate(detail, 1500))}</p>'
    return f"""
    <article class="brief-detail{' is-featured' if featured else ''}">
      <p class="article-meta">{_source_line(item)}</p>
      <{title_tag}>{_e(_truncate(item.title, 190))}</{title_tag}>
      <div class="brief-copy">{paragraphs}</div>
    </article>
    """


def dossier_story(
    item: NewsItem, *, featured: bool = False, max_chars: int | None = None,
) -> str:
    detail = item.expanded_summary or item.summary
    limit = max_chars or (1000 if featured else 520)
    paragraphs = f'<p>{_e(_truncate(detail, limit))}</p>'
    return f"""
    <article class="dossier-story{' is-featured' if featured else ''}">
      <p class="article-meta">{_source_line(item)}</p>
      <h2>{_e(_truncate(item.title, 180))}</h2>
      <div class="dossier-copy">{paragraphs}</div>
    </article>
    """


def front_watch(items: list[DigestItem], limit: int = 3) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<li><span>{index:02d}</span><p><strong>{_e(item.title)}</strong> '
        f'{_e(_truncate(item.summary, 105))}</p></li>'
        for index, item in enumerate(items[:limit], 1)
    )
    return f'<section class="front-watch">{section_header("A surveiller")}<ol>{rows}</ol></section>'


def front_footer_band(edition: MorningEdition) -> str:
    pieces: list[str] = []
    note = edition.personal.note or edition.personal.greeting
    if note:
        pieces.append(
            '<aside class="front-intention"><span>Intention du jour</span>'
            f'<p>{_e(_truncate(note, 260))}</p></aside>'
        )
    if edition.extras.word:
        word = edition.extras.word
        pieces.append(
            '<article class="front-word"><span>Mot du jour</span>'
            f'<h3>{_e(word.word)}</h3><p>{_e(_truncate(word.definition, 110))}</p></article>'
        )
    if edition.extras.stat_of_day:
        stat = edition.extras.stat_of_day
        pieces.append(
            '<article class="front-number"><span>Le chiffre</span>'
            f'<strong>{_e(stat.title)}</strong><p>{_e(_truncate(stat.summary, 110))}</p></article>'
        )
    return '<section class="front-footer-band">' + "".join(pieces) + "</section>" if pieces else ""


def front_pause(edition: MorningEdition) -> str:
    pieces: list[str] = []
    if edition.personal.free_window:
        pieces.append(
            '<article><span>Fenetre libre</span>'
            f'<p>{_e(_truncate(edition.personal.free_window, 150))}</p></article>'
        )
    if edition.extras.reflection:
        pieces.append(
            '<article><span>Question du matin</span>'
            f'<p>{_e(_truncate(edition.extras.reflection, 150))}</p></article>'
        )
    return '<section class="front-pause">' + "".join(pieces) + "</section>" if pieces else ""


def continuation_news(title: str, items: list[NewsItem], limit: int = 5) -> str:
    if not items:
        return ""
    cards = "".join(
        f'<article><p class="article-meta">{_source_line(item)}</p>'
        f'<h3>{_e(_truncate(item.title, 105))}</h3>'
        f'<p>{_e(_truncate(item.summary, 145))}</p></article>'
        for item in items[:limit]
    )
    return f'<section class="continuation-news">{section_header(title)}<div>{cards}</div></section>'


def curiosity_engraving() -> str:
    return """
    <figure class="curiosity-engraving" aria-label="Illustration au trait de livres, d'une plante et d'un crayon">
      <svg viewBox="0 0 720 155" role="img">
        <g fill="none" stroke="#242422" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M55 122 H665" stroke="#85857f" stroke-width="1.2"/>
          <path d="M86 94 H270 L250 119 H66 Z" fill="#f6f5f0"/>
          <path d="M105 65 H287 L270 94 H86 Z" fill="#fbfaf6"/>
          <path d="M118 39 H304 L287 65 H105 Z" fill="#f0efe9"/>
          <path d="M130 47 H278 M118 73 H260 M95 102 H240" stroke="#85857f" stroke-width="1.2"/>
          <path d="M389 116 C380 88 381 56 397 24 M398 26 C419 34 431 49 434 68 M396 46 C377 51 363 62 354 78 M404 67 C425 70 441 83 450 100"/>
          <path d="M397 25 C381 15 364 20 356 34 C373 40 387 36 397 25 Z" fill="#d8d7d1"/>
          <path d="M433 68 C451 60 468 65 478 81 C460 86 445 81 433 68 Z" fill="#d8d7d1"/>
          <path d="M353 78 C334 72 318 78 309 94 C328 98 343 92 353 78 Z" fill="#d8d7d1"/>
          <path d="M365 118 H430 L421 87 H374 Z" fill="#f8f7f2"/>
          <path d="M506 112 L635 42 L650 53 L521 123 Z" fill="#f8f7f2"/>
          <path d="M635 42 L663 29 L650 53 M524 115 L515 131 L506 112"/>
          <circle cx="606" cy="41" r="23" stroke="#85857f" stroke-width="1.2"/>
        </g>
      </svg>
    </figure>
    """


def digest_list(title: str, items: list[DigestItem], limit: int = 5) -> str:
    if not items:
        return ""
    cards = []
    for item in items[:limit]:
        source = f'<small>{_e(item.source.name)}</small>' if item.source else ""
        cards.append(f'<article class="digest-item"><h3>{_e(item.title)}</h3><p>{_e(_truncate(item.summary, 360))}</p>{source}</article>')
    return f'<section class="digest-section">{section_header(title)}{"".join(cards)}</section>'


def social_digest(edition: MorningEdition, limit: int = 4) -> str:
    return digest_list(
        "Reseaux & communaute",
        [*edition.social_digest, *edition.community_digest],
        limit,
    )


def recommendation_list(items: list[Recommendation], limit: int = 4) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<article class="recommendation"><span>{_e(item.kind)}</span><h3>{_e(item.title)}</h3><p>{_e(_truncate(item.reason, 260))}</p></article>'
        for item in items[:limit]
    )
    return f'<section>{section_header("Recommandations", "Pour plus tard")}{rows}</section>'


def extras_block(
    edition: MorningEdition,
    *,
    include_stat: bool = True,
    limit: int | None = None,
) -> str:
    extras = edition.extras
    pieces = []
    if extras.quote:
        author = f'<cite>{_e(extras.quote.author)}</cite>' if extras.quote.author else ""
        pieces.append(f'<blockquote><p>{_e(extras.quote.text)}</p>{author}</blockquote>')
    if extras.word:
        pieces.append(f'<article class="word"><span>Mot du jour</span><h3>{_e(extras.word.word)}</h3><p>{_e(extras.word.definition)}</p><small>{_e(extras.word.example)}</small></article>')
    if include_stat and extras.stat_of_day:
        pieces.append(f'<article class="stat"><strong>{_e(extras.stat_of_day.title)}</strong><p>{_e(extras.stat_of_day.summary)}</p></article>')
    if extras.quiz:
        pieces.append(
            '<article class="quiz"><span>Mini quiz</span>'
            f'<p>{_e(extras.quiz.question)}</p>'
            f'<small>Reponse : {_e(extras.quiz.answer)}</small></article>'
        )
    if extras.reflection:
        pieces.append(f'<article class="reflection"><span>Question du matin</span><p>{_e(extras.reflection)}</p></article>')
    if limit is not None:
        pieces = pieces[:limit]
    return (
        f'<section class="extras-grid extras-count-{len(pieces)}">'
        + "".join(pieces) + "</section>"
        if pieces else ""
    )


def news_context_block(edition: MorningEdition, *, include_lead: bool = True) -> str:
    """Complete la page actualites avec du contexte utile, sans inventer de faits."""
    pieces: list[str] = []
    if include_lead and edition.news.lead:
        pieces.append(
            '<article><span>Contexte utile</span>'
            f'<p>{_e(_truncate(edition.news.lead.summary, 420))}</p></article>'
        )
    if edition.watch:
        watch = " ".join(
            f'<strong>{_e(item.title)}.</strong> {_e(_truncate(item.summary, 180))}'
            for item in edition.watch[:2]
        )
        pieces.append(f'<article><span>A surveiller</span><p>{watch}</p></article>')
    if edition.extras.stat_of_day:
        stat = edition.extras.stat_of_day
        pieces.append(
            '<article class="context-stat"><span>Chiffre du jour</span>'
            f'<strong>{_e(stat.title)}</strong><p>{_e(stat.summary)}</p></article>'
        )
    return (
        f'<section class="news-context context-count-{len(pieces)}">'
        + "".join(pieces)
        + "</section>"
        if pieces else ""
    )


def notes_space(tall: bool = False) -> str:
    lines = "".join('<span aria-hidden="true"></span>' for _ in range(8))
    return (
        f'<section class="notes-space{" is-tall" if tall else ""}">'
        f'{section_header("Carnet du jour", "Notes, idees, choses a retenir")}'
        f'<div class="writing-lines">{lines}</div></section>'
    )


def _page(edition: MorningEdition, number: int, label: str, content: str,
          first: bool = False, slug: str = "") -> str:
    header = masthead(edition) if first else f"""
      <header class="running-head">
        <strong>{_e(edition.edition.title)}</strong>
        <span>{_e(label.upper())}</span>
        <span>{_e(_date_fr(edition.edition.date))}</span>
      </header>"""
    return f"""
    <section class="sheet page-{number}{f' page-{slug}' if slug else ''}" data-page="{number}">
      {header}
      <main class="page-content">{content}</main>
      <footer><span>{_e(edition.edition.title)} / {_e(edition.edition.subtitle)}</span><span>{number}</span></footer>
    </section>
    """


def _page_one(edition: MorningEdition) -> str:
    secondary = edition.news.all_secondary()
    left = "".join(filter(None, [
        weather_block(edition),
        agenda_block(edition.agenda, 5),
        task_list("Priorites", edition.priorities, 4),
        task_list("A ne pas oublier", edition.reminders, 3),
    ]))
    right = news_lead(edition.news.lead, 360) + news_briefs(secondary, FRONT_BRIEF_LIMIT)
    right += '<div class="front-lower">'
    right += digest_list("IA & tech", edition.tech, 1)
    right += social_digest(edition, 1) or front_watch(edition.watch, 2)
    right += '</div>'
    right += front_pause(edition)
    tail = front_footer_band(edition)
    return _page(
        edition, 1, "Le briefing",
        f'<div class="briefing-grid"><div>{left}</div><div>{right}</div></div>{tail}',
        first=True, slug="front",
    )


def _page_briefs_detail(
    edition: MorningEdition, number: int, *, start: int = 0, part: int = 1,
) -> str:
    items = edition.news.all_secondary()[start:start + BRIEF_DETAIL_PAGE_LIMIT]
    if not items:
        return ""
    eyebrow = "Les sujets annonces en une" if part == 1 else "La suite du cahier d actualites"
    body = section_header("En bref, en detail", eyebrow)
    body += '<div class="briefs-detail-layout">'
    body += detailed_brief(items[0], featured=True)
    body += '<div class="briefs-detail-side">'
    body += "".join(detailed_brief(item) for item in items[1:])
    body += '</div></div>'
    if part == 1:
        body += '<p class="continued-note">Suite du cahier d actualites page suivante.</p>'
    return _page(edition, number, "En bref, en detail", body, slug="briefs-detail")


def _page_news(edition: MorningEdition, number: int = 2, start: int = 0) -> str:
    items = edition.news.all_secondary()[start:]
    body = section_header("Actualites & monde", "Comprendre sans defiler")
    if items:
        selected = items[:NEWS_PAGE_LIMIT]
        body += news_opening(selected)
        body += news_followups(
            selected[3:],
            summary_limit=150 if edition.edition.density == DensityMode.EXTENDED else 260,
        )
    elif edition.news.lead:
        body += news_lead(edition.news.lead)
    else:
        body += '<p class="empty-state">Aucune actualite disponible : aucun flux n\'a pu etre lu. Cette rubrique reste volontairement vide et aucun article n\'est invente.</p>'
    body += news_context_block(edition)
    return _page(edition, number, "Actualites & monde", body, slug="news")


def _page_day(edition: MorningEdition, number: int) -> str:
    intro = f"""
    <div class="day-intro"><p class="dropcap">{_e(_truncate(edition.personal.greeting, 220))}</p>
    {f'<p class="free-window"><span>Fenetre libre</span>{_e(_truncate(edition.personal.free_window, 240))}</p>' if edition.personal.free_window else ''}</div>"""
    body = section_header("Ta journee", "Direction et respiration") + intro
    body += '<div class="day-grid"><div>' + agenda_block(edition.agenda, 10)
    body += '</div><div>'
    body += task_list("Tes priorites", edition.priorities, 8)
    body += task_list("A ne pas oublier", edition.reminders, 8)
    body += '</div></div>'
    if edition.personal.note:
        body += f'<aside class="editorial-aside"><span>Note personnelle</span><p>{_e(_truncate(edition.personal.note, 500))}</p></aside>'
    body += notes_space(tall=not edition.agenda)
    return _page(edition, number, "Ta journee", body, slug="day")


def _page_tech(edition: MorningEdition, number: int) -> str:
    body = section_header("Technologie & IA", "Comprendre ce qui change vraiment")
    items = edition.tech_news
    if items:
        body += '<div class="tech-dossier">'
        body += dossier_story(items[0], featured=True, max_chars=950)
        body += '<div class="tech-secondary">'
        body += "".join(dossier_story(item, max_chars=480) for item in items[1:5])
        body += '</div></div>'
    elif edition.tech:
        body += '<div class="tech-fallback">' + digest_list(
            "La veille technique", edition.tech, 6,
        ) + '</div>'
    else:
        body += '<p class="empty-state">Aucune actualite technique recente n a pu etre verifiee ce matin. La page reste volontairement vide plutot que de recycler un ancien sujet.</p>'
    return _page(edition, number, "Technologie & IA", body, slug="tech")


def _page_curiosity(edition: MorningEdition, number: int) -> str:
    body = section_header("Veille & curiosites", "Signaux faibles, sciences et culture")
    if edition.curiosity_news:
        body += '<div class="curiosity-stories">'
        body += dossier_story(
            edition.curiosity_news[0], featured=True, max_chars=760,
        )
        body += '<div>' + "".join(
            dossier_story(item, max_chars=340)
            for item in edition.curiosity_news[1:4]
        ) + '</div></div>'
    body += '<div class="curiosity-lower">'
    body += digest_list("A surveiller", edition.watch, 4)
    body += digest_list("Lettres suivies", edition.newsletter_digest, 3)
    body += recommendation_list(edition.recommendations, 3)
    body += social_digest(edition, 4)
    body += '</div>'
    if not edition.curiosity_news and not any((
        edition.watch, edition.newsletter_digest, edition.recommendations,
        edition.social_digest, edition.community_digest,
    )):
        body += curiosity_engraving()
    return _page(edition, number, "Veille & curiosite", body, slug="curiosity")


def crossword_block(edition: MorningEdition) -> str:
    puzzle = edition.learning.crossword
    if puzzle is None or not puzzle.entries:
        return '<p class="empty-state">La grille du jour n a pas pu etre composee.</p>'
    letters: dict[tuple[int, int], str] = {}
    starts: dict[tuple[int, int], int] = {}
    for entry in puzzle.entries:
        dr, dc = (0, 1) if entry.direction == "across" else (1, 0)
        starts[(entry.row, entry.column)] = entry.number
        for index, letter in enumerate(entry.answer):
            letters[(entry.row + dr * index, entry.column + dc * index)] = letter
    rows = []
    for row in range(puzzle.size):
        cells = []
        for column in range(puzzle.size):
            point = (row, column)
            if point in letters:
                number = f'<span>{starts[point]}</span>' if point in starts else ""
                cells.append(f'<td class="crossword-cell">{number}</td>')
            else:
                cells.append('<td class="crossword-block"></td>')
        rows.append('<tr>' + "".join(cells) + '</tr>')
    across = "".join(
        f'<li><strong>{entry.number}</strong>{_e(entry.clue)}</li>'
        for entry in puzzle.entries if entry.direction == "across"
    )
    down = "".join(
        f'<li><strong>{entry.number}</strong>{_e(entry.clue)}</li>'
        for entry in puzzle.entries if entry.direction == "down"
    )
    solution = " - ".join(
        f'{entry.number} {entry.answer}' for entry in sorted(puzzle.entries, key=lambda value: value.number)
    )
    return f"""
    <section class="crossword-panel">
      {section_header("Mots croises du jour", "Une grille, six passerelles")}
      <div class="crossword-layout">
        <table class="crossword-grid" aria-label="Grille de mots croises"><tbody>{''.join(rows)}</tbody></table>
        <div class="crossword-clues">
          <h3>Horizontal</h3><ol>{across}</ol>
          <h3>Vertical</h3><ol>{down}</ol>
        </div>
      </div>
      <p class="crossword-solution">Solutions : {_e(solution)}</p>
    </section>
    """


def _page_learning(edition: MorningEdition, number: int) -> str:
    learning = edition.learning
    body = section_header("La pause du matin", "Jouer, apprendre, retenir")
    body += crossword_block(edition)
    body += (
        '<section class="scratch-zone"><div><span>Zone de brouillon</span>'
        '<p>Calculs, essais et mots trouves</p></div><div class="scratch-grid"></div></section>'
    )
    cards = []
    if learning.tech_word:
        word = learning.tech_word
        cards.append(
            '<article class="learning-card"><span>Vocabulaire tech</span>'
            f'<h3>{_e(word.word)}</h3><p>{_e(word.definition)}</p>'
            f'<small>{_e(word.example)}</small></article>'
        )
    if learning.french_word:
        word = learning.french_word
        cards.append(
            '<article class="learning-card"><span>Mot francais</span>'
            f'<h3>{_e(word.word)}</h3><p>{_e(word.definition)}</p>'
            f'<small>{_e(word.example)}</small></article>'
        )
    if learning.math:
        challenge = learning.math
        cards.append(
            '<article class="learning-card math-card"><span>Calcul mental</span>'
            f'<h3>{_e(challenge.question)}</h3><p>{_e(challenge.hint)}</p>'
            f'<small>Reponse : {_e(challenge.answer)}</small></article>'
        )
    body += '<section class="learning-strip">' + "".join(cards) + '</section>'
    return _page(edition, number, "La pause du matin", body, slug="learning")


def _page_compact(edition: MorningEdition, number: int, start: int = 0) -> str:
    body = section_header("La suite du matin", "Journee, nouvelles et curiosite")
    body += '<div class="compact-grid"><div>'
    body += task_list("Rappels", edition.reminders, 5)
    body += digest_list("IA & tech", edition.tech, 2)
    body += digest_list("A surveiller", edition.watch, 2)
    body += '</div><div>'
    compact_news = edition.news.all_secondary()[start:]
    if compact_news:
        selected = compact_news[:8]
        body += news_opening(selected, compact=True)
        body += news_followups(selected[3:], compact=True)
    elif edition.news.lead:
        body += news_lead(edition.news.lead, 260)
    else:
        body += '<p class="empty-state">Aucune actualite disponible : aucun flux n\'a pu etre lu et aucun article n\'est invente.</p>'
    body += recommendation_list(edition.recommendations, 2)
    body += '</div></div>'
    extras = extras_block(edition, limit=2)
    body += extras
    if not extras:
        body += '<div class="compact-art-floor">' + curiosity_engraving() + '</div>'
    return _page(edition, number, "La suite du matin", body, slug="compact-tail")


def _page_standard_tail(edition: MorningEdition, number: int) -> str:
    sparse = sum(map(len, (
        edition.agenda, edition.priorities, edition.reminders,
        edition.social_digest, edition.community_digest,
    ))) <= 11
    secondary_count = len(edition.news.all_secondary())
    detail_count = min(secondary_count, FRONT_BRIEF_LIMIT * 2)
    continuation = edition.news.all_secondary()[detail_count + NEWS_PAGE_LIMIT:]
    body = '<div class="standard-tail"><div>'
    body += section_header("Ta journee", "Ce qui merite ton attention")
    body += agenda_block(edition.agenda, 8)
    body += task_list("Priorites", edition.priorities, 6)
    body += task_list("Rappels", edition.reminders, 5)
    if not edition.agenda:
        body += notes_space()
    body += '</div><div>'
    body += section_header("Reseaux & liens")
    body += social_digest(edition, 5)
    body += digest_list("Boite de reception", edition.newsletter_digest, 3)
    if sparse:
        body += continuation_news("A lire ensuite", continuation, 4)
    body += '</div></div>'
    if sparse and not continuation:
        body += '<div class="standard-tail-floor">' + curiosity_engraving() + '</div>'
    body += extras_block(edition, limit=3)
    return _page(edition, number, "Journee & liens", body, slug="standard-tail")


def render_html(edition: MorningEdition, css: str | None = None) -> str:
    css = CSS_PATH.read_text(encoding="utf-8") if css is None else css
    mode = edition.edition.density
    pages = [_page_one(edition)]
    secondary = edition.news.all_secondary()
    brief_count = min(FRONT_BRIEF_LIMIT, len(secondary))
    detail_pages = 1 if brief_count else 0
    if mode != DensityMode.COMPACT and len(secondary) > FRONT_BRIEF_LIMIT:
        detail_pages = 2
    detail_count = min(len(secondary), detail_pages * BRIEF_DETAIL_PAGE_LIMIT)
    number = 2
    for part in range(detail_pages):
        pages.append(_page_briefs_detail(
            edition, number, start=part * BRIEF_DETAIL_PAGE_LIMIT, part=part + 1,
        ))
        number += 1
    if mode == DensityMode.COMPACT:
        pages.append(_page_compact(edition, number, start=detail_count))
        pages.append(_page_learning(edition, number + 1))
    elif mode == DensityMode.STANDARD:
        pages.extend([
            _page_news(edition, number, start=detail_count),
            _page_tech(edition, number + 1),
            _page_standard_tail(edition, number + 2),
            _page_curiosity(edition, number + 3),
            _page_learning(edition, number + 4),
        ])
    else:
        pages.extend([
            _page_news(edition, number, start=detail_count),
            _page_day(edition, number + 1),
            _page_tech(edition, number + 2),
            _page_curiosity(edition, number + 3),
            _page_learning(edition, number + 4),
        ])
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(edition.edition.title)} - {_e(_date_fr(edition.edition.date))}</title>
  <style>{css}</style>
</head>
<body class="density-{mode.value}">
  <div class="publication">{''.join(pages)}</div>
</body>
</html>"""


def write_html(edition: MorningEdition, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(edition), encoding="utf-8")
    return path
