# Satellites — Jarvis dans d'autres pièces

Un **satellite** est une extension du **corps** de Jarvis : oreilles + bouche +
visage déportés dans une autre pièce (Raspberry Pi aujourd'hui, ESP32 demain). Le
**cerveau reste sur le PC** — le satellite capte l'audio, le PC transcrit
(Whisper) → LLM + outils → TTS, et renvoie l'audio + des états pour l'écran.
Hermes n'est pas concerné.

Statut : **côté PC fait** (endpoint + protocole + multi-pièces + token + client de
test). Client Raspberry Pi : voir [satellite_pi.md](satellite_pi.md) *(à venir)*.

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
| *(trames binaires)* | Audio PCM capté, envoyé au fil de la parole. |
| `{"type":"fin_parole"}` | Fin de l'énoncé → le serveur transcrit et traite. |
| `{"type":"ping"}` | Keep-alive (réponse `pong`). |

### Serveur → client
| Message | Rôle |
|---|---|
| `{"type":"pret","piece":"cuisine"}` | Auth acceptée ; pièce du satellite. |
| `{"type":"etat","etat":"..."}` | État pour le visage/HUD : `veille`, `ecoute`, `reflexion`, `parole`, `attente_confirmation`. |
| `{"type":"transcription","texte":"..."}` | Ce que le serveur a entendu. |
| `{"type":"texte","texte":"..."}` | Texte de la réponse (affichage). |
| `{"type":"audio_debut","freq":24000}` | Début de l'audio de réponse (fréquence des trames binaires qui suivent). |
| *(trames binaires)* | Audio PCM de la réponse. |
| `{"type":"audio_fin"}` | Fin de l'audio. |
| `{"type":"erreur","message":"..."}` | Erreur. |

### Cycle type
`hello` → `pret` → *(binaire audio…)* → `fin_parole` → `etat:reflexion` →
`transcription` → `etat:parole` + `texte` + `audio_debut` + *(binaire…)* +
`audio_fin` → `etat:veille`.

## Multi-pièces

Chaque satellite a une `piece` (config `satellites[].piece`) injectée dans le
contexte du LLM : « allume la lumière » depuis le satellite **cuisine** cible la
**cuisine** par défaut, sans que tu aies à le préciser.

## Wake word — deux modes (config `satellites[].wake`)

- `appareil` *(recommandé)* : le satellite détecte « Hey Jarvis » **lui-même**,
  puis n'envoie QUE l'énoncé (moins de trafic, plus rapide). C'est le mode du
  client de test et du futur ESP32-S3-BOX-3.
- `serveur` : le satellite envoie un **flux continu**, le PC détecte le wake word
  avec l'openWakeWord existant. Plus de trafic ; utile si le satellite n'a pas de
  wake word embarqué.

## Sécurité

- **LAN uniquement** : jamais exposé via ngrok (la garde X-Forwarded rejette le
  trafic tunnelisé). Pour qu'un satellite du réseau atteigne le PC, mets
  `serveur.host: "0.0.0.0"` — les **gardes IP-socket** gardent panneau/cockpit en
  loopback, seul `/satellite` (authentifié) accepte le LAN.
- **Token par satellite** (`satellites[].token`), comparé en **timing-safe**.
- **Droits = commande vocale à la maison** : N1/N2 direct ; **N3 (mail, appel,
  extinction…) avec CONFIRMATION vocale sur le satellite** (le serveur passe en
  `attente_confirmation` et attend un « oui » dans l'énoncé suivant).

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

## Mode nuit (prévu — pas encore implémenté)

Objectif futur : quand le **PC est éteint**, un satellite **Raspberry Pi** assure
la **domotique en autonomie** (il a Python + réseau) et **réveille le PC** via la
prise **Tapo** (cf. [wol.md](wol.md)) quand une demande dépasse ses capacités.

Rien dans l'architecture actuelle ne le rend impossible :
- le dispatch est **isolé** (`core/satellite.traiter_texte`) — réutilisable côté Pi ;
- le protocole prévoit déjà les états et la confirmation ;
- la détection « PC injoignable » se ferait **côté Pi** (ping), avec bascule sur
  un mini-cerveau local (domotique seule) + réveil Tapo. À implémenter plus tard.
