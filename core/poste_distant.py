"""Pont LAN authentifie vers le poste Windows principal de Jarvis.

Le client initie lui-meme la connexion WebSocket : aucun port entrant n'est
necessaire sur le poste pilote.  Le serveur n'accepte qu'une petite liste
d'actions locales, jamais une commande shell ni un chemin arbitraire.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import uuid
from dataclasses import dataclass, field

from core.config import reglage

LOG = logging.getLogger("jarvis.poste_distant")

ACTIONS_AUTORISEES = frozenset({
    "astra_action",
    "astra_escape_state",
    "browser_open",
    "controler_media",
    "launch_app",
    "ouvrir_application",
    "regler_volume",
    "sortie_audio",
    "spotify_open",
    "spotify_search",
    "outil_local",
})

# Outils dont le corps physique appartient au poste principal. Leur raisonnement,
# leur politique de confirmation et leurs secrets restent sur le serveur.
OUTILS_POSTE = frozenset({
    "afficher_reponse", "afficher_reponses", "browser_close_tabs",
    "browser_current_page", "browser_interact", "browser_open", "browser_tabs",
    "capture_screen", "cliquer_ecran", "controler_gestes", "controler_media",
    "eteindre_pc", "annuler_extinction", "get_system_stats", "identifier_musique", "lancer_calibration_gestes",
    "lancer_demo_gestes", "lancer_mode_regard", "launch_app", "lire_netflix",
    "mode_silencieux_visuel", "ouvrir_application", "quitter_mode_regard",
    "reglage_overlay", "regler_volume", "save_replay", "sortie_audio",
    "start_record", "start_stream", "stop_record", "stop_stream", "switch_scene",
})


def agents_configures():
    """Retourne les agents valides indexes par identifiant."""
    agents = {}
    for entree in (reglage("desktop_agents", []) or []):
        if not isinstance(entree, dict) or not entree.get("id"):
            continue
        identifiant = str(entree["id"]).strip()
        if identifiant:
            agents[identifiant] = {
                "token": str(entree.get("token", "") or ""),
            }
    return agents


def _principal():
    conf = reglage("poste_principal", {}) or {}
    if not isinstance(conf, dict) or not bool(conf.get("actif", False)):
        return ""
    return str(conf.get("agent", "bureau") or "bureau").strip()


@dataclass
class _Connexion:
    websocket: object
    boucle: asyncio.AbstractEventLoop
    capacites: set[str]
    attentes: dict[str, asyncio.Future] = field(default_factory=dict)
    verrou_envoi: asyncio.Lock = field(default_factory=asyncio.Lock)


_CONNEXIONS: dict[str, _Connexion] = {}
_VERROU = threading.RLock()


def agent_disponible(identifiant=None):
    identifiant = identifiant or _principal()
    with _VERROU:
        return bool(identifiant and identifiant in _CONNEXIONS)


async def _envoyer(identifiant, action, args, timeout):
    with _VERROU:
        connexion = _CONNEXIONS.get(identifiant)
    if connexion is None:
        raise ConnectionError(f"{identifiant} n'est pas connecte")
    if action not in ACTIONS_AUTORISEES:
        raise ValueError("action distante interdite")
    if connexion.capacites and action not in connexion.capacites:
        raise ValueError(f"{identifiant} ne prend pas en charge {action}")

    identifiant_commande = uuid.uuid4().hex
    futur = connexion.boucle.create_future()
    connexion.attentes[identifiant_commande] = futur
    message = json.dumps({
        "type": "commande",
        "id": identifiant_commande,
        "action": action,
        "args": args or {},
    }, ensure_ascii=False)
    try:
        async with connexion.verrou_envoi:
            await connexion.websocket.send_text(message)
        return await asyncio.wait_for(futur, timeout=timeout)
    finally:
        connexion.attentes.pop(identifiant_commande, None)


def executer_resultat(action, args=None, identifiant=None, timeout=15.0):
    """Execute une action et conserve son type (texte, capture image, etc.)."""
    identifiant = str(identifiant or _principal()).strip()
    if not identifiant:
        return None
    with _VERROU:
        connexion = _CONNEXIONS.get(identifiant)
    if connexion is None:
        return (f"Le poste {identifiant} n'est pas connecté. Lance l'agent Jarvis "
                "sur ce PC.")
    try:
        futur = asyncio.run_coroutine_threadsafe(
            _envoyer(identifiant, action, args or {}, float(timeout)),
            connexion.boucle,
        )
        enveloppe = futur.result(timeout=float(timeout) + 1.0)
        if not isinstance(enveloppe, dict):
            return "Le poste distant a renvoyé une réponse invalide."
        message = str(enveloppe.get("message", "") or "").strip()
        if enveloppe.get("ok"):
            resultat = enveloppe.get("resultat")
            return resultat if resultat is not None else (message or "C'est fait.")
        return message or "Le poste distant n'a pas pu exécuter la commande."
    except Exception as exc:
        LOG.warning("commande distante %s/%s: %s", identifiant, action, exc)
        return f"Le poste {identifiant} ne répond pas."


def executer(action, args=None, identifiant=None, timeout=15.0):
    """Execute une action simple et garantit une reponse textuelle."""
    resultat = executer_resultat(action, args, identifiant, timeout)
    if resultat is None or isinstance(resultat, str):
        return resultat
    return str(resultat)


def executer_principal(action, args=None, timeout=15.0):
    """None = routage distant desactive ; texte = resultat distant definitif."""
    if not _principal():
        return None
    return executer(action, args=args, timeout=timeout)


def executer_outil_principal(nom, args=None, timeout=90.0):
    """Route un outil PC vers le poste principal, après confirmation côté serveur."""
    if nom not in OUTILS_POSTE or not _principal():
        return None
    return executer_resultat(
        "outil_local", {"outil": nom, "args": args or {}}, timeout=timeout)


def monter_routes(app):
    """Monte /desktop-agent sur l'application LAN minimale."""
    from fastapi import WebSocket, WebSocketDisconnect
    from core.satellite import _origine_locale_ou_lan

    @app.websocket("/desktop-agent")
    async def desktop_agent(ws: WebSocket):
        if not _origine_locale_ou_lan(ws):
            LOG.warning("poste distant: connexion hors LAN refusee")
            await ws.close(code=1008, reason="agent accessible uniquement sur le LAN")
            return
        await ws.accept()
        identifiant = ""
        connexion = None
        try:
            brut = await asyncio.wait_for(ws.receive_text(), timeout=8.0)
            if len(brut) > 16_384:
                raise ValueError("message initial trop long")
            hello = json.loads(brut)
            identifiant = str(hello.get("agent", "") or "").strip()
            conf = agents_configures().get(identifiant)
            jeton = str(hello.get("token", "") or "")
            if (hello.get("type") != "hello" or not conf or not conf["token"]
                    or not secrets.compare_digest(jeton, conf["token"])):
                await ws.send_text(json.dumps({
                    "type": "erreur", "message": "agent inconnu ou token invalide"}))
                await ws.close(code=1008)
                return

            capacites = {
                str(x) for x in (hello.get("capabilities", []) or [])
                if str(x) in ACTIONS_AUTORISEES
            }
            connexion = _Connexion(ws, asyncio.get_running_loop(), capacites)
            with _VERROU:
                precedente = _CONNEXIONS.get(identifiant)
                _CONNEXIONS[identifiant] = connexion
            if precedente is not None:
                try:
                    await precedente.websocket.close(code=1012)
                except Exception:
                    pass
            await ws.send_text(json.dumps({
                "type": "pret", "agent": identifiant,
                "capabilities": sorted(ACTIONS_AUTORISEES),
            }))
            LOG.info("poste distant connecte : %s", identifiant)

            while True:
                brut = await ws.receive_text()
                if len(brut) > 8_000_000:
                    continue
                donnees = json.loads(brut)
                typ = donnees.get("type")
                if typ == "resultat":
                    futur = connexion.attentes.get(str(donnees.get("id", "")))
                    if futur is not None and not futur.done():
                        futur.set_result({
                            "ok": bool(donnees.get("ok", False)),
                            "message": str(donnees.get("message", ""))[:2000],
                            "resultat": donnees.get("resultat"),
                        })
                elif typ == "ping":
                    await ws.send_text('{"type":"pong"}')
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except Exception:
            LOG.exception("poste distant: boucle WebSocket")
        finally:
            if connexion is not None:
                for futur in list(connexion.attentes.values()):
                    if not futur.done():
                        futur.set_exception(ConnectionError("agent deconnecte"))
                with _VERROU:
                    if _CONNEXIONS.get(identifiant) is connexion:
                        _CONNEXIONS.pop(identifiant, None)
            if identifiant:
                LOG.info("poste distant deconnecte : %s", identifiant)

    LOG.info("poste distant: route /desktop-agent montee (LAN, token par agent)")
