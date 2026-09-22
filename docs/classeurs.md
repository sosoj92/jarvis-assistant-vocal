# 📊 Google Sheets : CRM, facturation, plannings

Tes classeurs Google Sheets deviennent des outils de Jarvis : il **lit**,
**cherche** et **écrit** dedans — pour tes listes de clients/partenaires, tes
factures, tes plannings.

La règle **95/5** s'applique : Jarvis lit et prépare tout seul, mais chaque
écriture demande ta **confirmation vocale** avant d'agir.

---

## 1. Autoriser Google (une seule fois)

Même fichier d'identifiants que Gmail et l'Agenda (`google_credentials.json`,
voir [mail.md](mail.md)) :

```bash
uv run python scripts/google_login.py sheets
```

Un navigateur s'ouvre, tu acceptes, le jeton (`google_token_sheets.json`)
se rafraîchit ensuite tout seul.

## 2. Déclarer tes classeurs (facultatif mais recommandé)

Pour parler de tes classeurs par des noms courts, ajoute des alias dans
`config.yaml` (id = la partie entre `/d/` et `/edit` dans l'URL du classeur) :

```yaml
classeurs:
  alias:
    partenaires: "1AbC...id_US_Partner_List"
    factures: "1XyZ...id_Invoice_2026"
    planning: "1QrS...id_Schedule_2026"
```

Sans alias, tu peux donner l'URL complète du classeur à la voix — mais un
alias est plus fiable pour la reconnaissance vocale.

## 3. Ce que Jarvis sait faire

| Outil | Confirmation | Exemple de phrase |
|---|---|---|
| `classeurs_lire` | non (lecture) | « Lis la plage A1 à F20 du classeur factures » |
| `classeurs_chercher` | non (lecture) | « Est-ce que PhoneBox est dans les partenaires ? » |
| `classeurs_ecrire_cellule` | **oui** | « Marque le partenaire Acme comme actif » |
| `classeurs_ajouter_ligne` | **oui** | « Ajoute un nouveau client : Acme, contact John, statut en discussion » |

## 4. Sécurité

- Les écritures (`classeurs_ecrire_cellule`, `classeurs_ajouter_ligne`)
  exigent **toujours** ta confirmation vocale — « toujours autoriser » est
  refusé pour ce niveau de criticité.
- Les outils Sheets ne sont **pas exposés** via le serveur MCP de Jarvis :
  un agent externe ne peut pas lire ton CRM ni tes factures.
- Les données de tes classeurs ne sont jamais écrites dans les logs.

## 5. Monday.com en complément

Si ton CRM vit dans monday.com plutôt que (ou en plus de) Sheets, utilise
le pont MCP universel (`mcp_externes:` dans `config.yaml`) :

```yaml
mcp_externes:
  - nom: monday
    url: "https://mcp.monday.com/mcp"
    entetes:
      Authorization: "Bearer TON_JETON_API_MONDAY"
```

Le jeton se crée dans monday.com : avatar → *Settings* → *API* (voir la
[doc monday.com](https://developer.monday.com/api-reference/docs/mcp-api-token)).
Les outils monday apparaissent comme des outils natifs, avec confirmation
vocale systématique — voir [mcp_externe.md](mcp_externe.md).
