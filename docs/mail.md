# 📬 Gmail — lire, écrire, envoyer à la voix

Jarvis expose cinq outils : `lire_mails`, `lire_mail`, `preparer_mail`,
`envoyer_mail`, `mettre_a_la_corbeille`. Les deux derniers demandent ton accord
vocal avant d'agir.

Deux authentifications possibles. **Choisis selon ton compte :**

| Ton compte | Méthode |
|---|---|
| Gmail personnel avec 2FA | mot de passe d'application (§ A, 2 minutes) |
| **Google Workspace** (domaine perso/pro) | **OAuth 2.0** (§ B) |

Sur Workspace, l'administrateur peut interdire les mots de passe d'application —
et Google les retire progressivement. OAuth est le chemin officiel, et souvent
le seul qui marche.

---

## A. Mot de passe d'application (Gmail personnel)

1. Active la **validation en deux étapes** sur ton compte Google (obligatoire).
2. Va sur **[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)**.
3. Crée un mot de passe nommé « Jarvis » → 16 caractères.
4. Dans `config.yaml` :

```yaml
mail:
  adresse: "ton.adresse@gmail.com"
  mot_de_passe_app: "abcd efgh ijkl mnop"   # les espaces sont ignorés
```

> Si la page répond **« Cette option n'est pas disponible pour votre compte »**,
> c'est que tu es sur Workspace ou que l'admin l'a désactivée → passe en § B.

---

## B. OAuth 2.0 (Google Workspace)

Une fois pour toutes : tu autorises Jarvis dans un navigateur, il garde un jeton
qui se rafraîchit tout seul.

### 1. Créer les identifiants OAuth

Dans la [console Google Cloud](https://console.cloud.google.com/) :

1. Crée un projet (ou prends-en un existant).
2. **API et services → Bibliothèque** → cherche **Gmail API** → **Activer**.
3. **API et services → Écran de consentement OAuth** :
   - Type **Interne** si tu veux le réserver à ton domaine Workspace,
     **Externe** sinon.
   - Renseigne un nom d'application et ton adresse. En **Externe**, ajoute-toi
     comme **utilisateur test** — sinon Google bloquera la connexion.
4. **Identifiants → Créer des identifiants → ID client OAuth →
   Application de bureau**.
5. **Télécharge le JSON** et place-le à la racine du projet sous le nom
   **`google_credentials.json`**.

> C'est le même fichier que pour l'Agenda : si tu l'as déjà, saute cette étape
> et ajoute simplement l'API Gmail au projet.

### 2. Autoriser

```bash
uv run python scripts/google_login.py mail
```

Un navigateur s'ouvre. Choisis ton compte, accepte. Le jeton est écrit dans
`google_token_mail.json`.

Pour autoriser aussi l'Agenda : `uv run python scripts/google_login.py mail agenda`

### 3. Activer dans la config

```yaml
mail:
  adresse: "arturo@ton-domaine.fr"
  oauth: true          # ← bascule sur OAuth ; mot_de_passe_app devient inutile
```

Relance Jarvis, puis : « **j'ai des nouveaux mails ?** »

### Si tu es l'administrateur du domaine

Workspace peut bloquer les applications OAuth tierces, même les tiennes.
Console d'admin → **Sécurité → Contrôle des API → Gérer l'accès des applications
tierces** → ajoute ton **ID client** en **Approuvé**.

---

## Ce que la permission couvre

Le scope demandé est `https://mail.google.com/`, qui donne l'accès IMAP et SMTP
— nécessaire pour lire, envoyer et mettre à la corbeille. C'est un scope large :
il ne quitte jamais ta machine, mais garde `google_token_mail.json` privé (il est
dans `.gitignore`, et créé en lecture seule pour toi).

Pour révoquer à tout moment :
[myaccount.google.com/permissions](https://myaccount.google.com/permissions).

---

## Dépannage

| Symptôme | Cause | Correctif |
|---|---|---|
| « la messagerie n'est pas configurée » | `mail.adresse` vide, ou ni `oauth` ni mot de passe | remplis `config.yaml` |
| `PermissionError: autorisation Google absente` | jeton jamais créé ou révoqué | `uv run python scripts/google_login.py mail` |
| `[AUTHENTICATIONFAILED]` en OAuth | Gmail API pas activée, ou scope refusé | refais le § B.1, puis réautorise |
| `Username and Password not accepted` | mot de passe d'application invalide | régénère-le, ou passe en OAuth |
| `access_denied` dans le navigateur | tu n'es pas utilisateur test (mode Externe) | ajoute ton adresse aux utilisateurs test |

Commence toujours par `preparer_mail` (brouillon) avant `envoyer_mail` : tu vois
ce qu'il a rédigé avant que ça parte.
