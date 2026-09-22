# 🇫🇷 Mistral AI comme modèle cloud de Jarvis

Jarvis peut parler à **Mistral AI** (La Plateforme, `console.mistral.ai`) au
lieu d'OpenAI ou de Claude. L'API Mistral est compatible OpenAI : le même
client, une `base_url` différente — aucun abonnement ChatGPT/Claude requis.

La voix, elle, reste **locale** (Piper) : Mistral n'offre pas de synthèse
vocale, et une voix locale est gratuite et privée. Voir
[local.md](local.md).

## Configuration

Dans `config.yaml` :

```yaml
cloud:
  fournisseur: mistral

mistral:
  cle: "TA-CLE"                 # console.mistral.ai -> API keys
  modele: "mistral-small-latest"        # mode hybride : rapide, economique
  modele_qualite: "mistral-large-latest"  # mode qualite : le plus fort
  max_tokens: 2048
```

Puis relance Jarvis. Le message de démarrage doit afficher
`provider LLM : Mistral (mode hybride, modele mistral-small-latest)`.

## Quels modèles ?

| Rôle | Modèle | Pourquoi |
|---|---|---|
| hybride (défaut) | `mistral-small-latest` | rapide, peu cher, bon function calling |
| qualité | `mistral-large-latest` | le plus capable de la famille |
| vision | `pixtral-large-latest` | capture d'écran / analyse d'image |

`*-latest` suit automatiquement les mises à jour de Mistral ; remplace par
une version épinglée (ex. `mistral-small-2503`) si tu veux un comportement
figé.

## Ce qui marche

- **Boucle vocale complète** : Whisper capte, Mistral raisonne et appelle
  les outils (domotique, OBS, navigateur…), Piper parle.
- **Appels d'outils** (function calling) : natif, y compris en parallèle.
- **Vision** : les captures d'écran passent par `pixtral` — configure
  `astra_pc.modele: pixtral-large-latest` pour le contrôle souris/clavier.
- **Sous-pipelines** : réservations, appels téléphoniques, indexation —
  tout ce qui passe par `core/cloud.py` suit le fournisseur actif.

## Ce qui ne change pas

- La facturation se suit dans le budget Jarvis (`mon_budget`) : prix au
  million de tokens, ajustables dans `config.yaml` (`budget.prix`).
- Ollama reste le mode 100 % local ; Gemini reste l'alternative gratuite.
- `mistral.url` permet de pointer vers un endpoint compatible (proxie,
  auto-hébergé) si tu en as un.
