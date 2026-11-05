# Satellite Raspberry Pi — installation générique

Le client `satellite_pi/` transforme un Raspberry Pi en point audio distant
pour Jarvis. Le Pi détecte le mot d'activation localement, transmet la parole au PC
qui héberge Jarvis, puis joue la réponse reçue.

Le PC reste le serveur central. Le satellite n'a besoin ni de caméra ni d'écran :
une entrée audio, une sortie audio, une alimentation adaptée et une connexion au
même réseau local suffisent. Le protocole et son modèle de sécurité sont décrits
dans [satellite.md](satellite.md).

## 1. Matériel compatible

| Élément | Requis | Recommandation générale |
|---|---:|---|
| Ordinateur monocarte | oui | Raspberry Pi 4 ou 5 sous Raspberry Pi OS 64 bits. Le Pi Zero 2 W et d'autres machines Linux ARM64 sont expérimentaux et doivent être validés avec leurs périphériques audio. |
| Stockage | oui | Carte micro-SD ou SSD de 16 Go minimum. |
| Alimentation | oui | Alimentation conforme au modèle de carte utilisé ; éviter les chargeurs sous-dimensionnés. |
| Entrée audio | oui | Tout microphone exposé à ALSA : USB, interface audio USB ou carte/HAT audio compatible. |
| Sortie audio | oui | Toute sortie exposée à ALSA : USB, interface audio, HDMI ou sortie analogique si la carte en possède une. |
| Réseau | oui | Ethernet ou Wi-Fi sur le même LAN que le PC Jarvis. |
| Caméra / écran | non | Le client actuel est audio uniquement. |

### Choisir l'audio

Plusieurs montages sont possibles ; le logiciel n'impose aucune marque ni aucune
connectique :

1. **Speakerphone USB (micro + haut-parleur)** : solution la plus simple, avec un
   seul périphérique d'entrée/sortie.
2. **Micro et haut-parleur séparés** : micro USB avec enceinte USB, HDMI ou sortie
   analogique disponible sur la carte.
3. **Carte audio/HAT I2S** : adaptée à une intégration fixe, mais demande la
   configuration du pilote ALSA correspondant.
4. **Bluetooth** : possible si le périphérique est correctement exposé à ALSA,
   mais moins recommandé pour un service autonome à cause de la latence et des
   reconnexions.

La qualité de captation dépend surtout de la distance, du bruit de la pièce et de
l'annulation d'écho du périphérique. Une webcam n'est jamais requise par le
satellite.

Pour le Pi Zero 2 W, prévoir un hub/adaptateur USB OTG ou une carte audio I2S et
utiliser Raspberry Pi OS Lite 64 bits. Le guide central détaille les limites :
[satellite_installation.md](satellite_installation.md).

## 2. Installer le client

Sur Raspberry Pi OS 64 bits :

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip portaudio19-dev

# Copier satellite_pi/ sur le Pi, puis :
cd satellite_pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Le dossier peut être copié par Git, SCP ou support amovible. Le fichier local
`satellite_pi/config.yaml` contient les paramètres propres à l'installation et
ne doit pas être versionné.

## 3. Déclarer le satellite sur le PC

Dans le `config.yaml` du PC, ajouter une entrée par satellite. Chaque appareil
doit avoir un identifiant et un token distincts :

```yaml
satellites:
  - id: "satellite-1"
    piece: "salon"             # exemple : contexte domotique de cette pièce
    token: "<TOKEN_ALEATOIRE>"
    wake: "appareil"

satellite_lan:
  actif: true
  host: "0.0.0.0"
  tls: true        # facultatif (défaut) : port chiffré (wss://), certificat créé dans certs/
  port_tls: 8792
  port: 8791       # port EN CLAIR, seulement le temps de la bascule
```

Générer un token avec :

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Après redémarrage de Jarvis, le listener LAN dédié n'expose que la route
`/satellite`. Le pare-feu doit autoriser le port chiffré `8792` uniquement sur le
profil réseau privé. Au premier démarrage, Jarvis crée dans `certs/` une clé
privée et le certificat **public** `certs/jarvis-lan.crt`.

## 4. Configurer le Pi

```bash
cp config.exemple.yaml config.yaml
nano config.yaml
```

Copier le certificat **public** du PC à côté de cette configuration, sous le nom
`satellite_pi/jarvis-lan.crt` (clé USB, ou `scp` depuis le PC). Ne copier **jamais**
`certs/jarvis-lan.key` : la clé privée ne quitte pas le PC.

Renseigner obligatoirement :

- `pc_url` : `wss://<ADRESSE_LAN_DU_PC>:8792/satellite` ;
- `certificat` : `jarvis-lan.crt` ;
- `satellite_id` : le même identifiant que dans la configuration du PC ;
- `token` : le token associé à cet identifiant.

Le satellite n'accepte que ce certificat : le token et l'audio ne passent pas en
clair. L'ancien `ws://<ADRESSE_LAN_DU_PC>:8791/satellite` (en clair, sans
certificat) n'est qu'un mode de transition déconseillé : il cesse de fonctionner
dès que le PC passe `satellite_lan.clair: false`.

Pour lister les périphériques audio :

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Les clés `micro` et `haut_parleur` acceptent un index de périphérique.

Si un autre service, par exemple Raspotify, joue sur la même enceinte USB,
configure un PCM ALSA partagé (`plug` au-dessus de `dmix`) avec
`pcm_sortie_alsa`. `alsa_config_path` peut désigner le fichier qui déclare ce
PCM. Jarvis utilise alors `aplay` pour ses accusés de réveil et ses réponses,
sans interrompre Spotify et sans changer le périphérique du micro.
La valeur `null` utilise le périphérique par défaut d'ALSA.

## 5. Tester

```bash
python jarvis_satellite.py
```

Dire « Hey Jarvis », attendre le « Oui ? » vocal, puis poser une question. Le terminal
affiche la connexion, la détection du mot d'activation, la transcription et les
éventuelles erreurs audio ou réseau.

Quand plusieurs micros entendent le même mot d'activation, le satellite demande au
PC l'autorisation de répondre. Seul le micro ayant le meilleur score de détection
prononce « Oui ? » ; les autres affichent `wake ignoré` et retournent en veille.
Le texte, l'activation et le délai de repli se règlent côté PC avec
`satellite_lan.texte_accuse_reveil`, `accuse_reveil_vocal` et
`delai_accuse_reveil`. Si la synthèse vocale n'est pas disponible à temps, le Pi
émet son bip local afin de ne jamais bloquer la conversation.

Après chaque réponse, le satellite garde par défaut une fenêtre de conversation de
8 secondes : on peut enchaîner une question sans répéter « Hey Jarvis ». La clé
`fenetre_relance` de `config.yaml` règle cette durée (`0` la désactive). Pendant une
activation, `satellite_lan.max_relances` borne aussi le nombre de fenêtres
successives (2 par défaut). Un bruit ou une transcription vide ne peut donc plus
renouveler l'écoute indéfiniment : une fois la limite atteinte, « Hey Jarvis »
redevient obligatoire. Une confirmation N3 déjà demandée reste toujours écoutée.
Pendant une vraie tâche lente, Jarvis peut prononcer un accusé lié à l'intention (« Je regarde
tes mails », « Je cherche une recette »). La transcription reste silencieuse :
Jarvis attend de connaître la demande avant de décider si une annonce est utile.
Les questions simples comme « Comment ça va ? » ou « Quelle heure est-il ? » restent
directes, sans phrase de remplissage. Les seuils se règlent côté PC dans
`satellite_lan`.
Dire « Hey Jarvis, mets-toi en veille » ferme immédiatement la conversation suivie.
Le satellite ignore alors toute parole ordinaire jusqu'à un nouveau « Hey Jarvis ».

Par défaut, deux blocs audio très courts sont ignorés après l'accusé pour éviter que
le micro réentende le haut-parleur. Avec un speakerphone doté d'une annulation
d'écho, `blocs_purge_bip: 0` permet de dire « Hey Jarvis, quelle heure est-il ? »
d'une traite, sans perdre le début de la question.

## 6. Démarrage automatique

Le service fourni emploie `%h` et ne dépend donc pas d'un nom d'utilisateur
particulier. Il suppose que le dossier se trouve dans `~/satellite_pi` :

```bash
mkdir -p ~/.config/systemd/user
cp ~/satellite_pi/jarvis-satellite.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jarvis-satellite

# Autoriser le service utilisateur à démarrer sans session SSH ouverte.
sudo loginctl enable-linger "$USER"

systemctl --user status jarvis-satellite
journalctl --user -u jarvis-satellite -f
```

Si le dossier est installé ailleurs, adapter `WorkingDirectory` et
`ExecStart` dans le fichier de service.

## Dépannage

- **Configuration refusée au démarrage** : vérifier `pc_url`,
  `satellite_id` et `token` dans le fichier local.
- **Aucun micro / aucun son** : vérifier les index avec `sd.query_devices()`,
  le périphérique ALSA par défaut et les niveaux dans `alsamixer`.
- **Token invalide** : l'identifiant et le token doivent correspondre exactement à
  une entrée `satellites[]` côté PC.
- **Serveur injoignable** : vérifier que les deux machines sont sur le même réseau,
  que `satellite_lan.actif` est activé et que le pare-feu autorise le port LAN.
- **Certificat du serveur inutilisable** : le fichier `certificat` est absent ou
  différent du certificat actuel du PC. Recopier `certs/jarvis-lan.crt` vers
  `satellite_pi/jarvis-lan.crt` (jamais la clé `.key`).
- **Coupures ou latence** : privilégier Ethernet ou un Wi-Fi stable, puis vérifier
  la charge du PC et les backends STT/LLM/TTS sélectionnés.
- **Écho acoustique** : éloigner le micro du haut-parleur, réduire le volume ou
  utiliser un périphérique avec annulation d'écho.

## Extensions possibles

Le protocole prévoit déjà les états d'écoute, de réflexion et de parole. Un écran,
un mode local de secours ou d'autres clients embarqués peuvent être ajoutés plus
tard sans être requis par l'installation audio de base.
