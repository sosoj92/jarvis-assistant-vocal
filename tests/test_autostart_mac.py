import plistlib
import subprocess
from pathlib import Path

PROJET = Path(__file__).resolve().parent.parent
SCRIPT = PROJET / "scripts" / "autostart_mac.sh"


def test_autostart_mac_genere_un_plist_valide(tmp_path, monkeypatch):
    """Le script launchd doit produire un plist parseable avec KeepAlive."""
    # On isole la generation : HOME vers un faux repertoire.
    faux_home = tmp_path / "home"
    (faux_home / ".local" / "bin").mkdir(parents=True)
    uv = faux_home / ".local" / "bin" / "uv"
    uv.write_text("#!/bin/sh\n")
    uv.chmod(0o755)
    monkeypatch.setenv("HOME", str(faux_home))
    r = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True,
        env={**__import__("os").environ, "HOME": str(faux_home)},
    )
    # launchctl n'existe pas hors macOS : le script doit avoir ecrit le plist
    # meme si le chargement echoue.
    plist = faux_home / "Library" / "LaunchAgents" / "com.jarvis.assistant.plist"
    assert plist.exists(), r.stdout + r.stderr
    d = plistlib.loads(plist.read_bytes())
    assert d["Label"] == "com.jarvis.assistant"
    assert d["RunAtLoad"] is True
    assert d["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}
    assert d["ThrottleInterval"] == 15
    assert d["ProgramArguments"][-1] == "jarvis14.py"
    assert d["WorkingDirectory"] == str(PROJET)
