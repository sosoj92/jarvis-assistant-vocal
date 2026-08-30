# Politique de sécurité

Merci de contribuer à la sécurité de ce projet. Jarvis est un assistant vocal
qui **détient des identifiants** (clés API, tokens) et **pilote la machine**
(domotique, souris/clavier, extinction du PC) : les vulnérabilités sont prises
au sérieux.

## Signaler une vulnérabilité

**Ne créez PAS d'issue publique pour une faille de sécurité.** Utilisez un canal
privé :

1. **De préférence** — GitHub *Private vulnerability reporting* : onglet
   **Security → Report a vulnerability** de ce dépôt. Le rapport reste privé
   jusqu'à ce qu'un correctif soit publié.
2. À défaut, ouvrez une issue **sans aucun détail technique** demandant un canal
   de contact privé (comme l'a fait la communauté), et nous conviendrons d'un
   moyen (e-mail, clé PGP).

Merci d'inclure si possible : description, étapes de reproduction, impact estimé,
et une suggestion de correctif.

## Divulgation coordonnée

Nous nous engageons à :

- **accuser réception** rapidement et vous tenir informé·e ;
- **corriger** en priorité selon la sévérité ;
- ne rien exposer publiquement **avant** qu'un correctif soit disponible, sauf
  accord mutuel ;
- **créditer** les personnes qui le souhaitent (GitHub Security Advisory, avec
  CVE si pertinent).

Ce projet est un projet personnel sans programme de bug bounty : pas de
récompense financière, mais une vraie reconnaissance et un traitement sérieux.

## Périmètre & bonnes pratiques côté utilisateur

- Les secrets vivent **uniquement** dans `config.yaml` (jamais versionné). Ne
  committez jamais votre `config.yaml`, vos tokens Google, `budget.json`, ni le
  dossier `finances/`.
- Le serveur web local écoute par défaut sur **127.0.0.1** (loopback) : ne le
  passez sur `0.0.0.0` (`serveur.host`) que si vous comprenez l'exposition réseau.
- Le pont iPhone et les appels sortants passent par un **token/secret** :
  gardez-les secrets et régénérez-les au moindre doute.
