# Hermes dans une VM Ubuntu Server (Hyper-V)

Cette installation conserve Windows et exécute Hermes dans une VM Ubuntu Server
isolée. Windows garde le micro, la caméra, l'écran, Ollama, les intégrations et
tous les identifiants. La VM héberge uniquement Hermes et ses données de travail.

## Architecture

- `127.0.0.1:8642` sur Windows → API Hermes dans la VM ;
- `127.0.0.1:8765` dans la VM → serveur MCP Jarvis sur Windows ;
- `127.0.0.1:11434` dans la VM → Ollama sur Windows.

Ces trois liaisons passent dans un tunnel SSH. Aucun de ces ports n'est publié sur
le réseau local ni sur Internet. Le pare-feu Ubuntu n'autorise en entrée que SSH.

## Prérequis

- Windows 11 Pro avec Hyper-V ;
- Ubuntu Server 24.04 LTS dans une VM génération 2 ;
- au moins 2 vCPU, 4 Gio de RAM et 40 Gio de disque virtuel ;
- OpenSSH activé pendant l'installation d'Ubuntu ;
- Docker Engine et le plugin Compose dans la VM ;
- Ollama et `qwen3.5:4b` sur le PC Windows.

Le disque virtuel est un fichier stocké sur Windows : l'installation d'Ubuntu
dans la VM n'efface pas Windows.

## Préparer Ubuntu

Depuis la VM, connecte-toi avec le compte créé pendant l'installation puis copie
et exécute le script de préparation :

```bash
sudo bash scripts/provision_ubuntu_server.sh
```

Le script installe Docker, Tailscale, UFW, fail2ban et les mises à jour de sécurité,
puis crée `/opt/jarvis`. Il doit être lancé avec `sudo` depuis le compte applicatif,
pas directement depuis une session `root`.

Copie ensuite dans la VM :

- `deploy/server/compose.hermes.yaml` vers `/opt/jarvis/config/compose.hermes.yaml` ;
- `deploy/server/hermes-config.yaml` vers `/opt/jarvis/data/hermes/config.yaml`.

Crée localement `/opt/jarvis/config/hermes-api.env` avec les droits `600` :

```text
API_SERVER_KEY=<une-cle-aleatoire-longue>
```

Ne place jamais cette clé dans Git, une capture d'écran ou une commande partagée.

## Clé SSH et tunnel Windows

Crée une clé dédiée sans réutiliser une clé personnelle, copie seulement sa partie
publique dans `~/.ssh/authorized_keys` de la VM, puis désactive l'authentification
SSH par mot de passe une fois le test par clé réussi.

Sur Windows, crée le fichier local suivant, déjà couvert par `logs/` dans
`.gitignore` :

```text
logs/hermes-server-target.txt
```

Son unique ligne est la cible SSH, par exemple :

```text
utilisateur@jarvis-server.local
```

La clé privée dédiée attendue par défaut est :

```text
%USERPROFILE%\.ssh\jarvis_server_ed25519
```

Lance ensuite :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_hermes_server_tunnel.ps1
```

Le script refuse une cible mal formée, vérifie la clé, utilise une empreinte SSH
déjà approuvée et s'arrête si un transfert ne peut pas être créé.

## Démarrer Hermes

Dans la VM :

```bash
sudo docker compose -f /opt/jarvis/config/compose.hermes.yaml up -d
sudo docker ps --filter name=jarvis-hermes
```

L'image est verrouillée par digest. Le conteneur redémarre automatiquement, n'a
pas de privilèges supplémentaires et son API écoute seulement sur le loopback de
la VM.

## Outils autorisés

Le profil fourni n'expose à Hermes que cinq outils N1 : heure/date, météo, état du
système, recherche d'inspirations et état des contenus. Caméra, micro, écran,
domotique, finances et actions sensibles restent côté Jarvis. Une extension de ce
périmètre doit être décidée et testée outil par outil.

## Démarrage automatique

`scripts/demarrer_jarvis_complet.ps1` démarre le serveur MCP local, le tunnel puis
Jarvis sans créer de doublons. Il peut être lancé par le dossier Démarrage Windows.

Pour que la VM démarre également avec Windows, ouvre PowerShell en administrateur :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configurer_vm_autostart.ps1
```

Le script utilise d'abord l'autostart natif Hyper-V. Si Hyper-V le refuse, il crée
une tâche `SYSTEM` strictement limitée au démarrage de `Jarvis-Server`.

## Vérifications

Avec le tunnel actif, ces contrôles doivent réussir depuis Windows :

```powershell
Test-NetConnection 127.0.0.1 -Port 8642
Test-NetConnection 127.0.0.1 -Port 8765
Test-NetConnection 127.0.0.1 -Port 11434
```

Le premier port est l'API Hermes. Les deux autres services restent hébergés sur
Windows et ne sont accessibles à la VM qu'au travers des retours du tunnel SSH.
