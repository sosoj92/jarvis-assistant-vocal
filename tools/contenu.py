"""Outils de contenu : recherche d'inspiration (Jarvis) + generation (deleguee a Hermes).

Doctrine : Jarvis = interface vocale rapide ; Hermes = moteur d'analyse/generation.
Hermes lit le Vault + le projet Scripts en LECTURE SEULE dans son conteneur Docker
(cf. HERMES_NOTES.md §17) ; il n'ecrit que dans drafts/.
"""
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from core import hub_contenu, voix
from core.config import reglage
from core.registre import outil
from tools.deleguer_a_hermes import deleguer_en_fond


def _bash() -> str:
    """Git Bash (les scripts du projet Scripts sont en bash + cygpath)."""
    cfg = reglage("integrations.bash", "")
    if cfg:
        return cfg
    for c in (r"C:\Program Files\Git\bin\bash.exe",
              r"C:\Program Files\Git\usr\bin\bash.exe"):
        if Path(c).exists():
            return c
    return shutil.which("bash") or "bash"


@outil(
    nom="chercher_inspiration",
    mcp_expose=True,
    description=(
        "Cherche dans le vault d'inspirations (videos Insta/TikTok sauvegardees) sur un "
        "sujet : titres, themes, tags, resumes et transcriptions. Repond COURT a la voix "
        "et laisse le detail dans la conversation. Ex: 'cherche mes inspirations sur les hooks'."),
    parametres={"type": "object", "properties": {
        "sujet": {"type": "string", "description": "Le sujet ou mot-cle a chercher."}},
        "required": ["sujet"]},
)
def chercher_inspiration(sujet):
    """Recherche ponderee dans le Vault (cote Jarvis, rapide)."""
    resultats = hub_contenu.chercher(sujet, n=6)
    if not resultats:
        return f"Rien trouve sur « {sujet} » dans le vault."
    lignes = [f"- {e['titre']} — {e['auteur']} [{', '.join(e['themes'])}]\n  {e['lien']}"
              for e in resultats]
    return (f"{len(resultats)} inspiration(s) sur « {sujet} » "
            f"(annonce-en UNE a la voix, garde le detail ici) :\n" + "\n".join(lignes))


@outil(
    nom="generer_idees_contenu",
    mcp_expose=True,
    description=(
        "Genere des idees de contenu en DELEGUANT a Hermes l'analyse du vault (tendances, "
        "formats, hooks recurrents) puis la proposition de concepts. Jarvis repond tout de "
        "suite et annonce le resultat a voix haute quand c'est pret. Ex: 'genere-moi des idees'."),
)
def generer_idees_contenu():
    """Delegue l'analyse du vault + 5 concepts a Hermes ; notif vocale differee."""
    tache = (
        "Tu as acces en LECTURE au dossier /vault (mes inspirations video Insta/TikTok : "
        "/vault/index.md + fiches /vault/raw/*.md avec front-matter themes/tags/format et "
        "transcriptions). Analyse-le : degage les tendances, les formats qui reviennent et "
        "les hooks recurrents, puis propose 5 CONCEPTS de contenu concrets et originaux, "
        "adaptes a ce que je sauvegarde. Termine par une ligne commencant par 'RESUME:' de "
        "2 phrases maximum pour une lecture a voix haute.")
    return deleguer_en_fond(tache, intro="Hermes a des idees. ", nom_thread="idees-contenu")


@outil(
    nom="generer_script",
    confirmation=True,
    description=(
        "Ecrit un brouillon de script video en DELEGUANT a Hermes (skill maison : "
        "corrections.md en autorite max, ma fiche de style, mes scripts existants). Le "
        "brouillon atterrit dans drafts/. Confirmation requise. Ex: 'ecris un script sur X'."),
    parametres={"type": "object", "properties": {
        "sujet": {"type": "string", "description": "Le sujet du script."},
        "style": {"type": "string", "description": "Createur/style de reference (optionnel)."}},
        "required": ["sujet"]},
    annonce=lambda a: f"Je vais demander a Hermes un brouillon de script sur : {a.get('sujet', '')}.",
)
def generer_script(sujet, style=""):
    """Delegue la redaction a Hermes (skill generer_script_maison) ; sortie dans drafts/."""
    contrainte = f" Style de reference : {style}." if style else ""
    tache = (
        f"Ecris un brouillon de SCRIPT VIDEO sur : {sujet}.{contrainte}\n\n"
        "Tu as acces en LECTURE a /scripts (mon projet d'ecriture). HIERARCHIE STRICTE, en "
        "cas de contradiction : 1) /scripts/corrections.md = AUTORITE MAXIMALE (ne reproduis "
        "JAMAIS une formulation que j'y ai corrigee) ; 2) /scripts/sources/clean/moi/*.md = "
        "mes scripts reels ; 3) /scripts/styles/moi.md = ma fiche de style ; "
        "4) /scripts/styles/<createur>.md pour la structure et le rythme SEULEMENT. Ecris "
        "DANS MA VOIX, jamais celle des createurs de reference. Angle et plan d'abord dans ta "
        "reflexion, puis redaction. Ecris le brouillon final dans un fichier "
        "/scripts/drafts/<nom-court>.md (tu n'as le droit d'ecrire QUE dans drafts/). "
        "Termine par une ligne 'RESUME:' donnant le nom du fichier cree et l'angle choisi, "
        "en 2 phrases, pour la voix.")
    return deleguer_en_fond(tache, intro="Ton brouillon est pret. ", nom_thread="generer-script")


@outil(
    nom="lancer_ingestion_youtube",
    mcp_expose=True,
    description=(
        "Lance l'ingestion d'une chaine ou video YouTube (yt-dlp + transcription) COTE HOTE "
        "via le projet Scripts. Job long en arriere-plan ; notification vocale a la fin. "
        "Sortie dans sources/clean/<cible>/. C'est l'outil que Hermes appelle pour ingerer "
        "du YouTube (lui ne peut pas lancer les jobs bash depuis son conteneur)."),
    parametres={"type": "object", "properties": {
        "url": {"type": "string", "description": "URL de la chaine ou video YouTube."},
        "cible": {"type": "string", "description": "Nom court du dossier de destination (ex. createur-x)."},
        "whisper": {"type": "boolean", "description": "true = transcription Whisper ponctuee (lent) ; false = sous-titres (rapide, defaut)."},
        "max": {"type": "integer", "description": "Nb de videos les plus recentes (chaine). 0 = tout."}},
        "required": ["url", "cible"]},
)
def lancer_ingestion_youtube(url, cible, whisper=False, max=0):
    """Declenche ingest.sh (Git Bash, hote) en arriere-plan ; previent a voix haute a la fin."""
    scripts = Path(reglage("integrations.scripts", "") or str(Path.home() / "Downloads" / "Scripts"))
    if not (scripts / "scripts" / "ingest.sh").exists():
        return f"Projet Scripts introuvable (ingest.sh) sous {scripts}."
    # SÉCURITÉ : outil déclenchable à distance (mcp_expose=True). On valide l'URL
    # avant de la passer au downloader -> pas d'injection d'options yt-dlp (URL
    # commençant par « - ») ni de fetch d'une cible arbitraire (SSRF).
    from urllib.parse import urlparse
    url = str(url or "").strip()
    if url.startswith("-"):
        return "URL invalide (ne peut pas commencer par « - »)."
    hote = (urlparse(url).hostname or "").lower()
    if not any(hote == d or hote.endswith("." + d)
               for d in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
        return "URL refusée : seuls les liens YouTube sont acceptés."
    cible = re.sub(r"[^A-Za-z0-9_-]", "-", str(cible)).strip("-") or "youtube"
    args = [_bash(), "scripts/ingest.sh"]
    if whisper:
        args.append("--whisper")
    if max:
        args += ["--max", str(int(max))]
    args += [url, cible]

    def worker():
        try:
            subprocess.run(args, cwd=str(scripts), capture_output=True, text=True,
                           timeout=int(reglage("hub.timeout_youtube", 3600)),
                           env=dict(os.environ, WHISPER_DEVICE="cpu"))
            clean = scripts / "sources" / "clean" / cible
            n = len(list(clean.glob("*.md"))) if clean.exists() else 0
            if n:
                voix.parler(f"Ingestion YouTube terminee : {n} transcription pour {cible}."
                            if n == 1 else
                            f"Ingestion YouTube terminee : {n} transcriptions pour {cible}.")
            else:
                voix.parler(f"L'ingestion YouTube de {cible} n'a produit aucune transcription "
                            "(chaine privee, pas de sous-titres, ou lien invalide).")
        except Exception as e:
            voix.parler(f"L'ingestion YouTube a echoue : {str(e)[:100]}")

    threading.Thread(target=worker, daemon=True, name="ingest-youtube").start()
    return f"Je lance l'ingestion YouTube de « {cible} » en arriere-plan. Je te previens a la fin."
