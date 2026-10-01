# Fournisseurs cloud : OpenAI et Claude/Anthropic

Jarvis sépare le **mode de routage** du **fournisseur cloud**. OpenAI et
Claude/Anthropic sont intégrés aujourd'hui. Gemini n'a pas encore de connecteur
natif ; il ne faut donc pas le présenter comme disponible tant que ce connecteur
n'est pas ajouté.

## OpenAI

Jarvis utilise l'API **Responses** d'OpenAI pour la conversation, la vision et les
appels d'outils. Le modèle recommandé au quotidien est `gpt-5.6-luna` ;
`gpt-6-astra` est disponible pour le mode qualité.

## Quel cerveau reçoit quelle tâche ?

Jarvis ne transmet plus systématiquement ses quelque cent outils au modèle. Un
routeur commun au PC et aux satellites choisit d'abord le chemin le plus court :

- **conversation simple** : le modèle répond sans catalogue d'outils ;
- **heure, météo, média, domotique, agenda…** : seulement les outils du domaine ;
- **lecture ponctuelle de l'écran** : capture de la fenêtre active et modèle
  quotidien avec vision, sans contrôle du PC ;
- **action Windows en plusieurs étapes** : Astra, uniquement sur demande explicite
  ou après confirmation quand aucun outil direct ne suffit ;
- **recherche de fond et création de contenu** : Hermes, en arrière-plan ;
- **navigation web spécialisée** : les outils navigateur bornés du domaine.

Une commande directe comme « ouvre Spotify » ou « éteins la lumière » n'emploie
donc pas Astra. Le nombre de tours et d'appels d'outils est aussi borné pour éviter
une boucle autonome. Les limites peuvent être ajustées dans `config.yaml` :

```yaml
assistant:
  max_tours_outils: 6
  max_appels_outils: 12
  timeout_tour: 120
```

## Mode opérateur Astra sur le PC

Deux formulations déclenchent directement une tâche locale bornée :

- « Jarvis, utilise Astra pour ouvrir le dossier Téléchargements » ;
- « Jarvis, prends le contrôle de mon PC pour chercher ce réglage ».

Si une demande ordinaire nécessite plusieurs clics ou saisies et qu'aucun outil
direct ne suffit, Jarvis propose lui-même le mode opérateur et demande une
confirmation vocale avant de démarrer. Le contrôle est local, jamais exposé à
Hermes/MCP ni au pont distant. **Échap** interrompt immédiatement la boucle.

Astra reçoit une capture puis choisit une seule action structurée ; Jarvis exécute
l'action et renvoie une nouvelle capture. Il n'obtient aucun shell libre. Le mode
refuse les mots de passe/codes, achats et paiements, envois/publications,
suppressions, installations et commandes système : ces opérations restent dans
leurs outils spécialisés avec leurs confirmations propres.

Réglages optionnels :

```yaml
astra_pc:
  actif: true
  modele: "gpt-6-astra"
  max_actions: 12
  timeout: 90
```

## Point important : ChatGPT et l'API sont séparés

Un abonnement ChatGPT (Plus, Pro, etc.) ne fournit pas automatiquement un solde
API. Jarvis a besoin d'une **clé API Platform** et d'une facturation API active.
Les crédits achetés dans ChatGPT/Codex ne sont pas des crédits API.

1. Ouvre <https://platform.openai.com/api-keys> et crée une clé de projet.
2. Vérifie la facturation sur <https://platform.openai.com/settings/organization/billing>.
3. Ajoute la clé uniquement dans `config.yaml` (ce fichier est gitignoré) :

```yaml
cloud:
  fournisseur: openai

openai:
  cle: "sk-proj-..."
  modele: "gpt-5.6-luna"
  modele_qualite: "gpt-6-astra"
  raisonnement: low
  raisonnement_qualite: high
```

Ne mets jamais la clé dans une issue, un commit, une capture d'écran ou
l'environnement d'Hermes.

## Changer de modèle depuis le panneau

Ouvre <http://localhost:8790/panneau>, onglet **Modèles** :

- **Hybride** active le modèle choisi pour les demandes quotidiennes ;
- **Qualité** active le modèle choisi pour les demandes exigeantes ;
- **Local** active Ollama et garantit que rien ne sort de la machine.

Le panneau interroge `/v1/models` avec la clé locale et affiche si chaque modèle
du catalogue est réellement autorisé pour le projet API. Le changement prend
effet au tour vocal suivant, sans redémarrer Jarvis.

Modèles proposés :

| Modèle | Usage conseillé | Outils | Vision |
|---|---|---|---|
| `gpt-5.6-luna` | quotidien recommandé, très économique et rapide | oui | oui |
| `gpt-5.6-terra` | équilibre renforcé si Luna ne suffit pas | oui | oui |
| `gpt-5.6-sol` | qualité professionnelle | oui | oui |
| `gpt-6-astra` | raisonnement et tâches complexes | oui | oui |

## Ce qui a été migré

- boucle vocale principale et appels d'outils ;
- captures d'écran et vision ;
- assistant navigateur et réservations ;
- indexation du hub de contenu ;
- conversations téléphoniques ;
- comptage des tokens et estimation du coût dans le panneau État.

## Claude / Anthropic

Claude/Anthropic est une **alternative cloud prise en charge** : choisir
`cloud.fournisseur: anthropic`, puis renseigner `anthropic.cle`,
`anthropic.modele` et `anthropic.modele_qualite` dans le fichier local.

## Voix ElevenLabs

Le LLM et la voix sont désormais deux choix séparés. Dans l'onglet **Réglages**,
choisis `ElevenLabs`, `Piper`, `Kokoro`, `Windows` ou `Auto`, puis sélectionne une
voix du compte ElevenLabs et clique **Tester la voix**.

Le mode `local` garde sa promesse de confidentialité : si ElevenLabs est choisi,
Jarvis force tout de même un moteur local. En mode hybride/qualité, `Auto` choisit
ElevenLabs quand une clé valide est configurée.

## Dépannage

- **Clé absente** : ajoute `openai.cle`, puis recharge le panneau.
- **Modèle non autorisé** : choisis un modèle marqué autorisé ou vérifie le projet
  et le niveau de facturation API.
- **401** : clé invalide/révoquée ou mauvais projet.
- **429** : limite de débit ou solde API insuffisant.
- **ElevenLabs retombe sur Windows** : vérifie le badge de connexion dans
  Réglages, sélectionne `ElevenLabs`, puis teste la voix.
