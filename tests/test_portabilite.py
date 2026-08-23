"""Tests de portabilité : ce qui empêcherait Jarvis de démarrer hors Windows.

L'idée n'est pas de tester le comportement métier (déjà couvert ailleurs) mais
de verrouiller le portage : plus aucun chemin C:\\, plus aucun appel Win32 hors
de core/plateforme.py, et les modules d'outils s'importent bien sur cet OS.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent

# Modules dont on garantit l'import sur les trois systèmes. Ils ne doivent
# dépendre d'aucune bibliothèque spécifique à un OS *au moment de l'import*.
MODULES_PORTABLES = [
    "core.plateforme",
    "tools.systeme",
    "tools.apps",
    "tools.stats",
    "tools.presence",
    "tools.ecran",
]

# Fichiers Python du projet, hors environnements et dossiers de travail.
IGNORES = {".venv", "venv", "build", "dist", "__pycache__", ".git", "tests"}


def fichiers_python():
    for chemin in RACINE.rglob("*.py"):
        if IGNORES & set(chemin.relative_to(RACINE).parts):
            continue
        yield chemin


@pytest.mark.parametrize("module", MODULES_PORTABLES)
def test_module_importable(module):
    """Un import qui explose = Jarvis qui ne démarre pas. C'est le test clé."""
    __import__(module)


def test_aucun_chemin_windows_en_dur():
    """Plus un seul « C:\\... » dans le code : tout passe par pathlib/plateforme."""
    motif = re.compile(r"[\"']\s*[A-Za-z]:\\\\?[A-Za-z]")
    coupables = []
    for chemin in fichiers_python():
        for num, ligne in enumerate(chemin.read_text(encoding="utf-8",
                                                     errors="replace").splitlines(), 1):
            if motif.search(ligne) and "plateforme" not in chemin.name:
                coupables.append(f"{chemin.relative_to(RACINE)}:{num}: {ligne.strip()}")
    assert not coupables, "chemins Windows en dur :\n" + "\n".join(coupables)


# Attributs et constantes purement Win32.
_ATTRIBUTS_WIN32 = {"windll", "startfile"}
_DRAPEAUX_WIN32 = {"CREATE_NO_WINDOW", "DETACHED_PROCESS"}


def test_appels_win32_confines_dans_plateforme():
    """ctypes.windll / os.startfile ne doivent vivre que dans la couche système.

    L'analyse porte sur le CODE (AST), pas sur le texte : un commentaire ou une
    docstring qui mentionne os.startfile n'est pas un appel Win32.

    overlay.py est la seule exception assumée : c'est une fenêtre Win32 native,
    déjà gardée par `if not _WIN: return`, sans équivalent tkinter.
    """
    autorises = {"core/plateforme.py", "overlay.py"}
    coupables = []
    for chemin in fichiers_python():
        relatif = chemin.relative_to(RACINE).as_posix()
        if relatif in autorises:
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"),
                          filename=str(chemin))
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Attribute) and noeud.attr in _ATTRIBUTS_WIN32:
                coupables.append(f"{relatif}:{noeud.lineno}: .{noeud.attr}")
            # getattr(subprocess, "CREATE_NO_WINDOW", 0) et compagnie.
            elif isinstance(noeud, ast.Constant) and noeud.value in _DRAPEAUX_WIN32:
                coupables.append(f"{relatif}:{noeud.lineno}: {noeud.value}")
    assert not coupables, "appels Win32 hors de la couche système :\n" + "\n".join(coupables)


def test_import_keyboard_toujours_protege():
    """`keyboard` exige root hors Windows : jamais d'import au niveau module."""
    coupables = []
    for chemin in fichiers_python():
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"),
                          filename=str(chemin))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Import):
                continue
            if not any(a.name == "keyboard" for a in noeud.names):
                continue
            # Un import de module (colonne 0) n'est pas protégé ; imbriqué, si.
            if noeud.col_offset == 0:
                coupables.append(f"{chemin.relative_to(RACINE)}:{noeud.lineno}")
    assert not coupables, "import keyboard non protégé :\n" + "\n".join(coupables)


def test_tous_les_fichiers_python_compilent():
    """Filet de sécurité : aucune erreur de syntaxe introduite par le portage."""
    erreurs = []
    for chemin in fichiers_python():
        try:
            ast.parse(chemin.read_text(encoding="utf-8", errors="replace"),
                      filename=str(chemin))
        except SyntaxError as e:
            erreurs.append(f"{chemin.relative_to(RACINE)}: {e}")
    assert not erreurs, "\n".join(erreurs)


def test_scripts_bash_presents_et_executables():
    """Les équivalents des .bat doivent exister et être lançables."""
    attendus = ["launch_jarvis.sh", "launch_mcp_server.sh", "update_jarvis.sh",
                "save_jarvis.sh", "chrome_jarvis.sh"]
    for nom in attendus:
        chemin = RACINE / nom
        assert chemin.exists(), f"{nom} manquant"
        if sys.platform != "win32":
            assert chemin.stat().st_mode & 0o111, f"{nom} n'est pas exécutable"


def test_dependances_windows_marquees():
    """Les paquets sans roue macOS doivent porter un marqueur d'environnement."""
    pyproject = (RACINE / "pyproject.toml").read_text(encoding="utf-8")
    for paquet in ("keyboard", "nvidia-cublas-cu12", "nvidia-cudnn-cu12",
                   "nvidia-ml-py", "soundcard"):
        ligne = [l for l in pyproject.splitlines()
                 if l.strip().startswith(f'"{paquet}')]
        assert ligne, f"{paquet} introuvable dans pyproject.toml"
        assert ";" in ligne[0], f"{paquet} n'a pas de marqueur de plateforme"
