# Coûts, budgets & routage (N12)

> **Doctrine** : Hermes orchestre et pense ; Jarvis détient les clés et le corps.
> Le routage ci-dessous **est** l'implémentation de la doctrine — qui fait quoi, et à
> quel coût.

## Les 3 modes (config `mode`)

| Mode | LLM | Voix | Pour quoi |
|---|---|---|---|
| **local** | Ollama | Piper/Kokoro/Windows | tout local, **rien ne sort**, gratuit |
| **hybride** *(défaut)* | modèle quotidien économique du fournisseur choisi : Luna pour OpenAI, Haiku pour Claude | moteur vocal configuré | demandes courtes en cloud ; **tâches de fond → Hermes** |
| **qualite** | profil puissant du même fournisseur | moteur vocal configuré | modèle le plus capable pour les demandes exigeantes |

*(L'ancien `mode: cloud` reste accepté = `hybride`.)* Changement **à la voix** :
« passe en local », « repasse en hybride », « mode qualité » (`mode_routage`).

**Routage vers Hermes** : en hybride, une **tâche de fond** (analyse, recherche
longue, veille) est confiée à Hermes via `deleguer_a_hermes` — le modèle l'appelle
de lui-même (« je confie ça à Hermes »), plus besoin de le dire. Les réflexes
restent sur le chemin court de Jarvis (rapide, économique).

Le profil hybride contient bien **deux choix persistants** : le fournisseur et
son modèle quotidien. Par défaut, Jarvis retient `gpt-5.6-luna` pour OpenAI et
`claude-haiku-4-5` pour Anthropic. Un modèle choisi explicitement dans le HUD,
le panneau ou `config.yaml` reste prioritaire ; Jarvis ne le remplace pas en
silence. Le mode qualité possède son modèle séparé.

## Suivi des coûts (centralisé, persisté)

Compteurs par fournisseur, agrégés **jour / mois**, dans `budget.json` (non versionné) :

- **LLM cloud Jarvis** : les appels OpenAI ou Claude/Anthropic sont instrumentés
  (tokens in/out + cache) et comptés via `budget.prix` ($/Mtok).
- **Voix ElevenLabs** : facturée au caractère → `budget.prix_elevenlabs` ($/1000 car.).
- **Twilio** (appels) : compteur mensuel `logs/calls/compteur.json`.
- **Hermes** : tient **sa propre** compta (`hermes insights`) — Jarvis la lit mais ne
  la double pas ; la part d'Hermes est affichée à part (tokens).

À la voix : « **mon budget ?** » → réponse ventilée (coût jour/mois, par poste, % du
plafond, + tokens Hermes). Aussi visible dans le **panneau → État**.

## Budgets & garde-fous (jamais de blocage silencieux)

Dans `config.yaml → budget` :

```yaml
budget:
  plafond_jour: 2.0        # $/jour (null = pas de plafond)
  plafond_mois: 30.0       # $/mois
  alerte_pct: 80           # alerte VOCALE à 80 % du plafond
  mode_normal: hybride     # mode repris le lendemain après une bascule auto
  crons_critiques: []      # crons Hermes jamais suspendus (ex: ["reveil"])
```

- **80 %** d'un plafond → **alerte vocale** (« j'ai dépensé 80 % de mon plafond du
  jour, il reste ~X dollars »), une fois par jour.
- **Plafond atteint** → **bascule automatique en local** (Ollama + Piper, gratuit)
  avec annonce claire, **+ suspension des crons Hermes non critiques** jusqu'au
  lendemain. **Le lendemain** : budget réarmé, crons repris, retour au `mode_normal`
  — automatiquement.
- Un **changement manuel** de mode désarme la bascule auto (tu décides).

## Proposition pour les petits budgets cloud *(roadmap)*

Aujourd'hui, les fournisseurs cloud intégrés sont **OpenAI** et
**Claude/Anthropic**. **Gemini et DeepSeek ne sont pas encore sélectionnables** :
les options ci-dessous décrivent une évolution possible, pas une configuration à
ajouter dès maintenant dans `config.yaml`.

L'objectif serait de conserver les commandes déterministes (domotique, applications,
Spotify, minuteurs…) en local, puis de n'appeler un LLM cloud que lorsqu'une demande
nécessite réellement de comprendre ou de produire du texte :

| Option proposée | Intérêt | Limites à afficher clairement |
|---|---|---|
| **Gemini Flash-Lite — niveau gratuit** | conversations quotidiennes sans coût dans les quotas | quotas variables ; au niveau gratuit, Google indique que le contenu peut servir à améliorer ses produits |
| **DeepSeek Flash — paiement à l'usage** | API très économique et [compatible avec le format Responses d'OpenAI](https://api-docs.deepseek.com/api/create-response/) | ce n'est pas gratuit ; fournisseur cloud externe et tarifs susceptibles de changer |
| **Petit modèle du fournisseur déjà intégré** | aucune nouvelle clé ni nouveau connecteur | moins puissant qu'un profil qualité, mais souvent suffisant pour une commande vocale |
| **Ollama + voix locale** | aucun coût d'API et aucune donnée envoyée | nécessite une machine locale suffisante et peut être moins fiable sur les tâches complexes |

Une intégration correcte devrait prévoir :

- un connecteur explicite par fournisseur, testé avec les appels d'outils ;
- une bascule automatique vers le mode local lors d'un quota gratuit épuisé ou
  d'une erreur de débit, sans boucle de requêtes payantes ;
- l'interdiction d'envoyer secrets, mots de passe et données sensibles à un niveau
  cloud gratuit ;
- une voix locale (Piper, Kokoro ou Windows) pour ne pas remplacer l'économie du
  LLM par un abonnement TTS ;
- le maintien d'**Astra/OpenAI comme option séparée** pour le contrôle visuel avancé
  du PC, sans l'imposer aux commandes simples.

Références tarifaires à vérifier au moment de l'installation :
[Gemini API](https://ai.google.dev/gemini-api/docs/pricing),
[DeepSeek API](https://api-docs.deepseek.com/quick_start/pricing/) et
[OpenAI API](https://developers.openai.com/api/docs/models). Les quotas et tarifs
ne doivent jamais être figés dans le code sans date ni possibilité de les modifier.

## Coûts typiques (ordres de grandeur, à titre indicatif)

*Estimations — dépendent de tes modèles/offres. Ajuste `budget.prix*`.*

| Usage | Backend | Coût approx. |
|---|---|---|
| Commande domotique / timer / scène | hybride (`gpt-5.6-luna` par défaut) | dépend du contexte, généralement une petite fraction de centime |
| Question courte parlée (réponse ElevenLabs ~200 car.) | hybride | ~0,02 $ (voix) + LLM |
| Question avec vision (capture d'écran) | hybride | ~0,01–0,03 $ |
| Analyse / recherche de fond | Hermes | plus élevé (modèle fort, longue) |
| Appel téléphonique | Twilio | ~0,02 $/min + voix |
| Tout en **local** | Ollama + Piper | **0 $** |

Les tarifs exacts changent : le catalogue du panneau et `config.example.yaml`
servent de valeurs de départ, à vérifier dans la documentation du fournisseur
sélectionné avant de modifier les plafonds.

Pour ne rien dépenser : `mode: local` (ou « passe en local »). Pour la qualité
maximale ponctuelle : « mode qualité », puis « repasse en hybride ».
