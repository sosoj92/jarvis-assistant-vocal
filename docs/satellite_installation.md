# Installer Jarvis dans une autre pièce

Un satellite ajoute un micro et un haut-parleur dans une pièce, mais **le cerveau
reste sur le PC principal**. Il n'y a donc aucun câble à tirer jusqu'au PC : le
satellite a seulement besoin d'une alimentation et du même réseau local, en Wi-Fi
ou Ethernet.

## Ce qui peut être installé aujourd'hui

| Matériel | État | Guide |
|---|---|---|
| Raspberry Pi 4/5 ou autre Linux ARM64 | **pris en charge** | client Python fourni dans `satellite_pi/` |
| Raspberry Pi Zero 2 W | **expérimental** | même client Linux, mais dépendances et audio à valider sur chaque image |
| M5Stack ATOM Echo / ESP32 audio | **firmware à développer** | protocole défini, aucune image à flasher dans ce dépôt pour le moment |
| Ancien téléphone Android | **application à développer** | aucun APK Jarvis fourni pour le moment |

Pour une installation immédiate, utiliser la voie Raspberry/Linux. Ne pas acheter
un ATOM Echo en pensant qu'il est déjà prêt à rejoindre Jarvis : il constitue une
cible économique intéressante, mais il manque encore le firmware client.

## Architecture et prérequis communs

```text
micro + haut-parleur
        │
satellite de la pièce ── Wi-Fi/Ethernet local ── PC Jarvis
                                                ├─ transcription
                                                ├─ LLM et outils
                                                └─ synthèse vocale
```

- Le PC Jarvis doit être allumé et Jarvis lancé.
- Les deux appareils doivent être sur le même réseau local privé.
- Chaque satellite reçoit un identifiant, une pièce et un token distincts.
- Les clés OpenAI, Anthropic, ElevenLabs, Alexa et autres restent **uniquement sur
  le PC**. Le satellite ne reçoit jamais ces identifiants.
- Ne pas rediriger le port satellite sur Internet.

Le protocole complet et les règles de sécurité sont dans
[satellite.md](satellite.md).

## Installation prise en charge : Raspberry Pi / Linux

### 1. Préparer le matériel

Il faut :

- un Raspberry Pi ou une petite machine Linux ARM64 ;
- Raspberry Pi OS Lite **64 bits** ou une distribution Linux compatible ;
- une carte micro-SD de 16 Go ou plus ;
- une alimentation adaptée ;
- un microphone et une sortie audio reconnus par ALSA.

Le montage le plus simple est un speakerphone USB réunissant micro, haut-parleur
et annulation d'écho. Un micro USB et une enceinte séparée fonctionnent également.
La caméra et l'écran sont facultatifs : le client fourni est audio uniquement.

### 2. Installer le client sur le Pi

Après avoir configuré le réseau et SSH dans Raspberry Pi Imager :

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip portaudio19-dev

git clone https://github.com/sosoj92/jarvis-assistant-vocal.git
cd jarvis-assistant-vocal/satellite_pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Déclarer une pièce sur le PC

Dans le `config.yaml` privé du PC :

```yaml
satellites:
  - id: "satellite-cuisine"
    piece: "cuisine"
    token: "<TOKEN_ALEATOIRE>"
    wake: "appareil"

satellite_lan:
  actif: true
  host: "0.0.0.0"
  tls: true        # port chiffré (wss://), certificat créé dans certs/ (défaut)
  port_tls: 8792
  port: 8791       # port EN CLAIR, seulement le temps de la bascule (voir plus bas)
```

Créer le token sur le PC ou le Pi :

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Redémarrer Jarvis, puis autoriser le port chiffré `8792` dans le pare-feu
**uniquement sur le profil réseau privé**. Au premier démarrage, Jarvis crée dans
`certs/` une clé privée et le certificat **public** `certs/jarvis-lan.crt`, que le
satellite utilisera à l'étape suivante.

### 4. Configurer et tester le satellite

Sur le Pi :

```bash
cd ~/jarvis-assistant-vocal/satellite_pi
cp config.exemple.yaml config.yaml
nano config.yaml
```

Copier le certificat **public** du PC à côté de cette configuration, sous le nom
`satellite_pi/jarvis-lan.crt` (clé USB, ou `scp` depuis le PC). Ne copier **jamais**
`certs/jarvis-lan.key` : la clé privée ne quitte pas le PC.

Renseigner ensuite `pc_url`, `certificat`, `satellite_id` et `token`. L'URL ressemble à :

```yaml
pc_url: "wss://<ADRESSE_LAN_DU_PC>:8792/satellite"
certificat: "jarvis-lan.crt"
satellite_id: "satellite-cuisine"
token: "<LE_MEME_TOKEN_QUE_SUR_LE_PC>"
```

Le satellite n'accepte que ce certificat : le token et l'audio ne passent pas en
clair, et un autre appareil du Wi-Fi ne peut pas se faire passer pour le PC. L'ancien
`ws://<ADRESSE_LAN_DU_PC>:8791/satellite` (en clair, sans certificat) n'est qu'un mode
de transition déconseillé : il cesse de fonctionner dès que le PC passe
`satellite_lan.clair: false` (voir [satellite.md](satellite.md#sécurité)). Si le
client signale un certificat inutilisable, vérifier que le fichier est présent et
qu'il s'agit bien de la copie actuelle de `certs/jarvis-lan.crt`.

Lister les périphériques audio si les valeurs par défaut ne conviennent pas :

```bash
source .venv/bin/activate
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Puis lancer le test :

```bash
python jarvis_satellite.py
```

Dire « Hey Jarvis », attendre l'accusé vocal, puis poser une question. Pour le
démarrage automatique, le réglage audio partagé avec Spotify et le dépannage,
continuer avec le [guide Raspberry/Linux détaillé](satellite_pi.md).

## Cas du Raspberry Pi Zero 2 W

Le Zero 2 W peut être intéressant si le but est uniquement de relayer l'audio :
Whisper, le LLM et la synthèse restent sur le PC. Il n'est toutefois pas encore
validé officiellement dans ce projet.

- utiliser Raspberry Pi OS Lite 64 bits ;
- prévoir un adaptateur/hub USB OTG ou une carte audio I2S : le Zero 2 W n'offre
  pas à lui seul une entrée et une sortie audio prêtes à l'emploi ;
- tester l'installation des roues Python de `numpy`, `scipy` et `openwakeword`
  avant une intégration définitive ;
- éviter de compiler de lourdes dépendances sur la carte si une roue ARM64 n'est
  pas disponible ;
- commencer avec un seul périphérique audio et sans Spotify Connect afin de
  valider d'abord le dialogue Jarvis.

Si l'installation Python ou le wake word ne tient pas correctement sur cette
image, repasser sur un Pi 4/5 ou attendre le client ESP32 dédié.

## Cas de l'ATOM Echo / ESP32 audio

Un ESP32 ne peut pas exécuter le dossier Python `satellite_pi/`. Il lui faut un
firmware séparé, écrit avec ESP-IDF, Arduino ou PlatformIO. Le protocole Jarvis est
déjà documenté pour permettre ce travail, mais le dépôt ne fournit actuellement
ni firmware, ni binaire, ni procédure de flash fonctionnelle.

Le futur firmware devra au minimum :

1. se connecter au Wi-Fi et au WebSocket `/satellite` ;
2. envoyer `hello` avec l'identifiant et le token de la pièce ;
3. capturer le micro et produire du PCM mono 16 bits à 16 kHz ;
4. gérer le mot d'activation ou un bouton d'activation ;
5. envoyer `reveil`, l'audio puis `fin_parole` ;
6. lire les trames audio renvoyées par Jarvis ;
7. respecter `veille_forcee`, les confirmations et la reconnexion réseau.

Tant que cette étape de la roadmap n'est pas terminée, l'ATOM Echo est une option
de développement, pas une installation utilisateur. Les contributions sont les
bienvenues à condition de conserver le traitement sur le LAN et de ne stocker
aucune clé cloud dans l'ESP32.

## Sécurité avant de considérer l'installation terminée

- `config.yaml` du PC et du satellite ne doivent jamais être commités ;
- un token différent doit être utilisé pour chaque pièce ;
- le listener doit rester sur le réseau privé, sans redirection de port ;
- les journaux et captures audio de test ne doivent pas être publiés ;
- une action sensible continue de demander une confirmation vocale locale.
