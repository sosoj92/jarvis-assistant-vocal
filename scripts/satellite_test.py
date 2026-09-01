"""Client de TEST du satellite — simule un boîtier sur le PC lui-même (sans matériel).

Se connecte au WebSocket /satellite du serveur unifié, envoie une phrase audio
(un WAV, ou une phrase générée par la voix Windows), affiche les événements d'état
reçus (écoute / réflexion / parole / transcription / réponse) et enregistre l'audio
de réponse dans un WAV pour que tu puisses l'écouter. Mesure la latence.

Prérequis : Jarvis lancé (serveur unifié up), et un satellite déclaré en config :
  satellites:
    - id: "test"
      piece: "bureau"
      token: "..."

Usage :
  uv run python scripts/satellite_test.py                       # phrase par défaut
  uv run python scripts/satellite_test.py --texte "quelle heure est-il"
  uv run python scripts/satellite_test.py --wav chemin.wav      # ton propre audio
  uv run python scripts/satellite_test.py --satellite test --url ws://127.0.0.1:8790/satellite
"""
import argparse
import asyncio
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

try:                                   # console Windows cp1252 -> éviter les crash d'emoji
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from core.config import reglage  # noqa: E402

TAUX = 16000


def _token_du(satellite):
    for s in (reglage("satellites", []) or []):
        if isinstance(s, dict) and str(s.get("id")) == satellite:
            return str(s.get("token", "") or "")
    return ""


def _pcm_depuis_wav(chemin):
    """Lit un WAV -> PCM 16 bits mono 16 kHz (rééchantillonné si besoin)."""
    with wave.open(str(chemin), "rb") as w:
        n, sr, sw, ch = w.getnframes(), w.getframerate(), w.getsampwidth(), w.getnchannels()
        brut = w.readframes(n)
    a = np.frombuffer(brut, dtype=np.int16)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != TAUX:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(TAUX, sr)
        a = resample_poly(a.astype(np.float32), TAUX // g, sr // g).astype(np.int16)
    return a.tobytes()


def _generer_wav(texte, sortie):
    """Génère un WAV de `texte` via la voix Windows (SAPI)."""
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{sortie}'); $s.Speak('{texte}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   capture_output=True)
    return sortie


async def _run(url, satellite, token, pcm, sortie_wav):
    import websockets
    t_connexion = time.time()
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "satellite": satellite, "token": token}))
        # attendre "pret"
        while True:
            m = await ws.recv()
            if isinstance(m, (bytes, bytearray)):
                continue
            d = json.loads(m)
            if d.get("type") == "pret":
                print(f"✓ connecté — pièce « {d.get('piece','?')} »")
                break
            if d.get("type") == "erreur":
                print("✗ refusé :", d.get("message")); return

        # envoyer l'audio (frames binaires) puis fin_parole
        print(f"→ envoi de {len(pcm)} octets PCM ({len(pcm)/2/TAUX:.1f}s)...")
        for i in range(0, len(pcm), 4096):
            await ws.send(pcm[i:i + 4096])
        t_fin_parole = time.time()
        await ws.send(json.dumps({"type": "fin_parole"}))

        # recevoir les événements + l'audio de réponse
        audio = bytearray()
        freq = TAUX
        t_premier_audio = None
        while True:
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("✗ timeout (pas de réponse)"); break
            if isinstance(m, (bytes, bytearray)):
                if t_premier_audio is None:
                    t_premier_audio = time.time()
                audio.extend(m); continue
            d = json.loads(m)
            t = d.get("type")
            if t == "etat":
                print(f"   [état] {d.get('etat')}")
            elif t == "transcription":
                print(f"   [entendu] « {d.get('texte')} »")
            elif t == "texte":
                print(f"   [réponse] « {d.get('texte')} »")
            elif t == "audio_debut":
                freq = int(d.get("freq", TAUX))
            elif t == "audio_fin":
                break
            elif t == "erreur":
                print("   [erreur]", d.get("message"))

        if audio:
            with wave.open(str(sortie_wav), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(freq)
                w.writeframes(bytes(audio))
            lat = (t_premier_audio - t_fin_parole) if t_premier_audio else -1
            print(f"✓ réponse audio : {len(audio)} octets @ {freq} Hz -> {sortie_wav}")
            print(f"⏱  latence (fin de phrase -> 1er son) : {lat:.2f}s"
                  + ("  ✅ < 2s" if 0 <= lat < 2 else ""))
        else:
            print("… aucune réponse audio reçue")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8790/satellite")
    ap.add_argument("--satellite", default="test")
    ap.add_argument("--token", default="")
    ap.add_argument("--wav", default="")
    ap.add_argument("--texte", default="quelle heure est-il")
    a = ap.parse_args()

    token = a.token or _token_du(a.satellite)
    if not token:
        print(f"Pas de token pour le satellite « {a.satellite} ». Ajoute-le en config "
              "(satellites) ou passe --token."); return

    tmp = RACINE / "logs"
    tmp.mkdir(exist_ok=True)
    if a.wav:
        pcm = _pcm_depuis_wav(a.wav)
    else:
        wav = _generer_wav(a.texte, str(tmp / "_sat_test_in.wav"))
        pcm = _pcm_depuis_wav(wav)

    sortie = tmp / "_sat_test_reponse.wav"
    asyncio.run(_run(a.url, a.satellite, token, pcm, sortie))


if __name__ == "__main__":
    main()
