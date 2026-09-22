# 🤖 AI Operator : Jarvis, employé IA 24/7 branché à tes outils

Le concept d'**AI Operator** : un employé IA disponible 7j/7 et 24h/24, formé
sur tes tâches et branché à tes outils — emails, agenda, CRM, facturation.
Jarvis le fait déjà, avec sa doctrine de sécurité **95/5** :

> L'IA fait les 95 % — lire, trier, rédiger, préparer, chercher, résumer.
> Les 5 % qui comptent — envoyer, écrire, valider — exigent **ton feu vert**.

Chaque outil ci-dessous est marqué 🔍 lecture seule ou ✍️ écriture-avec-
confirmation.

---

## La pile complète

| Fonction | Outil | Doc |
|---|---|---|
| Emails (lire, trier, brouillon) | `tools/mail.py` 🔍 | [mail.md](mail.md) |
| Emails (envoyer) | `envoyer_mail` ✍️ | [mail.md](mail.md) |
| Agenda (tous tes calendriers) | `tools/agenda.py` 🔍 + créer/supprimer ✍️ | [agenda.md](agenda.md) |
| CRM / facturation Google Sheets | `tools/classeurs.py` 🔍 + écriture ✍️ | [classeurs.md](classeurs.md) |
| CRM monday.com (via MCP) | `mcp_externes:` ✍️ | [frameworks_mcp.md](frameworks_mcp.md) |
| Facturation facture.net (lecture) | `tools/factures.py` 🔍 | doc intégrée |
| ERP / SaaS / infra (via MCP) | `mcp_externes:` ✍️ | [mcp_externe.md](mcp_externe.md) |

## Mise en route (une fois)

```bash
uv run python scripts/setup.py          # choix cloud (Mistral) ou local
uv run python scripts/google_login.py mail agenda sheets   # Gmail + Agenda + Sheets
```

Puis dans `config.yaml` :

```yaml
mode: hybride                 # quotidien : Mistral ; le local prend le relais
classeurs:
  alias:
    partenaires: "1AbC..."    # tes classeurs CRM/facturation
    factures: "1XyZ..."
mcp_externes:
  - nom: monday               # si ton CRM vit dans monday.com
    url: "https://mcp.monday.com/mcp"
    entetes:
      Authorization: "Bearer TON_JETON_API_MONDAY"
```

## Exemples à la voix

- « Hey Jarvis, lis mes mails » → résume ta boîte, propose des réponses.
- « Est-ce que PhoneBox est dans la liste des partenaires ? » → `classeurs_chercher`.
- « Ajoute un nouveau client Acme, contact John, en discussion » → Jarvis
  prépare la ligne, te la relit, l'écrit **après** ton « oui ».
- « Où j'en suis sur mes factures ? » → résume les impayés.
- « Qu'est-ce que j'ai demain ? » → tous tes agendas, deadlines comprises.

## 24h/24, 7j/7

Sur macOS, Jarvis se relance tout seul s'il s'arrête :

```bash
./scripts/autostart_mac.sh    # installe le service launchd
```

Surveille ta consommation dans le panneau web → onglet **État** → **Budget** :
le mode `hybride` confie les tâches de fond au modèle local quand c'est
possible, et `budget.plafond_jour` coupe le cloud si un plafond est atteint.

## Le tableau de bord Operator

La page **`/operator`** (serveur web local, comme `/panneau`) reproduit le CRM
« AI Operator » : design sombre violet, KPIs des dernières 24 h, journal
« Pendant que tu dormais », et surtout la **file « À valider »** — les actions
en attente de ton feu vert, celles-là mêmes que Jarvis te demande à la voix.
Valider ou refuser depuis la page équivaut au oui/non vocal ; rien ne part
sans l'un ou l'autre.

Ouvre `http://localhost:8790/operator` pendant que Jarvis tourne
(`serveur.actif: true`). Accessible en local uniquement.

## Rappel sécurité

- Aucune écriture (mail, classeur, monday, agenda) ne part sans confirmation
  vocale — et « toujours autoriser » est refusé pour les actions critiques.
- Les outils financiers et CRM ne sont **pas** exposés via le serveur MCP :
  ni OpenJarvis ni isair/jarvis ne peuvent lire tes classeurs ni tes factures.
- Tes jetons (Google, monday) vivent dans `config.yaml` et les fichiers
  `google_token_*.json`, tous non versionnés, permissions 0600.
