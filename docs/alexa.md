# Alexa / Amazon Echo (via API non officielle)

> **✅ Fonctionne** (annonces, média, contrôle d'appareils via Routines) **mais via
> `alexapy`, une lib communautaire non officielle** (c'est ce qu'utilise Home
> Assistant). L'accès repose sur une session au compte Amazon : Amazon peut le
> casser à tout moment — si ça arrive, relance `python scripts/alexa_login.py`.
> Retours bienvenus via les
> [issues](https://github.com/sosoj92/jarvis-assistant-vocal/issues).

## Le choix d'API et ses limites (honnête)

Amazon n'a **aucune API officielle** pour *piloter* tes appareils Alexa depuis un
tiers. La seule voie viable est **`alexapy`** : login sur ton compte Amazon (cookie +
2FA), puis pilotage des **Echo**. Conséquences :

- ✅ Faire **parler** un Echo (annonce / TTS), contrôler le **média** (play/pause/volume),
  **lister** les Echo, et **déclencher une Routine**.
- 🔁 **Contrôle des appareils (lumières, prises…) = indirect, via Routines.** Tu crées
  dans l'app Alexa une routine avec un énoncé (« lumière salon on ») qui fait l'action,
  et Jarvis la déclenche par son nom. C'est le contournement standard (pas de contrôle
  direct on/off/luminosité par API).
- ⚠️ **Fragile** : si Amazon change son login, l'accès casse → relancer la connexion.

## Les outils

| Outil | Niveau | Effet |
|---|---|---|
| `alexa_etat` | N1 | Liste les Echo + en ligne / hors ligne |
| `alexa_annoncer` | N1 | Fait parler un Echo (TTS sur un appareil, ou annonce sur tous) |
| `alexa_media` | N1 | play / pause / volume sur un Echo |
| `alexa_appareil` | N1 | **« allume la clim », « éteins la télé »** → déclenche la routine correspondante (retrouvée parmi les tiennes, tolérant accents/pluriels/synonymes tv↔télé) |
| `alexa_routine` | **N2** | Déclenche une Routine par son énoncé exact *(confirmation — une routine peut être impactante)* |

---

## Mise en route

### 1. 2FA Amazon (fortement recommandé)
Active la **validation en deux étapes** sur ton compte Amazon avec une **appli
d'authentification** (pas seulement SMS). Lors de la configuration, Amazon affiche une
**clé secrète** (la « graine » TOTP, une longue chaîne). **Note-la** : mise dans
`alexa.otp_secret`, `alexapy` génère le code 2FA tout seul → reconnexion sans
intervention. *(Sans elle, tu devras saisir le code 2FA à chaque reconnexion.)*

### 2. `config.yaml`
```yaml
alexa:
  email: "ton.email@exemple.fr"
  password: "ton-mot-de-passe-amazon"
  otp_secret: "LA-GRAINE-TOTP"     # optionnel mais recommandé
  url: "amazon.fr"                 # ou amazon.com, amazon.de...
```

### 3. Connexion assistée par navigateur (une fois)
Amazon a fermé le login « headless » par identifiants ; on passe donc par un **proxy
local** (la méthode de Home Assistant) : tu te connectes **normalement dans ton
navigateur**, le proxy capture la session.

```bash
uv run python scripts/alexa_login.py
```
Le script affiche une adresse **`http://127.0.0.1:3000`** → **ouvre-la dans ton
navigateur, sur ce PC**. Le proxy de connexion n'écoute que sur `127.0.0.1` : il
faut l'ouvrir depuis le PC où tourne `scripts/alexa_login.py`. Sur une machine
sans écran (H24), ouvre l'URL à travers un tunnel
`ssh -L 3000:127.0.0.1:3000 <compte>@<machine>`, jamais par l'adresse IP du réseau
local. Connecte-toi à Amazon comme d'habitude (email/mot de passe
**pré-remplis**, puis **captcha / 2FA** dans le navigateur). **Va jusqu'à la page
« Successfully logged in »** : c'est ce moment qui capture la session. Le script
enregistre alors l'appareil et **sauvegarde les tokens OAuth durables**
(`refresh_token`, dans `logs/alexa/.storage/`, gitignoré), puis **vérifie** qu'une
session neuve fonctionne. Redémarre Jarvis : **« Jarvis, mes appareils Alexa »**.

> **Pourquoi OAuth et pas juste un cookie ?** Le cookie seul ne réauthentifie pas
> l'API Alexa au redémarrage. La voie réutilisable est le **`refresh_token`**
> (obtenu par `get_tokens()` après login) : Jarvis reconstruit une session neuve à
> chaque démarrage sans re-login. C'est ce que le script sauve et réinjecte.

Vérifier l'état **sans se reconnecter** :
```bash
uv run python scripts/alexa_login.py --check   # rejoue le vrai chemin runtime + liste les Echo
uv run python scripts/alexa_login.py --code    # un code TOTP frais, à taper si l'auto-remplissage rate
```

**2FA qui boucle sur la connexion ?** Deux causes traitées par le script : le code
TOTP figé/périmé (régénéré à chaque page maintenant) et SMS/WhatsApp qui ne passe
pas par le proxy (choisis **« appli d'authentification »**). Au pire, désactive la
2FA le temps du login puis **réactive-la après** — le token capturé reste valide.

*(Port occupé ? change `alexa.proxy_port` dans `config.yaml`.)*

### 4. Contrôler tes appareils (lumières, clim, TV…) via des Routines
Dans l'app **Alexa → Plus → Routines → +** : crée une routine, **nomme-la** comme ce
que tu diras (ex. `clim on`), déclencheur **« Quand vous dites… »** (`clim on`),
action **« Maison connectée »** → l'appareil. Fais-en une pour `clim off`.

Ensuite, **deux façons** de la déclencher :
- **Naturel** : **« Jarvis, allume la clim »**, **« éteins la télé »**, **« allume
  les lumières du salon »** → Jarvis retrouve la routine (`alexa_appareil`).
- **Explicite** : **« Jarvis, lance la routine clim on »** (`alexa_routine`).

Avec `alexa.routage_prioritaire: true` (valeur par défaut), ces formulations sont
reconnues **avant le LLM** : Jarvis ne peut donc plus choisir Hue ou répondre en
texte à la place. Les noms et énoncés des routines sont préchargés au démarrage ;
une routine peut aussi être prononcée directement, par exemple « bonne nuit ».
Mettre ce réglage à `false` rend le choix au modèle.

> **⚠️ La routine doit exister** avec un nom qui matche. `alexapy` échoue **en
> silence** si aucune routine ne correspond — Jarvis te le dit maintenant
> honnêtement, sans réciter ni afficher toute la liste de tes routines.
> **Convention conseillée** : nomme `<appareil> on` / `<appareil> off` en minuscules
> et sans accents (`clim on`, `salon off`, `tele on`). Jarvis tolère les accents,
> pluriels et synonymes courants (tv↔télé, lumière↔lampe), mais des noms simples
> évitent tout raté.

---

## Dépannage

- **« Connexion Alexa requise »** dans un outil → relance `python scripts/alexa_login.py`
  (le cookie a expiré ou l'auth a changé).
- **Captcha en boucle** → connecte-toi d'abord au site Amazon dans un navigateur
  (même IP), puis relance le script.
- **2FA demandé à chaque fois** → renseigne `alexa.otp_secret` (graine TOTP).
- **`amazon.com` vs `amazon.fr`** → mets le **domaine de ton compte** dans `alexa.url`.
- **Rien ne parle** → l'appareil ciblé n'est pas un Echo « qui parle », ou hors ligne
  (`alexa_etat` pour vérifier).

## Sécurité

Identifiants **uniquement dans `config.yaml`** (gitignoré) ; le cookie **et les
tokens OAuth** de session (`logs/alexa/.storage/*.oauth.json`) sont sous `logs/`
(gitignoré). Traite `password`, `otp_secret` **et le `refresh_token`** comme des
secrets. Les outils sont **N1/N2** (jamais N3) et **non exposés au MCP** — Alexa
n'est pas pilotable à distance ni par Hermes.
