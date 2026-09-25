# Poste principal Windows avec serveur Jarvis sans écran

Cette installation sépare Jarvis en deux machines :

- **ancien PC** : serveur 24 h/24, sans écran, clavier ni souris ; il héberge
  Jarvis, Hermes, les modèles, les clés et les confirmations ;
- **nouveau PC** : corps principal ; il porte l'écran, la webcam, le micro, les
  enceintes/Bluetooth, Chrome, Spotify, OBS, les gestes et les actions Astra.

L'écran actuellement branché à l'ancien PC doit être déplacé physiquement vers
le nouveau PC. Dans Windows, choisir **Étendre ces affichages** : le moniteur
habituel du nouveau PC reste principal et l'écran déplacé devient le deuxième
écran. Aucun écran n'est attendu sur l'ancien PC.

L'agent du nouveau PC ouvre lui-même deux WebSockets vers l'ancien PC. Il ne
demande donc aucun port entrant sur le nouveau PC. Le listener de l'ancien PC
n'expose que `/desktop-agent` et `/satellite` sur le LAN, avec un token différent
pour chaque usage. Il n'existe aucune action shell distante.

## 1. Préparer sur l'ancien PC

Dans le dépôt Jarvis :

```powershell
python scripts/preparer_poste_principal.py
```

Le script détecte l'adresse LAN, active `poste_principal`, ajoute les entrées
privées à `config.yaml` et crée `desktop_agent/config.yaml`. Les secrets ne sont
ni affichés ni suivis par Git.

Si les deux PC communiquent avec Tailscale, donner plutôt l'adresse Tailscale
stable de l'ancien PC :

```powershell
python scripts/preparer_poste_principal.py --host 100.x.y.z
```

Redémarrer Jarvis sur l'ancien PC après cette étape.

## 2. Installer sur le nouveau PC

1. Cloner ou copier tout le dépôt Jarvis sur le nouveau PC.
2. Copier **séparément et de manière privée** le fichier
   `desktop_agent/config.yaml` créé sur l'ancien PC vers le même emplacement du
   dépôt sur le nouveau PC. Ne jamais l'envoyer sur GitHub.
3. Ouvrir PowerShell dans le dépôt puis lancer :

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop_agent\install_autostart.ps1
```

Le script crée un environnement Python isolé, installe les dépendances et ajoute
`Jarvis-Bureau.cmd` au dossier de démarrage Windows. Il prépare également
l'environnement MediaPipe isolé utilisé par les gestes. L'agent se reconnecte
tout seul après une coupure réseau ou un redémarrage.

Si les gestes ne doivent pas être installés tout de suite, utiliser
`-SkipGestures`. Ils pourront être préparés plus tard avec
`python scripts/setup_gestes.py`.

Pour le navigateur pilotable, lancer une fois :

```powershell
.\desktop_agent\.venv\Scripts\python.exe -m playwright install chromium
```

Chrome installé normalement suffit pour ouvrir des pages. Le navigateur
Playwright/CDP est requis seulement pour lire et manipuler les onglets.

## 3. Audio et Bluetooth

Avec `audio.haut_parleur: null`, chaque réponse de Jarvis utilise la sortie
Windows active au moment de la lecture. Passer manuellement des enceintes au
casque Bluetooth ne demande donc aucune modification côté serveur.

Les commandes « monte le son », « pause », « morceau suivant » et Spotify sont
également exécutées sur le nouveau PC. Des alias fixes restent possibles sous
`audio.sorties` dans `desktop_agent/config.yaml`.

L'écran déplacé de l'ancien PC est préconfiguré comme **deuxième écran** du
nouveau PC (`overlay.ecran: 1`). L'overlay Jarvis y apparaît, tandis que les
gestes et Astra travaillent sur l'écran principal par défaut. Ces deux choix
restent modifiables séparément dans la configuration privée de l'agent.
Une demande Astra qui précise « sur le deuxième écran » ou « sur l'écran
secondaire » capture et pilote toutefois ce deuxième moniteur.

Attention aux index : l'overlay numérote `0 = principal, 1 = deuxième écran`,
alors que la capture et la souris numérotent `1 = principal, 2 = deuxième écran`.
Les valeurs livrées sont donc intentionnellement différentes.

## 4. Fonctionnement sans écran de l'ancien PC

L'ancien PC peut fonctionner capot fermé ou écran éteint à condition que :

- la veille et l'hibernation soient désactivées ;
- Hyper-V et la VM `Jarvis-Server` démarrent automatiquement ;
- la session Windows nécessaire au Jarvis hôte soit ouverte automatiquement ou
  que son lancement soit assuré par une tâche planifiée adaptée ;
- Ethernet soit privilégié pour la stabilité.

Une fois les deux agents marqués « connecté », écran, souris et clavier peuvent
être retirés de l'ancien PC. Ils restent nécessaires sur le nouveau PC pour les
actions visuelles.

Le mode serveur sans périphériques empêche le Jarvis de l'ancien PC d'ouvrir son
HUD, sa caméra, ses gestes ou son micro. Il ne tente donc jamais d'utiliser le
moniteur secondaire du nouveau PC comme s'il était encore branché localement.

## Sécurité

Les permissions restent décidées sur l'ancien PC. Une action N3 (contrôle Astra,
extinction, envoi, suppression, achat) conserve sa confirmation à chaque demande.
Le nouveau PC ne reçoit qu'une action structurée déjà autorisée ; jamais une
commande PowerShell, un terminal ou une clé API du serveur.
