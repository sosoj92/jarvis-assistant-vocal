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

**Choix important pour l'isolation :** au moment de créer le projet, le champ
**Organisation** détermine qui pourra le voir.

- **Organisation = `ton-domaine.fr`** → les super-administrateurs Workspace
  voient le projet dans la console. Ils voient le client OAuth, pas tes mails.
- **Organisation = « Aucune organisation »** → projet rattaché à ton compte
  seul. Cette option n'apparaît que si la politique de ton Workspace l'autorise,
  ou si tu crées le projet depuis un compte Google personnel.

Nomme-le clairement (« Jarvis perso »), ça t'évitera de le confondre plus tard.

### 2. Activer les API

**API et services → Bibliothèque**, puis active seulement ce dont tu as besoin :

- **Gmail API** — pour lire/envoyer les mails
- **Google Calendar API** — pour l'agenda

N'active rien d'autre : une API désactivée est une API qui ne peut pas être
utilisée, même avec un jeton valide.

### 3. L'écran de consentement

**API et services → Écran de consentement OAuth**.

| Type | Qui peut autoriser | Pour toi |
|---|---|---|
| **Interne** | uniquement les comptes de ton Workspace | ✅ recommandé si le projet est dans l'organisation |
| **Externe** | n'importe quel compte Google | à réserver aux **utilisateurs test** |

En **Externe**, va dans **Utilisateurs test** et n'ajoute **que ton adresse**.
Personne d'autre ne pourra passer l'écran de consentement — c'est la barrière la
plus efficace, et elle ne coûte rien.

Ne clique **pas** sur « Publier l'application » : en mode test, l'app reste
limitée à tes utilisateurs test, ce qui est exactement ce que tu veux.

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
tout compte que tu n'as pas mis là toi-même. Sur un projet créé dans une
organisation, les super-admins du domaine gardent un accès hérité — c'est une
propriété de Workspace, pas quelque chose que tu peux désactiver depuis le
projet.

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
