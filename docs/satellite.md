# Satellites — Jarvis dans d'autres pièces

Un **satellite** est une extension du **corps** de Jarvis : oreilles + bouche +
éventuellement visage déportés dans une autre pièce. Le **cerveau reste sur le
PC** — le satellite capte l'audio, le PC transcrit
(Whisper) → LLM + outils → TTS, et renvoie l'audio + des états pour l'écran.
Hermes n'est pas concerné.

Statut : **côté PC et client Raspberry/Linux faits** (endpoint, protocole,
multi-pièces, token et audio). Commencer par le
[guide de choix et d'installation](satellite_installation.md), puis consulter le
[guide Raspberry/Linux détaillé](satellite_pi.md). Le firmware ESP32/ATOM Echo et
l'application Android ne sont pas encore fournis.

## Choisir un matériel sans surdimensionner chaque pièce

Un micro et un haut-parleur passifs ne peuvent pas rejoindre seuls le réseau : il
faut dans chaque pièce un petit **client Wi-Fi** qui capte le son, dialogue avec le
PC et joue sa réponse. Ce client ne fait ni transcription ni appel au LLM.

| Option | Coût relatif | Points forts | Limites et état du projet |
|---|---:|---|---|
| **Ancien téléphone Android** | minimal si déjà disponible | micro, haut-parleur, Wi-Fi, batterie et écran déjà intégrés | meilleur candidat économique ; application Jarvis à développer, non fournie aujourd'hui |
| **ESP32 audio / Atom Echo** | faible | minuscule, basse consommation, wake word embarquable | audio plus modeste et firmware Jarvis à développer |
| **Raspberry Pi Zero 2 W / petit Linux ARM64** | faible à moyen | environnement Linux proche du client actuel | adaptateur audio, alimentation et carte micro-SD peuvent réduire l'économie ; non validé officiellement |
| **Raspberry Pi 4/5 ou mini-PC Linux** | moyen à élevé | USB audio simple, maintenance et extensions faciles | solution de référence actuellement documentée, mais surdimensionnée pour le seul relais audio |

Pour installer quelque chose **maintenant**, choisir le client Raspberry/Linux.
Le Pi Zero 2 W peut être essayé comme variante expérimentale. Un téléphone Android
ou un ESP32 ne devient pas encore un satellite Jarvis sans développer le client
manquant. Tous les futurs clients devront utiliser une identité et un token
distincts par pièce.

Le protocole ci-dessous est volontairement indépendant du matériel. **La
compatibilité architecturale ne signifie toutefois pas que tous ces clients sont
déjà implémentés** : le dépôt fournit actuellement le client Raspberry Pi/Linux et
le simulateur de test ; Android et ESP32 restent dans la feuille de route.

## Le protocole (WebSocket `/satellite`)

Volontairement **simple et transport-agnostique** pour qu'un **ESP32 l'utilise à
l'identique**. Deux types de trames :

- **Trames TEXTE** = messages de contrôle en **JSON**.
- **Trames BINAIRES** = audio **PCM brut 16 bits little-endian, mono, 16 kHz**
  (dans les deux sens).

### Client → serveur
| Message | Rôle |
|---|---|
| `{"type":"hello","satellite":"cuisine","token":"..."}` | Authentification + identité. **Obligatoire en premier.** |
| `{"type":"reveil","id":1,"score":0.84}` | Propose la détection locale du wake word à l'arbitrage multi-micros. |
| *(trames binaires)* | Audio PCM capté, envoyé au fil de la parole. |
| `{"type":"fin_parole"}` | Fin de l'énoncé → le serveur transcrit et traite. |
| `{"type":"scene_demarrage"}` | Demande le brief quotidien ; accepté uniquement pour un satellite autorisé avec `brief_au_demarrage: true`. |
| `{"type":"ping"}` | Keep-alive (réponse `pong`). |

### Serveur → client
| Message | Rôle |
|---|---|
| `{"type":"pret","piece":"cuisine"}` | Auth acceptée ; pièce du satellite. |
| `{"type":"reveil_accepte","id":1,"accuse_vocal":true}` / `reveil_refuse` | Autorise un seul micro à capter et répondre. Si accepté, le serveur envoie d'abord le court audio « Oui ? » ; `accuse_vocal` indique qu'il a bien été joué, sinon le client émet son bip de secours. |
| `{"type":"etat","etat":"..."}` | État pour le visage/HUD : `veille`, `ecoute`, `reflexion`, `parole`, `attente_confirmation`. |
| `{"type":"transcription","texte":"..."}` | Ce que le serveur a entendu. |
| `{"type":"progression","texte":"..."}` | Accusé ou étape vocale pendant une transcription/recherche longue. |
| `{"type":"texte","texte":"..."}` | Texte de la réponse (affichage). |
| `{"type":"audio_debut","freq":24000}` | Début de l'audio de réponse (fréquence des trames binaires qui suivent). |
| *(trames binaires)* | Audio PCM de la réponse. |
| `{"type":"audio_fin"}` | Fin de l'audio. |
| `{"type":"relance","secondes":8}` | Ouvre une courte écoute de suivi sans répéter le mot d'activation. |
| `{"type":"veille_forcee"}` | Ferme immédiatement l'écoute de suivi ; un nouveau « Hey Jarvis » devient obligatoire. |
| `{"type":"erreur","message":"..."}` | Erreur. |

### Cycle type
`hello` → `pret` → `reveil` → *« Oui ? »* → `reveil_accepte` →
*(binaire audio…)* → `fin_parole` → `etat:reflexion` →
`transcription` → `etat:parole` + `texte` + `audio_debut` + *(binaire…)* +
`audio_fin` → `relance` → `etat:veille`. Pendant les étapes lentes, un ou plusieurs
messages `progression` et leurs trames audio peuvent précéder la réponse finale.

Après la lecture de la réponse, le client écoute pendant quelques secondes. Une
question posée dans cette fenêtre repart directement au PC ; en l'absence de voix,
le satellite revient automatiquement à l'attente de « Hey Jarvis ». Le micro reste
verrouillé pendant que Jarvis parle afin de ne pas réécouter sa propre réponse.
Le serveur borne également le nombre de relances successives (deux par défaut) :
du bruit ambiant ne peut pas maintenir la conversation ouverte indéfiniment.
La commande « Hey Jarvis, mets-toi en veille » ferme explicitement cette fenêtre :
les paroles ordinaires sont alors ignorées jusqu'au prochain « Hey Jarvis ». Elle
annule également toute confirmation sensible encore en attente.

## Multi-pièces

Chaque satellite a une `piece` (config `satellites[].piece`) injectée dans le
contexte du LLM : « allume la lumière » depuis le satellite **cuisine** cible la
**cuisine** par défaut, sans que tu aies à le préciser.

Si le micro principal et un satellite entendent le même « Hey Jarvis », ils
comparent pendant une très courte fenêtre leur score openWakeWord. Seul le meilleur
score poursuit la capture ; l'autre ne bipe pas et ne répond pas. Les multiplicateurs
`assistant.priorite_micro` et `satellites[].priorite_micro` permettent un ajustement
si deux matériels ont des gains très différents.

## Wake word — deux modes (config `satellites[].wake`)

- `appareil` *(recommandé)* : le satellite détecte « Hey Jarvis » **lui-même**,
  puis n'envoie QUE l'énoncé (moins de trafic, plus rapide). C'est le mode du
  client de test et du futur ESP32-S3-BOX-3.
- `serveur` : valeur réservée au futur client à flux continu. Le client
  Raspberry/Linux fourni utilise actuellement `appareil`; ne pas sélectionner ce
  mode en pensant qu'il active déjà la détection distante.

## Sécurité

- **LAN ou tailnet privé uniquement** : jamais exposé via ngrok (la garde
  X-Forwarded rejette le trafic tunnelisé). Les adresses Tailscale
  `100.64.0.0/10` sont acceptées, mais le port doit rester filtré par le pare-feu
  et les règles du tailnet. Le serveur principal reste sur `127.0.0.1:8790`. Lorsqu'un
  satellite est configuré, un listener dédié `0.0.0.0:8791` est lancé avec
  **uniquement** `/satellite` ; panneau, cockpit, inbox et Twilio n'y existent pas.
- **Token par satellite** (`satellites[].token`), comparé en **timing-safe**.
- **Droits = commande vocale à la maison** : N1 direct ; N2 demande une
  confirmation qui peut être mémorisée ; **N3 (mail, appel, extinction…) exige une
  CONFIRMATION vocale à chaque fois**. Le serveur passe en
  `attente_confirmation` et attend un « oui » dans l'énoncé suivant.

## Tester sans matériel

Jarvis lancé + un satellite `test` en config :
```yaml
satellites:
  - id: "test"
    piece: "bureau"
    token: "<python -c \"import secrets;print(secrets.token_urlsafe(24))\">"
```
Puis :
```bash
uv run python scripts/satellite_test.py --texte "quelle heure est-il"
```
Le script simule un boîtier : il envoie l'audio, affiche les états + la
transcription + la réponse, enregistre l'audio de réponse dans
`logs/_sat_test_reponse.wav`, et mesure la latence.

## Mode autonome (prévu — pas encore implémenté)

Objectif futur : quand le **PC est éteint**, un satellite compatible pourrait
assurer un petit sous-ensemble de domotique locale et demander le réveil du serveur
par un mécanisme adapté au matériel (cf. [wol.md](wol.md)).

Rien dans l'architecture actuelle ne le rend impossible :
- le dispatch est **isolé** (`core/satellite.traiter_texte`) — réutilisable côté Pi ;
- le protocole prévoit déjà les états et la confirmation ;
- la détection d'indisponibilité se ferait **côté satellite**, avec bascule sur un
  mini-cerveau local et réveil optionnel du serveur. À implémenter plus tard.
