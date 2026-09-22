# 🔐 Identifiants Google — créer `google_credentials.json` proprement

Un seul fichier d'identifiants sert à **tout** le Google de Jarvis : Gmail,
Agenda, et ce que tu ajouteras ensuite. Ce guide explique comment le créer, et
surtout **ce qui protège réellement ton compte** — parce que le fichier que tu
vas télécharger n'est pas ce que tu crois.

---

## Le malentendu à lever d'abord

`google_credentials.json` contient un `client_id` et un `client_secret`. Malgré
son nom, **ce n'est pas un secret** pour une application de bureau. Google le
documente explicitement : une app installée sur la machine de l'utilisateur ne
peut pas garder un secret, puisqu'il est dans le binaire.

Ce que quelqu'un peut faire avec ton `google_credentials.json` :
- lancer *sa propre* demande de consentement, sur *son* compte à lui,
- voir le nom de ton projet Google Cloud.

Ce qu'il **ne peut pas** faire : lire tes mails, voir ton agenda, agir en ton
nom. Il lui faudrait que **toi** cliques « Autoriser » dans ton navigateur.

### Le vrai secret, c'est le jeton

| Fichier | Contenu | Gravité si fuite |
|---|---|---|
| `google_credentials.json` | identité de l'app | faible — inutilisable seul |
| **`google_token_mail.json`** | **jeton de rafraîchissement** | **critique — accès à ta boîte** |
| **`google_token.json`** | idem pour l'Agenda | **critique** |

Jarvis les écrit en **0600** (illisibles par les autres comptes de la machine) et
ils sont dans `.gitignore`. C'est eux qu'il faut protéger, sauvegarder avec soin,
et révoquer en cas de doute.

**Révoquer immédiatement :** [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
→ ton app → Supprimer l'accès. Les jetons deviennent inutilisables sur-le-champ.

---

## Créer les identifiants

### 1. Le projet

[console.cloud.google.com](https://console.cloud.google.com/) → sélecteur de
projet → **Nouveau projet**.

**Choix important pour l'isolation.** Connecté avec un compte Workspace, Google
place **d'office** le projet dans l'organisation du domaine : l'option « Aucune
organisation » n'apparaît pas, et ce n'est pas un réglage que tu peux changer.

Deux voies, selon ce dont tu veux te protéger.

### Voie 1 — rester dans l'organisation (le cas normal)

Qui verra le projet ?

| Qui | Voit le projet ? |
|---|---|
| Les utilisateurs normaux du domaine | **non** — il faut un rôle IAM explicite |
| Toi (créateur, donc Propriétaire) | oui |
| Un **super-administrateur** du domaine | **s'il le décide** — il peut s'attribuer le rôle d'administrateur d'organisation dans Cloud |

Si tu es le seul admin de ton domaine, cette voie est parfaitement sûre : tes
collaborateurs ne verront rien. Et rappel : même en voyant le projet, on ne peut
pas lire tes mails sans que tu aies cliqué « Autoriser ».

### Voie 2 — projet hors du domaine (isolation réelle)

Crée le projet depuis un **compte Google personnel** (`@gmail.com`), puis
autorise-le avec ton adresse Workspace :

1. Déconnecte-toi, ou ouvre la console en navigation privée avec ton compte perso.
2. Crée le projet là-bas — il n'appartiendra à aucune organisation.
3. Écran de consentement : type **Externe**, et ajoute **ton adresse Workspace**
   (`toi@ton-domaine.fr`) comme **utilisateur test**.
4. Crée le client « Application de bureau », télécharge le JSON.
5. Lance `scripts/google_login.py` et connecte-toi avec ton compte **Workspace**.

Le client OAuth vit alors dans un projet que **personne du domaine ne peut
voir**, et il accède quand même à ta boîte Workspace — parce que c'est toi qui
consens.

Seule réserve : si l'administrateur du domaine a restreint l'accès des
applications tierces (Console d'admin → Sécurité → Contrôle des API), il faudra
approuver ton ID client. Si tu es cet administrateur, c'est deux clics.

Nomme le projet clairement (« Jarvis perso »), ça t'évitera de le confondre.

### 2. Activer les API

**API et services → Bibliothèque**, puis active seulement ce dont tu as besoin :

- **Gmail API** — pour lire/envoyer les mails
- **Google Calendar API** — pour l'agenda

N'active rien d'autre : une API désactivée est une API qui ne peut pas être
utilisée, même avec un jeton valide.

### 3. L'écran de consentement

**API et services → Écran de consentement OAuth**.

| Type | Qui peut autoriser | Jetons | Pour toi |
|---|---|---|---|
| **Interne** | uniquement les comptes de ton Workspace | **permanents** | ✅ à prendre si le projet est dans l'organisation |
| **Externe** + Test | seulement les utilisateurs test déclarés | **expirent en 7 jours** | seulement en voie 2 |

**Le détail qui change tout :** une application **Externe** laissée en statut
« Test » voit ses **jetons de rafraîchissement expirer au bout de 7 jours**.
Concrètement, tu devrais relancer `google_login.py` toutes les semaines. Une
application **Interne** n'a pas cette limite — c'est la raison principale de
préférer la voie 1 quand elle est possible.

En **Externe**, va dans **Utilisateurs test** et n'ajoute **que ton adresse** ;
ne clique **pas** sur « Publier l'application » (cela déclencherait une
procédure de vérification Google, longue, pour un scope Gmail).

### 4. Le client OAuth

**Identifiants → Créer des identifiants → ID client OAuth →
Type : Application de bureau**.

Télécharge le JSON, place-le à la racine du projet sous le nom exact :

```
google_credentials.json
```

### 5. Autoriser Jarvis

```bash
uv run python scripts/google_login.py mail agenda
```

Un navigateur s'ouvre, une fois par usage. Les jetons sont écrits à côté.

```yaml
# config.yaml
mail:
  adresse: "toi@ton-domaine.fr"
  oauth: true
```

---

## Restreindre l'accès au projet Cloud

Même si le client OAuth n'est pas exploitable seul, autant limiter qui le voit.

**IAM et administration → IAM** : tu dois être le seul **Propriétaire**. Retire
tout compte que tu n'as pas mis là toi-même, et vérifie la case « Inclure les
attributions de rôles fournies par Google » pour voir les accès hérités.

Sur un projet créé dans une organisation, un super-administrateur du domaine
peut toujours s'attribuer un accès au niveau de l'organisation. Ça ne se
désactive pas depuis le projet — c'est une propriété de Workspace. Si c'est ton
souci, prends la **voie 2** ci-dessus.

**Ne crée jamais de clé de compte de service** pour cet usage. Une clé de compte
de service, elle, est un vrai secret exploitable sans consentement — et avec la
délégation à l'échelle du domaine, elle peut lire les boîtes de **tout** le
Workspace. Jarvis n'en a pas besoin et n'en utilise pas.

---

## Si tu es administrateur du domaine

Workspace peut bloquer les applications OAuth tierces, y compris les tiennes.
Console d'admin → **Sécurité → Contrôle des API → Gérer l'accès des applications
tierces** :

- Soit tu laisses « Autoriser » par défaut,
- soit tu ajoutes **ton ID client** comme application **approuvée** — et tu
  peux même restreindre l'accès aux seules API que tu as activées.

---

## Le point honnête sur le modèle de menace

Si ta crainte est « qu'un autre administrateur du Workspace récupère l'accès à
mes données », **la configuration OAuth n'y change rien**. Un super-administrateur
Google Workspace peut réinitialiser ton mot de passe et entrer dans ton compte,
indépendamment de Jarvis. C'est le fonctionnement de Workspace.

Ce que ce guide protège réellement, et qui compte :

- ✅ un **fichier fuité sur GitHub** ne donne rien d'exploitable
- ✅ un **autre utilisateur de ce Mac** ne peut pas lire tes jetons (0600)
- ✅ **personne d'autre que toi** ne peut passer l'écran de consentement
- ✅ les permissions sont **minimales** (deux API, pas plus)
- ✅ tu peux **tout révoquer** en un clic

Si tu veux une isolation réelle vis-à-vis des admins du domaine, la seule voie
est un **compte Google personnel** séparé, hors du Workspace.
