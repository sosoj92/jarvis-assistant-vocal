#!/usr/bin/env python3
"""Prepare les configs privees serveur + poste principal sans afficher les secrets."""
from __future__ import annotations

import argparse
import secrets
import shutil
import socket
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parent.parent
CONFIG_SERVEUR = RACINE / "config.yaml"
CONFIG_AGENT = RACINE / "desktop_agent" / "config.yaml"


def adresse_locale():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def _charger(chemin):
    if not chemin.exists():
        return {}
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


def _entree(liste, identifiant):
    for entree in liste:
        if isinstance(entree, dict) and str(entree.get("id", "")) == identifiant:
            return entree
    entree = {"id": identifiant}
    liste.append(entree)
    return entree


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", help="Adresse LAN ou Tailscale de l'ancien PC")
    parser.add_argument("--agent", default="bureau")
    args = parser.parse_args()
    hote = str(args.host or adresse_locale()).strip()
    identifiant = str(args.agent).strip() or "bureau"

    serveur = _charger(CONFIG_SERVEUR)
    if CONFIG_SERVEUR.exists():
        sauvegarde = RACINE / "logs" / "config-avant-poste-principal.yaml"
        sauvegarde.parent.mkdir(parents=True, exist_ok=True)
        if not sauvegarde.exists():
            shutil.copy2(CONFIG_SERVEUR, sauvegarde)
    serveur["poste_principal"] = {
        "actif": True,
        "agent": identifiant,
        "serveur_sans_peripheriques": True,
    }
    agents = serveur.setdefault("desktop_agents", [])
    agent = _entree(agents, identifiant)
    agent.setdefault("token", secrets.token_urlsafe(32))

    satellites = serveur.setdefault("satellites", [])
    satellite = _entree(satellites, identifiant)
    satellite.setdefault("piece", "bureau")
    satellite.setdefault("token", secrets.token_urlsafe(32))
    satellite.setdefault("wake", "appareil")
    satellite.setdefault("priorite_micro", 1.0)
    satellite["brief_au_demarrage"] = True
    CONFIG_SERVEUR.write_text(
        yaml.safe_dump(serveur, allow_unicode=True, sort_keys=False), encoding="utf-8")

    config_agent = {
        "serveur_url": f"ws://{hote}:8791/desktop-agent",
        "agent_id": identifiant,
        "token": agent["token"],
        "apps": {"spotify": "spotify:"},
        "overlay": {
            "actif": True,
            "ecran": 1,
            "coin": "bas-droite",
            "opacite": 0.92,
            "largeur": 420,
            "duree_min": 4.0,
            "duree_max": 14.0,
            "marge": 24,
            "exclure_obs": True,
            "muet_visuel": False,
        },
        "gestes": {"souris_moniteur": 1},
        "audio": {
            "actif": True,
            "brief_au_demarrage": True,
            "pc_url": f"ws://{hote}:8791/satellite",
            "satellite_id": identifiant,
            "token": satellite["token"],
            "micro": None,
            "haut_parleur": None,
            "sorties": {},
            "seuil_reveil": 0.5,
            "gain_reveil": 1.0,
            "gain_audio": 1.0,
            "seuil_silence": 0.010,
            "silence_fin": 1.0,
            "attente_parole": 3.0,
            "attente_arbitrage_reveil": 4.0,
            "fenetre_relance": 8.0,
            "blocs_purge_bip": 2,
            "duree_max": 20,
        },
    }
    CONFIG_AGENT.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_AGENT.write_text(
        yaml.safe_dump(config_agent, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    print("Configuration serveur mise a jour.")
    print("Configuration privee du nouveau PC creee dans desktop_agent/config.yaml.")
    print("Les secrets n'ont pas ete affiches et ces deux fichiers sont ignores par Git.")


if __name__ == "__main__":
    main()
