# Pont iPhone (app Raccourcis)

Envoie tes **notes/idées** et des **commandes** à Jarvis depuis ton iPhone, où que tu
sois, via l'app **Raccourcis** d'iOS. Idéal pour capter une idée de contenu en
déplacement, ou piloter la maison à distance (« Dis Siri, Dis à Jarvis, mode film »).

## 1. Côté Jarvis (une fois)

1. Génère un **token secret** (une longue chaîne aléatoire). Par exemple :
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```
2. Dans `config.yaml` (le pont iPhone partage le **serveur web unifié** de Jarvis, le
   même qui sert le webhook Twilio des appels V2 — un seul port, un seul tunnel) :
   ```yaml
   serveur:
     actif: true
     port: 8790
     public_url: "https://ton-domaine-statique.ngrok.app"   # ton domaine ngrok statique

   pont_iphone:
     token: "colle-ton-token-ici"
   ```
3. **Expose ce port via ton domaine ngrok statique** (un seul tunnel sert TOUT :
   `/api/inbox`, le `/stream` de Twilio, et tes futures PWA) :
   ```bash
   ngrok http --domain=ton-domaine-statique.ngrok.app 8790
   ```
   L'URL de base de tes raccourcis sera `https://ton-domaine-statique.ngrok.app`.
4. Relance Jarvis. Au démarrage il affiche « Serveur web : port 8790… ».
   Teste : `https://ton-domaine.ngrok.app/api/ping` doit répondre `{"ok": true}`.

L'endpoint est **POST `/api/inbox`**, en-tête `X-Jarvis-Token: <ton token>`, corps JSON :
```json
{ "type": "note",     "contenu": "...", "categorie": "idees" }   // categorie optionnelle
{ "type": "commande", "contenu": "eteins les lumieres" }
```
La réponse est un JSON clair (`{"ok": true, "message": "..."}`) que le raccourci affiche.

## 2. Les raccourcis à créer (app Raccourcis)

Pour chacun : **+** (nouveau raccourci) → ajoute les actions ci-dessous. L'action clé
est **« Obtenir le contenu de l'URL »** (Get Contents of URL).

### 🅐 « Note à Jarvis » (dicter/taper une idée)

1. Action **« Demander une entrée »** (Ask for Input) → Type : Texte → invite :
   « Ton idée ? ». (Tu peux dicter au micro.)
2. Action **« Obtenir le contenu de l'URL »** :
   - URL : `https://ton-domaine.ngrok.app/api/inbox`
   - Méthode : **POST**
   - En-têtes : ajoute `X-Jarvis-Token` = `ton token`
   - Corps de la requête : **JSON** →
     `type` = `note` · `contenu` = *la variable « Entrée fournie »* · (`categorie` : laisse vide, Jarvis devine)
3. Action **« Afficher la note »** (Show Result) → *Message* de la réponse.

Renomme-le « Note à Jarvis ». Tu peux l'ajouter à l'écran d'accueil.

### 🅑 « Envoyer à Jarvis » (feuille de partage)

Même chose que 🅐, **mais** :
- Dans les réglages du raccourci (icône ⚙︎), active **« Afficher dans la feuille de
  partage »**, type d'entrée : Texte.
- Au lieu de « Demander une entrée », le `contenu` = la variable **« Entrée du
  raccourci »** (le texte partagé).

Ainsi : surligne un texte n'importe où (Safari, Notes, un message…) → **Partager** →
**« Envoyer à Jarvis »** → c'est noté.

### 🅒 « Dis à Jarvis » (commande à distance) — **2 modes**

Ce raccourci accepte la commande de **deux façons** : soit **dictée directement à Siri**
(« Dis à Jarvis, **mode film** » → « mode film » part tout de suite, sans invite), soit —
si tu le lances sans rien dire — via une **invite** classique. Le premier mode est le plus
naturel (mains libres) ; le second est le filet de sécurité.

**a) Configurer l'entrée Siri** (icône ⚙︎ du raccourci → *Détails*) :
- Active **« Recevoir »** → type **Texte** → depuis **Siri** (garde aussi la feuille de
  partage si tu veux). *(L'en-tête du raccourci affiche alors « Recevoir **Texte** de Siri
  et de la feuille de partage ».)* **C'est ça** qui fait arriver le texte dit **après** le
  nom du raccourci dans la variable **« Entrée du raccourci »**.

**b) Les actions**, dans l'ordre :
1. **« Si »** (If) → sujet **« Entrée du raccourci »** → condition **« a une valeur »**.
   - Dans le Si : **« Définir la variable »** → nom `commande` → valeur **« Entrée du
     raccourci »**.
2. **« Sinon »** (Otherwise) :
   - **« Demander une entrée »** (Ask for Input) → Type : Texte → invite « Ta commande ? »
     (dictée au micro possible).
   - **« Définir la variable »** → nom `commande` → valeur **« Entrée fournie »**.
3. **« Fin de si »**.
4. **« Obtenir le contenu de l'URL »** : URL `.../api/inbox` · **POST** · en-tête
   `X-Jarvis-Token` = ton token · Corps **JSON** : `type` = `commande` · `contenu` =
   la variable **`commande`**.
5. *(option)* **« Afficher la note »** → *Message* de la réponse. Utile en test ; **retire-la**
   pour un usage mains-libres 100 % vocal (sinon Siri lit la réponse mais attend un tap).

> **Pourquoi le Si/Sinon** : en entrée **directe** (Siri a passé le texte), on saute l'invite
> → réponse immédiate. En lancement **manuel** (tap sur l'icône, ou Siri n'a rien capté après
> le nom), l'invite prend le relais → **jamais** de commande vide postée.

La phrase (« éteins les lumières », « mode film ») est traitée par Jarvis à la maison
**comme du vocal**, mais — **doctrine du pont** — seuls les outils ouverts à distance
s'exécutent : les outils N1 exposés au MCP, plus ceux que tu listes dans
`pont_iphone.domotique_distante` (voir **🛡️ Sécurité** plus bas). Toute action critique
(mail, réservation, appel, suppression…) est **refusée** avec « à faire à la voix à la
maison ». **Jamais de « toujours autoriser » depuis le distant.**

**c) La formulation Siri la plus fiable**

Nomme le raccourci **exactement** « **Dis à Jarvis** », puis dis-le en **une seule phrase
continue**, le **nom d'abord**, la **commande ensuite** :
- ✅ « Dis Siri… **Dis à Jarvis, mode film** »
- ✅ « **Dis à Jarvis, éteins les lumières** »
- ✅ « **Dis à Jarvis, mets une ambiance cosy** »

Astuces fiabilité :
- **Micro-pause** (la virgule) après « Dis à Jarvis » : Siri sépare mieux le **nom** du
  raccourci de l'**argument**.
- **Évite** qu'un autre raccourci commence par « Dis à Jarvis… » : Siri prend le nom le plus
  long qui matche → ambiguïté.
- Si Siri lance le raccourci **sans** passer la commande (ça arrive selon l'humeur d'iOS),
  pas grave : le **repli invite** (b-2) te la redemande. Tu peux aussi dire « **Dis à Jarvis** »
  **seul** pour forcer l'invite.
- Règle **Siri en français** (Réglages → Siri et Rechercher → Langue) pour bien capter les
  accents.

### 🅓 « Inspiration Jarvis » (partager un reel → vault de contenu)

Pour capter une inspiration (Insta/TikTok) en 2 taps depuis la **feuille de partage**.

1. Réglages du raccourci (⚙︎) → active **« Afficher dans la feuille de partage »**,
   type d'entrée : **URL** (et Texte).
2. *(optionnel)* Action **« Demander une entrée »** → invite « Pourquoi ? (hook, format…) »
   → tu peux laisser vide.
3. Action **« Obtenir le contenu de l'URL »** :
   - URL : `https://ton-domaine.ngrok-free.dev/api/inbox`
   - Méthode : **POST** · En-têtes : `X-Jarvis-Token` = `ton token`
   - Corps **JSON** : `type` = `inspiration` · `url` = *variable « Entrée du raccourci »* ·
     `commentaire` = *la variable de l'étape 2 (ou vide)*
4. Action **« Afficher la note »** (facultatif) → *Message* de la réponse.

Nomme-le **« Inspiration Jarvis »**. Usage : sur un reel → **Partager** →
**« Inspiration Jarvis »** → (option) tape ton commentaire → c'est envoyé. Jarvis
télécharge, transcrit, indexe **en fond**, puis **t'annonce à voix haute** :
« Inspiration ajoutée au vault : *titre* — *auteur* ». (Détails : docs/hub_contenu.md.)

## 3. Ce que Jarvis fait

- **type `note`** → range la note dans le bon fichier (`idees.md`, `courses.md`,
  `taches.md`…), avec l'heure et la mention « via iPhone ». Jarvis choisit la
  catégorie si tu ne la donnes pas.
- **type `commande`** → traite la phrase comme si tu l'avais dite à voix haute.

Puis, à la maison, à la voix :
- « **Jarvis, sors-moi une idée de contenu** » → il pioche au hasard dans tes idées.
- « **Qu'est-ce que j'ai noté aujourd'hui ?** » → le résumé du jour.

## ⚠️ Antivirus qui bloque ngrok (Avast / AVG)

Certains antivirus (**Avast**, AVG…) **bloquent ngrok** : ils le classent comme
outil de tunneling. Symptômes : le tunnel ne s'ouvre pas et le log dit
`x509: certificate signed by unknown authority` (Avast présente un certificat
« *Untrusted Root* » exprès non valide), ou le **téléchargement** du binaire ngrok
est coupé. Ton domaine renvoie alors **404** (aucun agent connecté).

**Solution — ajoute une exception dans Avast** (2 min, à faire une fois) :

1. Ouvre Avast → **Menu (☰)** → **Paramètres**.
2. **Général → Exceptions → Ajouter une exception**, et ajoute ces URL (une par
   ligne) :
   ```
   connect.ngrok-agent.com
   *.ngrok-free.app
   *.ngrok.app
   *.ngrok.io
   bin.ngrok.com
   bin.equinox.io
   ```
3. (Si ça bloque encore) **Protection → Web Shield (Bouclier Web)** →
   vérifie l'**analyse HTTPS** et ajoute les mêmes URL en exception, **ou** ajoute
   le fichier `ngrok.exe` en exception de processus
   (`%LOCALAPPDATA%\ngrok\ngrok.exe`).
4. Relance Jarvis. Au démarrage il doit afficher « Tunnel ngrok ouvert : … » et
   `…/api/ping` répondre `{"ok": true}`.

> Le binaire ngrok est installé via `winget install Ngrok.Ngrok` (le
> téléchargement direct depuis bin.ngrok.com est souvent coupé par l'antivirus).

**Alternative si tu ne veux pas toucher à Avast** : lance le tunnel toi-même dans
une console où l'antivirus laisse passer, et renseigne `serveur.public_url`
(mode manuel B ci-dessus) — mais l'agent ngrok subit le même blocage, donc
l'exception Avast reste la voie fiable.

## ⚠️ « La connexion réseau a été perdue » (erreur -1005 iOS)

Si un raccourci renvoie **« La connexion réseau a été perdue »** alors que
`/api/ping` répond depuis **Safari** et qu'**un autre raccourci** (ex. « Inspiration
Jarvis ») marche vers la **même** URL : le problème n'est **ni le réseau, ni ngrok,
ni le serveur** — c'est **le raccourci lui-même**. Cause quasi certaine : une **URL
abîmée par l'autocorrection iOS** (majuscule sur « Https », espace ou caractère
invisible collé, `.app` au lieu de `.dev`…). Saisir l'URL à la main dans « Obtenir
le contenu de l'URL » est le piège classique.

**Diagnostic express :**
- **Safari** sur l'iPhone → `…/api/ping` répond `{"ok":true}` ? → réseau/ngrok OK.
- Change **seulement l'URL** du raccourci par `https://postman-echo.com/post` et
  lance : tu récupères un gros JSON ? → Raccourcis sait poster, donc c'est bien
  l'URL/config ngrok **du raccourci** qui est en cause (pas iOS, pas le réseau).
- `logs/inbox.log` reste vide (aucun `ua='…CFNetwork…'`) → la requête n'atteint
  jamais le serveur. Côté PC, l'**inspecteur ngrok** (`http://127.0.0.1:4041`)
  logge **toute** requête atteignant le tunnel : pratique pour savoir si le POST
  meurt avant ngrok ou après.

**La solution qui marche à tous les coups : ne pas déboguer le raccourci cassé, le
refaire depuis un raccourci QUI MARCHE.** Duplique « Inspiration Jarvis » → renomme
→ **ne touche NI à l'URL, NI à la Méthode, NI aux En-têtes** → change seulement le
**Corps JSON** (`type`, champs). L'URL éprouvée est héritée telle quelle, sans
risque de faute de frappe. C'est ainsi que « Note à Jarvis » a été réparé.

## 🛡️ Sécurité (important)

Une **commande à distance** ne peut déclencher que deux familles d'outils :

- les outils **N1 exposés au MCP** (sans confirmation) : par exemple les minuteurs,
  l'arrêt d'un enregistrement OBS, les statistiques et le budget en lecture, la
  recherche dans tes inspirations, mais aussi la **génération d'idées de contenu par
  Hermes** (délégation qui coûte des tokens) et l'**ingestion d'une vidéo YouTube**
  (téléchargement et transcription sur la machine de Jarvis) ;
- les outils que tu listes toi-même dans `pont_iphone.domotique_distante` (lumières,
  scènes…). Ils s'exécutent **sans confirmation** depuis l'iPhone : un outil N2 placé
  dans cette liste **perd sa confirmation à distance**. N'y mets que des actions
  physiques réversibles. Un N3 y reste toujours refusé.

```yaml
pont_iphone:
  token: "colle-ton-token-ici"
  domotique_distante: []      # ex. [allumer_lumiere, regler_luminosite] ; vide par défaut
```

Toute action critique (N3 : mail, réservation, appel, suppression, extinction…) est
**refusée** avec « à faire à la voix à la maison », quel que soit ce réglage. Après la
lecture d'un **contenu externe** (par exemple une inspiration sauvegardée), son texte
est balisé comme donnée non fiable et toute action autre qu'une simple lecture est
refusée dans la même commande. Le nombre d'appels d'outils par commande est plafonné
(`assistant.max_appels_outils`, 12 par défaut).

Ce que permet donc un **token volé** : tout ce qui précède, y compris des coûts
(appels au modèle, délégation à Hermes), l'ajout de notes et l'envoi d'inspirations à
télécharger et indexer. Mais ni mail, ni appel, ni réservation, ni suppression. Garde
ton token secret, et régénère-le au moindre doute. L'onglet **Permissions** du panneau
local affiche la liste `domotique_distante` en vigueur.
