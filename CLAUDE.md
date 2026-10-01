# Contexte Claude Code — Jarvis

Ce fichier donne à Claude Code le contexte permanent nécessaire pour travailler
sur Jarvis sans devoir reconstituer le projet à chaque session.

## Mission du projet

Jarvis est un assistant vocal local en français, principalement destiné à
Windows 11. Il écoute un mot d'activation, transcrit la voix localement, choisit
un modèle local ou cloud, appelle des outils et répond à voix haute.

Le projet privilégie :

- une exécution locale dès que c'est raisonnable ;
- des intégrations facultatives qui échouent proprement ;
- une interaction vocale rapide et naturelle ;
- une séparation stricte entre raisonnement et actions réelles ;
- la confidentialité, la confirmation explicite et la maîtrise des coûts.

## Doctrine d'architecture

> **Hermes orchestre et pense ; Jarvis détient les clés et le corps.**

- **Hermes** : analyse longue, recherche, synthèse, planification, tâches de fond
  et brouillons.
- **Jarvis** : micro, caméra, écran, domotique, navigateur connecté, matériel,
  credentials, confirmations et exécution réelle.
- Hermes ne reçoit jamais les credentials de Jarvis et n'exécute jamais une
  action sensible directement.
- Une procédure Hermes récurrente, stable et éprouvée peut devenir une skill.

## Carte du dépôt

- `jarvis14.py` : point d'entrée principal de l'assistant vocal.
- `core/` : orchestration, configuration, voix, LLM, routage, sécurité, serveur,
  HUD, Hermes, satellites et services transverses.
- `tools/` : capacités appelables par le LLM, généralement une par fichier.
- `core/registre.py` : décorateur `@outil`, découverte des outils et permissions.
- `hud.py` et `hud.html` : interface locale principale.
- `web/` : interfaces web et ressources visuelles.
- `scripts/` : installation, diagnostic, automatisation et maintenance.
- `docs/` : guides par intégration.
- `tests/` : tests unitaires et de sécurité ciblés.
- `config.example.yaml` : schéma public et générique de la configuration.
- `config.yaml` : configuration locale privée, jamais versionnée.

## Ajouter ou modifier un outil

Une nouvelle capacité se place normalement dans `tools/<nom>.py` avec le
décorateur `@outil(...)`. Copier le style d'un outil voisin et :

1. décrire précisément quand l'outil doit être utilisé ;
2. définir un schéma de paramètres strict ;
3. choisir le bon niveau de confirmation ;
4. ne jamais coder de credential en dur ;
5. éviter `mcp_expose=True` sauf pour une lecture explicitement sûre ;
6. ajouter des tests et une documentation généraliste.

## Permissions non négociables

| Niveau | Nature | Confirmation | Accès distant | Autorisation permanente |
|---|---|---|---|---|
| N1 | lecture ou action locale sûre | non | possible si explicitement prévu | sans objet |
| N2 | action sensible mais réversible | oui | non par défaut | mémorisable et révocable |
| N3 | action critique, externe ou difficile à annuler | toujours | jamais | jamais |

Les mails, appels, réservations, paiements, suppressions importantes et
extinctions sont des actions N3. Ne jamais affaiblir ce verrou pour simplifier
une intégration ou un test.

Micro, caméra, gestes, Alexa, lumières et données financières ne doivent jamais
être exposés au MCP par commodité.

## Secrets et données locales

- Ne jamais lire, copier, afficher, modifier ou versionner
  `.claude/settings.local.json`.
- Ne jamais publier `config.yaml`, `.env`, OAuth, cookies, journaux, mémoires,
  notes, finances, inventaires, transcriptions, IP/MAC privées ou chemins
  personnels.
- Ne jamais demander à l'utilisatrice de coller une clé dans le chat.
- Les nouvelles clés publiques d'exemple vont dans `config.example.yaml` avec
  des valeurs factices ; les vraies valeurs restent dans `config.yaml`.
- Avant chaque commit public, scanner le diff pour les secrets et les données
  personnelles.

## Modes et fournisseurs

- `local` : Ollama et voix locale, sans API cloud.
- `hybride` : modèle quotidien économique, avec délégation des tâches longues à
  Hermes.
- `qualite` : meilleur modèle cloud configuré pour les demandes exigeantes.

Le choix du LLM et celui de la voix sont indépendants. OpenAI et Anthropic sont
intégrés ; les autres fournisseurs doivent être ajoutés sous forme de
connecteurs optionnels, avec suivi des coûts et repli propre.

## État fonctionnel utile

Les socles suivants existent déjà : voix, wake word, outils, HUD/panneau local,
permissions N1/N2/N3, routage local/hybride/qualité, Hermes, satellites audio,
gestes webcam, overlay, Alexa, Spotify, agenda, navigateur, Signal Matin,
cockpit, hub et suivi de contenu.

Ne pas réécrire un sous-système avant d'avoir inspecté son implémentation et ses
tests. Certaines intégrations peuvent être codées mais encore en attente d'une
validation sur un compte ou un matériel réel.

## Priorités actuelles

1. Valider le fournisseur OpenAI depuis le HUD avec une clé placée uniquement
   dans `config.yaml`.
2. Valider une voix ElevenLabs réelle depuis le tiroir de configuration.
3. Consolider le satellite audio Raspberry/Linux sur voix réelle.
4. Reprendre ensuite le backlog uniquement à la demande explicite.

Une roadmap n'est jamais une autorisation à implémenter toutes ses phases.

## Commandes de travail

Installation et lancement :

```powershell
uv sync
uv run playwright install chromium
uv run python jarvis14.py
```

Tests :

```powershell
uv run pytest
uv run pytest tests/test_nom_du_module.py -q
```

Pour un changement ciblé, commencer par les tests du sous-système concerné,
puis élargir si le risque le justifie. Ne jamais lancer une impression, un
appel, un mail, une réservation, une commande domotique ou une action matérielle
pendant les tests sans autorisation explicite.

## Méthode de travail attendue

1. Lire la demande puis inspecter uniquement les fichiers utiles.
2. Préserver les modifications existantes, même non commitées.
3. Expliquer brièvement l'hypothèse retenue si la demande est ambiguë.
4. Faire une modification ciblée et cohérente avec le code voisin.
5. Ajouter ou adapter les tests pertinents.
6. Vérifier la sécurité, les permissions et les erreurs de repli.
7. Résumer le résultat en français, avec les fichiers et tests concernés.

Ne pas committer, pousser, publier, imprimer ou déclencher une action externe
sans demande explicite.

## Travail à plusieurs agents

Quand plusieurs agents (équipe ou sous-agents) travaillent en parallèle :

- Un agent = un périmètre de fichiers. Deux agents ne modifient jamais le même
  fichier.
- Fichiers partagés, modifiés par un seul agent à la fois (le chef par défaut) :
  `jarvis14.py`, `hud.py`, `hud.html`, `core/registre.py`, `core/routage.py`,
  `core/routage_intentions.py`, `config.example.yaml`, `README.md`,
  `README.en.md`, `CHANGELOG.md`, `pyproject.toml`, `requirements.txt`,
  `uv.lock`.
- Un nouvel outil, son test et sa documentation sont confiés au même agent.
- L'agent de relecture travaille en lecture seule.
- Les règles de permissions, de secrets et d'actions réelles ci-dessus
  s'appliquent à chaque agent, sans exception. Aucun agent ne committe ni ne
  pousse.
- Ce qui dépend du matériel (micro, satellites, webcam, lumières, imprimante) ne
  peut pas être validé par un agent : le signaler clairement dans le résumé.
