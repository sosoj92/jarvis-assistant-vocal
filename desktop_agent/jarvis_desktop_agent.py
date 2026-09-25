#!/usr/bin/env python3
"""Agent Windows limite pour le poste principal de Jarvis.

Il se connecte vers le serveur (connexion sortante) et n'execute que les actions
listees dans ``CAPACITES``. Il n'expose ni shell, ni fichiers, ni port entrant.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus, urlparse

RACINE = Path(__file__).resolve().parent
DEPOT = RACINE.parent
CAPACITES = frozenset({
    "astra_action", "astra_escape_state",
    "browser_open", "controler_media", "launch_app", "ouvrir_application",
    "outil_local", "regler_volume", "sortie_audio", "spotify_open", "spotify_search",
})
OUTILS_LOCAUX = frozenset({
    "afficher_reponse", "afficher_reponses", "browser_close_tabs",
    "browser_current_page", "browser_interact", "browser_open", "browser_tabs",
    "capture_screen", "cliquer_ecran", "controler_gestes", "controler_media",
    "eteindre_pc", "annuler_extinction", "get_system_stats", "identifier_musique", "lancer_calibration_gestes",
    "lancer_demo_gestes", "lancer_mode_regard", "launch_app", "lire_netflix",
    "mode_silencieux_visuel", "ouvrir_application", "quitter_mode_regard",
    "reglage_overlay", "regler_volume", "save_replay", "sortie_audio",
    "start_record", "start_stream", "stop_record", "stop_stream", "switch_scene",
})
TOUCHES = {
    "muet": 0xAD, "baisser": 0xAE, "monter": 0xAF,
    "suivant": 0xB0, "precedent": 0xB1, "stop": 0xB2, "pause": 0xB3,
}
UTILITAIRES = {
    "calculatrice": "calc", "bloc-notes": "notepad",
    "explorateur": "explorer", "parametres": "ms-settings:",
    "spotify": "spotify:",
}


def charger_config():
    import yaml
    chemin = RACINE / "config.yaml"
    if not chemin.exists():
        raise RuntimeError("desktop_agent/config.yaml manque (copie config.example.yaml)")
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


def _normaliser(texte):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(texte).lower())
                   if unicodedata.category(c) != "Mn").strip()


class ActionsLocales:
    def __init__(self, conf):
        self.conf = conf
        self.satellite = None
        self.micro = None
        self.agent_pret = threading.Event()

    def lier_audio(self, satellite, micro):
        self.satellite, self.micro = satellite, micro

    @staticmethod
    def _presser(action, fois=1):
        code = TOUCHES[action]
        for _ in range(fois):
            ctypes.windll.user32.keybd_event(code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(code, 0, 2, 0)
            time.sleep(0.02)

    @staticmethod
    def _ouvrir(cible):
        os.startfile(cible)

    def _apps(self):
        apps = dict(self.conf.get("apps", {}) or {})
        for nom, cible in UTILITAIRES.items():
            apps.setdefault(nom, cible)
        return apps

    def _application(self, nom):
        cible = _normaliser(nom)
        for cle, chemin in self._apps().items():
            cle_norm = _normaliser(cle)
            if cible == cle_norm or (cible and (cible in cle_norm or cle_norm in cible)):
                if _normaliser(cle) == "discord" and not chemin:
                    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Discord"
                    maj = base / "Update.exe"
                    if not maj.exists():
                        return False, "Discord est introuvable sur ce PC."
                    subprocess.Popen([str(maj), "--processStart", "Discord.exe"])
                else:
                    self._ouvrir(str(chemin))
                return True, f"{cle} est lancé sur le poste principal."
        return False, (f"Je ne connais pas {nom} sur le poste principal. Ajoute-le "
                       "dans desktop_agent/config.yaml, section apps.")

    @staticmethod
    def _url_sure(url):
        try:
            analyse = urlparse(str(url).strip())
            return (analyse.scheme in {"http", "https"} and bool(analyse.hostname)
                    and len(str(url)) <= 4096)
        except Exception:
            return False

    def executer(self, action, args):
        if action not in CAPACITES or not isinstance(args, dict):
            return False, "Action distante interdite."
        try:
            if action == "outil_local":
                return self._outil_local(
                    str(args.get("outil", "")), args.get("args", {}))
            if action == "astra_escape_state":
                actif = bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
                return True, actif
            if action == "astra_action":
                return self._astra_action(args)
            if action in {"launch_app", "ouvrir_application"}:
                return self._application(str(args.get("nom", "")))
            if action == "controler_media":
                commande = _normaliser(args.get("action", ""))
                if commande == "reprendre":
                    commande = "pause"
                if commande not in TOUCHES:
                    return False, "Commande multimédia inconnue."
                self._presser(commande)
                return True, f"Commande {commande} envoyée au poste principal."
            if action == "regler_volume":
                sens = _normaliser(args.get("sens", ""))
                if sens not in {"monter", "baisser"}:
                    return False, "Sens du volume invalide."
                crans = max(1, min(int(args.get("crans", 10)), 50))
                self._presser(sens, crans)
                return True, f"Volume {sens} sur le poste principal."
            if action == "browser_open":
                url = str(args.get("url", "") or "").strip()
                recherche = str(args.get("recherche", "") or "").strip()
                if recherche:
                    url = "https://www.google.com/search?q=" + quote_plus(recherche)
                if not self._url_sure(url):
                    return False, "Adresse web refusée."
                if not webbrowser.open_new_tab(url):
                    return False, "Le navigateur n'a pas accepté la demande."
                return True, "J'ai ouvert la page sur le poste principal."
            if action in {"spotify_open", "spotify_search"}:
                if action == "spotify_search":
                    recherche = str(args.get("recherche", "") or "").strip()
                    if not recherche or len(recherche) > 300:
                        return False, "Recherche Spotify invalide."
                    cible = "spotify:search:" + quote_plus(recherche)
                else:
                    cible = str(args.get("uri", "spotify:") or "spotify:").strip()
                    if (not cible.startswith("spotify:") or len(cible) > 2048
                            or any(ord(c) < 32 for c in cible)):
                        return False, "Lien Spotify refusé."
                self._ouvrir(cible)
                return True, "Spotify est ouvert sur le poste principal."
            if action == "sortie_audio":
                return self._sortie_audio(str(args.get("cible", "")))
        except Exception as exc:
            return False, f"Commande impossible sur le poste principal : {str(exc)[:160]}"
        return False, "Action distante non prise en charge."

    def _outil_local(self, nom, args):
        if nom not in OUTILS_LOCAUX or not isinstance(args, dict):
            return False, "Outil local interdit."
        if str(DEPOT) not in sys.path:
            sys.path.insert(0, str(DEPOT))
        from core import config, registre
        # Cette configuration ne contient que les réglages matériels du poste.
        # Elle désactive implicitement tout nouveau routage distant et évite une boucle.
        config._CONFIG = self.conf
        registre.charger_outils()
        outil = registre.get(nom)
        if outil is None:
            return False, f"L'outil {nom} n'est pas installé sur ce PC."
        resultat = outil.fonction(**args)
        return True, resultat

    def _astra_action(self, args):
        action = str(args.get("action", "") or "").lower()
        if action in {"cliquer", "double_cliquer"}:
            ok, resultat = self._outil_local("cliquer_ecran", {
                "x": int(args.get("x", -1)), "y": int(args.get("y", -1)),
                "double": action == "double_cliquer",
            })
            return ok, resultat
        if action == "taper":
            import keyboard
            keyboard.write(str(args.get("texte", "") or "")[:500], delay=0.01)
            return True, "texte saisi"
        if action == "touche":
            import keyboard
            touche = _normaliser(args.get("touche", ""))
            autorisees = {
                "tab", "shift+tab", "enter", "esc", "escape", "backspace",
                "home", "end", "pageup", "pagedown", "up", "down", "left",
                "right", "ctrl+a", "ctrl+c", "ctrl+l", "alt+tab",
            }
            if touche not in autorisees:
                return False, "Touche refusée."
            keyboard.send("esc" if touche == "escape" else touche)
            return True, "touche envoyée"
        if action == "defiler":
            delta = 720 if str(args.get("direction", "bas")).lower() == "haut" else -720
            ctypes.windll.user32.mouse_event(0x0800, 0, 0, delta, 0)
            return True, "écran défilé"
        if action == "attendre":
            time.sleep(1.0)
            return True, "attente terminée"
        return False, "Action Astra locale refusée."

    def _sortie_audio(self, cible):
        if self.satellite is None:
            return False, "Le module audio du poste principal n'est pas actif."
        import sounddevice as sd
        nom = _normaliser(cible)
        if nom in {"", "defaut", "par defaut", "windows", "auto", "systeme"}:
            appareil, label = None, "la sortie Windows par défaut"
        else:
            valeur = cible
            for alias, reel in (self.conf.get("audio", {}).get("sorties", {}) or {}).items():
                if nom == _normaliser(alias):
                    valeur = reel
                    break
            appareil, label = None, ""
            for index, info in enumerate(sd.query_devices()):
                if info.get("max_output_channels", 0) <= 0:
                    continue
                if ((isinstance(valeur, int) and index == valeur)
                        or _normaliser(str(valeur)) in _normaliser(info.get("name", ""))):
                    appareil, label = index, info.get("name", str(index))
                    break
            if appareil is None:
                return False, "Cette sortie audio est introuvable sur le poste principal."
        self.satellite.CONF["haut_parleur"] = appareil
        if self.micro is not None:
            self.micro.sortie = appareil
        return True, f"Ma voix sort maintenant sur {label}."


def demarrer_audio(conf, actions):
    audio = dict(conf.get("audio", {}) or {})
    if not bool(audio.get("actif", False)):
        return
    sys.path.insert(0, str(DEPOT))
    from satellite_pi import jarvis_satellite as satellite
    try:
        import overlay
        reglages_overlay = dict(conf.get("overlay", {}) or {})
        if bool(reglages_overlay.get("actif", True)):
            overlay.demarrer({
                "actif": True,
                "muet": bool(reglages_overlay.get("muet_visuel", False)),
                "ecran": int(reglages_overlay.get("ecran", 1)),
                "coin": reglages_overlay.get("coin", "bas-droite"),
                "opacite": float(reglages_overlay.get("opacite", 0.92)),
                "largeur": int(reglages_overlay.get("largeur", 420)),
                "duree_min": float(reglages_overlay.get("duree_min", 4.0)),
                "duree_max": float(reglages_overlay.get("duree_max", 14.0)),
                "marge": int(reglages_overlay.get("marge", 24)),
                "exclure_obs": bool(reglages_overlay.get("exclure_obs", True)),
            })

            def afficher_texte(texte, typ):
                overlay.memoriser(texte, "reponse")
                overlay.afficher(texte, type="reponse" if typ == "reponse" else "statut")

            audio["_texte_callback"] = afficher_texte
            audio["_muet_callback"] = overlay.est_muet
    except Exception as exc:
        print("[overlay] indisponible:", exc)
    satellite.CONF = audio
    audio["_poste_pret_event"] = actions.agent_pret
    file_audio = queue.Queue()
    occupe = threading.Event()
    micro = satellite.Micro(audio, file_audio, occupe)
    actions.lier_audio(satellite, micro)
    threading.Thread(target=micro.run, name="jarvis-micro", daemon=True).start()

    def boucle_audio():
        asyncio.run(satellite._boucle(
            str(audio.get("pc_url", "")), str(audio.get("satellite_id", "")),
            str(audio.get("token", "")), file_audio, occupe, micro))

    threading.Thread(target=boucle_audio, name="jarvis-audio", daemon=True).start()


async def session(conf, actions):
    import websockets
    url = str(conf.get("serveur_url", "") or "").strip()
    async with websockets.connect(url, max_size=131_072) as ws:
        await ws.send(json.dumps({
            "type": "hello", "agent": str(conf.get("agent_id", "bureau")),
            "token": str(conf.get("token", "")),
            "capabilities": sorted(CAPACITES),
        }))
        reponse = json.loads(await ws.recv())
        if reponse.get("type") != "pret":
            raise RuntimeError(reponse.get("message", "connexion refusée"))
        print("[agent] connecté au serveur Jarvis")
        actions.agent_pret.set()
        try:
            async for brut in ws:
                if not isinstance(brut, str):
                    continue
                commande = json.loads(brut)
                if commande.get("type") != "commande":
                    continue
                ok, resultat = await asyncio.to_thread(
                    actions.executer, str(commande.get("action", "")),
                    commande.get("args", {}))
                if isinstance(resultat, str):
                    message = resultat
                else:
                    message = "C'est fait." if ok else "La commande a échoué."
                try:
                    json.dumps(resultat)
                except (TypeError, ValueError):
                    resultat = str(resultat)
                await ws.send(json.dumps({
                    "type": "resultat", "id": commande.get("id"),
                    "ok": ok, "message": message, "resultat": resultat,
                }, ensure_ascii=False))
        finally:
            actions.agent_pret.clear()


async def boucle(conf, actions):
    prevenu = False
    while True:
        try:
            await session(conf, actions)
            prevenu = False
        except Exception as exc:
            if not prevenu:
                print(f"[agent] serveur injoignable ({str(exc)[:100]}), nouvelle tentative…")
                prevenu = True
            await asyncio.sleep(3)


def main():
    conf = charger_config()
    manquants = [nom for nom in ("serveur_url", "agent_id", "token")
                 if not str(conf.get(nom, "") or "").strip()]
    if manquants:
        raise SystemExit("Configuration manquante : " + ", ".join(manquants))
    # Les outils matériels qui modifient un réglage écrivent dans la config privée
    # de l'agent, jamais dans la configuration (et les secrets) du serveur.
    if str(DEPOT) not in sys.path:
        sys.path.insert(0, str(DEPOT))
    from core import config
    config.FICHIER = RACINE / "config.yaml"
    config._CONFIG = conf
    actions = ActionsLocales(conf)
    demarrer_audio(conf, actions)
    try:
        asyncio.run(boucle(conf, actions))
    except KeyboardInterrupt:
        print("\nAgent arrêté.")


if __name__ == "__main__":
    main()
