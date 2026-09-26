"""Facade historique du journal du matin, maintenant rendu par Signal Matin.

Le contenu reste sur le PC. Les connecteurs existants de Jarvis sont reutilises
quand ils sont deja configures ; une source indisponible ne bloque pas le reste
du journal. L'impression cible la file Windows configuree, sans la rendre
obligatoirement imprimante par defaut.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import tempfile
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
            sections.append(("MAILS A VOIR", _appel(lambda: lire_mails(5))))
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


def _infos_imprimantes() -> list[dict[str, str]]:
    """Interroge le spooler Windows sans imprimer ni modifier sa configuration."""
    if os.name != "nt":
        return []
    commande = (
        "Get-Printer | Select-Object Name,DriverName,PortName "
        "| ConvertTo-Json -Compress"
    )
    try:
        resultat = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", commande],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            check=False,
        )
        if resultat.returncode != 0 or not resultat.stdout.strip():
            return []
        donnees = json.loads(resultat.stdout)
        if isinstance(donnees, dict):
            donnees = [donnees]
        return [
            {str(cle): str(valeur or "") for cle, valeur in element.items()}
            for element in donnees if isinstance(element, dict)
        ]
    except (OSError, ValueError, subprocess.SubprocessError) as erreur:
        LOG.warning("Impossible de lire les imprimantes Windows: %s", erreur)
        return []


def _choisir_imprimante() -> dict[str, str]:
    nom_demande = str(reglage("journal_matin.imprimante", "") or "").strip().lower()
    imprimantes = _infos_imprimantes()
    if nom_demande:
        for imprimante in imprimantes:
            if imprimante.get("Name", "").strip().lower() == nom_demande:
                return imprimante
        raise RuntimeError(f"Imprimante configuree introuvable : {nom_demande}")

    candidates = [
        p for p in imprimantes
        if p.get("Name", "").lower() not in {
            "fax", "microsoft print to pdf", "onenote (desktop)"
        }
    ]
    if not candidates:
        raise RuntimeError("Aucune imprimante Windows compatible n'a ete trouvee.")
    if len(candidates) > 1:
        raise RuntimeError(
            "Plusieurs imprimantes sont disponibles. Renseigne journal_matin.imprimante."
        )
    return candidates[0]


def imprimer(chemin: Path) -> dict[str, str]:
    """Envoie un fichier texte a la file Windows choisie via son pilote."""
    if os.name != "nt":
        raise RuntimeError("L'impression du journal est disponible sur Windows uniquement.")
    imprimante = _choisir_imprimante()
    requis = (imprimante.get("Name"), imprimante.get("DriverName"), imprimante.get("PortName"))
    if not all(requis):
        raise RuntimeError("La file d'impression ne fournit pas nom, pilote et port.")
    script = RACINE / "scripts" / "imprimer_texte_windows.ps1"
    resultat = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-Fichier", str(chemin),
            "-Imprimante", imprimante["Name"],
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        check=False,
    )
    if resultat.returncode != 0:
        detail = (resultat.stderr or resultat.stdout).strip()
        raise RuntimeError(
            f"Le pilote Windows n'a pas accepte le travail ({resultat.returncode})"
            + (f" : {detail}" if detail else ".")
        )
    return imprimante


def preparer_et_imprimer(
    maintenant: dt.datetime | None = None,
    apercu: bool = False,
) -> tuple[Path, dict[str, str] | None]:
    """Genere le journal PDF, puis l'imprime sauf en mode apercu."""
    maintenant = maintenant or dt.datetime.now().astimezone()
    sections = collecter_sections()
    texte = construire_texte(maintenant=maintenant, sections=sections)
    chemin_txt = ecrire_journal(texte, maintenant=maintenant)
    from core.journal_pdf import generer_pdf
    chemin = _chemin("journal_matin.dossier_sortie", "logs/journal_matin") / (
        f"journal-{maintenant:%Y%m%d}.pdf")
    generer_pdf(chemin, maintenant, sections)
    if apercu:
        return chemin, None
    imprimante = _choisir_imprimante()
    if os.name != "nt":
        raise RuntimeError("L'impression du journal est disponible sur Windows uniquement.")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm est requis pour imprimer la maquette PDF.")
    with tempfile.TemporaryDirectory(prefix="jarvis-journal-") as dossier_tmp:
        prefixe = str(Path(dossier_tmp) / "page")
        rendu = subprocess.run(
            [pdftoppm, "-png", "-r", "150", str(chemin), prefixe],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            check=False,
        )
        if rendu.returncode != 0:
            raise RuntimeError(f"Rendu PDF impossible : {rendu.stderr.strip()}")
        pages = sorted(Path(dossier_tmp).glob("page-*.png"))
        if not pages:
            raise RuntimeError("Le rendu PDF n'a produit aucune page.")
        for page in pages:
            _imprimer_image(page, imprimante)
    return chemin, imprimante


def _imprimer_image(chemin: Path, imprimante: dict[str, str]) -> None:
    """Imprime une page PNG via le pilote Windows, en la centrant sur le papier."""
    script = RACINE / "scripts" / "imprimer_image_windows.ps1"
    resultat = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-Image", str(chemin),
            "-Imprimante", imprimante["Name"],
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        check=False,
    )
    if resultat.returncode != 0:
        detail = (resultat.stderr or resultat.stdout).strip()
        raise RuntimeError(f"Impression de la page impossible : {detail}")
