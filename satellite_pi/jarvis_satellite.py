#!/usr/bin/env python3
"""Client audio satellite Jarvis pour Raspberry Pi ou machine Linux compatible.

Le dossier satellite_pi/ peut être déployé sans le reste du dépôt. Le client :
  1. écoute le micro et détecte « Hey Jarvis » SUR LE PI (openWakeWord) ;
  2. capture ta phrase jusqu'au silence, l'envoie en PCM 16 kHz au PC
     (WebSocket /satellite) ;
  3. joue l'audio de réponse renvoyé par le PC sur le haut-parleur ;
  4. se reconnecte automatiquement si le serveur est temporairement indisponible.

Config : satellite_pi/config.yaml (pc_url, satellite_id, token, pièce côté PC,
device micro/haut-parleur). Voir docs/satellite_pi.md.

Dépendances : sounddevice, numpy, openwakeword, websockets, pyyaml (+ le modèle
hey_jarvis fourni par openwakeword). Cf. requirements.txt.
"""
import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
import time
from math import gcd
from pathlib import Path

import numpy as np
import sounddevice as sd
import yaml
from scipy.signal import resample_poly

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

    def __init__(self, conf, file_sortie, occupe):
        self.conf = conf
        self.file = file_sortie
        self.occupe = occupe
        self.stop = threading.Event()
        self.seuil_reveil = float(conf.get("seuil_reveil", 0.5))
        self.gain_reveil = float(conf.get("gain_reveil", 1.0))
        self.gain_audio = float(conf.get("gain_audio", 1.0))
        self.seuil_silence = float(conf.get("seuil_silence", 0.010))
        self.silence_fin = float(conf.get("silence_fin", 1.0))
        self.duree_max = float(conf.get("duree_max", 15))
        self.attente_parole = float(conf.get("attente_parole", 3.0))
        self.fenetre_relance = float(conf.get("fenetre_relance", 8.0))
        self.blocs_purge_bip = max(0, int(conf.get("blocs_purge_bip", 2)))
        self.attente_arbitrage_reveil = float(
            conf.get("attente_arbitrage_reveil", 4.0))
        self.device = conf.get("micro", None)
        self.sortie = conf.get("haut_parleur", None)
        self._relance_jusqua = 0.0
        self._relance_lock = threading.Lock()
        self._reveil_lock = threading.Lock()
        self._reveil_event = threading.Event()
        self._reveil_id = 0
        self._reveil_accepte = False
        self._reveil_accuse_vocal = False
        try:
            info = sd.query_devices(self.device, "input")
            self.taux_capture = int(round(info.get("default_samplerate") or TAUX))
        except Exception:
            self.taux_capture = TAUX
        self.bloc_capture = int(round(BLOC * self.taux_capture / TAUX))

    def _reveil(self):
        import openwakeword
        from openwakeword.model import Model
        chemin = (Path(openwakeword.__file__).parent / "resources" / "models"
                  / "hey_jarvis_v0.1.onnx")
        return Model(wakeword_model_paths=[str(chemin)])

    def _niveau(self, bloc):
        return float(np.sqrt(np.mean(bloc ** 2)))

    def _vers_16k(self, bloc):
        """Ramène un bloc capturé au taux natif du micro vers 16 kHz."""
        if self.taux_capture == TAUX:
            return bloc
        facteur = gcd(TAUX, self.taux_capture)
        return resample_poly(
            bloc, TAUX // facteur, self.taux_capture // facteur
        ).astype(np.float32)

    def _lire_bloc(self, flux):
        bloc, _ = flux.read(self.bloc_capture)
        return self._vers_16k(bloc.flatten())

    def ouvrir_relance(self, secondes=None):
        """Autorise une phrase de suivi sans nouveau mot d'activation."""
        try:
            duree = float(self.fenetre_relance if secondes is None else secondes)
        except (TypeError, ValueError):
            duree = self.fenetre_relance
        with self._relance_lock:
            self._relance_jusqua = time.monotonic() + max(0.0, min(duree, 30.0))

    def fermer_relance(self):
        with self._relance_lock:
            self._relance_jusqua = 0.0

    def _relance_restante(self):
        with self._relance_lock:
            return max(0.0, self._relance_jusqua - time.monotonic())

    def _demander_reveil(self, score):
        """Demande au PC si ce micro est le mieux placé pour répondre."""
        with self._reveil_lock:
            self._reveil_id += 1
            identifiant = self._reveil_id
            self._reveil_accepte = False
            self._reveil_accuse_vocal = False
            self._reveil_event.clear()
        self.file.put({
            "type": "reveil",
            "id": identifiant,
            "score": float(score),
            "_cree": time.monotonic(),
        })
        if not self._reveil_event.wait(timeout=max(
                1.5, min(self.attente_arbitrage_reveil, 6.0))):
            return False, False
        with self._reveil_lock:
            accepte = self._reveil_id == identifiant and self._reveil_accepte
            return accepte, accepte and self._reveil_accuse_vocal

    def resoudre_reveil(self, identifiant, accepte, accuse_vocal=False):
        with self._reveil_lock:
            if identifiant != self._reveil_id:
                return
            self._reveil_accepte = bool(accepte)
            self._reveil_accuse_vocal = bool(accuse_vocal)
            self._reveil_event.set()

    def _capturer_enonce(self, flux, attente, message_vide):
        """Attend le début de la voix, puis capture jusqu'au silence."""
        morceaux, debut, dernier = [], time.monotonic(), None
        while not self.stop.is_set():
            b = self._lire_bloc(flux)
            maintenant = time.monotonic()
            if self._niveau(b) > self.seuil_silence:
                dernier = maintenant
            if dernier is not None:
                morceaux.append(b)
                if maintenant - dernier > self.silence_fin:
                    break
            elif maintenant - debut > attente:
                print(message_vide)
                break
            if maintenant - debut > self.duree_max:
                break
        if not morceaux:
            return None
        audio = np.concatenate(morceaux)
        print(
            f"  [micro] capture {len(audio) / TAUX:.2f}s "
            f"rms={self._niveau(audio):.4f} "
            f"pic={float(np.max(np.abs(audio))):.4f} "
            f"gain_envoi=x{self.gain_audio:g}"
        )
        audio_envoi = np.clip(audio * self.gain_audio, -1, 1)
        return (audio_envoi * 32767).astype(np.int16).tobytes()

    def _bip(self):
        """Petit accusé sonore local : l'utilisateur peut parler après le bip."""
        try:
            info = sd.query_devices(self.sortie, "output")
            taux = int(round(info.get("default_samplerate") or 48_000))
            duree = 0.11
            t = np.arange(int(taux * duree), dtype=np.float32) / taux
            enveloppe = np.minimum(1.0, np.minimum(t / 0.012, (duree - t) / 0.025))
            signal = (0.15 * enveloppe * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
            sd.play(signal, samplerate=taux, device=self.sortie)
            sd.wait()
        except Exception as exc:
            print("  [audio] bip impossible:", exc)

    def run(self):
        reveil = self._reveil()
        flux = sd.InputStream(
            samplerate=self.taux_capture,
            channels=1,
            dtype="float32",
            device=self.device,
            blocksize=self.bloc_capture,
        )
        flux.start()
        if self.taux_capture != TAUX:
            print(
                f"  [audio] micro {self.taux_capture} Hz -> 16000 Hz "
                f"({self.bloc_capture} -> {BLOC} échantillons)"
            )
        if self.gain_reveil != 1.0:
            print(
                f"  [wake] gain x{self.gain_reveil:g}, "
                f"seuil {self.seuil_reveil:g}"
            )
        print("Satellite prêt. Dites « Hey Jarvis ».")
        try:
            while not self.stop.is_set():
                bloc = self._lire_bloc(flux)
                if self.occupe.is_set():
                    reveil.reset()
                    continue
                relance = self._relance_restante()
                if relance > 0:
                    reveil.reset()
                    print(f"  [conversation] écoute ouverte {relance:.0f}s")
                    pcm = self._capturer_enonce(
                        flux, relance, "  [conversation] retour en veille")
                    self.fermer_relance()
                    if pcm:
                        self.occupe.set()
                        self.file.put(pcm)
                    continue
                bloc_reveil = np.clip(bloc * self.gain_reveil, -1, 1)
                scores = reveil.predict((bloc_reveil * 32767).astype(np.int16))
                score_reveil = max(scores.values())
                if score_reveil < self.seuil_reveil:
                    continue
                reveil.reset()
                accepte, accuse_vocal = self._demander_reveil(score_reveil)
                if not accepte:
                    print("  [wake] ignoré — un micro plus proche a répondu")
                    continue
                print("  [wake] Hey Jarvis — j'écoute")
                # Le serveur joue normalement « Oui ? » avant d'autoriser la
                # capture. Un bip local reste le repli si le TTS est indisponible.
                if not accuse_vocal:
                    self._bip()
                # Le micro continue de tourner pendant le bip. Purge son écho
                # résiduel avant d'attendre la question, sinon Whisper reçoit
                # parfois seulement le bip puis du silence.
                for _ in range(self.blocs_purge_bip):
                    self._lire_bloc(flux)
                pcm = self._capturer_enonce(
                    flux, self.attente_parole,
                    "  [micro] aucune question après le wake word")
                if not pcm:
                    continue
                self.occupe.set()
                self.file.put(pcm)
        finally:
            flux.stop(); flux.close()


def _jouer_alsa_partage(pcm, freq):
    """Joue via un PCM ALSA partagé lorsque le satellite en fournit un.

    Le nom du PCM et le fichier ALSA restent des réglages locaux. Le recours à
    ``aplay`` évite que PortAudio ouvre directement le périphérique USB déjà
    utilisé par un récepteur Spotify Connect.
    """
    appareil = str(
        CONF.get("pcm_sortie_alsa")
        or os.environ.get("JARVIS_ALSA_OUTPUT_PCM", "")
    ).strip()
    if not appareil:
        return False

    config_alsa = str(
        CONF.get("alsa_config_path")
        or os.environ.get("JARVIS_ALSA_CONFIG_PATH", "")
    ).strip()
    environnement = os.environ.copy()
    if config_alsa:
        environnement["ALSA_CONFIG_PATH"] = config_alsa

    taux = max(1, int(freq))
    duree = len(pcm) / (2 * taux)
    try:
        subprocess.run([
            "aplay", "--quiet", f"--device={appareil}", "--file-type=raw",
            "--format=S16_LE", f"--rate={taux}", "--channels=1",
        ], input=pcm, check=True, env=environnement,
           timeout=max(5.0, duree + 5.0))
        return True
    except (OSError, subprocess.SubprocessError) as e:
        print("  [audio] lecture ALSA partagée impossible:", e)
        return False


def _jouer(pcm, freq):
    """Joue du PCM mono en l'adaptant au taux natif du haut-parleur.

    Certains périphériques USB, notamment les speakerphones, n'acceptent que
    48 kHz alors que le TTS peut renvoyer du 16, 22,05 ou 24 kHz. PortAudio
    refuse alors d'ouvrir la sortie avec ``paInvalidSampleRate``. Le satellite
    rééchantillonne donc la réponse avant de la lire.
    """
    muet = CONF.get("_muet_callback")
    if callable(muet) and muet():
        return
    if _jouer_alsa_partage(pcm, freq):
        return
    try:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        sortie = CONF.get("haut_parleur", None)
        taux_source = max(1, int(freq))
        info = sd.query_devices(sortie, "output")
        taux_sortie = int(round(info.get("default_samplerate") or taux_source))
        if taux_sortie != taux_source:
            facteur = gcd(taux_source, taux_sortie)
            audio = resample_poly(
                audio, taux_sortie // facteur, taux_source // facteur
            ).astype(np.float32)
            print(
                f"  [audio] réponse {taux_source} Hz -> "
                f"{taux_sortie} Hz"
            )
        sd.play(audio, samplerate=taux_sortie, device=sortie)
        sd.wait()
    except Exception as e:
        print("  [audio] lecture impossible:", e)


async def _session(url, satellite, token, file_audio, occupe, micro):
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
            while True:
                try:
                    element = file_audio.get_nowait()
                except queue.Empty:
                    # Évite de laisser un thread bloqué lors d'un arrêt systemd.
                    await asyncio.sleep(0.05)
                    continue
                if isinstance(element, dict):
                    message = dict(element)
                    cree = float(message.pop("_cree", time.monotonic()))
                    if time.monotonic() - cree > 2.0:
                        micro.resoudre_reveil(message.get("id"), False)
                        continue
                    await ws.send(json.dumps(message))
                    continue
                pcm = element
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
                    if d.get("etat") == "veille":
                        occupe.clear()
                elif t in ("reveil_accepte", "reveil_refuse"):
                    micro.resoudre_reveil(
                        d.get("id"),
                        t == "reveil_accepte",
                        d.get("accuse_vocal", False),
                    )
                elif t == "transcription":
                    print(f"  [entendu] {d.get('texte')}")
                elif t == "progression":
                    print(f"  [progression] {d.get('texte')}")
                    notifier = CONF.get("_texte_callback")
                    if callable(notifier):
                        notifier(d.get("texte"), "progression")
                elif t == "texte":
                    print(f"  [réponse] {d.get('texte')}")
                    notifier = CONF.get("_texte_callback")
                    if callable(notifier):
                        notifier(d.get("texte"), "reponse")
                elif t == "audio_debut":
                    audio, freq = bytearray(), int(d.get("freq", TAUX))
                elif t == "audio_fin":
                    _jouer(bytes(audio), freq); audio = bytearray()
                elif t == "relance":
                    micro.ouvrir_relance(d.get("secondes"))
                    occupe.clear()
                elif t == "veille_forcee":
                    micro.fermer_relance()
                    occupe.clear()
                    print("  [conversation] veille forcée — dites « Hey Jarvis » pour me réveiller")
                elif t == "erreur":
                    print("  [erreur]", d.get("message"))
        finally:
            tache_emet.cancel()


async def _boucle(url, satellite, token, file_audio, occupe, micro):
    """Reconnexion automatique tant que le PC n'est pas joignable."""
    prevenu = False
    while True:
        try:
            await _session(url, satellite, token, file_audio, occupe, micro)
            prevenu = False
        except Exception as e:
            micro.fermer_relance()
            occupe.clear()
            if not prevenu:
                print(f"  [serveur] injoignable ({str(e)[:60]}) — nouvelle tentative…")
                prevenu = True
            await asyncio.sleep(3)


CONF = {}


def main():
    global CONF
    CONF = _conf()
    url = str(CONF.get("pc_url", "")).strip()
    satellite = str(CONF.get("satellite_id", "")).strip()
    token = str(CONF.get("token", "")).strip()
    manquants = [nom for nom, valeur in (
        ("pc_url", url), ("satellite_id", satellite), ("token", token)
    ) if not valeur]
    if manquants:
        print("configuration manquante dans config.yaml : " + ", ".join(manquants))
        sys.exit(1)
    if not url.startswith(("ws://", "wss://")):
        print("pc_url doit commencer par ws:// ou wss://")
        sys.exit(1)

    file_audio = queue.Queue()
    occupe = threading.Event()
    micro = Micro(CONF, file_audio, occupe)
    threading.Thread(target=micro.run, name="micro", daemon=True).start()
    try:
        asyncio.run(_boucle(url, satellite, token, file_audio, occupe, micro))
    except KeyboardInterrupt:
        micro.stop.set()
        print("\nAu revoir.")


if __name__ == "__main__":
    main()
