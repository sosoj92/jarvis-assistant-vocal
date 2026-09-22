# 🔌 Brancher un serveur MCP externe à Jarvis

Jarvis sait faire les **deux sens** du Model Context Protocol :

| Sens | Fichier | Rôle |
|---|---|---|
| Jarvis **expose** ses outils | `jarvis/mcp_server.py` | Claude Desktop pilote tes lumières — voir [mcp.md](mcp.md) |
| Jarvis **appelle** des outils distants | `core/mcp_externe.py` | ← ce document |

Les outils distants rejoignent le registre à côté des outils natifs. Le modèle
(Claude, Gemini ou Ollama) les voit et les appelle comme les autres — tu parles,
il agit.

---

## Configuration

Dans `config.yaml` :

```yaml
mcp_externes:
  - nom: yorkhost
    url: "https://mcp.yorkhost.fr/mcp"
    entetes:
      Authorization: "Bearer TON_JETON"
    sans_confirmation: ["statut_serveur", "lister_conteneurs"]
```

| Clé | Rôle |
|---|---|
| `nom` | préfixe des outils (`yorkhost_statut_serveur`) et libellé vocal |
| `url` | point d'entrée **Streamable HTTP** du serveur |
| `entetes` | en-têtes HTTP, typiquement le jeton d'authentification |
| `sans_confirmation` | outils qui s'exécutent **sans** demander l'accord — noms **courts**, sans le préfixe |
| `prefixe` | `false` pour garder les noms tels quels (déconseillé) |

Relance Jarvis. Au démarrage il affiche :

```
MCP externe : yorkhost : 7 outil(s), 5 a confirmation
```

Puis, à la voix :

> « Hey Jarvis, quel est l'état du VPS 01 ? »
> « Hey Jarvis, redémarre le conteneur nginx » → *« Je vais lancer redemarrer_conteneur sur yorkhost. Tu confirmes ? »*

---

## La règle de sécurité

**Tout outil distant demande confirmation, sauf mention explicite.**

C'est l'inverse du réglage par défaut des outils natifs, et c'est délibéré :

- ces outils touchent à de l'infra que tu **ne vois pas** en parlant ;
- leurs effets ne se devinent pas depuis leur nom — `sync_nodes` efface-t-il
  quelque chose ? ;
- la transcription est faillible. Whisper entend « Iacoste » pour « YorkHost » :
  une commande destructive ne doit jamais partir sur une phrase mal comprise.

Mets dans `sans_confirmation` uniquement ce qui est **en lecture seule** —
statut, métriques, logs, listes. Tout ce qui écrit, redémarre ou supprime doit
rester derrière la confirmation vocale.

Deux garanties supplémentaires, non désactivables :

- **Jamais de ré-exposition.** Un outil distant n'est jamais republié par le
  serveur MCP de Jarvis. Sinon on créerait un pont invisible entre deux systèmes
  de permissions : un client autorisé sur Jarvis hériterait de ton infra.
- **Jamais de blocage au démarrage.** Un serveur injoignable est signalé et
  ignoré ; Jarvis démarre normalement sans ses outils.

---

## Ce qui est géré

- **Streamable HTTP** avec en-têtes d'authentification.
- **Schémas de paramètres** : lus depuis le serveur, dans les deux conventions
  du SDK (`input_schema` en v2, `inputSchema` en v1).
- **Plusieurs serveurs** : le préfixe évite qu'un `statut` en écrase un autre.
- **Délai maximum** de 30 s par appel, avec un message clair au-delà.
- **Sessions persistantes** : la connexion reste ouverte, tenue dans un thread
  dédié (le SDK MCP est asynchrone, le registre de Jarvis est synchrone).

## Ce qui ne l'est pas

- **Transport stdio** (serveur lancé en sous-processus) : non implémenté. Seul
  le HTTP l'est. Si tu en as besoin, dis-le.
- **OAuth** : seuls les en-têtes statiques sont gérés. Pour un serveur en OAuth,
  génère un jeton longue durée et mets-le dans `entetes`.
- **Ressources et prompts MCP** : seuls les **outils** sont importés.

---

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `yorkhost injoignable (...)` au démarrage | URL fausse, serveur éteint, ou jeton refusé |
| Les outils apparaissent mais sans paramètres | schéma non publié côté serveur |
| `n'a pas repondu en 30 secondes` | l'outil distant est trop lent |
| `Erreur de l'outil distant : ...` | le serveur a répondu une erreur — le message vient de lui |

Pour vérifier ton serveur indépendamment de Jarvis :

```bash
uv run python -c "
import asyncio
from mcp import Client
async def main():
    async with Client('https://mcp.yorkhost.fr/mcp') as c:
        for t in (await c.list_tools()).tools:
            print(t.name, '-', t.description)
asyncio.run(main())"
```
