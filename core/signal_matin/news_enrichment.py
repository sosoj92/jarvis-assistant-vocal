"""Enrichissement facultatif des articles publics de Signal Matin.

Le texte source est lu en memoire, resume par le fournisseur cloud deja choisi
dans Jarvis, puis immediatement oublie. Seule la synthese francaise est conservee
dans l'edition. Un echec reseau ou LLM laisse le resume RSS intact.
"""
from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from core import cloud
from core.config import reglage

from .models import NewsItem

LOG = logging.getLogger("jarvis.signal_matin")


class _ArticleParser(HTMLParser):
    """Petit extracteur sans dependance, limite aux paragraphes editoriaux."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_article = 0
        self.in_p = 0
        self.current: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "article":
            self.in_article += 1
        if tag == "p" and self.in_article:
            self.in_p += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self.in_p:
            text = " ".join("".join(self.current).split())
            if len(text) >= 45:
                self.paragraphs.append(text)
            self.current.clear()
            self.in_p -= 1
        if tag == "article" and self.in_article:
            self.in_article -= 1

    def handle_data(self, data: str) -> None:
        if self.in_p:
            self.current.append(data)


def _public_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.casefold()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            addresses = {row[4][0] for row in socket.getaddrinfo(host, None)}
        except OSError:
            return False
        return bool(addresses) and all(
            not ipaddress.ip_address(address).is_private
            and not ipaddress.ip_address(address).is_loopback
            and not ipaddress.ip_address(address).is_link_local
            and not ipaddress.ip_address(address).is_reserved
            for address in addresses
        )
    except (ValueError, TypeError):
        return False


def _download(url: str, timeout: float = 18) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Signal-Matin/1.0 (+local personal digest)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "")
        if "text/" not in content_type and "json" not in content_type:
            return ""
        payload = response.read(1_500_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _plain_markdown(value: str) -> str:
    value = value.partition("Markdown Content:")[2] or value
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"^\s*#{1,6}\s*", "", value, flags=re.M)
    value = re.sub(r"^\s*[-*|].*$", " ", value, flags=re.M)
    value = re.sub(r"\s+", " ", html.unescape(value))
    return value.strip()


def _article_text(url: str, *, allow_public_proxy: bool) -> str:
    if not _public_http_url(url):
        return ""
    try:
        raw = _download(url)
        parser = _ArticleParser()
        parser.feed(raw)
        direct = "\n\n".join(parser.paragraphs)
        if len(direct) >= 900:
            return direct[:7_000]
    except Exception as error:
        LOG.info("Signal Matin : article direct indisponible (%s): %s", url, error)

    # Le proxy de lecture ne recoit que des URL deja verifiees comme publiques,
    # et uniquement pour les flux publics de repli ou sur opt-in explicite.
    if not allow_public_proxy:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        target = "http://" + parsed.netloc + parsed.path
        if parsed.query:
            target += "?" + parsed.query
        return _plain_markdown(_download("https://r.jina.ai/" + target, timeout=30))[:7_000]
    except Exception as error:
        LOG.info("Signal Matin : extracteur public indisponible (%s): %s", url, error)
        return ""


def _json_payload(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        value = json.loads(match.group(0))
    except (TypeError, ValueError):
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def enrichir_actualites(
    items: list[NewsItem], *, limite: int = 6, allow_public_proxy: bool = False,
) -> list[NewsItem]:
    """Ajoute une synthese developpee aux premiers articles accessibles."""
    if not items or limite <= 0 or not cloud.disponible():
        return items
    documents: list[dict[str, str | int]] = []
    for index, item in enumerate(items[:limite]):
        if item.expanded_summary:
            continue
        url = str(item.source.url or "")
        article = _article_text(url, allow_public_proxy=allow_public_proxy) if url else ""
        if len(article) < 350:
            continue
        documents.append({
            "id": index,
            "titre": item.title,
            "resume_rss": item.summary,
            "article": article,
        })
    if not documents:
        return items

    systeme = (
        "Tu es secretaire de redaction d'un quotidien francais. Redige des syntheses "
        "factuelles et originales a partir des seuls textes fournis. Ne copie aucune "
        "phrase, n'ajoute aucun fait, ne formule pas d'opinion et ne mentionne ni API "
        "ni methode technique. Reponds uniquement par le tableau JSON demande."
    )
    prompt = (
        "Pour chaque article, produis un champ developpe de 110 a 160 mots en 2 ou "
        "3 paragraphes separes par \\n. Le premier paragraphe explique le fait, le "
        "second apporte le contexte et, si la source le permet, les consequences. "
        "Conserve exactement l'id. Format: [{\"id\":0,\"developpe\":\"...\"}].\n\n"
        + json.dumps(documents, ensure_ascii=False)
    )
    try:
        response = cloud.repondre_texte(
            systeme,
            [{"role": "user", "content": prompt}],
            max_tokens=max(1800, len(documents) * 360),
            nom_modele=str(reglage("signal_matin.modele_actualites", "") or ""),
        )
        expanded = {
            int(row["id"]): "\n\n".join(
                paragraph.strip() for paragraph in str(row.get("developpe") or "").splitlines()
                if paragraph.strip()
            )[:3200]
            for row in _json_payload(response)
            if str(row.get("id", "")).isdigit() and str(row.get("developpe") or "").strip()
        }
    except Exception as error:
        LOG.warning("Signal Matin : syntheses detaillees indisponibles: %s", error)
        return items

    return [
        item.model_copy(update={"expanded_summary": expanded[index]})
        if index in expanded else item
        for index, item in enumerate(items)
    ]
