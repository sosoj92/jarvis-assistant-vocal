# 🔌 Brancher d'autres assistants à Jarvis

Deux assistants externes, très différents, peuvent se brancher sur Jarvis par
MCP — et ils ne le font pas de la même manière :

| | [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Stanford) | [Jarvis](https://github.com/isair/jarvis) (isair) |
|---|---|---|
| Nature | Framework de recherche local-first (moteurs d'inférence, agents, mémoire, évals) | Assistant vocal local-first concurrent, avec mémoire de conversation et visage animé |
| Pilote la domotique de Jarvis | ✅ `[tools.mcp]` dans son `config.toml` | ✅ `"mcps"` dans sa config JSON |
| Se pilote depuis Jarvis | ✅ son serveur MCP (`jarvis serve`) | ❌ pas de serveur MCP — client uniquement |
| Transports | stdio + streamable HTTP | **stdio uniquement** |

Le scénario pour les deux : Jarvis garde la voix et la maison (Hue, OBS,
minuteurs) ; l'assistant externe amène sa propre intelligence. Vérifié en
pratique dans les deux cas : découverte des 19 outils exposés, puis appel
réel de `heure_et_date`.

---

## 1. OpenJarvis pilote Jarvis

Démarre le serveur MCP de Jarvis en mode HTTP (il tourne indépendamment de
l'assistant vocal) :

```bash
./launch_mcp_server.sh        # ou : JARVIS_MCP_TRANSPORT=http uv run python -m jarvis.mcp_server
```

Le serveur écoute sur `http://127.0.0.1:8765/mcp` (streamable HTTP). Puis dans
le `config.toml` d'OpenJarvis :

```toml
[tools.mcp]
enabled = true
servers = """
[{"name": "jarvis", "url": "http://127.0.0.1:8765/mcp"}]
"""
```

Les outils exposés par Jarvis (lumieres Hue, OBS, `meteo`, `lancer_minuteur`,
`heure_et_date`, stats système…) apparaissent comme des outils natifs du
registre d'OpenJarvis. Ses agents peuvent alors les appeler — le
`scheduled-monitor` peut par exemple piloter les lumières sur calendrier.

> **Sécurité** : le transport HTTP de Jarvis n'a **pas d'authentification**,
> c'est pourquoi il n'écoute que sur la boucle locale (`mcp.host` dans
> `config.yaml`). N'expose pas ce port au réseau sans ajouter un reverse
> proxy authentifié. Les outils à confirmation exigent toujours
> `confirm: true` — un agent externe ne peut pas couper ton stream en
> silence.

Vérifié : `initialize` → `tools/list` (19 outils) → `call_tool("heure_et_date")`
répond *"Il est 4 heures 23, le mardi 22 septembre 2026."* — pont testé en
stdio puis en HTTP avec le code client réel d'OpenJarvis.

## 2. Jarvis (isair) pilote Jarvis

Sa config MCP est en JSON (`"mcps"`) et ne supporte que **stdio**. Déclare le
serveur de Jarvis comme n'importe quel serveur MCP :

```json
{
  "mcps": {
    "jarvis_vocal": {
      "command": "/bin/sh",
      "args": ["-c", "cd /chemin/vers/jarvis-assistant-vocal && exec .venv/bin/python -m jarvis.mcp_server"]
    }
  }
}
```

⚠️ **Pourquoi ce `sh -c "cd … && exec …"`** : son client MCP (comme celui
d'OpenJarvis) lance le sous-processus **sans répertoire de travail**. Le
serveur de Jarvis doit tourner depuis sa racine (config.yaml, logs/, registre).
Sans ce contournement, la connexion échoue silencieusement — « Connection
closed » sans autre indice.

Sens inverse : **non disponible** — isair/jarvis n'expose pas de serveur MCP,
seul le sens « il pilote la domotique » existe.

Vérifié avec son `MCPClient` réel : `list_tools` → 19 outils,
`invoke_tool("jarvis_vocal", "heure_et_date")` → réponse correcte.

## 3. Jarvis délègue à OpenJarvis (raisonnement)

Démarre le serveur MCP d'OpenJarvis (voir sa documentation — `jarvis serve`),
puis déclare-le dans `config.yaml` :

```yaml
mcp_externes:
  - nom: openjarvis
    url: "http://127.0.0.1:8000/mcp"
    sans_confirmation: []   # la recherche et la lecture mémoire sont sans risque ;
                            # ajoute ici les seuls outils en lecture seule
```

Au démarrage, Jarvis affiche le nombre d'outils découverts ; à la voix :

> « Hey Jarvis, fais une recherche approfondie sur l'efficacité des modèles
> locaux » → Jarvis transcrit, appelle l'agent `deep_research` d'OpenJarvis,
> et énonce le résultat avec ses sources par Piper.

Rappels de sécurité (voir [mcp_externe.md](mcp_externe.md)) : tout outil
distant demande confirmation vocale sauf `sans_confirmation` — c'est voulu,
car les effets d'un agent distant ne se devinent pas depuis son nom.

## 4. monday.com (CRM) via son serveur MCP hébergé

monday.com expose un serveur MCP officiel hébergé — aucun code à installer :
Jarvis s'y branche avec le pont universel `mcp_externes:`.

1. Crée un jeton API : monday.com → avatar → *Settings* → *API & Webhooks* →
   *Personal API tokens* (voir la
   [doc monday.com](https://developer.monday.com/api-reference/docs/mcp-api-token)).
2. Déclare-le dans `config.yaml` :

```yaml
mcp_externes:
  - nom: monday
    url: "https://mcp.monday.com/mcp"
    entetes:
      Authorization: "Bearer TON_JETON_API_MONDAY"
    sans_confirmation: []   # lecture ET ecriture demandent ton accord vocal
```

Les outils monday (rechercher des items, créer des fiches, mises à jour,
dashboards… plus de 60 outils) apparaissent comme des outils natifs de Jarvis,
préfixés `monday_`. Chaque appel distant exige ta confirmation vocale,
sauf ceux listés dans `sans_confirmation` — tu peux y mettre les outils en
lecture seule si tu veux un CRM interrogeable sans friction.

> **Attention** : l'URL correcte est `https://mcp.monday.com/mcp` — le
> transport SSE (`/sse`) est déprécié et non supporté par monday.com.

Tes données CRM Sheets et monday restent couvertes par la règle 95/5 :
Jarvis lit, prépare, rédige — rien ne part sans ton feu vert.

## 5. Aller plus loin

- **Vocabulaire** : OpenJarvis répond en anglais par défaut ; Jarvis lui
  parlera dans la langue de ses prompts système comme avec tout serveur MCP.
- **Skills** : OpenJarvis importe des skills depuis n'importe quel dépôt
  GitHub ([agentskills.io](https://agentskills.io)). Les intentions de
  routage de Jarvis (`core/routage.py`) peuvent être empaquetées de la sorte.
- **Moteur Apple Foundation Models** : OpenJarvis embarque un moteur local
  macOS 26+ (`afm`). L'abstraction fournisseur de Jarvis
  (`core/llm.py` + `core/cloud.py`) peut l'adopter sans MCP — piste pour un
  mode 100 % local sur Mac.
- **Nom des deux Jarvis** : attention à la collision de noms — le module
  Python s'appelle `jarvis` chez isair aussi. Ils ne peuvent pas cohabiter
  dans le même `PYTHONPATH` ; ça ne gêne pas le pont MCP (processus séparés).
