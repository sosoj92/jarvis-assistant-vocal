# Satellite Raspberry Pi — installation

Le satellite Pi = les **oreilles + la bouche** de Jarvis dans une pièce. Il détecte
« Hey Jarvis » **sur le Pi**, envoie ta phrase au PC (cerveau), et joue la réponse.
Protocole et sécurité : voir [satellite.md](satellite.md).

Statut : **client fait** (`satellite_pi/`). Il te reste à **brancher un micro + un
haut-parleur** et suivre ce guide (tu m'as dit que tu ferais le flash/install
toi-même — tout est ici).

## 1. Matériel

| Élément | Statut | Détail |
|---|---|---|
| **Raspberry Pi 4 (8 Go)** | ✅ tu l'as | Largement suffisant (le gros du calcul est sur le PC). |
| **Carte micro-SD** | à vérifier | 16 Go+ (Raspberry Pi OS 64-bit). |
| **Alimentation Pi 4** (USB-C, 5V/3A) | à vérifier | Celle du Pi. |
| **Micro** | **à brancher** | Le Pi n'a **pas** de micro intégré. Voir ci-dessous. |
| **Haut-parleur** | **à brancher** | Prise **jack 3,5 mm** du Pi 4, ou USB, ou HDMI. |
| Écran | optionnel | Le « visage » (HUD/orbe) c'est surtout pour le futur boîtier ESP32. Le Pi v1 peut être **audio seul**. |

### Micro / haut-parleur — ce qui marche avec ce que tu as vs à acheter

**Si tu as déjà sous la main (ça marche, zéro achat) :**
- une **webcam USB** (elle a un micro) → micro OK ; + n'importe quelle enceinte/écouteurs en **jack 3,5 mm** → son OK ;
- un **casque/micro USB** (gaming) → fait les deux ;
- une vieille **enceinte Bluetooth/USB** + un micro USB quelconque.

**Si tu dois acheter (le mieux pour une pièce) :**
- 🥇 **Un speakerphone USB** (micro + HP tout-en-un, type Anker PowerConf, Jabra Speak, ou générique ~25-40 €) → plug-and-play, bonne captation à distance, un seul câble. **C'est ce que je recommande.**
- 🥈 **ReSpeaker 2-Mic HAT** (~13 €) + une petite enceinte jack → meilleure captation « pièce » (far-field), un peu plus de config.
- 🥉 **Micro USB basique** (~8 €) + enceinte jack que tu as → le moins cher.

> Conseil : commence avec **ce que tu as** (webcam USB + enceinte jack) pour valider,
> puis passe à un **speakerphone USB** si la captation à distance te déçoit.

## 2. Installation sur le Pi

```bash
# Raspberry Pi OS 64-bit à jour
sudo apt update && sudo apt install -y python3-venv python3-pip portaudio19-dev

# Copie le dossier satellite_pi/ sur le Pi (clé USB, scp, git clone...), puis :
cd satellite_pi
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # sounddevice, numpy, openwakeword, websockets, pyyaml
```

## 3. Côté PC (une fois)

Dans `config.yaml` du PC, déclare le satellite et ouvre le serveur au réseau local :
```yaml
serveur:
  host: "0.0.0.0"              # le Pi doit joindre le PC (les gardes gardent panneau/cockpit en loopback)
satellites:
  - id: "cuisine"
    piece: "cuisine"
    token: "un-secret-long"    # python -c "import secrets;print(secrets.token_urlsafe(24))"
    wake: "appareil"
```
Puis **relance Jarvis**. Récupère l'**IP du PC** sur le réseau (`ipconfig` → IPv4).

## 4. Config du Pi

```bash
cp config.exemple.yaml config.yaml
nano config.yaml
```
Renseigne :
- `pc_url: "ws://<IP-DU-PC>:8790/satellite"`
- `satellite_id: "cuisine"` (le même qu'au PC)
- `token: "<le même token qu'au PC>"`
- `micro` / `haut_parleur` : lance
  `python -c "import sounddevice as sd; print(sd.query_devices())"`
  et mets les **index** de ton micro et de ta sortie (ou laisse `null` pour le défaut).

## 5. Lancer

```bash
python jarvis_satellite.py
```
Dis **« Hey Jarvis, quelle heure est-il »** → le Pi capte, le PC répond, le Pi parle.
Si le PC est éteint : « Jarvis dort, rallume la tour » (reconnexion auto ensuite).

## 6. Démarrage auto au boot (optionnel — systemd)

`/etc/systemd/system/jarvis-satellite.service` :
```ini
[Unit]
Description=Satellite Jarvis
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/satellite_pi
ExecStart=/home/pi/satellite_pi/.venv/bin/python jarvis_satellite.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now jarvis-satellite
journalctl -u jarvis-satellite -f      # voir les logs
```

## Dépannage

- **Pas de son / micro** : vérifie les index (`sd.query_devices()`), et le volume ALSA
  (`alsamixer`). Un speakerphone USB s'auto-sélectionne souvent bien.
- **« token invalide »** : le `token` du Pi doit être identique à celui du PC pour ce `satellite_id`.
- **« injoignable »** : le PC doit avoir `serveur.host: "0.0.0.0"`, être allumé, et sur le même réseau ; teste `ping <IP-DU-PC>` depuis le Pi.
- **Latence** : normal ~2-3 s (transcription + LLM + voix). Le 1er échange après un
  démarrage du PC est plus lent (chargement des modèles).

## Plus tard (prévu, pas encore fait)
- **Écran/visage** sur le Pi (états veille/écoute/parole) — l'overlay version boîtier.
- **Mode nuit** : le Pi assure la domotique seul quand le PC est éteint et le réveille
  via la Tapo (cf. [wol.md](wol.md)). L'architecture le permet déjà (dispatch isolé).
- **Boîtier ESP32-S3-BOX-3** : même protocole, firmware dédié (phase suivante).
