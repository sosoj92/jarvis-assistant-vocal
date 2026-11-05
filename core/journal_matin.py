"""Facade historique du journal du matin, maintenant rendu par Signal Matin.

Le contenu reste sur le PC. Les connecteurs existants de Jarvis sont reutilises
quand ils sont deja configures ; une source indisponible ne bloque pas le reste
du journal. Ce module ne fait que collecter et mettre en forme : l'impression
passe uniquement par ``core.signal_matin`` (``print --confirm``).
"""
from __future__ import annotations

import datetime as dt
import logging
import textwrap
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from core.config import reglage

LOG = logging.getLogger("jarvis.journal_matin")
RACINE = Path(__file__).resolve().parent.parent


def _chemin(cle: str, defaut: str) -> Path:
    valeur = Path(reglage(cle, defaut) or defaut)
    return valeur if valeur.is_absolute() else RACINE / valeur


def _nom_balise(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _enfant_texte(element: ET.Element, noms: tuple[str, ...]) -> str:
    for enfant in element:
        if _nom_balise(enfant) in noms and enfant.text:
            return " ".join(enfant.text.split())
    return ""


def lire_actualites() -> list[tuple[str, str]]:
    """Lit les titres des flux RSS/Atom declares dans config.yaml.

    Aucun flux n'est active par defaut : l'utilisatrice choisit les medias a
    imprimer. Seuls les titres et le nom de la source sont conserves.
    """
    flux = reglage("journal_matin.flux", []) or []
    limite = max(1, min(int(reglage("journal_matin.nombre_actualites", 5) or 5), 12))
    actualites: list[tuple[str, str]] = []
    for entree in flux:
        if isinstance(entree, str):
            nom, url = "Source", entree
        elif isinstance(entree, dict):
            nom = str(entree.get("nom") or "Source")
            url = str(entree.get("url") or "")
        else:
            continue
        if not url:
            continue
        try:
            requete = urllib.request.Request(
                url, headers={"User-Agent": "Jarvis-journal-matin/1.0"})
            with urllib.request.urlopen(requete, timeout=8) as reponse:
                racine = ET.fromstring(reponse.read())
            items = [e for e in racine.iter() if _nom_balise(e) in {"item", "entry"}]
            for item in items:
                titre = _enfant_texte(item, ("title",))
                if titre:
                    actualites.append((nom, titre))
                if len(actualites) >= limite:
                    return actualites
        except Exception as erreur:
            LOG.warning("Flux d'actualites indisponible (%s): %s", nom, erreur)
    return actualites


def _appel(fonction, defaut: str = "Non disponible.") -> str:
    try:
        valeur = str(fonction() or "").strip()
        return valeur or defaut
    except Exception as erreur:
        LOG.warning("Section du journal indisponible: %s", erreur)
        return defaut


def _agenda_pret() -> bool:
    token = _chemin("agenda.token", "google_token.json")
    return token.exists()


def collecter_sections() -> list[tuple[str, str]]:
    """Collecte les sections disponibles sans declencher d'OAuth interactif."""
    sections: list[tuple[str, str]] = []

    try:
        from tools.meteo import meteo
        sections.append(("METEO", _appel(meteo)))
    except Exception:
        sections.append(("METEO", "Non disponible."))

    if bool(reglage("journal_matin.agenda", True)) and _agenda_pret():
        try:
            from tools.agenda import get_events
            sections.append(("AGENDA DU JOUR", _appel(lambda: get_events("aujourd'hui"))))
        except Exception:
            sections.append(("AGENDA DU JOUR", "Non disponible."))

    try:
        from tools.mail import _mail_configure, lire_mails
        if _mail_configure() and bool(reglage("journal_matin.mails", True)):
            sections.append(("MAILS A VOIR", _appel(lambda: lire_mails(5, memoriser=False))))
    except Exception:
        pass

    try:
        from tools.loopstr import deadlines_brief
        echeances = _appel(deadlines_brief, "")
        if echeances:
            sections.append(("ECHEANCES", echeances))
    except Exception:
        pass

    flux = lire_actualites()
    if flux:
        sections.append(("ACTUALITES", "\n".join(f"- {source} : {titre}" for source, titre in flux)))

    fichier_hermes = str(reglage("journal_matin.hermes_fichier", "") or "").strip()
    if fichier_hermes:
        chemin = Path(fichier_hermes)
        chemin = chemin if chemin.is_absolute() else RACINE / chemin
        try:
            contenu = chemin.read_text(encoding="utf-8").strip()
            if contenu:
                sections.append(("VEILLE HERMES", contenu))
        except OSError:
            LOG.info("Brief Hermes absent ou illisible: %s", chemin)

    return sections


def _date_fr(date: dt.datetime) -> str:
    jours = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    mois = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
            "aout", "septembre", "octobre", "novembre", "decembre")
    return f"{jours[date.weekday()]} {date.day} {mois[date.month - 1]} {date.year}"


def construire_texte(
    maintenant: dt.datetime | None = None,
    sections: list[tuple[str, str]] | None = None,
) -> str:
    """Construit le contenu imprimable ; ``sections`` facilite les tests."""
    maintenant = maintenant or dt.datetime.now().astimezone()
    largeur = max(50, min(int(reglage("journal_matin.largeur", 82) or 82), 110))
    lignes = [
        "SIGNAL MATIN - LE JOURNAL ANTI-SCROLL",
        _date_fr(maintenant),
        "=" * min(largeur, 82),
        "",
    ]
    for titre, contenu in sections if sections is not None else collecter_sections():
        lignes.append(titre)
        lignes.append("-" * min(len(titre), largeur))
        for paragraphe in str(contenu).splitlines() or [""]:
            lignes.extend(textwrap.wrap(
                paragraphe,
                width=largeur,
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""])
        lignes.append("")
    lignes.append("Bonne journee.")
    return "\n".join(lignes).rstrip() + "\n"


def ecrire_journal(texte: str, maintenant: dt.datetime | None = None) -> Path:
    maintenant = maintenant or dt.datetime.now().astimezone()
    dossier = _chemin("journal_matin.dossier_sortie", "logs/journal_matin")
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"journal-{maintenant:%Y%m%d}.txt"
    chemin.write_text(texte, encoding="utf-8-sig")
    return chemin
