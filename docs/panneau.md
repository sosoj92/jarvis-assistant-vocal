# Panneau de configuration web (local)

Un tableau de bord **servi par le serveur web unifié** de Jarvis, mais
**accessible uniquement en local** : un garde rejette toute requête arrivant par
le tunnel ngrok (en-tête `X-Forwarded-For`, ou `Host` ≠ localhost). Le panneau ne
passe donc **jamais** par Internet, même si le même port sert le pont iPhone.

Ouvre-le dans un navigateur **sur la machine de Jarvis** :

```
http://localhost:8790/panneau
```

Le **HUD/orbe** (`http://127.0.0.1:8770`) possède aussi un bouton **⚙ Config**
en haut à droite. Son tiroir permet les bascules du quotidien sans quitter le
visage de Jarvis :

- mode `local` / `hybride` / `qualité` ;
- fournisseur et modèle cloud (OpenAI ou Anthropic), avec profils hybride et
  qualité ;
- modèle Ollama déjà installé ;
- moteur TTS, voix et modèle ElevenLabs, avec bouton de test.

Ces changements prennent effet dès la réponse suivante. Le panneau complet
reste l'endroit où installer, tester ou supprimer les modèles et modifier les
réglages avancés. Le HUD ne reçoit jamais les clés API : il ne voit que leur
état « configurée / absente » et les noms des modèles/voix disponibles.

**À la voix** : « **ouvre le tableau de configuration** » (ou « tableau de bord »,
« ouvre le panneau ») → l'outil `ouvrir_panneau` (N1, local, non exposé au MCP)
lance le navigateur sur cette page. Si le serveur n'est pas démarré, Jarvis le dit.

**Doctrine** : c'est du **Jarvis pur** (config locale). Il *affiche* l'état
d'Hermes mais ne lui donne **aucun droit nouveau**. Il n'écrit que ce qui est sans
danger (choix de modèle, modèle d'Hermes) — **jamais une règle de sécurité**.

## 1. Page Modèles (la pièce maîtresse)

- **Matériel** : GPU, VRAM totale et *exploitable* (total − marge pour l'OS +
  Whisper CPU), via la même logique que `scripts/doctor.py` (pynvml).
- **Modèles LLM locaux (Ollama)** : un **catalogue recommandé** avec des badges
  par modèle — *tient en VRAM* (mémoire requise vs exploitable), *tool calling*,
  *français*, *licence*, *taille* — plus la liste de tes modèles déjà installés.
  Boutons : **Installer** (`ollama pull`, avec barre de progression), **Tester**
  (mini-benchmark : latence + un appel d'outil factice + une phrase en français),
  **Supprimer**, **Activer**.
- **Modèles Whisper** (tiny → large-v3-turbo) : reco + badge *français fiable* ;
  installer / activer / supprimer. Le panneau effectue ses tests sur **CPU** pour
  rester portable ; le moteur principal choisit CPU ou CUDA selon l'environnement.
- **Modèles cloud OpenAI** : catalogue `gpt-5.6-luna/terra/sol` et
  `gpt-6-astra`, tarifs, vision, appels d'outils et vérification de l'accès réel
  via la clé API locale.
- Le profil **hybride** mémorise son propre modèle quotidien (`luna` par défaut
  chez OpenAI, `haiku` chez Claude), séparément du modèle du profil qualité.
- **Modèle actif par backend** : local (Ollama), cloud (OpenAI ou Anthropic),
  Whisper et **Hermes**. Le LLM cloud/local change au tour suivant ;
  Whisper demande encore un redémarrage.

## 2. Page Réglages (voix, audio, mot d'activation)

Les réglages du quotidien, écrits dans `config.yaml` (**redémarre Jarvis** pour les
appliquer). Écriture **whitelistée** : seules ces clés sont modifiables depuis le
panneau — jamais une clé/secret (`_CLES_REGLABLES` dans `core/panneau.py`).

- **Mode de routage** : `local`, `hybride` ou `qualite`. Le changement est
  immédiat et réinitialise proprement les providers LLM/TTS.
- **Audio** : **micro** (`audio.micro`) et **haut-parleur** (`audio.haut_parleur`,
  « défaut » = sortie Windows) — listés en direct via `sounddevice.query_devices()`.
- **Moteur vocal** : `Auto`, `ElevenLabs`, `Piper`, `Kokoro` ou `Windows`, liste
  des voix du compte ElevenLabs et bouton de test. La clé n'est jamais envoyée au
  navigateur. En mode local, un moteur cloud est toujours remplacé par un moteur local.
- **Voix & écoute** : **personnalité** (`assistant.personnalite`) et **durée
  d'écoute enchaînée** (`assistant.duree_suite`, secondes où Jarvis continue
  d'écouter après une réponse sans redire le mot d'activation).
- **Mot d'activation** : la phrase est fixe (« Hey Jarvis », modèle openWakeWord
  embarqué) ; **sensibilité** réglable (`assistant.seuil_reveil` : bas = déclenche
  facilement, haut = strict).

## 3. Page État (le `status-hermes.ps1` en visuel)

La chaîne complète **UP / DOWN** : serveur Jarvis, serveur MCP, tunnel ngrok,
gateway Hermes, Docker, et la **connexion MCP Hermes → Jarvis**. Bouton
**Reconnecter MCP** = le remède du « parking » (`hermes mcp remove/add jarvis`).

> Le tunnel est **lu**, jamais rouvert (sinon ngrok refuse « endpoint already
> online »).

### Budget par fournisseur (N9)

- **Jarvis (mesuré)** : chaque appel OpenAI/Claude est instrumenté (`core/budget.py`) →
  tokens (in/out, cache compris) + **coût estimé** via la table de prix
  `budget.prix` (config). Résumé **du jour** et **du mois**, persistant dans
  `budget.json` (non versionné). Redémarre Jarvis pour activer le comptage.
- **Twilio** : le compteur mensuel existant (`logs/calls/compteur.json`).
- **Hermes** : tokens (jour / 30 j) lus via `hermes insights` — Hermes tient sa
  propre comptabilité, Jarvis ne la double pas.

### Activité Hermes (N9)

Crons planifiés (nom, planning, prochaine exécution), derniers runs de cron, et
tâches kanban en cours — via le CLI `hermes` (`cron list` / `cron runs` /
`kanban list`). *(Les commandes sont lancées en UTF-8 : la sortie d'Hermes
contient cadres et emoji.)*

## 4. Page Permissions (niveaux N1/N2/N3 — N8)

Une seule vue = tout le **périmètre de sécurité**, avec le **niveau de permission**
de chaque outil :

| Niveau | Sens | Confirmation | « toujours autoriser » | À distance (iPhone) |
|---|---|---|---|---|
| **N1** sûr | domotique, PC, lectures | non | — | **oui** |
| **N2** sensible | actions réversibles | oui | **mémorisable** (révocable ici) | non |
| **N3** critique 🔒 | mail, appels, réservations, suppressions | **toujours** | **jamais** | jamais |

- **Mémoriser un N2** : à la voix, réponds **« oui, toujours »** à la demande de
  confirmation → l'outil passe en « toujours autorisé » **en local** (stocké dans
  `config.yaml → securite.toujours`). La page l'affiche avec un bouton **Révoquer**.
- **N3** : confirmation à chaque fois, « toujours » refusé, jamais à distance —
  **verrouillé dans le code** (`core/registre.py → _N3`).
- Le **« toujours autoriser » n'ouvre RIEN à distance** : le pont iPhone teste
  `confirmation` en direct, il ne consulte jamais le store.

La page montre aussi l'**accès fichiers d'Hermes** (montages Docker : `/vault` ro,
`/scripts` ro, `/scripts/drafts` rw).

## Sécurité

- **Local only** : garde sur chaque route (`X-Forwarded-For` / `Host`).
- **Écriture limitée** au sans-danger : sélection de modèle, **révocation d'une
  autorisation « toujours »**, reconnexion MCP. Jamais les règles N3.
- Rien de nouveau n'est accordé à Hermes : le panneau **observe** sa config.
