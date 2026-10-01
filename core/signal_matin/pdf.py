"""Rendu Chromium exact A4 et inspection de la mise en page."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import MorningEdition
from .renderer import render_html, write_html


def _browser_candidates() -> list[Path]:
    values = [
        os.environ.get("PROGRAMFILES", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
    ]
    return [Path(value) for value in values if value and Path(value).is_file()]


def _launch_browser(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as first_error:
        for executable in _browser_candidates():
            try:
                return playwright.chromium.launch(headless=True, executable_path=str(executable))
            except Exception:
                continue
        raise RuntimeError(
            "Chromium est indisponible. Lance : uv run playwright install chromium"
        ) from first_error


def _measure(page) -> list[dict[str, Any]]:
    return page.eval_on_selector_all(
        ".sheet",
        """pages => pages.map((p, index) => {
          const content = p.querySelector('.page-content');
          const rect = p.getBoundingClientRect();
          return {
            page: index + 1,
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            content_client_height: content ? content.clientHeight : 0,
            content_scroll_height: content ? content.scrollHeight : 0,
            overflow: content ? content.scrollHeight > content.clientHeight + 2 : false,
            used_ratio: content && content.children.length
              ? Math.round((Math.max(...[...content.children].map(
                  child => child.getBoundingClientRect().bottom
                )) - content.getBoundingClientRect().top) / content.clientHeight * 1000) / 1000
              : 0,
            adaptive: p.dataset.adaptiveContinuation === 'true',
            sparse: p.classList.contains('adaptive-sparse')
          };
        })""",
    )


def _paginate_adaptive(page) -> dict[str, int]:
    """Laisse le document creer/repartir ses pages de continuation."""
    result = page.evaluate(
        """() => window.SignalMatinPagination
          ? window.SignalMatinPagination.paginate()
          : {pages: document.querySelectorAll('.sheet').length, unresolved: 0}
        """
    )
    return result or {"pages": 0, "unresolved": 0}


def _fit_moderate_overflow(
    page,
    layout: list[dict[str, Any]],
    *,
    minimum_scale: float = 0.85,
) -> list[dict[str, Any]]:
    """Reduit seulement les pages legerement trop longues.

    Les sources live n'ont pas toujours la meme longueur. Un depassement modere
    ne doit pas annuler tout le journal du matin : Chromium agrandit ici la
    hauteur logique du contenu et applique un zoom equivalent, sans changer le
    format A4 physique. Les gros depassements restent des erreurs afin de ne pas
    produire une page minuscule ou illisible.
    """
    overflowing = [item for item in layout if item["overflow"]]
    if not overflowing:
        return layout

    for _ in range(4):
        page.evaluate(
            """({ overflowing, minimumScale }) => {
              for (const item of overflowing) {
                const sheet = document.querySelector(`.sheet[data-page="${item.page}"]`);
                const content = sheet && sheet.querySelector('.page-content');
                if (!content || !item.content_scroll_height) continue;

                const currentScale = Number(content.dataset.autoFit || 1);
                const physicalHeight = Number(
                  content.dataset.autoFitPhysicalHeight ||
                  content.clientHeight * currentScale
                );
                const nextScale = Math.min(
                  1,
                  currentScale *
                    ((item.content_client_height - 3) / item.content_scroll_height)
                );
                if (nextScale < minimumScale) continue;

                content.dataset.autoFitPhysicalHeight = String(physicalHeight);
                content.dataset.autoFit = String(nextScale);
                content.style.zoom = String(nextScale);
                content.style.height = `${physicalHeight / nextScale}px`;
              }
            }""",
            {"overflowing": overflowing, "minimumScale": minimum_scale},
        )
        layout = _measure(page)
        overflowing = [item for item in layout if item["overflow"]]
        if not overflowing:
            break
    return layout


def inspecter_html(html_text: str) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_content(html_text, wait_until="load")
            page.evaluate("document.fonts.ready")
            _paginate_adaptive(page)
            return _measure(page)
        finally:
            browser.close()


def generer_pdf(
    edition: MorningEdition,
    pdf_path: Path,
    html_path: Path | None = None,
    verifier_debordement: bool = True,
) -> Path:
    """Compose puis imprime le HTML en PDF A4, sans en-tete navigateur."""
    from playwright.sync_api import sync_playwright

    html_text = render_html(edition)
    if html_path is not None:
        write_html(edition, html_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_content(html_text, wait_until="load")
            page.evaluate("document.fonts.ready")
            _paginate_adaptive(page)
            layout = _measure(page)
            # Une variation minime peut encore venir d'une police ou d'un pilote.
            # Au-dela de 5 %, la pagination a deja cree une vraie page de suite.
            layout = _fit_moderate_overflow(page, layout, minimum_scale=0.95)
            overflows = [item["page"] for item in layout if item["overflow"]]
            if verifier_debordement and overflows:
                raise RuntimeError(
                    "Contenu trop long sur les pages : " + ", ".join(map(str, overflows))
                )
            page.emulate_media(media="print")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=False,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()
    return pdf_path
