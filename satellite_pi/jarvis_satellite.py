#!/usr/bin/env python3
"""Satellite Jarvis pour Raspberry Pi — les oreilles + la bouche dans une pièce.

À COPIER SUR LE PI (pas besoin du reste du dépôt). Il :
  1. écoute le micro et détecte « Hey Jarvis » SUR LE PI (openWakeWord) ;
  2. capture ta phrase jusqu'au silence, l'envoie en PCM 16 kHz au PC
     (WebSocket /satellite — même protocole qu'un futur ESP32) ;
  3. joue l'audio de réponse renvoyé par le PC sur le haut-parleur ;
  4. se reconnecte tout seul, et te le dit si le PC est injoignable.

Config : satellite_pi/config.yaml (pc_url, satellite_id, token, pièce côté PC,
device micro/haut-parleur). Voir docs/satellite_pi.md.

Dépendances : sounddevice, numpy, openwakeword, websockets, pyyaml (+ le modèle
hey_jarvis fourni par openwakeword). Cf. requirements.txt.
"""
import asyncio
import json
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import yaml

RACINE = Path(__file__).resolve().parent
TAUX = 16000            # 16 kHz mono, comme attendu par openWakeWord ET par le PC
BLOC = 1280             # 80 ms


def _conf():
    p = RACINE / "config.yaml"
    if not p.exists():
        print("config.yaml manquant — copie config.exemple.yaml en config.yaml.")
        sys.exit(1)
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


class Micro:
    """Capture micro + wake word (openWakeWord) + capture d'énoncé (VAD simple).
    Tourne dans un thread ; pousse chaque énoncé complet (PCM int16 bytes) dans une
    file pour l'envoi au PC."""

    def __init__(self, conf, file_sortie):
        self.conf = conf
        self.file = file_sortie
        self.stop = threading.Event()
        self.seuil_reveil = float(conf.get("seuil_reveil", 0.5))
        self.seuil_silence = float(conf.get("seuil_silence", 0.010))
        self.silence_fin = float(conf.get("silence_fin", 1.0))
        self.duree_max = float(conf.get("duree_max", 15))
        self.device = conf.get("micro", None)

    def _reveil(self):
        import openwakeword
        from openwakeword.model import Model
        chemin = (Path(openwakeword.__file__).parent / "resources" / "models"
                  / "hey_jarvis_v0.1.onnx")
        return Model(wakeword_model_paths=[str(chemin)])

    def _niveau(self, bloc):
        return float(np.sqrt(np.mean(bloc ** 2)))

    def run(self):
        reveil = self._reveil()
        flux = sd.InputStream(samplerate=TAUX, channels=1, dtype="float32",
                              device=self.device, blocksize=BLOC)
        flux.start()
        print("Satellite prêt. Dites « Hey Jarvis ».")
        try:
            while not self.stop.is_set():
                bloc, _ = flux.read(BLOC)
                bloc = bloc.flatten()
                scores = reveil.predict((bloc * 32767).astype(np.int16))
                if max(scores.values()) < self.seuil_reveil:
                    continue
                reveil.reset()
                print("  [wake] Hey Jarvis — j'écoute")
                # capture jusqu'au silence
                morceaux, debut, dernier = [bloc], time.time(), time.time()
                while not self.stop.is_set():
                    b, _ = flux.read(BLOC)
                    b = b.flatten()
                    morceaux.append(b)
                    if self._niveau(b) > self.seuil_silence:
                        dernier = time.time()
                    if time.time() - dernier > self.silence_fin:
                        break
                    if time.time() - debut > self.duree_max:
                        break
                audio = np.concatenate(morceaux)
                pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
                self.file.put(pcm)
        finally:
            flux.stop(); flux.close()


def _jouer(pcm, freq):
    """Joue du PCM 16-bit mono à `freq` Hz sur le haut-parleur."""
    try:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, samplerate=freq, device=CONF.get("haut_parleur", None))
        sd.wait()
    except Exception as e:
        print("  [audio] lecture impossible:", e)


async def _session(url, satellite, token, file_audio):
    """Une connexion au PC : envoie les énoncés de la file, joue les réponses."""
    import websockets
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "satellite": satellite, "token": token}))
        # attendre pret
        while True:
            m = await ws.recv()
            if isinstance(m, str) and json.loads(m).get("type") == "pret":
                print("  [pc] connecté."); break
            if isinstance(m, str) and json.loads(m).get("type") == "erreur":
                print("  [pc] refusé:", json.loads(m).get("message")); return

        async def emetteur():
            loop = asyncio.get_event_loop()
            while True:
                pcm = await loop.run_in_executor(None, file_audio.get)  # bloque jusqu'à un énoncé
                for i in range(0, len(pcm), 4096):
                    await ws.send(pcm[i:i + 4096])
                await ws.send(json.dumps({"type": "fin_parole"}))

        tache_emet = asyncio.create_task(emetteur())
        try:
            audio, freq = bytearray(), TAUX
            while True:
                m = await ws.recv()
                if isinstance(m, (bytes, bytearray)):
                    audio.extend(m); continue
                d = json.loads(m)
                t = d.get("type")
                if t == "etat":
                    print(f"  [état] {d.get('etat')}")
                elif t == "transcription":
                    print(f"  [entendu] {d.get('texte')}")
                elif t == "texte":
                    print(f"  [réponse] {d.get('texte')}")
                elif t == "audio_debut":
                    audio, freq = bytearray(), int(d.get("freq", TAUX))
                elif t == "audio_fin":
                    _jouer(bytes(audio), freq); audio = bytearray()
                elif t == "erreur":
                    print("  [erreur]", d.get("message"))
        finally:
            tache_emet.cancel()


async def _boucle(url, satellite, token, file_audio):
    """Reconnexion automatique tant que le PC n'est pas joignable."""
    prevenu = False
    while True:
        try:
            await _session(url, satellite, token, file_audio)
            prevenu = False
        except Exception as e:
            if not prevenu:
                print(f"  [pc] injoignable ({str(e)[:60]}) — Jarvis dort, rallume la tour ? "
                      "Je réessaie…")
                prevenu = True
            await asyncio.sleep(3)


CONF = {}


def main():
    global CONF
    CONF = _conf()
    url = CONF.get("pc_url", "ws://192.168.1.10:8790/satellite")
    satellite = str(CONF.get("satellite_id", "cuisine"))
    token = str(CONF.get("token", ""))
    if not token:
        print("token manquant dans config.yaml"); sys.exit(1)

    file_audio = queue.Queue()
    micro = Micro(CONF, file_audio)
    threading.Thread(target=micro.run, name="micro", daemon=True).start()
    try:
        asyncio.run(_boucle(url, satellite, token, file_audio))
    except KeyboardInterrupt:
        micro.stop.set()
        print("\nAu revoir.")


if __name__ == "__main__":
    main()
