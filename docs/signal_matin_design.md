# Design system - Signal Matin

## Intention

Un quotidien personnel contemporain : autorite typographique d'un journal,
respiration d'un magazine et chaleur d'un objet que l'on garde sur la table. Le
document ne reprend aucune identite de presse existante.

## Format et grille

- A4 portrait exact : 210 x 297 mm.
- Blanc tournant : 13 mm lateral, 10 mm haut, 13 mm bas.
- Zone utile : 184 x 274 mm, pied de page reserve.
- Page 1 : deux colonnes asymetriques, 1 / 1,55.
- Pages editoriales : deux ou trois colonnes selon la rubrique.
- Gouttiere : 5 mm ; filet fin entre colonnes quand il renforce la lecture.

## Typographie

- Masthead et titres : `Georgia`, puis `Times New Roman` ou `Liberation Serif`.
- Corps : la meme famille serif pour garder une couleur editoriale homogene.
- Metadonnees : `Arial`, `Helvetica Neue` ou `Liberation Sans`.
- Corps courant : 8,4 a 10 pt selon le role, jamais compresse pour sauver une page.
- Metadonnees : 5,7 a 6,7 pt, courtes, en capitales espacees.
- Titres : interlettrage legerement negatif, interligne serre mais non chevauche.

Ces polices sont utilisees via des piles locales. Chromium les incorpore au PDF
depuis la machine de rendu ; aucune police distante n'est chargee.

## Couleur et contraste

- Encre principale : presque noir `#151515`.
- Papier : blanc chaud `#fbfaf6`, rendu blanc en l'absence de fonds imprimes.
- Gris utilitaire : `#5e5e5b`.
- Fonds rares : `#eeede8` et `#d5d4cf`.
- Aucune information ne depend d'une couleur. Importance = graisse, ordre et filet.

## Rythme

- Unite courte : 1,2 a 1,7 mm pour separer une meta de son contenu.
- Unite moyenne : 2,5 a 3 mm pour l'interieur d'un module.
- Unite longue : 4,5 a 5 mm entre rubriques.
- Tous les titres et modules sont proteges contre les coupures de page.

## Filets et encadres

- Filet fin : 0,25 mm, separateur de lignes ou de colonnes.
- Filet fort : 0,45 mm, ouverture de rubrique et structure du masthead.
- Pas d'ombres, pas de grands arrondis, pas de cartes flottantes.
- Les fonds gris servent uniquement a marquer un changement de registre.

## Densite

- COMPACT : 2 pages, ou 3 avec la page de developpement des breves.
- STANDARD : 3 pages, ou 4 avec la page de developpement des breves.
- EXTENDED : 4 pages, ou 5 avec la page de developpement des breves.
- Le renderer tronque proprement les resumes selon des limites connues et reduit
  le nombre d'items avant d'envisager un changement de taille de texte.

## Illustrations

- Noir et blanc, line art, gravure contemporaine ou diagramme.
- Legende courte et source dans les donnees.
- Repli abstrait local lorsque le chemin d'image est absent.
- Une illustration n'est jamais indispensable a la comprehension de l'article.

## Composants

Le renderer expose des fonctions correspondant aux composants editoriaux :
masthead, metadonnees d'edition, meteo, agenda, priorites, une, grille de news,
breves, veille, recommandations, citation, mot, chiffre et question du matin.
Leur apparence reste centralisee dans `web/signal_matin.css`.
