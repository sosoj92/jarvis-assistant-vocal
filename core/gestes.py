"""Contrôle par gestes — côté Jarvis (Python 3.13).

Pilote le SOUS-PROCESS tracker (Python 3.11 isolé, cf. gestes/tracker.py), reçoit
les labels de gestes en loopback (POST /api/gestes, protégé par un token), et les
mappe à des actions **N1/N2 uniquement** (jamais N3 : pas d'extinction, d'appel, de
réservation par geste — un faux positif ne coûte qu'une lumière).

Frontière vie privée : aucune image ne transite ici ; seuls un label ("poing"…)
ou, en mode souris, un point normalisé (x,y) arrivent en loopback. La caméra
n'est JAMAIS exposée au MCP ni accessible à Hermes.
"""
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.config import reglage
from core.util import sans_accents

LOG = logging.getLogger("jarvis.gestes")
_RACINE = Path(__file__).resolve().parent.parent

_TOKEN = None          # jeton courant (None = gestes coupés) ; protège /api/gestes
_PROC = None           # sous-process tracker
_MODE_DEMO = False     # tracker visible + actions réelles (pour démonstration locale)
_PROC_CALIBRATION = None  # fenêtre de calibration locale, lancée à la voix
_PROC_REGARD = None    # contrôle local du pointeur par les yeux
_PROC_CAMERA_APP = None  # application qui fournit éventuellement la caméra virtuelle
_CAMERA_APP_LANCEE_PAR_JARVIS = False
_COUPER_TTS = None     # callback fourni par jarvis14 (couper_parole)
_FEEDBACK = None       # callback fourni par jarvis14 (bip + flash HUD)
_CURSEUR_LUM = {}      # compatibilité des anciens mappings par pincement
_DERNIER = 0.0         # anti-rebond côté Jarvis (en plus du cooldown du tracker)
_GESTES_CONTINUS = {
    "fenetre_droite", "fenetre_gauche", "defilement_haut", "defilement_bas",
    "volume_haut", "volume_bas", "piste_suivante", "piste_precedente",
}

# Mapping par défaut geste -> action (surchargé par config.yaml gestes.mapping).
# TOUTES les actions ici sont N1/N2 par construction.
_MAPPING_DEFAUT = {
    "main_ouverte":     {"action": "media", "commande": "pause", "label": "⏸ Pause"},
    "pouce_leve":       {"action": "media", "commande": "pause", "label": "▶ Lecture"},
    "poing":            {"action": "couper_tts"},
    "mode_fenetres":    {"action": "mode_feedback", "label": "🗂 Mode onglets"},
    "fenetre_droite":   {"action": "fenetre", "sens": "suivant"},
    "fenetre_gauche":   {"action": "fenetre", "sens": "precedent"},
    "defilement_haut":  {"action": "defiler", "sens": "haut"},
    "defilement_bas":   {"action": "defiler", "sens": "bas"},
    "mode_souris":      {"action": "mode_feedback", "label": "🖱 Mode souris"},
    "zoom_agrandir":    {"action": "zoom", "sens": "agrandir", "crans": 1},
    "zoom_reduire":     {"action": "zoom", "sens": "reduire", "crans": 1},
    "mode_audio":       {"action": "mode_feedback", "label": "🔊 Mode audio"},
    "volume_haut":      {"action": "volume", "sens": "monter", "crans": 4},
    "volume_bas":       {"action": "volume", "sens": "baisser", "crans": 4},
    "piste_suivante":   {"action": "media", "commande": "suivant", "label": "⏭ Piste suivante"},
    "piste_precedente": {"action": "media", "commande": "precedent", "label": "⏮ Piste précédente"},
}
# Actions autorisées par geste (garde-fou : rien d'autre ne peut être déclenché).
_ACTIONS_SURES = {"luminosite", "play_pause", "couper_tts", "obs_scene", "swipe",
                  "armement", "media", "mode_feedback", "fenetre", "defiler", "volume",
                  "zoom"}


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


def _trouver_application_camera():
    """Résout l'application caméra facultative sans imposer Logitech au projet."""
    configure = str(reglage("gestes.camera_app.executable", "") or "").strip()
    if configure:
        chemin = Path(os.path.expandvars(configure)).expanduser()
        return chemin if chemin.exists() else None
    if os.name != "nt":
        return None
    candidats = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Logitech" / "LogiCapture" / "bin" / "LogiCapture.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Logitech" / "LogiCapture" / "bin" / "LogiCapture.exe",
    )
    return next((chemin for chemin in candidats if chemin.exists()), None)


def _application_camera_deja_active():
    """Évite d'ouvrir une seconde instance de Logitech Capture sous Windows."""
    if (_PROC_CAMERA_APP is not None
            and _PROC_CAMERA_APP.poll() is None):
        return True
    if os.name != "nt":
        return False
    try:
        resultat = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq LogiCapture.exe", "/NH"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        return "logicapture.exe" in (resultat.stdout or "").lower()
    except Exception:
        return False


def _demarrer_application_camera():
    """Prépare la caméra virtuelle configurée avant d'ouvrir le tracker visible."""
    global _PROC_CAMERA_APP, _CAMERA_APP_LANCEE_PAR_JARVIS
    if not bool(reglage("gestes.camera_app.actif", False)):
        return True, ""
    if _application_camera_deja_active():
        return True, ""
    executable = _trouver_application_camera()
    if executable is None:
        return False, (
            "Je n'ai pas trouvé l'application caméra configurée. "
            "Vérifie gestes.camera_app.executable dans config.yaml."
        )
    try:
        _PROC_CAMERA_APP = subprocess.Popen(
            [str(executable)], cwd=str(executable.parent),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _CAMERA_APP_LANCEE_PAR_JARVIS = True
        attente = max(0.0, min(
            10.0, float(reglage("gestes.camera_app.attente_s", 3.0))))
        if attente:
            time.sleep(attente)
        LOG.info("gestes: application caméra lancée (%s)", executable.name)
        return True, ""
    except Exception as exc:
        _PROC_CAMERA_APP = None
        _CAMERA_APP_LANCEE_PAR_JARVIS = False
        LOG.exception("gestes: démarrage application caméra")
        return False, f"Je n'ai pas pu ouvrir l'application caméra ({exc})."


def _arreter_application_camera():
    """Ferme uniquement l'instance démarrée par Jarvis, jamais celle de l'utilisateur."""
    global _PROC_CAMERA_APP, _CAMERA_APP_LANCEE_PAR_JARVIS
    if (_CAMERA_APP_LANCEE_PAR_JARVIS
            and bool(reglage("gestes.camera_app.fermer_avec_mode", True))):
        _terminer_processus(_PROC_CAMERA_APP)
    _PROC_CAMERA_APP = None
    _CAMERA_APP_LANCEE_PAR_JARVIS = False


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


def regard_actif():
    return _PROC_REGARD is not None and _PROC_REGARD.poll() is None


def _terminer_processus(proc):
    """Ferme un sous-process et son éventuel interpréteur enfant sous Windows."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        else:
            proc.terminate()
            proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _demarrer_tracker(demo=False):
    """Lance l'unique tracker, invisible normalement ou visible en mode démo."""
    global _TOKEN, _PROC, _MODE_DEMO
    if regard_actif():
        arreter_regard()
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
    commande = [str(py), str(_RACINE / "gestes" / "tracker.py")]
    if demo:
        commande.append("--demo")
    try:
        _PROC = subprocess.Popen(commande, env=env, cwd=str(_RACINE))
    except Exception as e:
        _TOKEN = None
        _MODE_DEMO = False
        LOG.exception("gestes: démarrage tracker")
        return f"Je n'ai pas pu démarrer les gestes ({e})."
    _MODE_DEMO = bool(demo)
    LOG.info("gestes: tracker lancé (pid %s, demo=%s)", _PROC.pid, demo)
    if demo:
        return ("Mode démo des gestes activé. La caméra et les repères restent "
                "visibles, et les gestes contrôlent réellement le PC.")
    return "Contrôle par gestes activé. La webcam est allumée."


def demarrer():
    """Lance le sous-process tracker invisible (idempotent)."""
    if actif():
        return "Les gestes sont déjà actifs."
    return _demarrer_tracker(demo=False)


def demarrer_demo():
    """Remplace le tracker courant par une fenêtre visible qui agit vraiment."""
    if actif():
        arreter()
    pret, erreur = _demarrer_application_camera()
    if not pret:
        return erreur
    reponse = _demarrer_tracker(demo=True)
    if not actif():
        _arreter_application_camera()
    return reponse


def arreter():
    global _TOKEN, _PROC, _MODE_DEMO
    _TOKEN = None
    if _PROC is not None:
        _terminer_processus(_PROC)
        _PROC = None
    _MODE_DEMO = False
    _arreter_application_camera()
    return "Contrôle par gestes coupé. La webcam est éteinte."


def demarrer_regard():
    """Lance le mode regard : calibration puis contrôle local par les yeux."""
    global _PROC_REGARD, _PROC_CALIBRATION
    if regard_actif():
        return "Le mode regard est déjà actif."
    if actif():
        arreter()
    if (_PROC_CALIBRATION is not None
            and _PROC_CALIBRATION.poll() is None):
        _terminer_processus(_PROC_CALIBRATION)
        _PROC_CALIBRATION = None
    py = _python_tracker()
    script = _RACINE / "gestes" / "regard.py"
    modele = _RACINE / "gestes" / "models" / "face_landmarker.task"
    if not py.exists():
        return ("L'environnement de suivi n'est pas installé "
                "(lance : python scripts/setup_gestes.py).")
    if not script.exists() or not modele.exists():
        return ("Le contrôle du regard n'est pas installé "
                "(lance : python scripts/setup_regard.py).")
    commande = [str(py), str(script), "--device",
                str(int(reglage("gestes.device", 0))), "--clics-actifs"]
    try:
        _PROC_REGARD = subprocess.Popen(commande, cwd=str(_RACINE))
    except Exception as exc:
        _PROC_REGARD = None
        LOG.exception("gestes: démarrage contrôle du regard")
        return f"Je n'ai pas pu ouvrir le mode regard ({exc})."
    LOG.info("gestes: contrôle du regard lancé (pid %s)", _PROC_REGARD.pid)
    return ("Mode regard activé. La calibration est ouverte ; appuie sur "
            "Espace pour commencer. Le clic par sourcils sera déjà actif ensuite.")


def arreter_regard():
    """Ferme le contrôle du regard et libère la webcam."""
    global _PROC_REGARD
    _terminer_processus(_PROC_REGARD)
    _PROC_REGARD = None
    return "Mode regard coupé. Le contrôle des yeux et la webcam sont arrêtés."


def arreter_mode_visio():
    """Coupe uniquement le mode visio des gestes de la main."""
    if not actif():
        return "Le mode visio est déjà coupé."
    arreter()
    return "Mode visio coupé. Les gestes sont arrêtés et la webcam est libérée."


def lancer_calibration():
    """Ouvre la fenêtre locale de calibration, après avoir libéré la webcam."""
    global _PROC_CALIBRATION
    if _PROC_CALIBRATION is not None and _PROC_CALIBRATION.poll() is None:
        return "La calibration des gestes est déjà ouverte sur le PC."
    if regard_actif():
        arreter_regard()
    if actif():
        arreter()
    script = _RACINE / "scripts" / "gestes_calibrer.py"
    py_tracker = _python_tracker()
    if not py_tracker.exists():
        return ("L'environnement des gestes n'est pas installé "
                "(lance : python scripts/setup_gestes.py).")
    if not script.exists():
        return "Le programme de calibration des gestes est introuvable."
    try:
        _PROC_CALIBRATION = subprocess.Popen(
            [sys.executable, str(script)], cwd=str(_RACINE))
    except Exception as exc:
        LOG.exception("gestes: lancement calibration")
        return f"Je n'ai pas pu ouvrir la calibration des gestes ({exc})."
    return ("Calibration des gestes ouverte sur le PC. Appuie sur S pour sauvegarder "
            "et sur Q pour quitter.")


def statut():
    vivant = actif()
    regard = regard_actif()
    return {"actif": bool(vivant or regard), "tracker_vivant": vivant,
            "demo": bool(vivant and _MODE_DEMO),
            "regard": regard, "mode_regard": regard,
            "mode_visio": bool(vivant and _MODE_DEMO)}


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
    # Le tracker cadence déjà les mouvements continus. Leur appliquer les
    # 400 ms historiques faisait perdre une partie des petits pas successifs.
    delai = 0.10 if geste in _GESTES_CONTINUS else 0.4
    if now - _DERNIER < delai:      # anti-rebond côté Jarvis
        return
    _DERNIER = now

    mapping = reglage("gestes.mapping", None) or _MAPPING_DEFAUT
    spec = mapping.get(geste)
    # Les anciennes configurations contiennent souvent une copie complète du
    # mapping antérieur. Le zoom intégré reste alors disponible sans toucher au
    # config.yaml local ; une entrée explicite continue de pouvoir le surcharger.
    if spec is None and geste in {"zoom_agrandir", "zoom_reduire", "mode_souris"}:
        spec = _MAPPING_DEFAUT[geste]
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


def _navigation_horizontale(sens, mode="onglets"):
    """Raccourci et libellé pour naviguer sans quitter l'application active."""
    suivant = str(sens).lower().startswith("suiv")
    mode = str(mode or "onglets").strip().lower().replace("_", "-")
    if mode in {"application", "applications", "alt-tab"}:
        return (
            "alt+tab" if suivant else "alt+shift+tab",
            "🪟 Application suivante" if suivant else "🪟 Application précédente",
        )
    return (
        "ctrl+tab" if suivant else "ctrl+shift+tab",
        "🗂 Onglet suivant" if suivant else "🗂 Onglet précédent",
    )


def _raccourci_zoom(sens):
    """Raccourci de zoom compatible navigateurs, PDF et applications courantes."""
    agrandir = str(sens).lower() in {"agrandir", "avant", "+", "plus"}
    return (
        "ctrl+=" if agrandir else "ctrl+-",
        "🔎 Zoom avant" if agrandir else "🔍 Zoom arrière",
    )


def _traiter_pointeur(evenement):
    """Déplace la souris depuis un événement local borné et authentifié."""
    try:
        x = float(evenement.get("x"))
        y = float(evenement.get("y"))
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return
        clic = bool(evenement.get("clic", False))
        moniteur = int(reglage("gestes.souris_moniteur", 1))
        from tools.souris import controler_pointeur_geste
        controler_pointeur_geste(x, y, clic=clic, moniteur=moniteur)
    except Exception:
        LOG.exception("gestes: événement pointeur")


def _executer(action, spec):
    if action == "luminosite":
        piece = spec.get("piece", "salon")
        pas = int(spec.get("pas", 10))
        # Compatibilité avec un ancien mapping personnalisé par pincement.
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
    elif action == "mode_feedback":
        _overlay_geste(spec.get("label", "Mode gestes"))
    elif action == "media":
        from tools.systeme import controler_media
        _verifier_non_n3("controler_media")
        controler_media(spec.get("commande", "pause"))
        _overlay_geste(spec.get("label", "Média"))
    elif action == "volume":
        from tools.systeme import regler_volume
        _verifier_non_n3("regler_volume")
        sens = spec.get("sens", "monter")
        regler_volume(sens, int(spec.get("crans", 4)))
        _overlay_geste("🔊 Volume +" if sens == "monter" else "🔉 Volume −")
    elif action == "fenetre":
        sens = spec.get("sens", "suivant")
        raccourci, label = _navigation_horizontale(
            sens, reglage("gestes.navigation_horizontale", "onglets"))
        import keyboard
        keyboard.send(raccourci)
        _overlay_geste(label)
    elif action == "defiler":
        sens = spec.get("sens", "bas")
        import keyboard
        keyboard.send("pagedown" if sens == "bas" else "pageup")
        _overlay_geste("📄 Défiler vers le bas" if sens == "bas"
                       else "📄 Défiler vers le haut")
    elif action == "zoom":
        raccourci, label = _raccourci_zoom(spec.get("sens", "agrandir"))
        import keyboard
        for _ in range(max(1, min(5, int(spec.get("crans", 1))))):
            keyboard.send(raccourci)
        _overlay_geste(label)


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


# ----- swipe CONTEXTUEL : OBS -> app vidéo (seek) -> onglets (du + spécifique au + général)

_LECTEURS = ("vlc", "mpv", "wmplayer", "mpc-hc", "mpc-be", "potplayer", "smplayer",
             "kmplayer", "movies", "films")
_VIDEO_TITRES = ("youtube", "vlc", "netflix", "twitch", "prime video", "disney",
                 "molotov", "- vlc", "lecteur", ".mp4", ".mkv", ".avi", ".mov")
_NAVIGATEURS = ("chrome", "firefox", "msedge", "brave", "opera")


def _fenetre_active():
    """(titre, processus) de la fenêtre au premier plan (Windows). ('', '') sinon."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        titre = buf.value or ""
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        proc = ""
        k = ctypes.windll.kernel32
        hp = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if hp:
            taille = wintypes.DWORD(260)
            nom = ctypes.create_unicode_buffer(260)
            if k.QueryFullProcessImageNameW(hp, 0, nom, ctypes.byref(taille)):
                proc = nom.value.rsplit("\\", 1)[-1]
            k.CloseHandle(hp)
        return titre, proc.lower()
    except Exception:
        return "", ""


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
    (3) défaut -> onglet/vue de l'application active. Feedback overlay du mode choisi."""
    suivant = str(sens).startswith("suiv") or sens in ("droite", "avant", "+")
    # 1) OBS
    if _obs_actif():
        _obs_scene("suivante" if suivant else "precedente", force=True)
        _overlay_geste("📺 Scène OBS " + ("suivante" if suivant else "précédente"))
        return
    titre, proc = _fenetre_active()
    # 2) app vidéo -> seek
    if _est_app_video(titre, proc):
        try:
            import keyboard
            youtube = "youtube" in sans_accents(titre.lower()) or \
                any(b in proc for b in _NAVIGATEURS)
            if youtube:
                keyboard.send("l" if suivant else "j")     # YouTube ±10 s
            else:
                keyboard.send("right" if suivant else "left")  # lecteurs (VLC…)
        except Exception:
            pass
        _overlay_geste("🎬 +10s" if suivant else "🎬 -10s")
        return
    # 3) défaut -> onglet/vue de l'application active (configurable)
    raccourci, label = _navigation_horizontale(
        "suivant" if suivant else "precedent",
        reglage("gestes.navigation_horizontale", "onglets"),
    )
    try:
        import keyboard
        keyboard.send(raccourci)
    except Exception:
        pass
    _overlay_geste(label)


# ---------------------------------------------------------------- routes

_HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1", "[::1]", ""}


def _local(request):
    # IP réelle de la socket, pas de X-Forwarded (ngrok) et Host local (anti
    # DNS rebinding) : cf. core/http_local.
    from core.http_local import requete_locale
    return requete_locale(getattr(request.client, "host", ""), request.headers)


def monter_routes(app):
    """Monte les routes locales de réception et de statut."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.post("/api/gestes")
    async def api_gestes(request: Request):
        if not _local(request):
            return JSONResponse({"ok": False}, status_code=403)
        if not _TOKEN or not secrets.compare_digest(
                request.headers.get("x-gestes-token", ""), _TOKEN):
            return JSONResponse({"ok": False, "message": "token"}, status_code=401)
        try:
            data = await request.json()
        except Exception:
            data = {}
        geste = str(data.get("geste", "")).strip()
        pointeur = data.get("pointeur")
        if isinstance(pointeur, dict):
            _traiter_pointeur(pointeur)
        if geste:
            threading.Thread(target=_traiter, args=(geste,), daemon=True).start()
        return {"ok": True}

    @app.get("/api/gestes/status")
    def api_gestes_status(request: Request):
        if not _local(request):
            return JSONResponse({"ok": False}, status_code=403)
        return statut()

    LOG.info("gestes: routes montées (/api/gestes, local + token)")
