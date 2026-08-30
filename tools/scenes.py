"""Scènes composites : au démarrage (matin) et extinction (« on éteint tout »).

Contrairement à tools/modes.py (ambiances LUMIÈRES seules), une scène orchestre
plusieurs domaines — musique, lumières, voix, OBS, PC. JARVIS PUR : physique et
réflexe, en local (doctrine règle 3).

- au_demarrage : jouée au 1er lancement du jour (Spotify + lumières selon l'heure
  + accueil vocal court). Si un brief Hermes du matin est dispo, on le VOCALISE à
  la place (Jarvis est la bouche, Hermes le rédacteur — doctrine règle 1).
- extinction : « Jarvis, on éteint tout » -> musique/ lumières off, pause OBS si
  actif, puis PROPOSE d'éteindre le PC (l'extinction PC reste N3, confirmée à part).

Réglages : config.yaml section `scenes`. Non exposé au MCP (physique/local).
"""
import datetime
import threading
import time
from pathlib import Path

from core.config import reglage
from core.registre import outil

_RACINE = Path(__file__).resolve().parent.parent
_ETAT = _RACINE / "notes" / ".scene_demarrage"        # notes/ est gitignoré


def _touche_media(nom):
    """Envoie une touche multimédia (play/pause, stop…). Best effort."""
    try:
        import keyboard
        keyboard.send(nom)
        return True
    except Exception:
        return False


# ------------------------------------------------------------ au démarrage

def _deja_fait_aujourdhui():
    try:
        return _ETAT.read_text(encoding="utf-8").strip() == datetime.date.today().isoformat()
    except Exception:
        return False


def _marquer_fait():
    try:
        _ETAT.parent.mkdir(parents=True, exist_ok=True)
        _ETAT.write_text(datetime.date.today().isoformat(), encoding="utf-8")
    except Exception:
        pass


def _lumieres_du_moment():
    """Allume des lumières adaptées à l'heure (chaudes matin/soir, rien en plein
    jour). Surcharge possible : scenes.lumieres = {matin, jour, soir} -> nom de mode."""
    h = datetime.datetime.now().hour
    cfg = reglage("scenes.lumieres", {}) or {}
    if 6 <= h < 11:
        mode = cfg.get("matin", "retour")
    elif 11 <= h < 18:
        mode = cfg.get("jour", "")            # plein jour : rien par défaut
    else:
        mode = cfg.get("soir", "retour")
    if not mode:
        return
    try:
        from tools import modes
        modes.activer(mode)
    except Exception:
        pass


def _brief_hermes():
    """Renvoie le texte du brief Hermes du matin s'il est disponible ET du jour,
    sinon None. Le brief est écrit par le cron Hermes (chantier rétrofit) dans le
    fichier scenes.brief_fichier. Doctrine : Hermes rédige, Jarvis vocalise."""
    chemin = reglage("scenes.brief_fichier", "")
    if not chemin:
        return None
    p = Path(chemin)
    if not p.is_absolute():
        p = _RACINE / p
    try:
        if not p.exists():
            return None
        # fraîcheur : fichier modifié aujourd'hui
        mtime = datetime.date.fromtimestamp(p.stat().st_mtime)
        if mtime != datetime.date.today():
            return None
        txt = p.read_text(encoding="utf-8", errors="replace").strip()
        return txt or None
    except Exception:
        return None


def _accueil():
    """Accueil vocal du matin. Par défaut le BRIEF COMPLET (faire_brief : heure,
    météo, aperçu mails, deadlines) ; accueil court si scenes.brief_complet = false."""
    if reglage("scenes.brief_complet", True):
        try:
            from tools.brief import faire_brief
            t = str(faire_brief() or "").strip()
            if t:
                return t
        except Exception:
            pass
    return _accueil_court()


def _accueil_court():
    """Petit accueil vocal : salutation + météo + premier rendez-vous."""
    morceaux = []
    prenom = reglage("assistant.prenom_utilisateur", "") or ""
    heure = datetime.datetime.now().hour
    salut = "Bonjour" if heure < 18 else "Bonsoir"
    morceaux.append(f"{salut}{(' ' + prenom) if prenom else ''}.")
    try:
        from tools.meteo import meteo
        m = str(meteo()).strip()
        if m:
            morceaux.append(m)
    except Exception:
        pass
    try:
        from tools.agenda import get_events
        rdv = str(get_events("aujourd'hui")).strip()
        if rdv and "aucun" not in rdv.lower():
            morceaux.append("Au programme : " + rdv)
    except Exception:
        pass
    return " ".join(morceaux)


def scene_au_demarrage(forcer=False):
    """Joue la scène du matin (une fois par jour sauf forcer=True). Non bloquant
    conseillé (voir jouer_au_demarrage_async)."""
    if not forcer and _deja_fait_aujourdhui():
        return "Scène de démarrage déjà jouée aujourd'hui."
    if not reglage("scenes.au_demarrage_actif", True):
        return "Scène de démarrage désactivée."
    _marquer_fait()

    # 1) Musique (Spotify) — best effort : lancer l'appli puis play.
    if reglage("scenes.spotify", True):
        try:
            from tools.systeme import ouvrir_application
            ouvrir_application(reglage("scenes.spotify_app", "spotify"))
        except Exception:
            pass
        time.sleep(float(reglage("scenes.spotify_delai", 4.0)))
        _touche_media("play/pause media")

    # 2) Lumières selon l'heure.
    _lumieres_du_moment()

    # 3) Accueil vocal : brief Hermes si dispo, sinon accueil court local.
    try:
        from core import voix
        texte = _brief_hermes() or _accueil()
        if texte:
            voix.parler(texte)
    except Exception:
        pass
    return "Scène de démarrage jouée."


def jouer_au_demarrage_async():
    """Lance la scène du matin en tâche de fond (appelée par jarvis14 au boot)."""
    if _deja_fait_aujourdhui() or not reglage("scenes.au_demarrage_actif", True):
        return
    threading.Thread(target=scene_au_demarrage, name="scene_demarrage", daemon=True).start()


# ------------------------------------------------------------ extinction

@outil(
    nom="eteindre_tout",
    description="Scène d'extinction : coupe la musique, éteint les lumières, met "
                "OBS en pause s'il enregistre, puis propose d'éteindre le PC. Pour "
                "« on éteint tout », « je vais dormir, coupe tout », « bonne nuit "
                "coupe tout ». N'éteint PAS le PC directement (il le propose).",
    parametres={"type": "object", "properties": {}},
    mcp_expose=False,
)
def eteindre_tout() -> str:
    faits = []

    # 1) Musique off.
    if _touche_media("stop media"):
        faits.append("musique coupée")

    # 2) Lumières off.
    try:
        from tools import modes
        modes.activer("off")
        faits.append("lumières éteintes")
    except Exception:
        pass

    # 3) OBS : pause de l'enregistrement s'il tourne (on NE coupe PAS un live en cours).
    try:
        from tools.obs import _client
        cl = _client()
        if getattr(cl.get_record_status(), "output_active", False):
            try:
                cl.pause_record()
                faits.append("enregistrement OBS en pause")
            except Exception:
                cl.stop_record()
                faits.append("enregistrement OBS arrêté")
        if getattr(cl.get_stream_status(), "output_active", False):
            faits.append("(live en cours laissé actif)")
    except Exception:
        pass

    resume = ", ".join(faits) if faits else "rien à couper"
    return (f"C'est fait : {resume}. Tu veux que j'éteigne aussi le PC ? "
            "Dis « oui, éteins le PC » et je le fais (avec un délai annulable).")
