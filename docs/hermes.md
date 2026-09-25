# Déléguer à Hermes (cerveau délibératif)

Jarvis peut confier une **tâche de réflexion / recherche de fond** à
[Hermes Agent](https://github.com/NousResearch/hermes-agent), qui tourne **en local**
soit sur le PC, soit dans une VM Ubuntu privée, puis t'annoncer le résultat **à
voix haute** quand c'est prêt. L'installation recommandée et isolée est décrite
dans [le guide du serveur Ubuntu/Hyper-V](hermes_server_vm.md).

- Outil : `deleguer_a_hermes(tache, session)` — **non exposé via MCP**. Chaque
  délégation utilise une session nommée et plusieurs tâches peuvent tourner en parallèle.
- Phrases déclencheuses : « **délègue à Hermes** … », « **fais une recherche de fond sur** … »,
  « **lance Hermes sur** … ».
- Les demandes explicites de **création de contenu** sont aussi routées
  automatiquement : écrire ou améliorer un script, proposer des hooks/accroches,
  trouver des idées vidéo ou analyser des inspirations. Hermes reçoit la demande
  avec instruction d'utiliser le Vault pour respecter le ton existant. Une simple
  mention (« j'ai tourné ma vidéo », « où en est mon script ? ») reste chez Jarvis.

> Exemple : « Jarvis, délègue à Hermes : compare les 3 meilleurs micros pour le streaming en 2026. »
> Jarvis : « Je délègue ça à Hermes. Je te préviens dès que c'est prêt. » … *(plus tard)* …
> « Hermes a terminé. En résumé : … »

## Comment ça marche

1. Jarvis **répond tout de suite** (« je délègue, je te préviens ») et lance la tâche **en
   fond** — il ne te fait pas attendre.
2. En tâche de fond, Jarvis appelle l'**API locale d'Hermes**. Avec la VM, un
   tunnel SSH la rend disponible uniquement sur le loopback Windows :
   `POST http://127.0.0.1:8642/v1/responses`, en-tête `Authorization: Bearer <clé>`, corps
   `{"model":"hermes-agent","input":"…","conversation":"jarvis-delegation"}`. Hermes réfléchit
   et ne reçoit que les outils MCP explicitement autorisés. Avec
   les versions récentes où `hermes gateway` ne fournit plus cette API, Jarvis se
   replie automatiquement sur le mode officiel `hermes -z`.
3. Le résultat passe par le **filtre de confidentialité** (`core/confidentialite.py` :
   caviarde mails/clés/numéros/jetons, raccourcit) puis est **lu à voix haute**.
4. **Sessions nommées** : chaque délégation reçoit sa propre conversation. Deux
   recherches longues ne se mélangent donc plus et s'exécutent en parallèle.

## Command Center et suivi vocal

La page **État** du panneau local affiche les délégations en cours, terminées,
échouées ou en attente de ta validation. Chaque ligne indique la session, la durée,
les tokens de la réponse quand l'API Hermes les fournit, et le résumé filtré.

Dis **« Jarvis, où en sont les tâches ? »** pour obtenir ce point à l'oral via
l'outil local `taches_hermes`.

## Notre équipe d'agents (skills Hermes)

Les chemins sont ceux du conteneur, jamais les chemins Windows personnels.

| Rôle | Périmètre fichiers | Outils autorisés pour ce rôle |
|---|---|---|
| **Analyste du Vault** (`analyser-vault`) | lecture seule `/vault` | `chercher_inspiration`, `etat_contenus`, `generer_idees_contenu` |
| **Scénariste maison** (`generer-script-maison`) | lecture seule `/scripts`, écriture uniquement `/scripts/drafts` | `chercher_inspiration`, `etat_contenus` |
| **Ingest YouTube** (`ingerer-chaine-youtube`) | lecture seule `/scripts`; les sorties passent par Jarvis | `lancer_ingestion_youtube` |
| **Veilleur** (`creer-une-veille`) | aucun dossier personnel requis | recherche web et crons internes Hermes, livraison Telegram |

Le profil serveur initial est volontairement plus strict : seulement cinq outils
N1 sont visibles (`heure_et_date`, `meteo`, `get_system_stats`,
`chercher_inspiration`, `etat_contenus`). Les autres capacités doivent être
ajoutées une par une après validation. Aucun credential ni outil physique/sensible
n'est ajouté à Hermes.

## Configuration (`config.yaml`)

```yaml
hermes:
  transport: "auto"                   # auto | cli | http
  api_url: "http://127.0.0.1:8642"   # API locale ou tunnel SSH loopback
  api_key: "…"                       # = API_SERVER_KEY du .env d'Hermes
  # api_key_file: "…"                # alternative : un fichier contenant la clé
  session: "jarvis-delegation"       # repli ; Jarvis crée normalement une session par tâche
  modele_facturation: ""              # optionnel si l'API ne renvoie pas le modele
  timeout: 900                       # une recherche de fond peut être longue
  resume_max: 500                    # longueur max du résumé vocal
  journaliser: true                  # false = aucun compte rendu local durable
  retention_jours: 30                # purge automatique des anciens comptes rendus
```

La clé doit correspondre à `API_SERVER_KEY` côté Hermes et rester uniquement dans
les fichiers locaux gitignorés. En transport `auto`, l'API sur le port 8642 est
utilisée si elle répond ; sinon le CLI Hermes local prend le relais lorsqu'il est
installé. `cli` force le chemin CLI et `http` exige l'API.

## Sécurité

- **Non exposé via MCP** : seule la voix (chez toi) peut déclencher une délégation ; un token
  MCP volé ne peut pas lancer Hermes.
- La délégation locale ne demande pas de confirmation, afin que le routage des
  tâches de fond puisse être automatique.
- **Filtre de confidentialité** sur le texte lu à voix haute (dernier garde-fou).
- Les comptes rendus locaux sont caviardés avant écriture, peuvent être désactivés
  et sont purgés après `retention_jours`. Ils ne sont jamais destinés au dépôt public.
- L'API 8642 est en **loopback** et protégée par la clé `API_SERVER_KEY`.
- Rappel (voir `HERMES_NOTES.md` §14) : Hermes n'a **aucun credential** de tes comptes ; toute
  action sensible reste côté Jarvis avec confirmation. La délégation sert à **réfléchir/chercher**,
  pas à agir sur tes comptes.

## Réglages utiles

- `timeout` : monte-le si tes recherches de fond sont longues (défaut 900 s).
- `resume_max` : longueur du résumé vocal (défaut 500 caractères).
- `session` : change le nom pour repartir d'un contexte vierge.
- `modele_facturation` : nom utilisé uniquement pour estimer le coût par tâche
  quand la réponse Hermes ne fournit pas son modèle réel.
