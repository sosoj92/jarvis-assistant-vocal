"""Contrôle par gestes — côté Jarvis (Python 3.13).

Pilote le SOUS-PROCESS tracker (Python 3.11 isolé, cf. gestes/tracker.py), reçoit
les labels de gestes en loopback (POST /api/gestes, protégé par un token), et les
mappe à des actions **N1/N2 uniquement** (jamais N3 : pas d'extinction, d'appel, de
réservation par geste — un faux positif ne coûte qu'une lumière).

Frontière vie privée : aucune image ne transite ici ; seul un label ("poing"…)
arrive. La caméra n'est JAMAIS exposée au MCP ni accessible à Hermes.
"""
import json
import logging
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

from core import plateforme
from core.config import reglage
from core.util import sans_accents

LOG = logging.getLogger("jarvis.gestes")
_RACINE = Path(__file__).resolve().parent.parent

_TOKEN = None          # jeton courant (None = gestes coupés) ; protège /api/gestes
_PROC = None           # sous-process tracker
_COUPER_TTS = None     # callback fourni par jarvis14 (couper_parole)
_FEEDBACK = None       # callback fourni par jarvis14 (bip + flash HUD)
_CURSEUR_LUM = {}      # piece -> luminosité courante (0..100), pour le pincement
_DERNIER = 0.0         # anti-rebond côté Jarvis (en plus du cooldown du tracker)

# Mapping par défaut geste -> action (surchargé par config.yaml gestes.mapping).
# TOUTES les actions ici sont N1/N2 par construction.
_MAPPING_DEFAUT = {
    "pincement_haut": {"action": "luminosite", "piece": "salon", "pas": 10},
    "pincement_bas":  {"action": "luminosite", "piece": "salon", "pas": -10},
    "main_ouverte":   {"action": "play_pause"},
    "poing":          {"action": "couper_tts"},
    "swipe_droite":   {"action": "swipe", "sens": "suivant"},
    "swipe_gauche":   {"action": "swipe", "sens": "precedent"},
}
# Actions autorisées par geste (garde-fou : rien d'autre ne peut être déclenché).
_ACTIONS_SURES = {"luminosite", "play_pause", "couper_tts", "obs_scene", "swipe",
                  "armement"}


def definir_hooks(couper_tts=None, feedback=None):
    """jarvis14 enregistre ses callbacks au démarrage (couper la parole, feedback)."""
    global _COUPER_TTS, _FEEDBACK
    _COUPER_TTS = couper_tts
    _FEEDBACK = feedback


# ---------------------------------------------------------------- lifecycle

def _python_tracker():
    p = reglage("gestes.python", "") or "gestes/.venv-tracker/Scripts/python.exe"
    p = Path(p)
    return p if p.is_absolute() else (_RACINE / p)


def _seuils():
    """Seuils config, écrasés par gestes/calibration.json s'il existe (calibration)."""
    base = dict(reglage("gestes.seuils", {}) or {})
    calib = _RACINE / "gestes" / "calibration.json"
    if calib.exists():
        try:
            base.update((json.loads(calib.read_text(encoding="utf-8")) or {}).get("seuils", {}))
        except Exception:
            pass
    return base


def _conf_tracker(token):
    port = int(reglage("serveur.port", 8790))
    return {
        "device": int(reglage("gestes.device", 0)),
        "fps": int(reglage("gestes.fps", 24)),
        "largeur": int(reglage("gestes.largeur", 640)),
        "hauteur": int(reglage("gestes.hauteur", 480)),
        "seuils": _seuils(),
        "confiance_detection": float(reglage("gestes.confiance_detection", 0.7)),
        "confiance_suivi": float(reglage("gestes.confiance_suivi", 0.7)),
        "armement": reglage("gestes.armement", {"actif": False}) or {"actif": False},
        "url": f"http://127.0.0.1:{port}/api/gestes",
        "token": token,
        "model_path": str(_RACINE / "gestes" / "models" / "hand_landmarker.task"),
    }


def actif():
    return _PROC is not None and _PROC.poll() is None


def demarrer():
    """Lance le sous-process tracker (idempotent). Renvoie un message vocal."""
    global _TOKEN, _PROC
    if actif():
        return "Les gestes sont déjà actifs."
    py = _python_tracker()
    if not py.exists():
        return ("L'environnement des gestes n'est pas installé "
                "(lance : python scripts/setup_gestes.py).")
    if not (_RACINE / "gestes" / "models" / "hand_landmarker.task").exists():
        return "Le modèle de gestes est manquant (lance : python scripts/setup_gestes.py)."
    # Le tracker POST en loopback : s'assurer que le serveur web unifié tourne.
    try:
        from core import serveur
        serveur.demarrer()
    except Exception:
        LOG.exception("gestes: démarrage serveur loopback")
    _TOKEN = secrets.token_urlsafe(24)
    env = dict(os.environ, GESTES_CONF=json.dumps(_conf_tracker(_TOKEN)))
    try:
        _PROC = subprocess.Popen([str(py), str(_RACINE / "gestes" / "tracker.py")],
                                 env=env, cwd=str(_RACINE))
    except Exception as e:
        _TOKEN = None
        LOG.exception("gestes: démarrage tracker")
        return f"Je n'ai pas pu démarrer les gestes ({e})."
    LOG.info("gestes: tracker lancé (pid %s)", _PROC.pid)
    return "Contrôle par gestes activé. La webcam est allumée."


def arreter():
    global _TOKEN, _PROC
    _TOKEN = None
    if _PROC is not None:
        try:
            _PROC.terminate()
        except Exception:
            pass
        _PROC = None
    return "Contrôle par gestes coupé. La webcam est éteinte."


def statut():
    return {"actif": actif(), "tracker_vivant": actif()}


# ---------------------------------------------------------------- dispatch

def _traiter(geste):
    """Reçoit un label de geste, applique le feedback puis l'action N1/N2 mappée."""
    global _DERNIER
    # feedback discret (bip + flash HUD), y compris pour l'armement.
    if _FEEDBACK:
        try:
            _FEEDBACK(geste)
        except Exception:
            pass
    if geste == "armement":
        return  # simple fenêtre "Jarvis regarde" : pas d'action, juste le feedback

    now = time.time()
    if now - _DERNIER < 0.4:      # anti-rebond côté Jarvis
        return
    _DERNIER = now

    mapping = reglage("gestes.mapping", None) or _MAPPING_DEFAUT
    spec = mapping.get(geste)
    if not spec:
        return
    action = spec.get("action")
    # GARDE-FOU : seules des actions sûres (N1/N2), jamais un outil N3.
    if action not in _ACTIONS_SURES:
        LOG.warning("gestes: action refusée (non sûre) : %r", action)
        return
    try:
        _executer(action, spec)
    except Exception:
        LOG.exception("gestes: exécution %s", action)


def _executer(action, spec):
    if action == "luminosite":
        piece = spec.get("piece", "salon")
        pas = int(spec.get("pas", 10))
        cur = _CURSEUR_LUM.get(piece, 50) + pas
        cur = max(0, min(100, cur))
        _CURSEUR_LUM[piece] = cur
        from tools.lumieres import regler_luminosite
        _verifier_non_n3("regler_luminosite")
        regler_luminosite(piece, cur)
    elif action == "play_pause":
        from tools.systeme import controler_media
        _verifier_non_n3("controler_media")
        controler_media("pause")
    elif action == "couper_tts":
        if _COUPER_TTS:
            _COUPER_TTS()
    elif action == "obs_scene":
        _obs_scene(spec.get("sens", "suivante"))
    elif action == "swipe":
        _swipe(spec.get("sens", "suivant"))


def _verifier_non_n3(nom_outil):
    """Défense en profondeur : refuse tout outil classé N3 (jamais par geste)."""
    from core import registre
    if registre.niveau(nom_outil) == "N3":
        raise PermissionError(f"outil N3 interdit par geste : {nom_outil}")


def _obs_scene(sens, force=False):
    """Scène OBS suivante/précédente. Ignoré pendant le live si configuré (sauf force)."""
    try:
        from tools.obs import _client
        cl = _client()
        if (not force and reglage("gestes.pause_pendant_live", True)
                and getattr(cl.get_stream_status(), "output_active", False)):
            LOG.info("gestes: swipe OBS ignoré (live en cours)")
            return
        rep = cl.get_scene_list()
        scenes = [s.get("sceneName", "") for s in rep.scenes if isinstance(s, dict)]
        courante = getattr(rep, "current_program_scene_name", None) or \
            getattr(cl.get_current_program_scene(), "scene_name", None)
        if not scenes:
            return
        i = scenes.index(courante) if courante in scenes else 0
        j = (i + (1 if str(sens).startswith("suiv") else -1)) % len(scenes)
        cl.set_current_program_scene(scenes[j])
    except Exception as e:
        LOG.info("gestes: OBS indisponible (%s)", e)


# ----- swipe CONTEXTUEL : OBS -> app vidéo (seek) -> Alt+Tab (du + spécifique au + général)

# Noms de processus (Windows : .exe ; macOS : nom de l'application).
_LECTEURS = ("vlc", "mpv", "wmplayer", "mpc-hc", "mpc-be", "potplayer", "smplayer",
             "kmplayer", "movies", "films",
             "iina", "quicktime player", "musique", "music", "tv", "infuse")
_VIDEO_TITRES = ("youtube", "vlc", "netflix", "twitch", "prime video", "disney",
                 "molotov", "- vlc", "lecteur", ".mp4", ".mkv", ".avi", ".mov")
_NAVIGATEURS = ("chrome", "firefox", "msedge", "brave", "opera", "safari", "arc",
                "microsoft edge", "google chrome")


def _fenetre_active():
    """(titre, processus) de la fenêtre au premier plan. ('', '') si inaccessible.

    Implémenté par OS dans core/plateforme (Win32 sur Windows, NSWorkspace +
    CoreGraphics sur macOS). Sur macOS, le titre peut rester vide tant que
    l'autorisation « Enregistrement de l'écran » n'est pas accordée ; le nom de
    l'application, lui, est toujours là — c'est ce qui décide de la cascade.
    """
    return plateforme.fenetre_active()


def _obs_actif():
    """OBS au premier plan, OU en train de streamer/enregistrer (live)."""
    _, proc = _fenetre_active()
    if "obs" in proc:
        return True
    try:
        from tools.obs import _client
        cl = _client()
        if getattr(cl.get_stream_status(), "output_active", False):
            return True
        return getattr(cl.get_record_status(), "output_active", False)
    except Exception:
        return False


def _est_app_video(titre, proc):
    t = sans_accents(titre.lower())
    if any(p in proc for p in _LECTEURS):
        return True
    return any(k in t for k in _VIDEO_TITRES)


def _overlay_geste(label):
    try:
        import overlay
        overlay.afficher(label, duree=2.0)
    except Exception:
        pass


def _swipe(sens):
    """Cascade : (1) OBS actif -> scène ; (2) app vidéo au 1er plan -> seek ±10s ;
    (3) défaut -> bascule de fenêtre (Alt+Tab). Feedback overlay du mode choisi."""
    suivant = str(sens).startswith("suiv") or sens in ("droite", "avant", "+")
    # 1) OBS
    if _obs_actif():
        _obs_scene("suivante" if suivant else "precedente", force=True)
        _overlay_geste("📺 Scène OBS " + ("suivante" if suivant else "précédente"))
        return
    titre, proc = _fenetre_active()
    # 2) app vidéo -> seek
    if _est_app_video(titre, proc):
        youtube = "youtube" in sans_accents(titre.lower()) or \
            any(b in proc for b in _NAVIGATEURS)
        if youtube:
            plateforme.envoyer_touches("l" if suivant else "j")     # YouTube ±10 s
        else:
            plateforme.envoyer_touches("right" if suivant else "left")  # VLC…
        _overlay_geste("🎬 +10s" if suivant else "🎬 -10s")
        return
    # 3) défaut -> bascule de fenêtre (Alt+Tab, ou Cmd+Tab sur macOS)
    plateforme.envoyer_touches("alt+tab" if suivant else "alt+shift+tab")
    _overlay_geste("🪟 Fenêtre " + ("suivante" if suivant else "précédente"))


# ---------------------------------------------------------------- routes

_HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1", "[::1]", ""}


def _local(request):
    if request.headers.get("x-forwarded-for") or request.headers.get("x-forwarded-host"):
        return False
    host = (request.headers.get("host", "") or "").split(":")[0].strip().lower()
    return host in _HOTES_LOCAUX


def monter_routes(app):
    """Monte /api/gestes (réception des labels) et /api/gestes/status."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.post("/api/gestes")
    async def api_gestes(request: Request):
        if not _local(request):
            return JSONResponse({"ok": False}, status_code=403)
        if not _TOKEN or request.headers.get("x-gestes-token", "") != _TOKEN:
            return JSONResponse({"ok": False, "message": "token"}, status_code=401)
        try:
            data = await request.json()
        except Exception:
            data = {}
        geste = str(data.get("geste", "")).strip()
        if geste:
            threading.Thread(target=_traiter, args=(geste,), daemon=True).start()
        return {"ok": True}

    @app.get("/api/gestes/status")
    def api_gestes_status(request: Request):
        if not _local(request):
            return JSONResponse({"ok": False}, status_code=403)
        return statut()

    LOG.info("gestes: routes montées (/api/gestes, local + token)")
