"""Ouverture d'une page web dans le navigateur choisi (reglage navigateur.prefere).

« firefox » (defaut) : nouvel onglet Firefox s'il est installe, sinon le navigateur
par defaut du systeme. « systeme » : toujours le navigateur par defaut. Les fenetres
propres a Jarvis (HUD, cockpit en mode application) et le Chrome pilote pour lire ou
agir sur une page ne passent pas par ici.
"""
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

from core.config import reglage

_FIREFOX = (r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
            r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
            r"%LocalAppData%\Mozilla Firefox\firefox.exe")


def navigateur_prefere():
    return str(reglage("navigateur.prefere", "firefox") or "systeme").strip().lower()


def firefox_exe():
    """Chemin de firefox.exe (reglage navigateur.firefox_exe, PATH, emplacements standards)."""
    candidats = [str(reglage("navigateur.firefox_exe", "") or ""), shutil.which("firefox") or ""]
    candidats += [os.path.expandvars(p) for p in _FIREFOX]
    return next((c for c in candidats if c and "%" not in c and Path(c).is_file()), None)


def ouvrir_url(url):
    """Ouvre url dans un nouvel onglet. Renvoie True si l'ouverture est partie."""
    if navigateur_prefere() == "firefox":
        exe = firefox_exe()
        if exe:
            try:
                subprocess.Popen([exe, "-new-tab", url], close_fds=True,
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
                return True
            except OSError:
                pass
    return bool(webbrowser.open_new_tab(url))


def nom_navigateur():
    """« Firefox » si c'est lui qui s'ouvrira, sinon « ton navigateur »."""
    return "Firefox" if navigateur_prefere() == "firefox" and firefox_exe() else "ton navigateur"
