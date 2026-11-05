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


def contexte_tls(url, certificat, base=RACINE):
    """Contexte TLS pour wss:// qui n'accepte QUE le certificat du serveur Jarvis
    (copie locale de certs/jarvis-lan.crt). None pour ws:// (ancien port en clair)."""
    if not str(url or "").startswith("wss://"):
        return None
    if not certificat:
        raise ValueError("wss:// demande « certificat: » (copie du certificat du serveur)")
    import ssl
    chemin = Path(str(certificat))
    chemin = chemin if chemin.is_absolute() else base / chemin
    # Classe d'origine : sur le PC, truststore.inject_into_ssl() remplace
    # ssl.SSLContext et melerait le magasin Windows a l'epinglage. Ses setters
    # Python (verify_mode, minimum_version) bouclent alors sans fin : on garde les
    # valeurs par defaut de PROTOCOL_TLS_CLIENT, deja strictes, et on les verifie.
    classe = next(c for c in ssl.SSLContext.__mro__ if c.__module__ == "ssl")
    contexte = classe(ssl.PROTOCOL_TLS_CLIENT)
    # Certificat epingle : seule la cle du serveur peut le presenter, quelle que
    # soit l'adresse IP utilisee pour le joindre (d'ou pas de controle du nom).
    contexte.check_hostname = False
    if (contexte.verify_mode != ssl.CERT_REQUIRED
            or contexte.minimum_version < ssl.TLSVersion.TLSv1_2):
        raise ValueError("contexte TLS trop permissif")
    contexte.load_verify_locations(cafile=str(chemin))
    return contexte


def _evenement(nom, valeur=None):
    """Point d'accroche facultatif pour un affichage local (fenetre Jarvis du poste
    Windows). Sans recepteur configure, comme sur un Raspberry Pi, rien ne se passe."""
    rappel = CONF.get("_evenement_callback")
    if callable(rappel):
        try:
            rappel(nom, valeur)
        except Exception as exc:
            print("  [affichage] evenement ignore:", exc)


def _etat_affiche(etat, micro):
    """Etat a afficher. Le serveur ouvre la conversation suivie PUIS annonce la
    veille : tant que le micro ecoute encore, l'affichage dit « ecoute »."""
    if etat == "veille" and micro._relance_restante() > 0:
        return "ecoute"
    return etat


def _silence_numerique(index, secondes=0.4):
    """Vrai si le micro ne renvoie que des zeros exacts (micro virtuel dont l'appli
    est fermee, micro coupe) ou s'il ne s'ouvre pas. Une vraie capsule n'est
    jamais a zero, meme dans une piece calme."""
    try:
        taux = int(round(sd.query_devices(index)["default_samplerate"] or TAUX))
        with sd.InputStream(samplerate=taux, channels=1, dtype="float32",
                            device=index) as flux:
            audio, _ = flux.read(int(taux * secondes))
        return float(np.max(np.abs(audio))) == 0.0
    except Exception:
        return True


def _resoudre_micro(choix):
    """Index PortAudio du micro a ouvrir.

    choix : None (micro par defaut du systeme), un index, un nom ou morceau de nom
    (« MOTIV Mix »), ou une liste de noms par ordre de preference. Les noms sont
    cherches dans l'API audio par defaut seulement (MME sous Windows) : Windows
    liste le meme micro sous plusieurs API, un nom seul y serait ambigu. Avec
    plusieurs candidats, un micro muet (zeros exacts) est saute au profit du
    suivant. Aucun nom trouve : micro par defaut, avec un avertissement.
    """
    if choix is None or isinstance(choix, bool):
        return None
    if isinstance(choix, int):
        return choix
    noms = [choix] if isinstance(choix, str) else [str(n) for n in choix]
    try:
        appareils = sd.query_devices()
        api = sd.default.hostapi
    except Exception:
        return None
    trouves = []
    for nom in noms:
        cle = nom.strip().lower()
        for index, appareil in enumerate(appareils):
            if (cle and index not in trouves and appareil["max_input_channels"] > 0
                    and appareil["hostapi"] == api and cle in appareil["name"].lower()):
                trouves.append(index)
                break
    for rang, index in enumerate(trouves):
        if rang == len(trouves) - 1 or not _silence_numerique(index):
            return index
        print(f"  [audio] « {appareils[index]['name']} » ne renvoie que du silence : "
              "micro suivant")
    print(f"  [audio] aucun micro ne correspond à {noms} : micro par défaut du système")
    return None


def sorties_utf8():
    """Console ou journal en UTF-8. Redirigee vers un fichier sous Windows, la
    sortie est en cp1252 : un emoji dans une reponse faisait planter le print,
    donc couper la session au milieu de la reponse."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _reinitialiser_portaudio():
    """PortAudio fige la liste des peripheriques a son demarrage : sans cela, un
    micro debranche puis rebranche (USB, Bluetooth) reste introuvable."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception as exc:
        print("  [audio] reinitialisation impossible :", exc)


class _MicroMuet(Exception):
    """Le micro ouvert ne renvoie plus que du silence numerique."""


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
        self.choix_micro = conf.get("micro", None)
        self.sortie = conf.get("haut_parleur", None)
        self._relance_jusqua = 0.0
        self._relance_lock = threading.Lock()
        self._reveil_lock = threading.Lock()
        self._reveil_event = threading.Event()
        self._reveil_id = 0
        self._reveil_accepte = False
        self._reveil_accuse_vocal = False
        self._configurer_micro()

    def _configurer_micro(self):
        """Choisit le micro (par nom si demande) et lit sa frequence native.
        Rappele a chaque reouverture : les index changent apres un debranchement."""
        self.device = _resoudre_micro(self.choix_micro)
        try:
            info = sd.query_devices(self.device, "input")
            self.nom_micro = str(info.get("name", "?"))
            self.taux_capture = int(round(info.get("default_samplerate") or TAUX))
        except Exception:
            self.nom_micro = "?"
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
        bloc = bloc.flatten()
        # Silence numerique juge sur le son brut, avant tout reechantillonnage.
        self.dernier_bloc_muet = not np.any(bloc)
        return self._vers_16k(bloc)

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

    # Silence numerique tolere avant de passer au micro suivant de la liste.
    SECONDES_MUET_MAX = 15.0

    def _ouvrir_flux(self):
        self._configurer_micro()
        flux = sd.InputStream(
            samplerate=self.taux_capture,
            channels=1,
            dtype="float32",
            device=self.device,
            blocksize=self.bloc_capture,
        )
        flux.start()
        print(f"  [audio] micro : {self.nom_micro} "
              f"({self.taux_capture} Hz -> 16000 Hz)")
        return flux

    def run(self):
        """Superviseur du micro : le rouvre s'il disparait (Bluetooth, USB, pilote
        reinitialise) au lieu de laisser Jarvis connecte mais sourd."""
        reveil = self._reveil()
        if self.gain_reveil != 1.0:
            print(
                f"  [wake] gain x{self.gain_reveil:g}, "
                f"seuil {self.seuil_reveil:g}"
            )
        attente, premiere, echecs = 1.0, True, 0
        while not self.stop.is_set():
            try:
                flux = self._ouvrir_flux()
            except Exception as exc:
                echecs += 1
                print(f"  [audio] micro indisponible ({type(exc).__name__}: "
                      f"{str(exc)[:80]}) — nouvel essai dans {attente:.0f} s")
                # Relire la liste des peripheriques (sd._terminate) coupe aussi un
                # son en cours : seulement apres deux echecs d'ouverture de suite
                # (un micro USB en cours de redemarrage revient souvent seul), et
                # jamais pendant la lecture d'une reponse.
                if echecs >= 2 and not LECTURE_EN_COURS.is_set():
                    _reinitialiser_portaudio()
                self.stop.wait(attente)
                attente = min(attente * 2, 15.0)
                continue
            echecs = 0
            if premiere:
                print("Satellite prêt. Dites « Hey Jarvis ».")
                premiere = False
            else:
                print("  [audio] micro retrouvé — j'écoute de nouveau.")
            debut = time.monotonic()
            try:
                self._ecouter(flux, reveil)
            except Exception as exc:
                print(f"  [audio] micro perdu ({type(exc).__name__}: "
                      f"{str(exc)[:80]}) — reconnexion…")
                self.fermer_relance()
                _evenement("etat", "veille")
                # Une panne immediate et repetee ne doit pas tourner en boucle folle.
                if time.monotonic() - debut < 5.0:
                    self.stop.wait(attente)
                    attente = min(attente * 2, 15.0)
                else:
                    attente = 1.0
            finally:
                try:
                    flux.stop()
                    flux.close()
                except Exception:
                    pass
            reveil.reset()

    def _ecouter(self, flux, reveil):
        """Boucle d'ecoute sur un micro ouvert ; leve une exception s'il tombe."""
        blocs_lus = 0
        blocs_muets = 0
        muet_max = int(self.SECONDES_MUET_MAX * TAUX / BLOC)
        # Une liste de micros permet de passer au suivant si celui-ci devient muet
        # (appli du micro virtuel fermee) ; avec un seul micro, rien a essayer.
        surveiller_muet = (isinstance(self.choix_micro, (list, tuple))
                           and len(self.choix_micro) > 1)
        while not self.stop.is_set():
            bloc = self._lire_bloc(flux)
            blocs_lus += 1
            if surveiller_muet:
                blocs_muets = blocs_muets + 1 if self.dernier_bloc_muet else 0
                if blocs_muets > muet_max:
                    raise _MicroMuet(f"{self.nom_micro} ne renvoie que du silence")
            if blocs_lus % 4 == 0 and "_evenement_callback" in CONF:
                _evenement("niveau", self._niveau(bloc))
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
                    _evenement("etat", "reflexion")
                else:
                    _evenement("etat", "veille")
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
            _evenement("reveil")
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
                # Personne n'a parlé : retour au repos ici et côté serveur, sinon la
                # fenêtre Jarvis du poste resterait en écoute (tableau de bord masqué).
                _evenement("etat", "veille")
                self.file.put({"type": "reveil_sans_suite"})
                continue
            self.occupe.set()
            self.file.put(pcm)


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


# Pose pendant la lecture d'une reponse : le fil du micro ne relit pas alors la
# liste des peripheriques audio (sd._terminate couperait le son en cours).
LECTURE_EN_COURS = threading.Event()


def _jouer(pcm, freq):
    LECTURE_EN_COURS.set()
    try:
        return _jouer_pcm(pcm, freq)
    finally:
        LECTURE_EN_COURS.clear()


def _jouer_pcm(pcm, freq):
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


class RefusServeur(Exception):
    """Le PC a refusé le hello (jeton renouvelé, satellite retiré de la config)."""


async def _session(url, satellite, token, file_audio, occupe, micro, tls=None,
                   sur_pret=None):
    """Une connexion au PC : envoie les énoncés de la file, joue les réponses.
    Lève RefusServeur si le PC refuse le hello ; ``sur_pret`` est appelé dès que
    le PC accepte la connexion."""
    import websockets
    options = {"ssl": tls} if tls is not None else {}
    async with websockets.connect(url, max_size=None, **options) as ws:
        await ws.send(json.dumps({"type": "hello", "satellite": satellite, "token": token}))
        # attendre pret
        while True:
            m = await ws.recv()
            if isinstance(m, str) and json.loads(m).get("type") == "pret":
                print("  [pc] connecté.")
                if sur_pret is not None:
                    sur_pret()
                break
            if isinstance(m, str) and json.loads(m).get("type") == "erreur":
                raise RefusServeur(json.loads(m).get("message"))

        if bool(CONF.get("brief_au_demarrage", False)):
            pret = CONF.get("_poste_pret_event")
            if pret is not None:
                await asyncio.to_thread(pret.wait, 10.0)
            await ws.send(json.dumps({"type": "scene_demarrage"}))

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
                    _evenement("etat", _etat_affiche(d.get("etat"), micro))
                elif t in ("reveil_accepte", "reveil_refuse"):
                    micro.resoudre_reveil(
                        d.get("id"),
                        t == "reveil_accepte",
                        d.get("accuse_vocal", False),
                    )
                elif t == "transcription":
                    print(f"  [entendu] {d.get('texte')}")
                    _evenement("transcription", d.get("texte"))
                elif t == "progression":
                    print(f"  [progression] {d.get('texte')}")
                    notifier = CONF.get("_texte_callback")
                    if callable(notifier):
                        notifier(d.get("texte"), "progression")
                elif t == "texte":
                    print(f"  [réponse] {d.get('texte')}")
                    _evenement("reponse", d.get("texte"))
                    notifier = CONF.get("_texte_callback")
                    if callable(notifier):
                        notifier(d.get("texte"), "reponse")
                elif t == "audio_debut":
                    audio, freq = bytearray(), int(d.get("freq", TAUX))
                elif t == "audio_fin":
                    _evenement("parole_debut")
                    # Lecture dans un fil : bloquer la boucle pendant une longue
                    # reponse (brief) empechait de repondre aux pings, et le
                    # serveur coupait la connexion (1011 keepalive ping timeout).
                    # L'ordre des messages est garde : on attend la fin ici.
                    await asyncio.to_thread(_jouer, bytes(audio), freq)
                    audio = bytearray()
                    _evenement("parole_fin")
                elif t == "relance":
                    micro.ouvrir_relance(d.get("secondes"))
                    occupe.clear()
                    _evenement("etat", "ecoute")
                elif t == "veille_forcee":
                    micro.fermer_relance()
                    occupe.clear()
                    _evenement("etat", "veille")
                    print("  [conversation] veille forcée — dites « Hey Jarvis » pour me réveiller")
                elif t == "statut":
                    _evenement("statut", d)
                elif t == "tableau":
                    _evenement("tableau", d)
                elif t == "erreur":
                    print("  [erreur]", d.get("message"))
        finally:
            tache_emet.cancel()


RECUL_REFUS_MIN = 3     # s : premier délai après un hello refusé
RECUL_REFUS_MAX = 60    # s : plafond du délai, doublé à chaque refus


async def _boucle(url, satellite, token, file_audio, occupe, micro, tls=None):
    """Reconnexion automatique tant que le PC n'est pas joignable.

    Un hello refusé (jeton renouvelé, satellite retiré) ne se règle pas en
    réessayant : sans pause, le client se reconnectait en boucle serrée et
    remplissait les journaux des deux côtés. Délai croissant de 3 s à 60 s, remis
    à zéro dès que le PC accepte la connexion, message une seule fois par série.
    Une panne réseau garde 3 s : la reprise après un redémarrage du PC reste rapide.
    """
    prevenu = False
    recul = 0

    def accepte():
        nonlocal recul
        recul = 0

    while True:
        try:
            await _session(url, satellite, token, file_audio, occupe, micro, tls=tls,
                           sur_pret=accepte)
            prevenu = False
        except RefusServeur as e:
            micro.fermer_relance()
            occupe.clear()
            if not recul:
                print(f"  [pc] refusé: {e} — vérifie satellite_id et token ; "
                      "nouvelle tentative de plus en plus espacée…")
            recul = min(RECUL_REFUS_MAX, recul * 2 if recul else RECUL_REFUS_MIN)
            await asyncio.sleep(recul)
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
    sorties_utf8()
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
    try:
        tls = contexte_tls(url, CONF.get("certificat"))
    except (ValueError, OSError) as e:
        print(f"certificat du serveur inutilisable : {e}")
        sys.exit(1)
    if tls is None:
        print("  [securite] pc_url en ws:// : jeton et audio passent EN CLAIR sur le "
              "reseau. Passe en wss:// avec « certificat: » (voir docs/satellite.md).")

    file_audio = queue.Queue()
    occupe = threading.Event()
    micro = Micro(CONF, file_audio, occupe)
    threading.Thread(target=micro.run, name="micro", daemon=True).start()
    try:
        asyncio.run(_boucle(url, satellite, token, file_audio, occupe, micro, tls=tls))
    except KeyboardInterrupt:
        micro.stop.set()
        print("\nAu revoir.")


if __name__ == "__main__":
    main()
