# Cockpit (tableau de bord perso)

Une **app web locale** servie par le serveur unifié de Jarvis, ouverte en **fenêtre
app** (`--app`, sans barre de navigateur) sur l'écran de ton choix. **Local-only** par
défaut (même garde que le panneau) : rien ne sort, aucune donnée exposée au MCP.

> **Doctrine** : Jarvis détient les clés et le corps — **toutes les données restent
> locales** (`finances/`, gitignoré). Hermes ne reçoit que des **agrégats**, sur
> demande (bilan mensuel — phase ultérieure). **Jamais** de credentials bancaires,
> **aucune** API d'agrégation.

## Activer

```yaml
cockpit:
  actif: true
  ecran: 0          # 0 = principal, 1 = 2e écran…
  navigateur: ""    # chemin chrome/edge ; vide = auto-détection
```

Au démarrage de Jarvis, le cockpit s'ouvre en fenêtre app. Sinon, à la main :
`http://localhost:8790/cockpit` (accessible uniquement depuis ce PC).

## Volet Finances (Phase 1 — disponible)

Copie l'exemple puis édite-le :
```
finances/abonnements.example.yaml  →  finances/abonnements.yaml
```
Chaque abonnement : `service`, `montant` (€), `periodicite` (mensuel / annuel /
trimestriel / semestriel / hebdomadaire), `jour` (jour du mois, pour le mensuel) **ou**
`date` (AAAA-MM-JJ d'ancrage), `categorie`.

- La périodicité **hebdomadaire** exige une `date` d'ancrage (`jour` n'est pas
  utilisé) : sans elle, l'échéance reste calculée au mois.
- Les montants acceptent `9.99`, `9,99` et `9,99 €`.
- Une ligne illisible est ignorée, avec une alerte qui la signale.

Le cockpit affiche :
- **Total mensuel** (les annuels/trimestriels sont ramenés au mois) et l'équivalent annuel ;
- **Timeline des prochaines échéances** (triée), avec « demain / dans N j » ;
- **Alertes** : ⏰ **prélèvement demain**, 🔔 **montant changé** (comparé à la dernière
  valeur vue, affichée pendant 7 jours) ;
- **Répartition par catégorie**.

### Détection automatique par mail (recommandé)

« **Jarvis, détecte mes abonnements** » (`detecter_abonnements`) : scanne tes **reçus
Gmail** (Apple, Netflix, Spotify, Adobe…) des derniers mois, en déduit service +
montant + périodicité, et écrit une **proposition** dans
`finances/abonnements_detectes.yaml` (revue, jamais d'écrasement). Puis « **intègre-les** »
(`integrer_abonnements_detectes`, **confirmation**) les ajoute à `abonnements.yaml`
sans toucher à tes entrées manuelles.

Avantages (fidèle à la doctrine) : **aucun credential bancaire, aucune API
d'agrégation** — ça passe par ton Gmail déjà connecté (IMAP), 100 % local. Attrape
même les **abonnements Apple** (que le relevé bancaire regroupe en une seule ligne).
C'est **heuristique** → d'où la revue avant intégration.

### Transactions : import CSV (dispo) + PSD2 (à venir)

Au-delà des abonnements, le cockpit suit tes **dépenses/rentrées** :

- **Import CSV** (dispo) : dépose l'export de ta banque dans `finances/releves/` puis
  « **Jarvis, importe mon relevé** » (`importer_releve`). Détection auto du séparateur
  et des colonnes (date / libellé / montant, ou débit+crédit). Stocké dans
  `finances/transactions.jsonl` (gitignoré).
- **Catégorisation** : règles par défaut (Courses, Restauration, Transport, Énergie,
  Abonnements…) + tes **corrections mémorisées** (« range Uber en Transport » →
  `corriger_categorie`, **rétroactif**). Vue **mois** entrées/sorties par catégorie.
- **Abonnements depuis les transactions** : un prélèvement qui **revient** chaque mois
  = un abonnement, avec **montant et date exacts** (plus fiable que les mails). Affiché
  dans le cockpit ; la détection par mail reste en complément.

**Banque en automatique (PSD2)** — honnêteté : le service gratuit **GoCardless Bank
Account Data (ex-Nordigen) a fermé ses inscriptions**. L'équivalent self-serve retenu
est **Enable Banking** (PSD2, banques FR). Le flux : Jarvis génère un lien, **tu
t'authentifies SUR LE SITE DE TA BANQUE** (SCA — jamais via Jarvis), un **token de
lecture seule** revient et est stocké en config ; un cron quotidien synchronise les
transactions en local. **Aucun mot de passe bancaire ne vit chez Jarvis.** Les
consentements PSD2 **expirent** (~90-180 j) → alerte claire pour re-consentir, jamais
de panne silencieuse. *(Connecteur Enable Banking : en cours — l'import CSV reste le
fallback si le fournisseur tombe ou si tu révoques.)*

> **Doctrine transactions** : `finances/` gitignoré, **jamais exposé au MCP**
> (`mcp_expose=False`). Hermes ne reçoit que des **agrégats** (bilan mensuel), jamais
> le détail des transactions.

## À venir (phases suivantes)

- **⚡ Énergie (N16)** : futur adaptateur indépendant du fabricant pour une prise ou
  un compteur disposant d'une API locale. Il séparera la **lecture de consommation**
  (W instantanés, kWh jour/mois) du contrôle d'alimentation. Aucun modèle de prise
  n'est supposé présent et aucun cycle automatique n'est encore implémenté. Voir les
  contraintes de sécurité dans [wol.md](wol.md).
- **📈 Réseaux** : Insta (tokens existants), Twitch/YouTube plus tard.
- **🎬 Contenu** : pipeline `contenus.yaml`, deadlines Loopstr, inspirations du Vault.
- **🏠 Maison/Système** : liens vers `/panneau` (état chaîne, budgets) — intégré, pas dupliqué.
- **🧠 Bilan mensuel Hermes** : cron optionnel → Hermes reçoit les **agrégats** →
  analyse envoyée sur Telegram.

## Vie privée

- Dossier `finances/` **entièrement gitignoré** (seul `abonnements.example.yaml` est
  versionné) — rien ne part vers le repo public.
- **Accès distant désactivé** par défaut (garde local-only). Une éventuelle activation
  distante authentifiée appartient à une phase ultérieure.
- Aucune donnée financière n'est exposée au MCP ni envoyée à Hermes, sauf agrégats sur demande.
