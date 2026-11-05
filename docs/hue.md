# Philips Hue

Contrôle des lumières Hue par la voix, via l'**API locale** du pont (aucun cloud).

- `allumer_lumiere` — « allume la chambre », « éteins le séjour »
- `regler_luminosite` — « mets le salon à 30 % »
- `changer_couleur` — « passe la chambre en orange »
- Ambiances/scènes via `activer_mode` (voir la section `modes` de `config.yaml`).

## Configuration

```yaml
hue:
  pont: "192.168.1.XXX"   # adresse IP de ton pont Hue sur le réseau
  cle: "ta-cle-hue"       # clé d'API générée par le pont
```

### 1. Trouver l'IP du pont
Ouvre [discovery.meethue.com](https://discovery.meethue.com) sur le même réseau, ou
regarde dans l'app Hue → Paramètres → Ponts. Note l'adresse `192.168.x.x`.

### 2. Générer une clé
1. **Appuie sur le bouton rond** du pont Hue (le gros bouton central).
2. Dans les **30 secondes**, envoie une requête pour créer un utilisateur :
   ```bash
   curl -X POST http://<IP_DU_PONT>/api -d "{\"devicetype\":\"jarvis#pc\"}"
   ```
   La réponse contient `"username": "..."` → c'est ta `cle`. Ne partage jamais
   cette réponse (ni dans une IA, ni dans une capture d'écran) : c'est la clé du pont.
3. Mets l'IP et la clé dans `config.yaml`.

Sans ces réglages, les outils Hue se désactivent proprement (le reste fonctionne).

## Noms de pièces
Jarvis lit les noms de pièces/salons définis dans ton app Hue et fait une
correspondance approximative. Dis les noms tels qu'ils apparaissent dans l'app
(« Séjour », « Chambre à coucher »…). Astuce : renomme tes pièces avec des noms
simples pour que la reconnaissance vocale tombe juste.
