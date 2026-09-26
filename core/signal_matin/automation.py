"""Declenchement automatique et idempotent de Signal Matin.

Le mode ``horaire`` reste gere par le Planificateur de taches Windows. Le mode
``premier_demarrage`` est appele par la scene du premier brief quotidien de
Jarvis. Un marqueur local, ignore par Git, empeche toute seconde impression le
meme jour, y compris si Jarvis est relance ou si la scene est forcee.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from pathlib import Path

from core.config import reglage

from .normalizer import ecrire_edition
from .pdf import generer_pdf
from .printer import PrintResult, WindowsRasterPrinter
from .renderer import write_html
from .sources import construire_edition_live

ROOT = Path(__file__).resolve().parents[2]
LOG = logging.getLogger(__name__)

_ETAT_IMPRESSION = ROOT / "notes" / ".signal_matin_impression"
_VERROU = threading.Lock()


def _declenchement() -> str:
    valeur = str(reglage("signal_matin.declenchement", "desactive") or "")
    return valeur.strip().lower().replace("-", "_").replace(" ", "_")


def _premier_demarrage_actif() -> bool:
    return (
        bool(reglage("signal_matin.actif", False))
        and bool(reglage("signal_matin.imprimer", False))
        and _declenchement() == "premier_demarrage"
    )


def _reserver_impression_du_jour(
    jour: dt.date | None = None,
    chemin: Path | None = None,
) -> bool:
    """Reserve atomiquement l'unique tentative quotidienne.

    Le marqueur est ecrit avant la generation. Une erreur d'API ou d'imprimante
    ne provoque donc pas plusieurs impressions lors des relances de Jarvis.
    """
    jour = jour or dt.date.today()
    chemin = chemin or _ETAT_IMPRESSION
    valeur = jour.isoformat()
    with _VERROU:
        try:
            if chemin.read_text(encoding="utf-8").strip() == valeur:
                return False
        except (FileNotFoundError, OSError):
            pass
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(valeur, encoding="utf-8")
        return True


def _chemins_sortie(jour: dt.date) -> tuple[Path, Path, Path]:
    dossier = Path(str(reglage("signal_matin.dossier_sortie", "output") or "output"))
    if not dossier.is_absolute():
        dossier = ROOT / dossier
    nom = f"{jour.isoformat()}-signal-matin"
    return (
        dossier / "pdf" / f"{nom}.pdf",
        dossier / "preview" / f"{nom}.html",
        dossier / "data" / f"{nom}.json",
    )


def _generer_et_imprimer() -> PrintResult:
    maintenant = dt.datetime.now().astimezone()
    mode = str(reglage("signal_matin.densite", "auto") or "auto").lower()
    if mode not in {"auto", "compact", "standard", "extended"}:
        mode = "auto"

    edition = construire_edition_live(now=maintenant, mode=mode)
    pdf, html, data = _chemins_sortie(maintenant.date())
    ecrire_edition(edition, data)
    write_html(edition, html)
    generer_pdf(edition, pdf, html_path=html)

    imprimante = str(reglage("signal_matin.imprimante", "") or "")
    recto_verso = bool(reglage("signal_matin.recto_verso", False))
    return WindowsRasterPrinter(
        imprimante,
        duplex=recto_verso,
    ).print_pdf(pdf, execute=True)


def _executer_impression() -> None:
    try:
        resultat = _generer_et_imprimer()
        LOG.info(
            "Signal Matin imprime au premier brief : %s page(s) sur %s",
            resultat.pages,
            resultat.printer,
        )
    except Exception:
        LOG.exception("Echec de l'impression Signal Matin au premier brief")


def lancer_impression_premier_brief_async() -> bool:
    """Lance l'impression du premier brief du jour et renvoie si elle a demarre."""
    if not _premier_demarrage_actif():
        return False
    if not _reserver_impression_du_jour():
        return False
    threading.Thread(
        target=_executer_impression,
        name="signal_matin_premier_brief",
        daemon=True,
    ).start()
    return True
