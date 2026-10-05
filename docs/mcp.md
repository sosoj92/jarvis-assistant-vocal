# Serveur MCP de Jarvis

Expose les outils domotique/PC de Jarvis via le **Model Context Protocol**, pour
qu'ils soient pilotables par n'importe quel client MCP (Claude Desktop, Hermes
Agent, MCP Inspector...). Le serveur tourne **independamment** de l'assistant
vocal : les deux peuvent tourner en meme temps.

```bash
uv run python -m jarvis.mcp_server
```

Reutilise le registre d'outils (`tools/`) : chaque outil marque `mcp_expose=True`
est publie automatiquement avec son nom, sa description et son schema de
parametres. Aucune duplication.

## Outils exposes

Des lectures sures et quelques utilitaires, par securite :

| Outil | Role |
|---|---|
| `get_system_stats` | GPU / CPU / RAM / disque |
| `lancer_minuteur`, `heure_et_date`, `meteo` | Utilitaires |
| `mon_budget` | Cout des API du jour |
| `stop_record` | Arrete un enregistrement OBS |
| `chercher_inspiration`, `generer_idees_contenu`, `etat_contenus`, `lancer_ingestion_youtube` | Contenu |

**Jamais exposes** (doctrine du projet) : lumieres, ambiances, micro, camera, gestes,
Alexa, OBS (direct, enregistrement, scenes, replay), donnees financieres, mails,
memoire personnelle, lancement d'apps, capture d'ecran, brief, presence, Discord.

## Securite

- **Exposition en opt-in** : un outil n'est visible via MCP que s'il porte
  `mcp_expose=True`. Un nouvel outil ajoute dans `tools/` est donc **prive par
  defaut** — c'est voulu (un agent externe ne doit voir que l'autorise).
- **Confirmation** : un outil qui demande une confirmation (`confirmation=True`)
  ou un N3 n'est **jamais** expose, meme marque `mcp_expose=True` : un client MCP
  ne peut pas confirmer a la place de l'utilisatrice.
- **Journal** : tous les appels externes sont ecrits dans `logs/mcp.log`.

## Exposer un outil de plus

Dans son decorateur `@outil(...)`, ajoute `mcp_expose=True`. Il apparait au
prochain demarrage du serveur, sans autre code.

```python
@outil(nom="mon_outil", mcp_expose=True, description="...", parametres={...})
def mon_outil(...): ...
```

## Brancher dans Claude Desktop

Edite `claude_desktop_config.json` (Windows :
`%APPDATA%\Claude\claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Users\\ton-utilisateur\\jarvis-vocal",
               "python", "-m", "jarvis.mcp_server"]
    }
  }
}
```

Redemarre Claude Desktop. Les 14 outils apparaissent ; demande par ex.
« allume la chambre » ou « donne-moi les stats systeme ».

## Brancher dans Hermes Agent

Meme principe (transport stdio). Dans la configuration MCP de Hermes, declare un
serveur :

```json
{
  "name": "jarvis",
  "command": "uv",
  "args": ["run", "--directory", "C:\\Users\\ton-utilisateur\\jarvis-vocal",
           "python", "-m", "jarvis.mcp_server"]
}
```

(Adapte le chemin. Si Hermes attend une simple ligne de commande, utilise
`uv run --directory C:\Users\ton-utilisateur\jarvis-vocal python -m jarvis.mcp_server`.)

## Client distant (HTTP/SSE)

Pour un client qui n'est pas sur la meme machine, passe en HTTP dans
`config.yaml` :

```yaml
mcp:
  transport: "http"     # au lieu de "stdio"
  host: "127.0.0.1"     # garde 127.0.0.1 : le transport HTTP n'a pas d'authentification
  port: 8765
```

Hors de `127.0.0.1`, n'importe quelle machine du reseau pourrait appeler les outils
exposes, et la protection contre le DNS rebinding du SDK MCP est desactivee. Pour un
client sur une autre machine, prefere un tunnel chiffre et authentifie (SSH,
Tailscale) vers `127.0.0.1:8765`.

Le serveur ecoute alors en streamable-http ; le client se connecte a
`http://<machine>:8765`. (Le transport stdio reste recommande pour les clients
desktop locaux.)

## Test rapide (MCP Inspector)

```bash
npx @modelcontextprotocol/inspector uv run --directory C:\Users\ton-utilisateur\jarvis-vocal python -m jarvis.mcp_server
```

Dans l'inspecteur, appelle `allumer_lumiere` avec `{"piece": "chambre",
"allumer": true}` : ta lumiere Hue doit s'allumer.
