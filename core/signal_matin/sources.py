"""Adaptateurs : sources Jarvis -> donnees normalisees de Signal Matin.

Le renderer n'importe jamais ce module. Les appels reseau et les credentials
restent donc du cote Jarvis, conformement a la doctrine du projet.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

from core.config import reglage

from .models import (
    AgendaItem, DataSourceStatus, DataState, DigestItem, EditionMeta, Extras,
    Illustration, Importance, MorningEdition, NewsBundle, NewsItem, PersonalBlock,
    SourceRef, TaskItem, WeatherBlock,
)
from .daily_learning import construire_apprentissage_du_jour
from .normalizer import normaliser_edition
from .news_enrichment import enrichir_actualites

LOG = logging.getLogger("jarvis.signal_matin")
ROOT = Path(__file__).resolve().parents[2]

# Repli public, uniquement lorsqu'aucun flux personnel n'est declare. Les URL
# viennent de la page officielle des flux RSS du Monde. Elles restent
# remplacables dans config.yaml et ne transportent aucun identifiant.
DEFAULT_PUBLIC_FEEDS = [
    {"nom": "Le Monde", "categorie": "Monde", "url": "https://www.lemonde.fr/international/rss_full.xml"},
    {"nom": "Le Monde", "categorie": "France", "url": "https://www.lemonde.fr/politique/rss_full.xml"},
    {"nom": "Le Monde", "categorie": "Economie", "url": "https://www.lemonde.fr/economie/rss_full.xml"},
    {"nom": "Le Monde", "categorie": "Sciences", "url": "https://www.lemonde.fr/sciences/rss_full.xml"},
    {"nom": "Le Monde", "categorie": "Culture", "url": "https://www.lemonde.fr/culture/rss_full.xml"},
]

DEFAULT_TECH_FEEDS = [
    {"nom": "Le Monde Pixels", "categorie": "Tech", "url": "https://www.lemonde.fr/pixels/rss_full.xml"},
    {"nom": "Le Monde IA", "categorie": "IA", "url": "https://www.lemonde.fr/intelligence-artificielle/rss_full.xml"},
    {"nom": "Le Monde Culture web", "categorie": "Tech", "url": "https://www.lemonde.fr/cultures-web/rss_full.xml"},
]


class EditionSource(Protocol):
    def collect(self, now: dt.datetime) -> dict: ...


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: set[str]) -> str:
    for child in element:
        if _tag(child) in names and child.text:
            return " ".join(child.text.split())
    return ""


def _child_link(element: ET.Element) -> str | None:
    for child in element:
        if _tag(child) == "link":
            return child.attrib.get("href") or (child.text or "").strip() or None
    return None


def _plain_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return " ".join(value.split())


def _published_at(element: ET.Element) -> dt.datetime | None:
    value = _child_text(element, {"pubdate", "published", "updated", "date"})
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()


def _collect_rss(
    entries: list, now: dt.datetime, *, limit: int, max_age_hours: int,
    status_name: str, state: DataState, detail: str,
) -> tuple[list[NewsItem], DataSourceStatus]:
    """Lit plusieurs flux, garde les sujets recents et les entrelace."""
    buckets: list[list[NewsItem]] = []
    seen: set[str] = set()
    per_feed = max(2, math.ceil(limit / max(1, len(entries))))
    cutoff = now - dt.timedelta(hours=max_age_hours)
    future_limit = now + dt.timedelta(hours=6)
    for entry in entries:
        if isinstance(entry, str):
            name, url, category = "Source", entry, "Actualites"
        elif isinstance(entry, dict):
            name = str(entry.get("nom") or "Source")
            url = str(entry.get("url") or "")
            category = str(entry.get("categorie") or "Actualites")
        else:
            continue
        if not url:
            continue
        bucket: list[NewsItem] = []
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Signal-Matin/1.0"})
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = response.read()
            try:
                root = ET.fromstring(payload)
            except ET.ParseError:
                # Certains flux valides en navigateur contiennent ponctuellement
                # un caractere de controle ou un esperluette non echappee.
                # On repare uniquement ces deux erreurs XML courantes.
                repaired = payload.decode("utf-8", errors="replace")
                repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", repaired)
                repaired = re.sub(
                    r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)",
                    "&amp;", repaired,
                )
                root = ET.fromstring(repaired)
            for item in (node for node in root.iter() if _tag(node) in {"item", "entry"}):
                title = _child_text(item, {"title"})
                link = _child_link(item) or url
                dedupe_key = link or title.casefold()
                published = _published_at(item)
                if not title or dedupe_key in seen:
                    continue
                if published and (published < cutoff or published > future_limit):
                    continue
                seen.add(dedupe_key)
                summary = _child_text(item, {"description", "summary", "content"})
                bucket.append(NewsItem(
                    title=_plain_text(title),
                    category=category,
                    summary=_plain_text(summary) or "Resume non fourni par le flux.",
                    source=SourceRef(name=name, url=link, published_at=published),
                ))
                if len(bucket) >= per_feed:
                    break
            if bucket:
                buckets.append(bucket)
        except Exception as error:
            LOG.warning("Signal Matin : flux indisponible (%s): %s", name, error)
    result: list[NewsItem] = []
    while len(result) < limit and any(buckets):
        for bucket in buckets:
            if bucket and len(result) < limit:
                result.append(bucket.pop(0))
    if result:
        return result, DataSourceStatus(
            name=status_name, state=state,
            detail=f"{detail} ; sujets de moins de {max_age_hours} h",
            item_count=len(result),
        )
    return [], DataSourceStatus(
        name=status_name, state=DataState.UNAVAILABLE,
        detail=f"Aucun sujet de moins de {max_age_hours} h n'a pu etre lu.",
    )


class RssSource:
    """Flux declares localement ; une panne d'un flux n'arrete pas l'edition."""

    def collect(self, now: dt.datetime) -> tuple[list[NewsItem], DataSourceStatus]:
        entries = reglage("signal_matin.flux", reglage("journal_matin.flux", [])) or []
        fallback = not entries and bool(reglage("signal_matin.actualites_publiques_par_defaut", True))
        if fallback:
            entries = DEFAULT_PUBLIC_FEEDS
        if not entries:
            return [], DataSourceStatus(
                name="Actualites", state=DataState.UNAVAILABLE,
                detail="Aucun flux RSS configure ; aucun article n'est invente.",
            )
        configured_limit = int(reglage("signal_matin.nombre_actualites", 12) or 12)
        fallback_limit = int(reglage("signal_matin.nombre_actualites_repli", 18) or 18)
        limit = max(1, min(fallback_limit if fallback else configured_limit, 36))
        max_age = max(12, min(int(reglage("signal_matin.actualites_age_max_heures", 48) or 48), 168))
        return _collect_rss(
            entries, now, limit=limit, max_age_hours=max_age,
            status_name="Actualites",
            state=DataState.FALLBACK if fallback else DataState.LIVE,
            detail="Flux publics de repli" if fallback else "Flux RSS configures",
        )


class TechRssSource:
    """Cahier tech distinct pour garantir une vraie profondeur editoriale."""

    def collect(self, now: dt.datetime) -> tuple[list[NewsItem], DataSourceStatus]:
        entries = reglage("signal_matin.flux_tech", []) or []
        fallback = not entries and bool(reglage("signal_matin.actualites_publiques_par_defaut", True))
        if fallback:
            entries = DEFAULT_TECH_FEEDS
        if not entries:
            return [], DataSourceStatus(
                name="Actualites tech", state=DataState.UNAVAILABLE,
                detail="Aucun flux tech configure.",
            )
        limit = max(3, min(int(reglage("signal_matin.nombre_actualites_tech", 6) or 6), 12))
        max_age = max(24, min(int(reglage("signal_matin.tech_age_max_heures", 72) or 72), 168))
        return _collect_rss(
            entries, now, limit=limit, max_age_hours=max_age,
            status_name="Actualites tech",
            state=DataState.FALLBACK if fallback else DataState.LIVE,
            detail="Veille tech publique" if fallback else "Flux tech configures",
        )


def _weather() -> tuple[WeatherBlock | None, DataSourceStatus]:
    try:
        from tools import meteo as meteo_tool
        data = meteo_tool._open_meteo(
            "current=temperature_2m,weather_code,wind_speed_10m"
            "&daily=temperature_2m_min,temperature_2m_max&forecast_days=1"
        )
        current = data["current"]
        code = int(current.get("weather_code", -1))
        condition = meteo_tool._CODES_METEO.get(code, "temps variable")
        location = str(meteo_tool._LIEU.get("ville") or "Position locale")
        temperature = float(current["temperature_2m"])
        wind = float(current.get("wind_speed_10m", 0))
        daily = data.get("daily") or {}
        low = (daily.get("temperature_2m_min") or [None])[0]
        high = (daily.get("temperature_2m_max") or [None])[0]
        advice = "Prevois de quoi rester au sec." if any(
            word in condition for word in ("pluie", "averse", "bruine", "orage")
        ) else "Conditions calmes pour commencer la journee."
        block = WeatherBlock(
            location=location,
            condition=condition.capitalize(),
            temperature_c=round(temperature),
            low_c=round(float(low)) if low is not None else None,
            high_c=round(float(high)) if high is not None else None,
            wind_kmh=round(wind),
            summary=f"{condition.capitalize()}, avec un vent autour de {round(wind)} km/h.",
            advice=advice,
        )
        return block, DataSourceStatus(
            name="Meteo", state=DataState.LIVE, detail="Open-Meteo", item_count=1,
        )
    except Exception as error:
        LOG.info("Signal Matin : meteo indisponible: %s", error)
        return None, DataSourceStatus(
            name="Meteo", state=DataState.UNAVAILABLE,
            detail="Service meteo non joignable.",
        )


def _event_end(event: dict, all_day: bool) -> dt.datetime | None:
    end = event.get("end", {})
    key = "date" if all_day else "dateTime"
    value = end.get(key)
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()


def _agenda(now: dt.datetime) -> tuple[list[AgendaItem], DataSourceStatus]:
    try:
        token = Path(reglage("agenda.token", "google_token.json") or "google_token.json")
        token = token if token.is_absolute() else ROOT / token
        if not reglage("signal_matin.agenda", True):
            return [], DataSourceStatus(
                name="Agenda", state=DataState.DISABLED, detail="Exclu par la configuration.",
            )
        if not token.exists():
            return [], DataSourceStatus(
                name="Agenda", state=DataState.UNAVAILABLE,
                detail="Connexion Google Agenda a retablir sur ce PC.",
            )
        from tools import agenda as agenda_tool
        service = agenda_tool._service()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)
        events: list[AgendaItem] = []
        for calendar_id, info in agenda_tool._calendriers(service).items():
            try:
                response = service.events().list(
                    calendarId=calendar_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()
            except Exception:
                continue
            for event in response.get("items", []):
                event_start, all_day = agenda_tool._debut_ev(event)
                if event_start is None:
                    continue
                events.append(AgendaItem(
                    title=str(event.get("summary") or "Sans titre"),
                    start=event_start,
                    end=_event_end(event, all_day),
                    all_day=all_day,
                    location=str(event.get("location") or ""),
                    note=str(info.get("nom") or ""),
                ))
        events.sort(key=lambda item: item.start or start)
        return events[:24], DataSourceStatus(
            name="Agenda", state=DataState.LIVE, detail="Google Agenda",
            item_count=len(events[:24]),
        )
    except Exception as error:
        LOG.info("Signal Matin : agenda indisponible: %s", error)
        return [], DataSourceStatus(
            name="Agenda", state=DataState.UNAVAILABLE,
            detail="Google Agenda n'a pas pu etre lu.",
        )


def _configured_tasks(key: str) -> list[TaskItem]:
    values = reglage(f"signal_matin.{key}", []) or []
    return [TaskItem(title=str(value)) for value in values if str(value).strip()]


def _date_time(value: object) -> dt.datetime | None:
    try:
        date = dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return dt.datetime.combine(date, dt.time(18)).astimezone()


def _content_tasks(now: dt.datetime) -> tuple[list[TaskItem], DataSourceStatus]:
    if not reglage("signal_matin.suivi", True):
        return [], DataSourceStatus(
            name="Suivi contenu", state=DataState.DISABLED,
            detail="Exclu par la configuration.",
        )
    try:
        from tools import suivi
        if not suivi._fichier().exists():
            return [], DataSourceStatus(
                name="Suivi contenu", state=DataState.UNAVAILABLE,
                detail="Aucun fichier local de suivi.",
            )
        tasks: list[TaskItem] = []
        for item in suivi._charger():
            if str(item.get("statut") or "") == "publie":
                continue
            due = _date_time(item.get("deadline"))
            urgent = due is not None and due.date() <= now.date() + dt.timedelta(days=3)
            context = " · ".join(filter(None, [
                str(item.get("statut") or "").capitalize(),
                str(item.get("plateforme") or ""),
            ]))
            title = str(item.get("titre") or "").strip()
            if title:
                tasks.append(TaskItem(
                    title=title, due=due, context=context,
                    importance=Importance.HIGH if urgent else Importance.NORMAL,
                ))
        return tasks[:8], DataSourceStatus(
            name="Suivi contenu", state=DataState.LOCAL,
            detail="Fichier Jarvis local", item_count=len(tasks[:8]),
        )
    except Exception as error:
        LOG.info("Signal Matin : suivi de contenu indisponible: %s", error)
        return [], DataSourceStatus(
            name="Suivi contenu", state=DataState.UNAVAILABLE,
            detail="Le suivi local n'a pas pu etre lu.",
        )


def _loopstr_tasks() -> tuple[list[TaskItem], DataSourceStatus]:
    if not reglage("signal_matin.loopstr", True):
        return [], DataSourceStatus(
            name="Loopstr", state=DataState.DISABLED, detail="Exclu par la configuration.",
        )
    if not reglage("loopstr.url", ""):
        return [], DataSourceStatus(
            name="Loopstr", state=DataState.UNAVAILABLE, detail="Flux iCal non configure.",
        )
    try:
        from tools import loopstr
        deadlines, absences, _label = loopstr._echeances("cette semaine")
        tasks = [TaskItem(
            title=title, due=due, context="Partenariat",
            importance=Importance.HIGH if due.date() <= dt.date.today() + dt.timedelta(days=2)
            else Importance.NORMAL,
        ) for due, title in (deadlines or [])]
        tasks.extend(TaskItem(title=title, due=due, context="Indisponibilite")
                     for due, title in (absences or []))
        return tasks[:8], DataSourceStatus(
            name="Loopstr", state=DataState.LIVE, detail="Flux iCal",
            item_count=len(tasks[:8]),
        )
    except Exception as error:
        LOG.info("Signal Matin : Loopstr indisponible: %s", error)
        return [], DataSourceStatus(
            name="Loopstr", state=DataState.UNAVAILABLE,
            detail="Le flux iCal n'a pas pu etre lu.",
        )


def _hermes_digest() -> tuple[list[DigestItem], DataSourceStatus]:
    value = str(reglage("signal_matin.hermes_fichier", "") or "").strip()
    if not value:
        return [], DataSourceStatus(
            name="Hermes", state=DataState.DISABLED, detail="Aucun brief local configure.",
        )
    path = Path(value)
    path = path if path.is_absolute() else ROOT / path
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return [], DataSourceStatus(
            name="Hermes", state=DataState.UNAVAILABLE, detail="Brief local introuvable.",
        )
    items = [DigestItem(title="Veille preparee par Hermes", summary=content[:900])] if content else []
    return items, DataSourceStatus(
        name="Hermes", state=DataState.LOCAL, detail="Brief local",
        item_count=len(items),
    )


def _instagram_digest() -> tuple[list[DigestItem], DataSourceStatus]:
    if not bool(reglage("signal_matin.reseaux_sociaux", True)):
        return [], DataSourceStatus(
            name="Instagram", state=DataState.DISABLED,
            detail="Exclu par la configuration.",
        )
    try:
        from tools import instagram as instagram_tool
        comptes = instagram_tool._comptes()
        if not comptes:
            return [], DataSourceStatus(
                name="Instagram", state=DataState.DISABLED,
                detail="Aucun compte Instagram configure.",
            )
        try:
            instagram_tool.rafraichir_tokens()
        except Exception:
            pass
        history = instagram_tool._charger_historique()
        today = dt.date.today().isoformat()
        digests = []
        for account in comptes:
            try:
                snapshot = instagram_tool._instantane(account)
            except Exception as error:
                LOG.info("Signal Matin : compte Instagram indisponible: %s", error)
                continue
            by_day = history.get(account["nom"], {})
            previous = instagram_tool._veille(by_day, today)
            by_day[today] = snapshot
            for old in sorted(by_day)[:-30]:
                by_day.pop(old, None)
            history[account["nom"]] = by_day
            phrase = instagram_tool._phrase(account, snapshot, previous)
            label = (f"@{snapshot.get('username')}" if snapshot.get("username")
                     else account["nom"])
            summary = phrase.split(" : ", 1)[1] if " : " in phrase else phrase
            digests.append(DigestItem(
                title=f"Instagram - {label}",
                summary=summary,
                importance=Importance.HIGH,
            ))
        instagram_tool._sauver_historique(history)
        if not digests:
            return [], DataSourceStatus(
                name="Instagram", state=DataState.UNAVAILABLE,
                detail="Les statistiques Instagram n'ont pas pu etre lues.",
            )
        return digests, DataSourceStatus(
            name="Instagram", state=DataState.LIVE,
            detail="Statistiques Graph officielles", item_count=len(digests),
        )
    except Exception as error:
        LOG.info("Signal Matin : Instagram indisponible: %s", error)
        return [], DataSourceStatus(
            name="Instagram", state=DataState.UNAVAILABLE,
            detail="Les statistiques Instagram n'ont pas pu etre lues.",
        )


def _discord_digest() -> tuple[list[DigestItem], DataSourceStatus]:
    if not bool(reglage("signal_matin.discord", True)):
        return [], DataSourceStatus(
            name="Discord", state=DataState.DISABLED,
            detail="Exclu par la configuration.",
        )
    try:
        from tools import discord_bot
        stats, error = discord_bot.digest_journal(
            heures=int(reglage("signal_matin.discord_heures", 24) or 24),
        )
        if error or stats is None:
            return [], DataSourceStatus(
                name="Discord", state=DataState.UNAVAILABLE,
                detail="Le bot Discord n'a pas pu produire son releve.",
            )
        actifs = ", ".join(
            f"{row['serveur']}/#{row['salon']} ({row['messages']})"
            for row in stats["actifs"]
        )
        summary = (
            f"{stats['messages']} messages dans {stats['salons']} salons sur les "
            f"dernieres 24 heures ; {stats['mentions']} mention(s) pour toi."
        )
        if actifs:
            summary += f" Les espaces les plus actifs : {actifs}."
        return [DigestItem(
            title="Discord - l'activite de la communaute",
            summary=summary,
        )], DataSourceStatus(
            name="Discord", state=DataState.LIVE,
            detail="Agregats du bot, sans contenu de message",
            item_count=stats["messages"],
        )
    except Exception as error:
        LOG.info("Signal Matin : Discord indisponible: %s", error)
        return [], DataSourceStatus(
            name="Discord", state=DataState.UNAVAILABLE,
            detail="Le bot Discord n'a pas pu produire son releve.",
        )


def _mail_digest() -> tuple[list[DigestItem], DataSourceStatus]:
    if not reglage("signal_matin.mails", reglage("journal_matin.mails", False)):
        return [], DataSourceStatus(
            name="E-mails", state=DataState.DISABLED,
            detail="Exclus par defaut pour proteger la vie privee.",
        )
    try:
        from tools import mail
        if not mail._mail_configure():
            return [], DataSourceStatus(
                name="E-mails", state=DataState.UNAVAILABLE,
                detail="Messagerie non configuree.",
            )
        summary = str(mail.lire_mails(3) or "").strip()
        if summary.lower().startswith("impossible"):
            raise RuntimeError("mail read failed")
        items = [DigestItem(title="Boite de reception", summary=summary)] if summary else []
        return items, DataSourceStatus(
            name="E-mails", state=DataState.LIVE, detail="Gmail en lecture seule",
            item_count=len(items),
        )
    except Exception as error:
        LOG.info("Signal Matin : messagerie indisponible: %s", error)
        return [], DataSourceStatus(
            name="E-mails", state=DataState.UNAVAILABLE,
            detail="La messagerie n'a pas pu etre lue.",
        )


def _free_window(items: list[AgendaItem], now: dt.datetime) -> str:
    timed = sorted((item for item in items if item.start and not item.all_day), key=lambda x: x.start)
    if not timed:
        return ""
    cursor = max(now, now.replace(hour=8, minute=0, second=0, microsecond=0))
    day_end = now.replace(hour=19, minute=0, second=0, microsecond=0)
    gaps: list[tuple[dt.timedelta, dt.datetime, dt.datetime]] = []
    for item in timed:
        start = item.start.astimezone()
        if start > cursor:
            gaps.append((start - cursor, cursor, start))
        cursor = max(cursor, (item.end or item.start).astimezone())
    if day_end > cursor:
        gaps.append((day_end - cursor, cursor, day_end))
    if not gaps:
        return ""
    duration, start, end = max(gaps, key=lambda gap: gap[0])
    if duration < dt.timedelta(minutes=30):
        return ""
    return f"Plus grande plage libre : {start:%H h %M} - {end:%H h %M}."


def construire_edition_live(
    now: dt.datetime | None = None,
    mode: str = "auto",
) -> MorningEdition:
    now = now or dt.datetime.now().astimezone()
    items, news_status = RssSource().collect(now)
    dedicated_tech, tech_status = TechRssSource().collect(now)
    news_items = [item for item in items if item.category.casefold() not in {"tech", "ia", "ia & tech"}]
    inline_tech = [item for item in items if item.category.casefold() in {"tech", "ia", "ia & tech"}]
    tech_items: list[NewsItem] = []
    seen_tech: set[str] = set()
    for item in [*dedicated_tech, *inline_tech]:
        key = str(item.source.url or "") or item.title.casefold()
        if key in seen_tech:
            continue
        seen_tech.add(key)
        tech_items.append(item)
    lead = news_items[0] if news_items else None
    if lead:
        lead = lead.model_copy(update={
            "importance": Importance.HIGH,
            "illustration": Illustration(
                type="engraving",
                alt="Illustration editoriale au trait",
                caption="Illustration editoriale locale ; le contenu factuel vient de la source citee.",
            ),
        })
    bundle = NewsBundle(lead=lead)
    category_map = {
        "monde": "world", "france": "france", "economie": "economy",
        "societe": "society", "sciences": "science", "science": "science",
        "culture": "culture",
    }
    for item in news_items[1:]:
        target = category_map.get(item.category.lower(), "world")
        getattr(bundle, target).append(item)

    # L'ordre editorial differe volontairement de l'ordre entrelace des flux.
    # On enrichit donc APRES le classement par rubrique : les six textes lus
    # seront exactement ceux imprimes sur les deux pages "En bref, en detail".
    detail_default = news_status.state == DataState.FALLBACK
    if bool(reglage("signal_matin.actualites_detaillees", detail_default)):
        detail_limit = max(0, min(
            int(reglage("signal_matin.nombre_actualites_detaillees", 6) or 6), 9,
        ))
        targets = ([bundle.lead] if bundle.lead else []) + bundle.all_secondary()[:detail_limit]
        proxy = news_status.state == DataState.FALLBACK or bool(
            reglage("signal_matin.extracteur_public", False))
        enriched = enrichir_actualites(
            targets, limite=len(targets), allow_public_proxy=proxy,
        )
        by_url = {str(item.source.url or ""): item for item in enriched}

        def replace(item: NewsItem) -> NewsItem:
            return by_url.get(str(item.source.url or ""), item)

        bundle = bundle.model_copy(update={
            "lead": replace(bundle.lead) if bundle.lead else None,
            "world": [replace(item) for item in bundle.world],
            "france": [replace(item) for item in bundle.france],
            "economy": [replace(item) for item in bundle.economy],
            "society": [replace(item) for item in bundle.society],
            "science": [replace(item) for item in bundle.science],
            "culture": [replace(item) for item in bundle.culture],
        })

    curiosity_candidates = [*bundle.science, *bundle.culture]
    tech_detail_limit = max(1, min(
        int(reglage("signal_matin.nombre_actualites_tech_detaillees", 5) or 5), 8,
    ))
    curiosity_limit = max(1, min(
        int(reglage("signal_matin.nombre_curiosites_detaillees", 4) or 4), 6,
    ))
    deep_targets = [
        *tech_items[:tech_detail_limit],
        *curiosity_candidates[:curiosity_limit],
    ]
    deep_proxy = (
        news_status.state == DataState.FALLBACK
        or tech_status.state == DataState.FALLBACK
        or bool(reglage("signal_matin.extracteur_public", False))
    )
    enriched_deep = enrichir_actualites(
        deep_targets, limite=len(deep_targets), allow_public_proxy=deep_proxy,
    )
    tech_news = enriched_deep[:min(tech_detail_limit, len(tech_items))]
    curiosity_start = min(tech_detail_limit, len(tech_items))
    curiosity_news = enriched_deep[curiosity_start:curiosity_start + curiosity_limit]

    weather, weather_status = _weather()
    agenda, agenda_status = _agenda(now)
    content_tasks, content_status = _content_tasks(now)
    loopstr_tasks, loopstr_status = _loopstr_tasks()
    hermes, hermes_status = _hermes_digest()
    mails, mail_status = _mail_digest()
    social, social_status = _instagram_digest()
    community, community_status = _discord_digest()
    configured_priorities = _configured_tasks("priorites")
    configured_reminders = _configured_tasks("rappels")
    priorities = [*configured_priorities, *content_tasks]
    reminders = [*configured_reminders, *loopstr_tasks]
    note = str(reglage("signal_matin.note", "") or "").strip()
    if not note and priorities:
        note = f"Commence par : {priorities[0].title}."

    tech = [DigestItem(
        title=item.title,
        summary=(item.expanded_summary or item.summary)[:880],
        source=item.source,
        importance=item.importance,
    ) for item in tech_news]

    first = dt.date(now.year, 1, 1)
    edition = MorningEdition(
        generated_at=now,
        edition=EditionMeta(date=now.date(), number=(now.date() - first).days + 1),
        sources=[
            weather_status, agenda_status, news_status, tech_status, content_status,
            loopstr_status, hermes_status, mail_status, social_status,
            community_status,
        ],
        weather=weather,
        agenda=agenda,
        priorities=priorities[:12],
        reminders=reminders[:16],
        news=bundle,
        tech=tech,
        tech_news=tech_news,
        curiosity_news=curiosity_news,
        watch=hermes,
        newsletter_digest=mails,
        social_digest=social,
        community_digest=community,
        personal=PersonalBlock(
            greeting=str(reglage("signal_matin.salutation", "Bonjour.") or "Bonjour."),
            note=note,
            free_window=_free_window(agenda, now),
        ),
        extras=Extras(
            stat_of_day=DigestItem(
                title=str(len(agenda)),
                summary="rendez-vous dans l'agenda aujourd'hui.",
            ) if agenda_status.state == DataState.LIVE else None,
        ),
        learning=construire_apprentissage_du_jour(now.date()),
    )
    return normaliser_edition(edition, mode=mode)
