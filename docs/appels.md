# Appels telephoniques (Twilio)

Jarvis peut passer un appel, jouer un message et te transcrire la reponse.

- `call_with_message(numero, message)` : appelle, se presente honnetement, dit ton
  message, enregistre la reponse, la transcrit (Whisper) et te la resume.
  Ex. « appelle le resto et demande s'ils sont ouverts ce soir ».
- `cout_appels` : « combien j'ai depense en appels ce mois ».

**V1** (ci-dessous) fonctionne **sans serveur public** : le TwiML est envoye en ligne
a la creation de l'appel, et l'enregistrement est recupere via l'API REST apres coup.

Ces outils **ne sont pas exposes via MCP** (passer des appels = sensible).

---

## 1. Creer le compte Twilio (pas a pas)

1. Va sur [twilio.com/try-twilio](https://www.twilio.com/try-twilio), cree un compte,
   verifie ton email et ton propre numero de portable.
2. Dans la console [console.twilio.com](https://console.twilio.com), note, section
   **Account Info** : ton **Account SID** (commence par `AC...`) et ton **Auth Token**.
3. **Achete un numero** : Phone Numbers -> Buy a number, avec la capacite **Voice**.
   - Pour un **numero francais**, Twilio demande un **Regulatory Bundle** (justificatif
     d'adresse) valide sous **1-2 jours**. C'est ce qui prend le plus de temps.
   - En attendant, tu peux tester avec un numero d'un autre pays (l'appel sortant
     fonctionne quand meme ; seul l'affichage du numero appelant change).
4. Mets tes valeurs dans `config.yaml` :

```yaml
twilio:
  account_sid: "AC...."
  auth_token: "....."
  numero: "+33....."   # ton numero Twilio (l'appelant)
```

> **Compte d'essai (trial)** : tant que tu n'as pas ajoute de credit, Twilio n'appelle
> **que des numeros que tu as verifies** dans la console, et ajoute un court message
> d'essai avant le tien. Pour appeler un vrai restaurant, il faut **crediter le compte**
> (passer en paye). Les identifiants et le code marchent pareil dans les deux cas.

## 2. Cout

- Appel sortant vers la France : ~0,10 a 0,20 EUR/min ; location du numero ~1 EUR/mois.
- Ajuste `appels.cout_par_minute` dans `config.yaml` selon tes tarifs Twilio reels.
- Jarvis tient un **compteur mensuel** (`logs/calls/compteur.json`) et l'annonce apres
  chaque appel ; demande « mes appels ce mois » quand tu veux.

## 3. Securite et ethique (integrees)

- **Confirmation vocale avant chaque appel** : Jarvis repete qui il appelle et pourquoi,
  et attend ton « oui ».
- **Presentation honnete** : l'appel commence toujours par « Bonjour, je suis l'assistant
  vocal automatise de [ton prenom]... ». Jamais de fausse identite humaine.
- **Numeros surtaxes bloques** (089x, numeros courts 3xxx / 118xxx / 10xx). Liste
  ajustable via `appels.prefixes_interdits`. Les surtaxes ne sont plus seulement
  francais : une liste de prefixes etrangers au format E.164 (ex. `+449`, `+882`)
  est aussi bloquee, en V1 comme en V2, et se remplace via
  `appels.prefixes_interdits_etrangers`.
- **Validation commune des numeros** (V1 et V2) : 8 a 15 chiffres, sans texte ;
  un numero mal forme est refuse avant toute preparation de l'appel.
- **Jamais** de donnees bancaires ou de mot de passe communiques.
- **Transcription** sauvegardee dans `logs/calls/` (gitignore) ; rien de plus n'est
  conserve de l'interlocuteur.

## 4. Utilisation

Par la voix, une fois configure :

> « Jarvis, appelle le 01 23 45 67 89 et demande s'ils ont une table pour deux ce soir. »

Jarvis : « Je vais appeler le +33123456789 et dire : "..." Tu confirmes ? » -> « oui » ->
il appelle, puis te resume la reponse transcrite.

---

## V2 — conversation temps reel

`call_and_book(numero, objectif, contraintes)` : Jarvis mene une **vraie
conversation**. Il se presente, expose la demande, comprend les reponses et negocie
dans les limites que tu donnes.

> « Jarvis, appelle le 01 23 45 67 89 et reserve une table pour 2 vendredi 20h,
>   pas apres 21h. »

Chaine : Twilio (mu-law 8kHz) -> Whisper -> modèle cloud (phrases courtes) -> ElevenLabs
(sortie ulaw_8000) -> Twilio. La V2 **exige une voix ElevenLabs** (`elevenlabs.cle`).

### Le serveur public (le point cle)

Twilio doit joindre un **serveur public** ; c'est le **serveur web unifie** de Jarvis
(le meme que le pont iPhone — un seul port, un seul tunnel, voir docs/iphone.md).
La route est `/stream` (WebSocket). Deux options dans `config.yaml` :

1. **Ton domaine ngrok statique** (recommande si tu en as un) :
   ```yaml
   serveur:
     public_url: "https://ton-domaine-statique.ngrok.app"   # sert /stream ET /api/inbox
   ```
   et lance le tunnel : `ngrok http --domain=ton-domaine-statique.ngrok.app 8790`.

2. **Tunnel ngrok automatique** (sans domaine statique) :
   ```yaml
   serveur:
     ngrok_authtoken: "ton_authtoken_ngrok"
   ```
   Jarvis ouvre le tunnel tout seul au moment de l'appel.

Sans l'un des deux, `call_and_book` te le dira et n'appellera pas. (Les anciennes cles
`twilio.public_url` / `twilio.ngrok_authtoken` restent lues en repli.)

### Cas geres

Repondeur (laisse un message court puis raccroche), attente/musique (patiente),
personne qui ne comprend pas (reformule puis propose un rappel), raccrochage. Jarvis
**ne confirme que ce que tu as valide** (l'objectif + les contraintes) ; tout imprevu
-> « je dois verifier, on vous rappelle ».

### Latence (honnete)

Chaque tour de parole enchaine : fin de phrase detectee (~0,7 s de silence) + Whisper
(~0,3-0,8 s) + modèle cloud (~0,5-2 s) + ElevenLabs (~0,3-0,8 s). En pratique, compte
**~2 a 4 secondes** avant que Jarvis reponde — correct pour une reservation, mais pas
le « moins de 2 s » vise dans l'absolu. Le moteur est teste en local de bout en bout ;
la latence reelle depend de ton GPU et de ta connexion. Reglages utiles :
`appels.silence_fin_ms` (reactivite) et `appels.seuil_voix` (sensibilite au bruit).
