"""Couche d'abstraction système : Windows, macOS (Intel + Apple Silicon), Linux.

Tout ce qui touche à l'OS passe par ici — volume, touches multimédia, lancement
d'applications, fenêtre au premier plan, extinction, ping, voix de secours. Les
outils (`tools/`) et la boucle principale n'ont ainsi plus une seule ligne
spécifique à un OS.

Règle de conception : chaque fonction rend un résultat exploitable sur les trois
systèmes, ou lève/renvoie une valeur neutre bien identifiée. Aucune dépendance
n'est obligatoire — PyObjC accélère macOS mais il y a toujours un repli
`osascript`, et `osascript` fait partie de macOS.
"""
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

LOG = logging.getLogger("jarvis")

EST_WINDOWS = sys.platform == "win32"
EST_MAC = sys.platform == "darwin"
EST_LINUX = not (EST_WINDOWS or EST_MAC)

SYSTEME = "windows" if EST_WINDOWS else ("macos" if EST_MAC else "linux")


def est_apple_silicon() -> bool:
    """Vrai sur un Mac à puce Apple (M1/M2/M3/M4...)."""
    return EST_MAC and platform.machine() in ("arm64", "aarch64")


def nom_machine() -> str:
    """Libellé lisible de la machine (« macOS 15.3 · Apple M2 Pro »)."""
    if EST_MAC:
        puce = _sysctl("machdep.cpu.brand_string") or platform.machine()
        return f"macOS {platform.mac_ver()[0]} · {puce}"
    if EST_WINDOWS:
        return f"Windows {platform.release()} · {platform.machine()}"
    return f"{platform.system()} {platform.release()} · {platform.machine()}"


def sans_fenetre() -> dict:
    """Arguments subprocess pour ne pas ouvrir de console (no-op hors Windows)."""
    if EST_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def detache() -> dict:
    """Arguments subprocess pour un processus qui survit à Jarvis."""
    if EST_WINDOWS:
        return {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0)}
    return {"start_new_session": True}


def _run(cmd, timeout=10, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", **sans_fenetre(), **kw)


def _sysctl(clef) -> str:
    if not EST_MAC:
        return ""
    try:
        r = _run(["sysctl", "-n", clef], timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def osascript(script, timeout=8) -> str:
    """Exécute un bout d'AppleScript et renvoie sa sortie. Lève si échec."""
    if not EST_MAC:
        raise RuntimeError("osascript n'existe que sur macOS")
    r = _run(["osascript", "-e", script], timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:200] or "osascript a échoué")
    return r.stdout.strip()


# ============================================================ chemins

def racine_disque() -> str:
    """Racine du disque système, pour psutil.disk_usage()."""
    return "C:\\" if EST_WINDOWS else "/"


def nom_disque() -> str:
    """Nom du disque système tel qu'on le dit à voix haute."""
    return "C" if EST_WINDOWS else "système"


def dossier_donnees(nom: str) -> Path:
    """Dossier de données applicatives, par convention de l'OS."""
    if EST_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif EST_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / nom


def chrome_exe():
    """Chemin de l'exécutable Chrome (ou Edge/Chromium), None si introuvable."""
    if EST_MAC:
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  str(Path.home() / "Applications" / "Google Chrome.app"
                      / "Contents" / "MacOS" / "Google Chrome"),
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
            if Path(p).exists():
                return p
        return shutil.which("google-chrome") or shutil.which("chromium")
    if EST_WINDOWS:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if not base:
                continue
            c = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if c.exists():
                return str(c)
        for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if Path(p).exists():
                return p
        return None
    for nom in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        exe = shutil.which(nom)
        if exe:
            return exe
    return None


def python_venv(dossier) -> Path:
    """Chemin du python d'un venv, quel que soit l'OS.

    Windows range l'interpreteur dans Scripts/python.exe, macOS et Linux dans
    bin/python. Les venvs secondaires du projet (gestes, reconnaissance
    musicale) passent tous par ici.
    """
    dossier = Path(dossier)
    if EST_WINDOWS:
        return dossier / "Scripts" / "python.exe"
    return dossier / "bin" / "python"


def bash_exe() -> str:
    """Interpréteur bash. Sur Windows il faut Git Bash ; ailleurs il est natif."""
    if EST_WINDOWS:
        for c in (r"C:\Program Files\Git\bin\bash.exe",
                  r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(c).exists():
                return c
    return shutil.which("bash") or "/bin/bash"


def python_systeme() -> str:
    """Python système (hors venv), pour les outils tiers (yt-dlp, gallery-dl...)."""
    if EST_WINDOWS:
        cand = r"C:\Python313\python.exe"
        if Path(cand).exists():
            return cand
    else:
        for c in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3"):
            if Path(c).exists():
                return c
    return shutil.which("python3") or shutil.which("python") or "python3"


# ============================================================ ouvrir / lancer

def ouvrir(cible: str) -> None:
    """Lance une application, un fichier, une URL ou un protocole (steam://...).

    Lève une exception si l'ouverture échoue — l'appelant formule le message.
    """
    cible = str(cible).strip()
    if not cible:
        raise ValueError("cible vide")

    if EST_WINDOWS:
        os.startfile(cible)   # gère .exe, fichiers et protocoles
        return

    if EST_MAC:
        chemin = Path(os.path.expanduser(cible))
        if "://" in cible or cible.startswith(("http:", "https:", "mailto:")):
            args = ["open", cible]                       # URL ou protocole
        elif chemin.exists():
            args = ["open", str(chemin)]                 # .app, dossier, fichier
        else:
            args = ["open", "-a", cible]                 # nom d'application
        r = _run(args, timeout=15)
        if r.returncode != 0:
            # Dernier recours : une commande en ligne (ex. « code », « obs »).
            if shutil.which(cible.split()[0]):
                subprocess.Popen(cible, shell=True, **detache())
                return
            raise RuntimeError((r.stderr or "").strip()[:160] or "open a échoué")
        return

    # Linux
    chemin = Path(os.path.expanduser(cible))
    if "://" in cible or chemin.exists():
        subprocess.Popen(["xdg-open", str(chemin) if chemin.exists() else cible],
                         **detache())
    else:
        subprocess.Popen(cible, shell=True, **detache())


def ouvrir_url(url: str) -> None:
    """Ouvre une URL dans le navigateur par défaut."""
    import webbrowser
    webbrowser.open(url)


# ============================================================ volume & média

# Codes des touches multimédia Windows.
_TOUCHES_WIN = {"muet": 0xAD, "baisser": 0xAE, "monter": 0xAF,
                "suivant": 0xB0, "precedent": 0xB1, "pause": 0xB3}

# Codes des touches spéciales macOS (NX_KEYTYPE_*).
_TOUCHES_MAC = {"monter": 0, "baisser": 1, "muet": 7,
                "pause": 16, "suivant": 17, "precedent": 18}


def _presser_win(code, fois=1):
    import ctypes
    for _ in range(fois):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)
        time.sleep(0.02)


def _presser_mac(code, fois=1) -> bool:
    """Touche multimédia macOS via un évènement système (PyObjC).

    Demande l'autorisation « Accessibilité » dans Réglages Système ; renvoie
    False si PyObjC est absent ou si l'évènement n'a pas pu être posté.
    """
    try:
        from AppKit import NSEvent
        from Quartz import CGEventPost, kCGHIDEventTap
    except Exception:
        return False
    # Sélecteur PyObjC très long : on le récupère par getattr pour tenir la ligne.
    fabriquer = getattr(NSEvent, "otherEventWithType_location_modifierFlags_"
                                 "timestamp_windowNumber_context_subtype_"
                                 "data1_data2_", None)
    if fabriquer is None:
        return False
    try:
        for _ in range(fois):
            for bas in (True, False):
                data1 = (code << 16) | ((0xA if bas else 0xB) << 8)
                # type 14 = NSSystemDefined, sous-type 8 = touches multimédia.
                ev = fabriquer(14, (0, 0), 0xA00 if bas else 0xB00, 0, 0,
                               None, 8, data1, -1)
                CGEventPost(kCGHIDEventTap, ev.CGEvent())
            time.sleep(0.02)
        return True
    except Exception as e:
        LOG.debug("plateforme: touche média macOS indisponible (%s)", e)
        return False


def volume_actuel():
    """Volume système en pourcentage (0-100), ou None si non mesurable."""
    if EST_MAC:
        try:
            return int(osascript("output volume of (get volume settings)"))
        except Exception:
            return None
    if EST_LINUX and shutil.which("pactl"):
        try:
            r = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=3)
            for mot in r.stdout.split():
                if mot.endswith("%"):
                    return int(mot.rstrip("%"))
        except Exception:
            return None
    return None


def volume_definir(pct: int) -> bool:
    """Fixe le volume système. False si l'OS ne le permet pas directement."""
    pct = max(0, min(100, int(pct)))
    if EST_MAC:
        try:
            osascript(f"set volume output volume {pct}")
            return True
        except Exception:
            return False
    if EST_LINUX and shutil.which("pactl"):
        return _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"],
                    timeout=3).returncode == 0
    return False


def volume_ajuster(sens: str, crans: int = 10) -> int:
    """Monte/baisse le volume de `crans` crans de 2 %. Renvoie le nouveau volume
    (ou -1 si non mesurable, l'action ayant tout de même été faite)."""
    sens = (sens or "").lower().strip()
    if sens not in ("monter", "baisser"):
        raise ValueError("sens invalide")
    crans = max(1, min(int(crans), 50))

    if EST_WINDOWS:
        _presser_win(_TOUCHES_WIN[sens], crans)
        return -1

    if EST_MAC:
        actuel = volume_actuel()
        if actuel is None:                       # osascript indisponible : touches
            _presser_mac(_TOUCHES_MAC[sens], crans)
            return -1
        cible = actuel + (2 * crans if sens == "monter" else -2 * crans)
        cible = max(0, min(100, cible))
        if volume_definir(cible):
            if cible > 0:
                volume_muet(False)
            return cible
        return -1

    actuel = volume_actuel()
    if actuel is not None:
        cible = max(0, min(100, actuel + (2 * crans if sens == "monter" else -2 * crans)))
        if volume_definir(cible):
            return cible
    return -1


def volume_muet(etat=None) -> bool:
    """Coupe/rétablit le son. `etat` None = bascule. Renvoie l'état appliqué."""
    if EST_MAC:
        try:
            if etat is None:
                etat = osascript("output muted of (get volume settings)") != "true"
            osascript(f"set volume {'with' if etat else 'without'} output muted")
            return bool(etat)
        except Exception:
            _presser_mac(_TOUCHES_MAC["muet"])
            return bool(etat) if etat is not None else True
    if EST_WINDOWS:
        _presser_win(_TOUCHES_WIN["muet"])          # bascule uniquement
        return bool(etat) if etat is not None else True
    if shutil.which("pactl"):
        arg = "toggle" if etat is None else ("1" if etat else "0")
        _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", arg], timeout=3)
    return bool(etat) if etat is not None else True


# Lecteurs macOS pilotables en AppleScript, par ordre de préférence.
# Spotify et Musique comprennent playpause / next track / previous track ;
# le `play` de VLC bascule lecture-pause, mais lui seul (celui d'IINA ou de
# QuickTime ne fait que lancer la lecture), d'où sa place à part.
_LECTEURS_MAC = ("Spotify", "Music")
_VERBES_MAC = {"pause": "playpause", "suivant": "next track",
               "precedent": "previous track"}


def _media_applescript(action: str) -> bool:
    """Repli macOS quand l'évènement multimédia n'a pas pu être posté."""
    verbe = _VERBES_MAC.get(action)
    if not verbe:
        return False
    for app in _LECTEURS_MAC:
        try:
            if osascript(f'application "{app}" is running') != "true":
                continue
            osascript(f'tell application "{app}" to {verbe}')
            return True
        except Exception:
            continue
    if action == "pause":
        try:
            if osascript('application "VLC" is running') == "true":
                osascript('tell application "VLC" to play')   # bascule
                return True
        except Exception:
            pass
    return False


def media(action: str) -> bool:
    """Lecture/pause, piste suivante/précédente, muet. False si rien n'a marché."""
    action = (action or "").lower().strip()
    if EST_WINDOWS:
        code = _TOUCHES_WIN.get(action)
        if code is None:
            return False
        _presser_win(code)
        return True

    if EST_MAC:
        if action == "muet":
            volume_muet()
            return True
        if action in _TOUCHES_MAC and _presser_mac(_TOUCHES_MAC[action]):
            return True
        return _media_applescript(action)

    if action == "muet":
        volume_muet()
        return True
    if shutil.which("playerctl"):
        verbe = {"pause": "play-pause", "suivant": "next", "precedent": "previous"}
        if action in verbe:
            return _run(["playerctl", verbe[action]], timeout=3).returncode == 0
    return False


# ============================================================ clavier

# Touches nommées -> « key code » macOS (System Events).
_CODES_MAC = {"right": 124, "left": 123, "up": 126, "down": 125,
              "space": 49, "tab": 48, "escape": 53, "return": 36}


def envoyer_touches(combo: str) -> bool:
    """Envoie une combinaison de touches à l'application au premier plan.

    Accepte la syntaxe de la lib `keyboard` (« alt+tab », « right », « l »).
    Sur macOS, passe par System Events (autorisation « Accessibilité » requise)
    et traduit alt+tab en cmd+tab, la bascule de fenêtres native.
    """
    combo = (combo or "").lower().strip()
    if not combo:
        return False

    if not EST_MAC:
        try:
            import keyboard
        except Exception:
            return False
        try:
            keyboard.send(combo)
            return True
        except Exception:
            return False

    morceaux = [m.strip() for m in combo.split("+") if m.strip()]
    touche = morceaux[-1]
    mods = set(morceaux[:-1])
    # alt+tab (Windows) == cmd+tab (macOS)
    if touche == "tab" and "alt" in mods:
        mods.discard("alt")
        mods.add("cmd")
    noms = {"cmd": "command down", "command": "command down", "ctrl": "control down",
            "control": "control down", "alt": "option down", "option": "option down",
            "shift": "shift down"}
    suffixe = ""
    appliques = [noms[m] for m in mods if m in noms]
    if appliques:
        suffixe = " using {" + ", ".join(appliques) + "}"
    if touche in _CODES_MAC:
        corps = f"key code {_CODES_MAC[touche]}{suffixe}"
    elif len(touche) == 1:
        corps = f'keystroke "{touche}"{suffixe}'
    else:
        return False
    try:
        osascript(f'tell application "System Events" to {corps}')
        return True
    except Exception as e:
        LOG.debug("plateforme: envoi de touches refusé (%s)", e)
        return False


# ============================================================ fenêtre active

def fenetre_active():
    """(titre, processus_en_minuscules) de la fenêtre au premier plan.

    ('', '') si l'information n'est pas accessible (permission refusée, OS non
    géré). Le processus est le nom de l'application, sans extension sur macOS.
    """
    if EST_WINDOWS:
        return _fenetre_active_windows()
    if EST_MAC:
        return _fenetre_active_mac()
    return "", ""


def _fenetre_active_windows():
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
        hp = k.OpenProcess(0x1000, False, pid.value)   # QUERY_LIMITED_INFORMATION
        if hp:
            taille = wintypes.DWORD(260)
            nom = ctypes.create_unicode_buffer(260)
            if k.QueryFullProcessImageNameW(hp, 0, nom, ctypes.byref(taille)):
                proc = nom.value.rsplit("\\", 1)[-1]
            k.CloseHandle(hp)
        return titre, proc.lower()
    except Exception:
        return "", ""


def _fenetre_active_mac():
    """App au premier plan via NSWorkspace, titre via CoreGraphics.

    CoreGraphics ne donne le TITRE des fenêtres qu'avec l'autorisation
    « Enregistrement de l'écran » ; sans elle on renvoie au moins le nom de
    l'application, ce qui suffit à la plupart des décisions (OBS actif, lecteur
    vidéo au premier plan...).
    """
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
    except Exception:
        return _fenetre_active_mac_applescript()
    if app is None:
        return _fenetre_active_mac_applescript()
    proc = (app.localizedName() or "").lower()
    pid = app.processIdentifier()

    try:
        from Quartz import (CGWindowListCopyWindowInfo, kCGNullWindowID,
                            kCGWindowListExcludeDesktopElements,
                            kCGWindowListOptionOnScreenOnly)
        fenetres = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID) or []
        for f in fenetres:
            if f.get("kCGWindowOwnerPID") != pid:
                continue
            if int(f.get("kCGWindowLayer", 0)) != 0:
                continue
            titre = f.get("kCGWindowName") or ""
            if titre:
                return str(titre), proc
        return "", proc
    except Exception:
        return "", proc


def _fenetre_active_mac_applescript():
    """Repli sans PyObjC : System Events donne le nom de l'app au premier plan."""
    try:
        nom = osascript(
            'tell application "System Events" to get name of first application '
            'process whose frontmost is true', timeout=4)
        return "", (nom or "").lower()
    except Exception:
        return "", ""


def moniteurs():
    """Rectangles (gauche, haut, droite, bas) des écrans, principal en premier.

    Liste vide si l'information n'est pas disponible.
    """
    if EST_MAC:
        try:
            from AppKit import NSScreen
            ecrans = list(NSScreen.screens())
            if not ecrans:
                return []
            # Cocoa place l'origine en BAS a gauche de l'ecran principal et fait
            # croitre y vers le haut ; tkinter (et le reste du code) attend
            # l'origine en HAUT a gauche avec y vers le bas. D'ou le retournement
            # autour de la hauteur de l'ecran principal, sans quoi l'overlay
            # atterrit hors champ sur un second ecran.
            hauteur_principale = ecrans[0].frame().size.height
            rects = []
            for e in ecrans:
                c = e.frame()
                gauche = int(c.origin.x)
                haut = int(hauteur_principale - (c.origin.y + c.size.height))
                rects.append((gauche, haut,
                              gauche + int(c.size.width),
                              haut + int(c.size.height)))
            rects.sort(key=lambda rc: (rc[0] != 0 or rc[1] != 0, rc[0], rc[1]))
            return rects
        except Exception:
            return []
    if EST_WINDOWS:
        try:
            import overlay
            return overlay._enum_moniteurs()
        except Exception:
            return []
    return []


# ============================================================ réseau

def ping(ip: str, timeout_ms: int = 800) -> bool:
    """Vrai si l'IP répond au ping. Sans fenêtre console, sans dépendance."""
    if not ip:
        return False
    if EST_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_ms)), ip]
    elif EST_MAC:
        # Sur macOS, -W est en millisecondes (contrairement à Linux).
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_ms)), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), ip]
    try:
        r = _run(cmd, timeout=max(2, timeout_ms / 1000 + 2))
        return "ttl=" in (r.stdout or "").lower()
    except Exception:
        return False


# ============================================================ extinction

_MINUTERIE_EXTINCTION = None      # threading.Timer, sur macOS/Linux


def _eteindre_maintenant():
    global _MINUTERIE_EXTINCTION
    _MINUTERIE_EXTINCTION = None
    try:
        if EST_MAC:
            osascript('tell application "System Events" to shut down', timeout=20)
        else:
            subprocess.run(["systemctl", "poweroff"], check=False, **sans_fenetre())
    except Exception as e:
        LOG.warning("plateforme: extinction refusée (%s)", e)


def programmer_extinction(delai: int):
    """Programme l'extinction dans `delai` secondes. Renvoie (ok, message).

    Windows utilise `shutdown /s /t` (natif, annulable par `shutdown /a`).
    macOS/Linux n'ont pas d'arrêt différé sans mot de passe administrateur : on
    tient donc la minuterie dans Jarvis, et l'arrêt est demandé au système au
    dernier moment (`System Events` sur macOS, aucun sudo requis).
    """
    global _MINUTERIE_EXTINCTION
    delai = max(5, int(delai))

    if EST_WINDOWS:
        try:
            r = _run(["shutdown", "/s", "/t", str(delai), "/c",
                      "Extinction demandee via Jarvis. Dis « annule l'extinction » "
                      "pour l'arreter."])
            if r.returncode == 0x45B:      # 1115 : un arrêt est déjà programmé
                return False, "deja_en_cours"
            if r.returncode != 0:
                return False, (r.stderr or "").strip()[:120]
        except Exception as e:
            return False, str(e)
        return True, ""

    if _MINUTERIE_EXTINCTION is not None:
        return False, "deja_en_cours"
    minuterie = threading.Timer(delai, _eteindre_maintenant)
    minuterie.daemon = True
    _MINUTERIE_EXTINCTION = minuterie
    minuterie.start()
    return True, ""


def annuler_extinction() -> bool:
    """Annule une extinction programmée. False s'il n'y en avait pas."""
    global _MINUTERIE_EXTINCTION
    if EST_WINDOWS:
        try:
            return _run(["shutdown", "/a"]).returncode == 0
        except Exception:
            return False
    if _MINUTERIE_EXTINCTION is None:
        return False
    try:
        _MINUTERIE_EXTINCTION.cancel()
    finally:
        _MINUTERIE_EXTINCTION = None
    return True


# ============================================================ voix de secours

_VOIX_SYSTEME = None      # nom de la voix française retenue (macOS), "" si aucune

_SCRIPT_SAPI = (
    "[Console]::InputEncoding = [Text.Encoding]::UTF8; "
    "$t = [Console]::In.ReadToEnd(); "
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$fr = $s.GetInstalledVoices() | "
    "Where-Object { $_.VoiceInfo.Culture.Name -like 'fr*' } | "
    "Select-Object -First 1; "
    "if ($fr) { $s.SelectVoice($fr.VoiceInfo.Name) }; "
    "$s.Rate = 1; "
    "$s.Speak($t)"
)


def _voix_francaise_mac() -> str:
    """Première voix française installée pour `say` ('' si aucune)."""
    global _VOIX_SYSTEME
    if _VOIX_SYSTEME is not None:
        return _VOIX_SYSTEME
    _VOIX_SYSTEME = ""
    try:
        r = _run(["say", "-v", "?"], timeout=6)
        for ligne in (r.stdout or "").splitlines():
            # « Thomas              fr_FR    # Bonjour, je m'appelle Thomas. »
            morceaux = ligne.split()
            if len(morceaux) >= 2 and any(m.startswith("fr_") for m in morceaux):
                nom = ligne.split("  ")[0].strip()
                if nom:
                    _VOIX_SYSTEME = nom
                    break
    except Exception:
        pass
    return _VOIX_SYSTEME


def nom_voix_systeme() -> str:
    """Libellé de la voix de secours, pour les messages et le diagnostic."""
    if EST_WINDOWS:
        return "voix Windows (SAPI)"
    if EST_MAC:
        v = _voix_francaise_mac()
        return f"voix macOS (say · {v})" if v else "voix macOS (say)"
    return "voix système (espeak/spd-say)"


def voix_systeme_disponible() -> bool:
    if EST_WINDOWS:
        return bool(shutil.which("powershell") or shutil.which("pwsh"))
    if EST_MAC:
        return bool(shutil.which("say"))
    return bool(shutil.which("spd-say") or shutil.which("espeak-ng")
                or shutil.which("espeak"))


def parler_systeme(texte: str):
    """Lance la voix intégrée à l'OS et renvoie le Popen (interruptible).

    Le texte passe TOUJOURS par l'entrée standard, jamais par la ligne de
    commande : une apostrophe française ne peut donc pas casser le littéral.
    Renvoie None si aucune voix système n'est disponible.
    """
    if EST_WINDOWS:
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            return None
        return subprocess.Popen(
            [exe, "-NoProfile", "-Command", _SCRIPT_SAPI],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, **sans_fenetre())

    if EST_MAC:
        if not shutil.which("say"):
            return None
        cmd = ["say", "-f", "-"]           # lit le texte sur stdin
        voix = _voix_francaise_mac()
        if voix:
            cmd[1:1] = ["-v", voix]
        return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for exe, args in ((shutil.which("spd-say"), ["-w", "-l", "fr", "-e"]),
                      (shutil.which("espeak-ng"), ["-v", "fr", "--stdin"]),
                      (shutil.which("espeak"), ["-v", "fr", "--stdin"])):
        if exe:
            return subprocess.Popen([exe, *args], stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return None


# ============================================================ audio & calcul

def micro_defaut():
    """Index/valeur par défaut du micro pour sounddevice.

    Windows garde l'historique (index 1) ; sur macOS et Linux, None laisse
    PortAudio choisir l'entrée système, ce qui est le comportement attendu
    (l'index 1 y désigne souvent une SORTIE).
    """
    return 1 if EST_WINDOWS else None


def peripherique_audio(valeur):
    """Normalise un réglage audio.micro / audio.haut_parleur pour sounddevice.

    Accepte un index (int ou chaîne de chiffres), un nom d'appareil, ou None.
    """
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, int):
        return valeur
    texte = str(valeur).strip()
    if texte.lstrip("-").isdigit():
        return int(texte)
    return texte


def accelerateur_whisper():
    """(device, compute_type) à essayer en premier pour faster-whisper.

    CTranslate2 ne gère pas Metal : sur Mac, le CPU est la seule cible, mais il
    est rapide sur Apple Silicon (int8 sur les cœurs performance).
    """
    if EST_MAC:
        return "cpu", "int8"
    return "cuda", "float16"


def infos_gpu():
    """Description de la carte graphique, ou '' si indéterminable.

    Sur Mac, le GPU est intégré à la puce : `system_profiler` donne son nom et
    le nombre de cœurs. Aucune API publique ne donne la température sans droits
    administrateur — on ne l'invente pas.
    """
    if not EST_MAC:
        return ""
    try:
        r = _run(["system_profiler", "SPDisplaysDataType"], timeout=12)
        nom, coeurs = "", ""
        for ligne in (r.stdout or "").splitlines():
            l = ligne.strip()
            if l.startswith("Chipset Model:"):
                nom = l.split(":", 1)[1].strip()
            elif l.lower().startswith("total number of cores:"):
                coeurs = l.split(":", 1)[1].strip()
        if nom and coeurs:
            return f"{nom} ({coeurs} cœurs GPU)"
        return nom or _sysctl("machdep.cpu.brand_string")
    except Exception:
        return _sysctl("machdep.cpu.brand_string")
