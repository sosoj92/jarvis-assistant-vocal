# Faire tourner Jarvis H24 sans posséder deux ordinateurs

Jarvis n'impose pas l'architecture « ancien PC serveur + nouveau PC principal ».
Cette configuration est pratique lorsqu'on possède déjà deux machines, mais le
cerveau, le corps Windows et les satellites peuvent être répartis autrement.

La règle à conserver est simple : le **cerveau** traite les demandes et détient
les clés ; le **corps Windows** accède à l'écran, au micro, au Bluetooth, à la
webcam et aux applications. Un appareil distant ne reçoit que des actions
structurées autorisées, jamais un shell générique ni les clés cloud.

## Comparatif rapide

| Solution | Achat supplémentaire | Disponible PC éteint | Écran/son/gestes | État dans ce projet |
|---|---:|---:|---|---|
| **Un seul PC Windows** | aucun | non | complets sur ce PC | pris en charge |
| **NAS déjà possédé** | aucun | oui | via l'agent Windows quand le PC est allumé | avancé, installation manuelle |
| **Petit VPS Ubuntu** | abonnement mensuel | oui | via l'agent Windows quand le PC est allumé | avancé, installation manuelle |
| **Mini-PC x86 d'occasion** | achat unique | oui | via l'agent Windows ou des satellites | architecture recommandée à domicile |
| **Raspberry Pi 4/5** | achat unique | oui | surtout satellite ; cerveau limité | satellite documenté, cerveau expérimental |
| **ESP32 Atom Echo** | faible achat unique | oui si un cerveau existe ailleurs | micro/enceinte seulement | satellite audio, jamais le cerveau complet |

## 1. Un seul PC Windows — le plus simple et le moins cher

Jarvis, Hermes et les fonctions écran/audio tournent sur le même ordinateur.
Le script `scripts/autostart_install.ps1` les lance à l'ouverture de session.
Il suffit de désactiver la veille pendant les périodes où Jarvis doit rester
disponible.

Avantages : aucune machine ni configuration réseau supplémentaire, toutes les
fonctions matérielles sont locales. Limite : Jarvis s'arrête avec le PC et ne
peut plus répondre depuis les autres pièces.

## 2. VPS Ubuntu — cerveau H24 dans le cloud

Un petit VPS peut héberger l'orchestration Jarvis, Hermes, les crons, le serveur
MCP et les fichiers d'état. Le PC Windows quotidien conserve l'agent
`desktop_agent` : dès qu'il est allumé, il apporte l'écran, le micro, le son,
Spotify, OBS, la webcam, les gestes et Astra.

Cette option convient surtout avec un LLM cloud. Faire tourner un gros modèle
Ollama sur un VPS CPU ordinaire est généralement lent ; un VPS GPU coûte beaucoup
plus cher. Le stockage des notes et journaux sur un hébergeur tiers demande aussi
plus de discipline sur le chiffrement, les sauvegardes et la confidentialité.

État actuel : l'architecture et le protocole sont compatibles, mais le dépôt ne
fournit pas encore d'installateur VPS en une commande. Il faut installer le
serveur sous Ubuntu, créer ses services `systemd`, puis relier le PC Windows par
un réseau privé.

### Réseau obligatoire : privé, jamais un port Jarvis public

Ne pas publier directement les ports `8790`, `8791` ou MCP sur Internet. Relier
le VPS et le PC avec Tailscale/WireGuard, limiter le pare-feu à cette interface et
utiliser une règle d'accès qui n'autorise que le poste principal. Tailscale
attribue notamment des adresses dans `100.64.0.0/10`, plage acceptée par la garde
réseau de Jarvis.

Documentation officielle :

- [plage d'adresses Tailscale](https://tailscale.com/docs/reference/reserved-ip-addresses) ;
- [sécuriser un tailnet et ses règles d'accès](https://tailscale.com/kb/1429/secure) ;
- [restreindre le trafic d'un serveur avec son pare-feu](https://tailscale.com/kb/1181/firewalls) ;
- [installer Docker Engine sur Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

## 3. NAS — utile si la maison en possède déjà un

Un NAS x86 capable d'exécuter des conteneurs ou une VM peut remplacer le VPS :
pas d'abonnement et les données restent à domicile. Le NAS héberge le cerveau ;
le PC Windows apporte toujours son corps lorsqu'il est allumé.

Vérifier avant installation : architecture CPU compatible, mémoire disponible,
stockage persistant, sauvegarde, Docker/VM et redémarrage automatique des
services. Un NAS ARM ancien peut ne pas accepter toutes les images ou dépendances.

## 4. Mini-PC ou thin client d'occasion — le meilleur compromis local

Un mini-PC x86 basse consommation sous Ubuntu remplit le même rôle que l'ancien
PC, mais prend peu de place et consomme moins. Il peut rester H24, utiliser Docker
et `systemd`, et garder les données dans la maison. C'est souvent le choix le plus
prévisible pour qui veut du H24 local sans louer de VPS.

Il ne remplace toutefois pas le GPU du PC principal pour un gros modèle local :
dans ce cas, utiliser un petit modèle CPU ou un fournisseur cloud.

## 5. Raspberry Pi et ESP32 — à choisir pour le bon rôle

Le Raspberry Pi est excellent comme relais micro/enceinte et peut héberger des
services légers. Le guide actuel le traite surtout comme
[satellite audio](satellite_pi.md). En faire le cerveau complet est possible
seulement avec des compromis importants sur Whisper, Ollama et certaines
dépendances ; ce chemin reste expérimental.

Un ESP32 Atom Echo ne peut pas héberger Jarvis, Hermes ou un LLM. Il sert de
micro/haut-parleur peu coûteux relié à un cerveau placé sur un PC, un NAS ou un
VPS. Voir le [guide des satellites économiques](satellite.md).

## Comment choisir ?

- Budget nul et usage uniquement lorsque le PC est allumé : **un seul PC**.
- NAS déjà présent : **NAS + agent Windows**.
- Besoin H24 sans matériel à domicile : **VPS + réseau privé + agent Windows**.
- Besoin H24 local, stable et sans abonnement : **mini-PC x86 d'occasion**.
- Besoin de voix dans plusieurs pièces : ajouter des **satellites Pi/ESP32**, quel
  que soit l'emplacement du cerveau.

Dans toutes les architectures, les actions N3 conservent leur confirmation, les
tokens sont différents par agent et les fichiers `config.yaml` ne doivent jamais
être envoyés sur GitHub.
