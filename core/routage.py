"""Routage à 3 modes + garde-fous budgétaires — l'implémentation de la doctrine
(Hermes pense, Jarvis détient les clés/le corps ; le routage EST le partage).

Modes (config.yaml `mode`) :
  - "local"   : tout en local (Ollama + Piper), rien ne sort.
  - "hybride" : DÉFAUT. Réflexes (domotique, timers, questions courtes) + vision/
                navigateur/résa → Jarvis cloud (modèle économique). Les tâches de
                FOND (analyses, recherches) sont confiées à Hermes (via l'outil
                deleguer_a_hermes, que le modèle appelle de lui-même).
  - "qualite" : cloud partout, modèle le plus fort.
(L'ancien "cloud" reste accepté comme alias de "hybride".)

Garde-fous (jamais de blocage silencieux) :
  - alerte vocale au seuil (défaut 80 %) du plafond jour/mois ;
  - plafond atteint → bascule AUTO en local (annonce claire) + suspension des crons
    Hermes non critiques jusqu'au lendemain (repris automatiquement le jour d'après).
"""
import logging
import re
import subprocess

from core.config import definir, reglage

LOG = logging.getLogger("jarvis")
_MODES = ("local", "hybride", "qualite")


# ------------------------------------------------------------------ modes

def mode_actuel():
    m = (reglage("mode", "hybride") or "hybride").lower()
    if m == "cloud":                 # compat : ancien binaire cloud/local
        m = "hybride"
    return m if m in _MODES else "hybride"


def definir_mode(m, raison=""):
    """Change le mode et réinitialise les providers (prise d'effet au tour suivant)."""
    m = (m or "").lower()
    if m == "cloud":
        m = "hybride"
    if m not in _MODES:
        return False
    definir("mode", m)
    try:
        from core import llm, tts
        llm.reinitialiser()
        tts.reinitialiser()
    except Exception:
        LOG.exception("routage: reinit providers")
    if raison:
        LOG.info("mode -> %s (%s)", m, raison)
    return True


# ------------------------------------------------------------------ Hermes CLI

def _hermes(args, timeout=25):
    """Lance `hermes …` en UTF-8 (la sortie contient cadres/emoji). '' si échec."""
    try:
        p = subprocess.run(["hermes", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (p.stdout or "").strip()
    except Exception:
        return ""


_ETATS_INACTIFS = ("[paused]", "[disabled]", "[completed]")


def _crons():
    """Crons Hermes via `hermes cron list` : liste de (nom, actif). L'etat vient de
    la ligne « <id> [active|paused|…] » qui precede « Name: … » ; inconnu = actif."""
    crons, etat = [], ""
    for ligne in _hermes(["cron", "list"]).splitlines():
        s = re.sub(r"\x1b\[[0-9;]*m", "", ligne).strip()     # couleurs ANSI eventuelles
        if s.startswith("Name:"):
            crons.append((s.split(":", 1)[1].strip(),
                          not any(m in etat for m in _ETATS_INACTIFS)))
            etat = ""
        elif s.endswith("]") and "[" in s:
            etat = s.lower()
    return crons


def suspendre_crons_non_critiques():
    """Met en pause les crons Hermes actifs sauf ceux listés dans budget.crons_critiques.
    Renvoie la liste des crons suspendus (pour reprise le lendemain) : un cron deja
    en pause (par l'utilisatrice) n'y figure pas, la reprise ne le relance donc pas."""
    critiques = {str(x).lower() for x in (reglage("budget.crons_critiques", []) or [])}
    suspendus = []
    for nom, actif in _crons():
        if not actif or nom.lower() in critiques:
            continue
        sortie = _hermes(["cron", "pause", nom], timeout=15)
        if sortie and "failed" not in sortie.lower():
            suspendus.append(nom)
    if suspendus:
        LOG.info("crons Hermes suspendus (plafond budget) : %s", suspendus)
    return suspendus


def reprendre_crons(noms):
    for nom in noms or []:
        _hermes(["cron", "resume", nom], timeout=15)
    if noms:
        LOG.info("crons Hermes repris : %s", noms)


# ------------------------------------------------------------------ garde-fous

def apres_depense():
    """Appelé après chaque dépense LLM. Alerte au seuil, bascule au plafond, et
    reprend les crons le lendemain. Best-effort, ne lève jamais."""
    try:
        from core import budget
        e = budget.etat()
    except Exception:
        return
    try:
        _reprendre_si_nouveau_jour(e)
        _alerter_si_seuil(e)
        _basculer_si_plafond(e)
    except Exception:
        LOG.exception("routage: garde-fous")


def verifier_nouveau_jour():
    """Appelé au début de chaque tour : le retour au mode normal et la reprise des
    crons « le lendemain » ne doivent pas attendre une dépense cloud, qui n'arrive
    plus après une bascule en local. Best-effort, ne lève jamais."""
    try:
        _reprendre_si_nouveau_jour(None)
    except Exception:
        LOG.exception("routage: verification du nouveau jour")


def _annoncer(texte):
    try:
        from core import voix
        voix.parler(texte)
    except Exception:
        LOG.info("(annonce budget non vocalisée) %s", texte)


def _alerter_si_seuil(e):
    from core import budget
    seuil = float(reglage("budget.alerte_pct", 80)) / 100.0
    for periode, libelle in (("jour", "aujourd'hui"), ("mois", "ce mois")):
        pct = e.get(f"pct_{periode}", 0.0)
        plafond = e.get(f"plafond_{periode}")
        if not plafond or pct < seuil or pct >= 1.0:
            continue
        if budget.deja_signale(f"alerte_{periode}"):
            continue
        budget.marquer(f"alerte_{periode}")
        _annoncer(f"Attention, budget : j'ai dépensé {int(pct*100)} pour cent de mon "
                  f"plafond {libelle}. Il reste environ {e['reste_'+periode]:.2f} dollars.")


def _basculer_si_plafond(e):
    from core import budget
    if not e.get("depasse"):
        return
    if mode_actuel() == "local":
        return
    if budget.deja_signale("bascule"):
        return
    budget.marquer("bascule")
    definir_mode("local", raison="plafond budget atteint")
    budget.activer_bascule_auto()
    suspendus = suspendre_crons_non_critiques()
    budget.memoriser_crons_suspendus(suspendus)
    reste = "jour" if e.get("depasse_jour") else "mois"
    _annoncer("Plafond de budget atteint pour " + ("aujourd'hui" if reste == "jour"
              else "ce mois") + ". Je bascule en local, gratuit : Ollama et Piper. "
              "Je mets aussi en pause les tâches de fond d'Hermes non critiques "
              "jusqu'à demain. Dis « repasse en cloud » si tu veux forcer.")


def _reprendre_si_nouveau_jour(e):
    """Nouveau jour + sous le plafond : on ré-autorise le cloud et on reprend les crons."""
    from core import budget
    if not budget.jour_a_change():
        return
    budget.reset_signaux()                       # ré-arme alertes/bascule
    # Le plafond MENSUEL survit au changement de jour : tant qu'il est dépassé, on
    # reste en local, crons en pause et sans annonce (sinon l'annonce de reprise,
    # dite en voix cloud, relancerait aussitôt la bascule, chaque jour du mois).
    e = e or budget.etat()
    if e.get("depasse"):
        return
    noms = budget.crons_suspendus()
    if noms:
        reprendre_crons(noms)
        budget.memoriser_crons_suspendus([])
    # On ne force pas le retour cloud si l'utilisateur a explicitement choisi local :
    # on ne repasse que si la bascule venait du plafond (mode local + drapeau).
    if mode_actuel() == "local" and budget.bascule_auto_active():
        definir_mode(reglage("budget.mode_normal", "hybride"),
                     raison="nouveau jour, budget réarmé")
        budget.effacer_bascule_auto()
        _annoncer("Nouveau jour : budget réarmé, je repasse en mode "
                  f"{reglage('budget.mode_normal', 'hybride')}.")
