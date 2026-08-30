"""Reconnaissance musicale (Shazam-like) — JARVIS PUR, réflexe local à la demande.

« C'est quoi cette musique ? » → capture ~8 s d'audio, empreinte via shazamio,
réponse courte. Deux sources : le MICRO de la pièce (musique ambiante) ou l'AUDIO
SYSTÈME du PC (loopback WASAPI — pour identifier le son d'une vidéo/un reel qu'on
regarde). Variante FICHIER pour un audio/vidéo déjà sur le disque (Vault).

Vie privée / sobriété :
- Reconnaissance UNIQUEMENT à la demande — jamais d'écoute musicale en fond.
- Ce qui part vers Shazam = l'empreinte des ~8 s capturées, rien d'autre.
- Les captures micro/système ne sont PAS exposées au MCP (le micro reste local) ;
  seule la variante fichier l'est (inoffensive). Voir docs/musique.md.

shazamio-core (Rust) n'a pas de wheel Python 3.13 → la reconnaissance tourne dans
un venv isolé 3.12 (musique/.venv-shazam, cf. scripts/setup_musique.py). Ce module
(3.13) capture l'audio, écrit un WAV, et appelle musique/reconnaisseur.py dedans.
"""
import datetime
import json
import subprocess
from pathlib import Path

from core.config import reglage
from core.registre import outil

_RACINE = Path(__file__).resolve().parent.parent
_PY_SHAZAM = _RACINE / "musique" / ".venv-shazam" / "Scripts" / "python.exe"
_RECONNAISSEUR = _RACINE / "musique" / "reconnaisseur.py"
_CAPTURES = _RACINE / "musique" / "captures"
_NOTES = _RACINE / "notes" / "musiques.md"

# Hook injecté par jarvis14 : capture depuis le micro EN SUSPENDANT le wake word
# (le micro est partagé). Signature : (secondes) -> (samples float32 mono, sr).
_CAPTURE_MICRO = None


def definir_capture_micro(fn):
    global _CAPTURE_MICRO
    _CAPTURE_MICRO = fn


# --------------------------------------------------------------- capture

def _capturer_micro(secondes):
    if _CAPTURE_MICRO is not None:
        return _CAPTURE_MICRO(secondes)          # gère la pause du wake word + bip
    # Repli (outil appelé hors de jarvis14, ex. test) : capture directe.
    import sounddevice as sd
    sr = 16000
    audio = sd.rec(int(secondes * sr), samplerate=sr, channels=1,
                   dtype="float32", device=reglage("audio.micro", 1))
    sd.wait()
    return audio.reshape(-1), sr


def _capturer_systeme(secondes):
    """Audio joué par le PC (loopback WASAPI du haut-parleur par défaut)."""
    try:
        import soundcard as sc
    except ImportError as e:
        raise ImportError("soundcard-absent") from e
    import numpy as np
    sr = 44100
    spk = sc.default_speaker()
    try:
        mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
    except Exception:
        loops = sc.all_microphones(include_loopback=True)
        if not loops:
            raise RuntimeError("aucun périphérique loopback")
        mic = loops[0]
    with mic.recorder(samplerate=sr, channels=1) as rec:
        data = rec.record(numframes=int(secondes * sr))
    return np.asarray(data).reshape(-1).astype("float32"), sr


def _ecrire_wav(samples, sr, chemin):
    import wave

    import numpy as np
    pcm = (np.clip(np.asarray(samples), -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())


# --------------------------------------------------------------- reconnaissance

def _reconnaitre(chemin):
    """Appelle le sous-process 3.12 (shazamio) sur un fichier, renvoie le dict JSON."""
    if not _PY_SHAZAM.exists():
        return {"ok": False, "message": "setup"}
    try:
        p = subprocess.run(
            [str(_PY_SHAZAM), str(_RECONNAISSEUR), str(chemin)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "délai dépassé (réseau Shazam ?)"}
    for ligne in reversed((p.stdout or "").splitlines()):
        ligne = ligne.strip()
        if ligne.startswith("{"):
            try:
                return json.loads(ligne)
            except json.JSONDecodeError:
                pass
    return {"ok": False, "message": (p.stderr or "sortie illisible")[:150]}


def _formuler(res):
    if not res.get("ok"):
        if res.get("message") == "setup":
            return ("La reconnaissance musicale n'est pas encore installée. Lance "
                    "« python scripts/setup_musique.py » une fois.")
        return "Je n'ai pas reconnu la musique — rapproche-moi de la source ?"
    phrase = f"C'est {res.get('titre') or '?'} de {res.get('artiste') or '?'}"
    if res.get("annee"):
        phrase += f" ({res['annee']})"
    return phrase + "."


def _logger(res, source):
    if not res.get("ok"):
        return
    try:
        _NOTES.parent.mkdir(parents=True, exist_ok=True)
        if not _NOTES.exists():
            _NOTES.write_text("# Musiques reconnues\n\n", encoding="utf-8")
        horo = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        ligne = f"- {horo} · **{res.get('titre','?')}** — {res.get('artiste','?')}"
        if res.get("album"):
            ligne += f" · _{res['album']}_"
        if res.get("annee"):
            ligne += f" ({res['annee']})"
        ligne += f" · [{source}]"
        if res.get("url"):
            ligne += f" · {res['url']}"
        with open(_NOTES, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")
    except Exception:
        pass


def _capturer_et_reconnaitre(source, secondes):
    secondes = max(4, min(15, int(secondes or reglage("musique.secondes", 8))))
    src = (source or "micro").lower()
    systeme = src in ("systeme", "système", "system", "loopback", "video", "vidéo",
                      "pc", "ordinateur", "stream", "reel")
    try:
        if systeme:
            samples, sr = _capturer_systeme(secondes)
            src_log = "système"
        else:
            samples, sr = _capturer_micro(secondes)
            src_log = "micro"
    except ImportError:
        return ("Pour identifier le son du PC, installe d'abord soundcard : "
                "« uv add soundcard ». Sinon, dis « c'est quoi cette musique » "
                "(via le micro).")
    except Exception as e:
        return f"Je n'ai pas pu capturer l'audio ({str(e)[:80]})."
    _CAPTURES.mkdir(parents=True, exist_ok=True)
    wav = _CAPTURES / "capture.wav"
    _ecrire_wav(samples, sr, wav)
    res = _reconnaitre(wav)
    _logger(res, src_log)
    if res.get("ok"):                     # découverte live -> auto-ajout Spotify (option)
        try:
            from tools import spotify
            spotify.auto_ajouter(res.get("titre"), res.get("artiste"))
        except Exception:
            pass
    return _formuler(res)


def derniere_reconnaissance():
    """(titre, artiste) de la dernière musique reconnue, ou None (pour Spotify)."""
    if not _NOTES.exists():
        return None
    import re
    lignes = [l for l in _NOTES.read_text(encoding="utf-8").splitlines()
              if l.startswith("- ")]
    if not lignes:
        return None
    m = re.search(r"\*\*(.+?)\*\*\s*—\s*([^·]+)", lignes[-1])
    return (m.group(1).strip(), m.group(2).strip()) if m else None


# --------------------------------------------------------------- outils

@outil(
    nom="identifier_musique",
    description="Identifie la musique en cours (comme Shazam). Capture ~8 s puis "
                "reconnaît. source='micro' pour la musique de la pièce (radio, "
                "ambiance) ; source='systeme' pour le son qui joue DANS le PC (vidéo, "
                "reel, stream). Pour « c'est quoi cette musique/chanson », « Shazam "
                "ça », « c'est quoi la musique de cette vidéo » (→ systeme).",
    parametres={
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["micro", "systeme"],
                       "description": "micro = la pièce ; systeme = l'audio du PC."},
            "secondes": {"type": "integer",
                         "description": "Durée de capture (4-15, défaut 8)."},
        },
    },
    mcp_expose=False,       # capture micro/système : le micro reste local
    affichage="toujours",   # overlay : titre/artiste toujours à l'écran
)
def identifier_musique(source: str = "micro", secondes: int = 8) -> str:
    return _capturer_et_reconnaitre(source, secondes)


@outil(
    nom="identifier_musique_fichier",
    description="Identifie la musique d'un FICHIER audio ou vidéo déjà sur le disque "
                "(ex. une vidéo d'inspiration du Vault). Pour « c'est quoi le son de "
                "cette vidéo/ce fichier ».",
    parametres={
        "type": "object",
        "properties": {
            "chemin": {"type": "string",
                       "description": "Chemin du fichier audio/vidéo à identifier."},
        },
        "required": ["chemin"],
    },
    lent=True,
    phrase_attente="Je cherche le son de ce fichier.",
    mcp_expose=False,       # SÉCURITÉ : chemin de fichier libre -> local uniquement
                            # (à distance = oracle d'existence + ffmpeg sur chemin arbitraire)
    affichage="toujours",
)
def identifier_musique_fichier(chemin: str) -> str:
    p = Path(chemin).expanduser()
    if not p.exists():
        return f"Fichier introuvable : {chemin}."
    res = _reconnaitre(str(p))
    _logger(res, "fichier")
    return _formuler(res)


@outil(
    nom="derniere_musique",
    description="Redonne la dernière musique reconnue (« c'était quoi la musique de "
                "tout à l'heure ? »).",
    mcp_expose=False,
    affichage="toujours",
)
def derniere_musique() -> str:
    if not _NOTES.exists():
        return "Je n'ai encore rien reconnu."
    lignes = [l.strip() for l in _NOTES.read_text(encoding="utf-8").splitlines()
              if l.startswith("- ")]
    if not lignes:
        return "Je n'ai encore rien reconnu."
    # « - 2026-08-13 14:30 · **Titre** — Artiste · … »
    derniere = lignes[-1].lstrip("- ")
    corps = derniere.split("·", 1)[1].strip() if "·" in derniere else derniere
    return "La dernière, c'était " + corps.replace("**", "").replace("_", "") + "."
