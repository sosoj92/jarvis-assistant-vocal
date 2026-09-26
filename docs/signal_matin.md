# Signal Matin

Signal Matin est le quotidien personnel A4 de Jarvis. Il transforme des sources
locales normalisees en un vrai objet editorial noir et blanc, puis en PDF. Le
renderer n'a acces a aucune API et ne connait aucun credential.

## Essai immediat

L'edition de demonstration est entierement fictive et explicitement marquee :

```powershell
uv run generate-morning-paper preview --demo
uv run generate-morning-paper generate --demo
```

Sorties locales, toutes ignorees par Git :

```text
output/data/AAAA-MM-JJ-signal-matin.json
output/preview/AAAA-MM-JJ-signal-matin.html
output/pdf/AAAA-MM-JJ-signal-matin.pdf
```

Pour les sources Jarvis reellement configurees :

```powershell
uv run generate-morning-paper preview
uv run generate-morning-paper generate
```

La provenance technique est conservee dans le JSON local de diagnostic, mais
n'est jamais imprimee dans le journal. Le lecteur ne voit que le contenu et les
attributions editoriales normales des articles. Une edition live ne remplace
jamais silencieusement une source absente par du texte fictif.

## Ce qui est reel et ce qui est simule

| Bloc | Source reelle | Repli |
|---|---|---|
| Meteo | Open-Meteo, sans cle | Bloc omis et marque indisponible. |
| Agenda | Google Agenda OAuth deja connecte | Bloc vide ; reconnexion signalee. |
| Actualites | Flux RSS declares dans `config.yaml`, relus a chaque generation | Jusqu'a 18 articles recents des flux publics du Monde, marques `repli public`. Les sujets trop anciens sont exclus. |
| Actualites tech | Flux tech dedies | Cahier separe alimente par les flux officiels Le Monde Pixels/IA/Culture web lorsque `flux_tech` est vide. |
| Priorites | `signal_matin.priorites` et `contenus.yaml` local | Bloc omis. |
| Rappels | `signal_matin.rappels` et echeances Loopstr | Bloc omis si le flux est absent. |
| Veille | Fichier local prepare par Hermes | Bloc omis. |
| E-mails | Gmail en lecture seule, sur opt-in | Exclus par defaut pour la vie privee. |
| Reseaux sociaux | Instagram Graph deja configure : abonnes, vues et nouvelles publications vs la veille | Bloc omis si le compte ou le jeton est indisponible. |
| Discord | Bot deja configure : volumes, mentions et salons les plus actifs sur 24 h | Aucun auteur ni contenu de message n'est imprime. |
| Mode `--demo` | Aucune source reelle | Toutes les rubriques sont explicitement marquees simulees. |

Les sorties personnelles (`output/data`, `output/preview`, `output/pdf`) et les
fichiers locaux (`config.yaml`, jetons Google, `contenus.yaml`) sont ignores par
Git. Le renderer PDF ne recoit que le JSON normalise et n'accede a aucun secret.

## Architecture

```text
sources Jarvis / RSS / mock
        |
        v
adaptateurs (sources.py)
        |
        v
MorningEdition valide (Pydantic)
        |
        +--> JSON versionne par schema
        |
        v
composants HTML semantiques + design system CSS
        |
        v
Chromium / Playwright -> PDF A4
        |
        v
backend d'impression explicite
```

- `models.py` contient le contrat de donnees. Une actualite factuelle doit avoir
  une source et conserve son URL et sa date lorsqu'elles existent.
- `sources.py` appelle les connecteurs Jarvis, puis normalise leurs retours.
- `renderer.py` compose uniquement un `MorningEdition` deja valide.
- `pdf.py` verifie les debordements avant de produire un A4 sans en-tetes de
  navigateur.
- `printer.py` ne peut imprimer que lors d'un appel explicite avec confirmation.

Les anciens `core/journal_matin.py`, `core/journal_pdf.py` et
`scripts/imprimer_journal_matin.py` sont conserves comme facades afin de ne pas
casser une automatisation existante.

## Densite adaptative

Le mode est choisi d'apres un score de contenu et peut etre force :

```powershell
uv run generate-morning-paper generate --demo --mode compact
uv run generate-morning-paper generate --demo --mode standard
uv run generate-morning-paper generate --demo --mode extended
```

| Mode | Pages | Usage |
|---|---:|---|
| COMPACT | 3 a 4 | Peu de contenu ; briefing, suite condensee et page ludique. |
| STANDARD | 7 a 8 | Deux cahiers d'actualites, Tech, journee, curiosites et pause. |
| EXTENDED | 7 a 8 | Edition riche avec journee et cahiers Tech/Veille entierement separes. |

Lorsqu'une rubrique **En bref** apparait en une, le journal ajoute automatiquement
un cahier juste apres la couverture. En STANDARD et EXTENDED, il occupe deux pages
de trois articles ; en COMPACT, une page. Les textes publics sont enrichis par le
modele cloud economique deja configure dans Jarvis, uniquement a partir du contenu
lu dans les articles. Si l'extraction ou le modele echoue, le resume RSS reste
affiche et la generation continue sans inventer de faits.

Les textes bruts des articles ne sont pas enregistres. Seule la synthese produite
est conservee dans le JSON de l'edition. Le proxy de lecture public n'est jamais
utilise pour un flux personnel sans `extracteur_public: true`.

Le cahier **Technologie & IA** possede sa propre collecte et ses syntheses
developpees. Le cahier **Veille & curiosites** donne davantage de place aux
sujets sciences/culture, au brief Hermes, aux lettres suivies et aux signaux
sociaux. La derniere page est produite localement : mots croises variables selon
la date, vocabulaire tech, mot francais et calcul mental. Elle ne consomme aucune
API.

Le moteur limite le nombre et la longueur des articles par composition. Il ne
retrecit pas arbitrairement le corps de texte pour faire rentrer trop de contenu.

## Configuration locale

Copier uniquement les options utiles de `config.example.yaml` dans le
`config.yaml` ignore par Git :

```yaml
signal_matin:
  actif: false
  declenchement: "desactive"
  heure: "08:00"
  imprimer: false
  recto_verso: false
  densite: "auto"
  imprimante: "Nom exact de la file Windows"
  agenda: true
  nombre_actualites: 12
  nombre_actualites_repli: 18
  actualites_age_max_heures: 48
  actualites_publiques_par_defaut: true
  actualites_detaillees: true
  nombre_actualites_detaillees: 6
  nombre_actualites_tech: 6
  nombre_actualites_tech_detaillees: 5
  nombre_curiosites_detaillees: 4
  tech_age_max_heures: 72
  modele_actualites: ""
  extracteur_public: false
  flux:
    - nom: "Nom du media"
      categorie: "Monde"
      url: "https://exemple.invalid/rss.xml"
  flux_tech: []
  suivi: true
  loopstr: true
  mails: false
  reseaux_sociaux: true
  discord: true
  discord_heures: 24
  priorites: []
  rappels: []
  hermes_fichier: ""
  salutation: "Bonjour."
  note: ""
```

Ne place jamais de notes, priorites, noms d'imprimante ou flux prives dans
`config.example.yaml`.

## JSON externe

Une autre automatisation peut produire le JSON, puis demander seulement le
rendu :

```powershell
uv run generate-morning-paper generate --input chemin\edition.json
```

Le fichier est valide par Pydantic avant tout rendu. Le schema est strict : les
champs inconnus sont refuses afin de detecter une integration devenue obsolete.

## Exemple d'integration dans une routine Jarvis

La commande est l'integration recommandee pour le Planificateur de taches. Un
outil Jarvis peut aussi appeler le pipeline directement, sans donner d'acces API
au renderer :

```python
from pathlib import Path

from core.signal_matin.normalizer import ecrire_edition
from core.signal_matin.pdf import generer_pdf
from core.signal_matin.sources import construire_edition_live

edition = construire_edition_live(mode="auto")
nom = f"{edition.edition.date.isoformat()}-signal-matin"
ecrire_edition(edition, Path("output/data") / f"{nom}.json")
generer_pdf(
    edition,
    Path("output/pdf") / f"{nom}.pdf",
    html_path=Path("output/preview") / f"{nom}.html",
)
```

`construire_edition_live` est la seule partie qui dialogue avec les connecteurs
Jarvis. `generer_pdf` ne recoit qu'un objet valide et n'a acces ni aux cles ni
aux comptes externes.

## Preview et iteration graphique

`preview` ecrit un HTML autonome et l'ouvre dans le navigateur. Le CSS est dans
`web/signal_matin.css`. La priorite est le media `print` A4 ; la vue desktop sert
uniquement d'atelier graphique.

## Impression

La generation n'imprime jamais. Pour preparer un travail sans l'envoyer :

```powershell
uv run generate-morning-paper print --demo
```

Pour envoyer reellement le PDF a la file configuree :

```powershell
uv run generate-morning-paper print --confirm
```

Pour une edition en recto verso, bord long :

```powershell
uv run generate-morning-paper print --confirm --duplex
```

S'il existe plusieurs imprimantes physiques, `signal_matin.imprimante` devient
obligatoire. Aucune imprimante par defaut n'est modifiee.

## Deux modes d'automatisation

Les deux modes sont exclusifs. Dans les deux cas, les donnees sont recollectees
juste avant la composition : le journal ne reutilise pas les actualites de la
veille.

### 1. Machine disponible 24 h/24 : heure fixe

La tache est creee en **generation seule** par defaut :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\installer_journal_matin.ps1 -Heure "07:00"
```

L'impression quotidienne doit etre demandee explicitement apres validation sur
papier :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\installer_journal_matin.ps1 -Heure "07:00" -Imprimer
```

Une file peut etre verrouillee explicitement et le PC est reveille si Windows et
le materiel l'autorisent :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\installer_journal_matin.ps1 `
  -Heure "08:00" -Imprimer -RectoVerso -Imprimante "Nom exact de la file Windows"
```

La tache appelle `print` sans fichier `--input` : elle recollecte donc la meteo,
l'agenda, les actualites generales, les actualites tech et les autres sources a
chaque execution, juste avant de composer puis d'imprimer l'edition du jour.

### 2. PC eteint la nuit : premier brief du jour

Ce mode ne cree aucune tache planifiee. Il attend le premier demarrage de Jarvis
qui annonce le brief quotidien, puis genere et imprime en arriere-plan :

```yaml
signal_matin:
  actif: true
  declenchement: "premier_demarrage"
  imprimer: true
  recto_verso: true
  imprimante: "Nom exact de la file Windows"
```

Le marqueur quotidien est conserve localement dans `notes/`, qui est ignore par
Git. Fermer puis relancer Jarvis le meme jour ne relance ni le brief ni
l'impression. Meme une scene de demarrage forcee ne peut pas creer de second
travail d'impression ce jour-la. Le lendemain, le verrou est automatiquement
libere.

Le script peut afficher le bloc de configuration correspondant sans modifier le
fichier prive `config.yaml` :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\installer_journal_matin.ps1 `
  -Mode premier_demarrage -RectoVerso -Imprimante "Nom exact de la file Windows"
```

Pour revenir au mode fixe, laisser `declenchement: "horaire"` (ou `desactive`,
car la tache Windows est autonome) et installer la tache planifiee. Ne pas
activer simultanement `premier_demarrage` et une tache quotidienne d'impression.

## Tests

```powershell
uv run python -m unittest tests.test_signal_matin tests.test_journal_matin -v
```

Les tests verifient le schema, les sections vides, les trois densites, les
debordements Chromium, le nombre de pages et les dimensions A4 du PDF.

## Limites actuelles

- Le contenu des articles RSS est limite au titre et au resume fournis par le
  media ; Signal Matin ne contourne ni abonnement ni paywall.
- Les e-mails restent optionnels et desactives par defaut. Quand ils sont actifs,
  seuls les trois derniers expediteurs et objets alimentent le digest.
- Les illustrations sont locales et decoratives. Leur legende rappelle que les
  faits viennent de la source citee, pas de l'image.
