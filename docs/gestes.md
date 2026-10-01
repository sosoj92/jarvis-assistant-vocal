# Contrôle par gestes de la main (webcam)

Piloter Jarvis d'un geste, en **temps réel** et **100 % en local**. Pensé pour être
**fiable** (petit vocabulaire de gestes tenus) et **respectueux de la vie privée**
(aucune image ne quitte jamais la machine, ni même le sous-process de tracking).

> **Doctrine — Jarvis pur (physique, temps réel).** Aucun rôle pour Hermes ici.
> Les gestes ne déclenchent que des actions **N1/N2** ; **jamais** de N3 (pas
> d'extinction, d'appel, de réservation par geste.

## Pourquoi un sous-process séparé (Python 3.11)

MediaPipe n'a **pas de wheel Python 3.13** (Jarvis tourne en 3.13). Le tracking
tourne donc dans un **venv isolé Python 3.11** (`gestes/.venv-tracker`). C'est aussi
la **frontière vie privée** : ce process est le **seul** à voir l'image ; il n'en
sort que des *labels de gestes* (`"poing"`, `"mode_fenetres"`…), envoyés à Jarvis
en **loopback** local. Bonus : process séparé = **il ne vole rien à Whisper** (CPU
ordonnancé par l'OS).

```
Webcam USB → [sous-process 3.11 : OpenCV + MediaPipe HandLandmarker + FSM anti-faux-positif]
               └─ POST http://127.0.0.1:8790/api/gestes  {geste: "poing"}   (loopback + token)
Jarvis (3.13) : core/gestes.py → mappe → action N1/N2 → feedback (bip + flash HUD)
```

## Installation

```bash
python scripts/setup_gestes.py
```

Crée le venv 3.11, installe `mediapipe`/`opencv-python`/`requests`, télécharge le
modèle `hand_landmarker.task` (~8 Mo). **Une webcam USB** est requise (pas une caméra
IP : latence rédhibitoire).

Puis, à la voix : **« Jarvis, active les gestes »** / **« coupe les gestes »**, ou
`gestes.actif: true` dans `config.yaml`, ou le **raccourci clavier** (défaut
`Ctrl+Alt+G`).

La calibration peut elle aussi être ouverte à la voix : **« Jarvis, lance la
calibration des gestes »**. Jarvis libère d'abord la webcam si le tracker normal
est actif, puis ouvre la fenêtre locale. Cet outil n'est exposé ni à MCP ni à
Hermes.

## Le vocabulaire (v2) et le mapping par défaut

Des gestes **tenus** (pas d'instantané) pour éviter les faux positifs :

| Geste | Action par défaut |
|---|---|
| **Main ouverte immobile, 5 doigts** tenue | Pause (touche média lecture/pause) |
| **Pouce levé** tenu | Lecture/reprise (touche média lecture/pause) |
| **Poing** tenu | Coupe le TTS hors mode ; dans Onglets/Audio, repositionne la main sans action |
| **2 doigts** tenus | Arme le mode **Onglets** |
| **3 doigts** tenus | Arme le mode **Audio** |
| **Index seul** tenu | Arme le mode **Souris** et pilote le pointeur |
| **Deux mains ouvertes, 5 doigts chacune** | Écarter = zoom avant ; rapprocher = zoom arrière |

Chaque geste reconnu = **feedback discret** (petit bip + flash HUD) pour savoir que
c'est pris. Le mapping est **entièrement éditable** dans `config.yaml → gestes.mapping`.

### Mode Onglets — 2 doigts

- tiens index + majeur environ 1 seconde → overlay `🗂 Mode onglets` ;
- passe à la main entière ouverte et garde-la brièvement immobile ; une perte
  momentanée du pouce par la caméra n'active jamais la souris dans ce mode ;
- clique d'abord dans le navigateur ou l'application à piloter ;
- déplace légèrement la paume à gauche/droite → onglet ou vue précédente/suivante de cette application
  (`Ctrl+Shift+Tab` / `Ctrl+Tab`) ;
- monte/descends progressivement la paume → défilement continu de la fenêtre
  active (`Page Up` / `Page Down`) ;
- arrête simplement la main pour mettre le mouvement en pause : le mode reste actif ;
- ferme le poing pour ramener la main au centre sans aucune action, puis rouvre-la
  et continue depuis cette nouvelle position ;
- chaque petit déplacement validé devient immédiatement le départ du suivant :
  enchaîne dans n'importe quelle direction sans restabiliser ni refaire les 2 doigts.

Le nom interne `mode_fenetres` est conservé pour la compatibilité des anciennes
calibrations. Les applications sans onglets peuvent ignorer `Ctrl+Tab`, mais Jarvis
ne quitte plus l'application active. Pour retrouver l'ancien changement entre
applications, règle `gestes.navigation_horizontale: applications`.

### Mode Audio — 3 doigts

- tiens index + majeur + annulaire environ 1 seconde → overlay `🔊 Mode audio` ;
- passe à la main entière ouverte et garde-la brièvement immobile ; une perte
  momentanée du pouce par la caméra n'active jamais la souris dans ce mode ;
- petits déplacements haut/bas → volume +/− ;
- petits déplacements gauche/droite → piste précédente/suivante ;
- le poing permet là aussi de recentrer la main sans couper le mode ni agir.

Le pouce levé ne confirme **jamais** une action N3 : il sert uniquement à la
lecture média. Une extinction, un appel ou une réservation reste soumis à la
confirmation vocale locale.

### Zoom à deux mains

- présente deux paumes entièrement ouvertes et stabilise-les brièvement ;
- écarte-les pour zoomer, rapproche-les pour dézoomer ;
- garde-les visibles : continue le mouvement pour plusieurs crans ou inverse-le
  directement pour changer le sens du zoom.

Le zoom envoie `Ctrl+=` ou `Ctrl+-` à l'application active. Il fonctionne donc
dans les navigateurs, les lecteurs PDF et la plupart des applications qui
utilisent ces raccourcis. Aucun mode à un doigt n'est déclenché tant que deux
mains sont visibles.

### Mode Souris — index seul

- tiens seulement l'index immobile jusqu'à voir `🖱 Mode souris` ;
- déplace ensuite ce même index pour piloter le curseur ;
- écarte d'abord le pouce, puis pince pouce-index pour cliquer si le clic est actif ;
- tiens le poing pour quitter immédiatement, ou retire la main du cadre.

Le pointeur reste strictement local. Aucune image ne sort du tracker : seul un
couple `(x,y)` normalisé est envoyé sur le loopback authentifié. Par sécurité, le
clic est désactivé dans la configuration publique (`souris_clic: false`) ; la
calibration locale permet de l'activer avec `p`, puis de sauvegarder avec `s`.

## Anti-faux-positifs (le vrai défi)

- **Gestes statiques tenus** : une pose accidentelle d'une seule image ne suffit pas.
- **Modes explicites** : aucun swipe n'agit sans 2 ou 3 doigts tenus au préalable.
- **Transition stabilisée** après la sélection : passer directement à la paume
  ouverte suffit ; sortir la main du cadre reste accepté.
- **Enchaînement continu** : chaque petit pas horizontal ou vertical produit une
  action et devient la nouvelle origine. Une main immobile ne produit rien.
- **Repositionnement au poing** : fermer la main désaccouple temporairement le
  mouvement ; on peut revenir au centre, rouvrir la paume et reprendre sans
  déclencher l'action opposée ni quitter le mode.
- **Sortie explicite** : le mode reste actif tant que la main demeure visible ;
  les pertes momentanées de suivi sont ignorées. Il se ferme après trois secondes
  réellement hors du cadre. Dans un mode continu, le poing sert uniquement au
  repositionnement neutre et ne ferme plus le mode.
- **Stabilisation contextuelle** : après l'armement Onglets/Audio, trois doigts
  longs visibles suffisent et ne peuvent plus lancer la souris. La main doit rester presque immobile pendant
  `swipe_pret_s` (0,35 s par défaut). Le changement de pose ou le trajet d'entrée
  dans le cadre ne peut donc plus être interprété comme un swipe.
- **Déplacement minimal + axe dominant** : un mouvement diagonal ambigu est ignoré.
- **Cooldown** entre deux commandes côté tracker et côté Jarvis.

## Calibration (à l'arrivée de la webcam)

```bash
python scripts/gestes_calibrer.py
```

Affiche la caméra + les landmarks, la pose et le mode en direct. Réglages :
`t/T` maintien −/+, `c/C` cooldown −/+, `w/W` pas horizontal −/+,
`v/V` pas vertical −/+, `z/Z` seuil du zoom avant −/+, `r/R` seuil du zoom
arrière −/+, `x/X` temps de stabilisation du zoom −/+, `i` inverse haut/bas,
`p` active/coupe le clic par pincement, `k/K` règle son seuil, `s` sauvegarde vers
`gestes/calibration.json`, `q`
quitte. Le fichier sauvegardé est rechargé à la prochaine ouverture. **Aucune
image n'est enregistrée** pendant la calibration.

### Mode visio : gestes de la main visibles

Dis « passe en mode visio », « ouvre la démo des gestes » ou « lance les gestes
visibles pour ma vidéo », ou utilise `Ctrl+Alt+D`. La fenêtre montre les points,
la pose et l'historique, et les gestes reconnus agissent réellement sur Windows. Le bandeau
`MODE DEMO : ACTIONS PC ACTIVES` évite toute ambiguïté. `Q` ferme la démo et
« quitte le mode visio », `Ctrl+Alt+G` ou « coupe les gestes » coupe le tracker.

Si le périphérique choisi est une caméra virtuelle fournie par Logitech Capture,
active `gestes.camera_app.actif`. Jarvis ouvre alors Logitech Capture, attend que
sa caméra virtuelle soit disponible, puis lance la démo. À la fermeture du mode,
il ne ferme Logitech Capture que s'il l'avait lui-même démarré. Le chemin peut
rester vide sous Windows pour profiter de la détection automatique.

### Mode regard : contrôle avec les yeux

Dis « passe en mode regard » ou « active le contrôle avec les yeux », ou utilise
`Ctrl+Alt+R`. Jarvis ferme d'abord le tracker des mains s'il est actif, puis ouvre
la calibration locale du regard. Après la calibration, les yeux déplacent le
pointeur et le clic gauche par haussement tenu des deux sourcils est immédiatement
actif. `C` permet encore de couper ou réactiver les clics manuellement. Dis
« quitte le mode regard » ou utilise de nouveau `Ctrl+Alt+R` pour arrêter le suivi.

## Caméra : cycle de vie & cohabitation

- **On/off mains** : à la voix (`controler_gestes`), au raccourci clavier, ou `gestes.actif`.
- **On/off regard** : « passe/quitte le mode regard » ou `Ctrl+Alt+R`. Le regard et les mains sont
  mutuellement exclusifs puisqu'ils partagent la même webcam.
  À l'arrêt de Jarvis, la webcam est **libérée** (`atexit`).
- **Choix du périphérique** : `gestes.device` (0 = première webcam USB).
- **Statut** : `GET http://127.0.0.1:8790/api/gestes/status` → `{actif}` (repris dans
  `hermes-workspace/status-hermes.ps1` : *Tracker de gestes : UP/DOWN*).
- **Cohabitation stream** : si OBS occupe déjà la webcam physique, sélectionne une
  autre `device`, ou utilise la **caméra virtuelle OBS** comme source des gestes.
  L'ancien mapping contextuel OBS reste compatible s'il est conservé manuellement,
  mais il n'est plus le mapping v2 par défaut.
- **Indicateur** : la LED de la webcam s'allume quand la caméra est active — jamais
  de capture à ton insu.

## 🔒 Vie privée (une caméra chez soi = sujet sérieux)

- **Traitement 100 % local.** Aucune image n'est **stockée**, **loggée** ni
  **transmise**. Seules des **coordonnées de landmarks** existent en mémoire du
  sous-process, et elles ne sont **même pas écrites dans les logs**.
- Ce qui traverse vers Jarvis : un **label de geste** et, seulement en mode
  souris, la position normalisée du pointeur. Jamais une image ni les landmarks.
- La caméra n'est **JAMAIS** exposée en **MCP** ni accessible à **Hermes**
  (`controler_gestes` est `mcp_expose=False`).
- L'endpoint `/api/gestes` est **loopback + token** : un process local malveillant ne
  peut pas injecter de faux gestes sans le jeton (généré à chaque activation, connu du
  seul sous-process lancé par Jarvis).

## 🛡️ Sécurité — N1/N2 uniquement

Un geste ne peut déclencher qu'une action **sûre** (lumières, média, couper le TTS,
scènes OBS). Double garde-fou dans `core/gestes.py` :
1. Seules les actions d'une **liste blanche** (`_ACTIONS_SURES`) sont exécutables.
2. Toute action qui viserait un outil classé **N3** est **refusée** en amont
   (`_verifier_non_n3`). Impossible d'éteindre le PC, d'appeler ou de réserver d'un
   geste — même en modifiant le mapping.

## Configuration (`config.yaml → gestes`)

Voir `config.example.yaml` pour toutes les clés (device, fps, seuils, armement,
mapping, `pause_pendant_live`, `raccourci`). `gestes/calibration.json` (issu de la
calibration) **prime** sur `gestes.seuils`.
