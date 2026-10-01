"""Pause papier quotidienne avec anti-doublon persistant.

Sans chemin d'historique, le contenu reste local et deterministe (demo/tests).
En production, chaque page est conservee dans un historique local gitignore :
une meme date reste stable et aucun contenu deja imprime n'est reutilise.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import (
    CrosswordEntry, CrosswordPuzzle, LearningPage, MathChallenge, WordOfTheDay,
)

LOG = logging.getLogger("jarvis.signal_matin")
WordGenerator = Callable[[dt.date, frozenset[str]], WordOfTheDay | None]
CrosswordTermGenerator = Callable[
    [dt.date, frozenset[str]], list[tuple[str, str]]
]


@dataclass(frozen=True)
class _Term:
    answer: str
    clue: str


TERMS = (
    _Term("ALGORITHME", "Suite d'etapes permettant de resoudre un probleme."),
    _Term("DONNEE", "Information recueillie puis traitee."),
    _Term("RESEAU", "Ensemble de machines ou de personnes reliees."),
    _Term("MODELE", "Representation simplifiee servant a comprendre ou predire."),
    _Term("LATENCE", "Delai entre une action et sa reponse."),
    _Term("PIXEL", "Plus petit element colore d'une image numerique."),
    _Term("SOURCE", "Origine verifiable d'une information."),
    _Term("LOGIQUE", "Art d'enchainer correctement les raisonnements."),
    _Term("SIGNAL", "Information transmise par un son, une image ou une onde."),
    _Term("NUANCE", "Difference delicate qui affine une idee."),
    _Term("LIMPIDE", "Clair et facile a comprendre."),
    _Term("SAGACE", "Qui comprend vite et avec finesse."),
    _Term("ASSIDU", "Regulier et applique dans son travail."),
    _Term("RESILIENCE", "Capacite a retrouver un equilibre apres une difficulte."),
    _Term("EPHEMERE", "Qui ne dure qu'un temps tres court."),
    _Term("ELOQUENCE", "Art de s'exprimer avec force et clarte."),
    _Term("CAPTEUR", "Composant qui mesure une grandeur de son environnement."),
    _Term("MEMOIRE", "Faculte ou espace permettant de conserver une information."),
    _Term("SERVEUR", "Machine qui fournit un service a d'autres appareils."),
    _Term("NUAGE", "Ensemble de ressources informatiques accessibles a distance."),
    _Term("VARIABLE", "Valeur nommee qui peut changer au cours d'un calcul."),
    _Term("ITERATION", "Repetition d'une operation dans le but de progresser."),
    _Term("PREUVE", "Element qui permet d'etablir la validite d'une affirmation."),
    _Term("BIAIS", "Deformation systematique qui influence un jugement."),
    _Term("ETHIQUE", "Reflexion sur ce qu'il est juste ou responsable de faire."),
    _Term("CURIOSITE", "Desir de comprendre, d'apprendre ou de decouvrir."),
    _Term("HYPOTHESE", "Proposition que l'on examine avant de la confirmer."),
    _Term("CONCISION", "Qualite d'une expression breve mais complete."),
    _Term("COHERENCE", "Accord logique entre plusieurs idees ou actions."),
    _Term("INTUITION", "Comprehension directe qui precede parfois le raisonnement."),
    _Term("EQUILIBRE", "Etat stable entre plusieurs forces ou priorites."),
    _Term("PERSPECTIVE", "Point de vue depuis lequel une situation est observee."),
    _Term("METHODE", "Maniere ordonnee de conduire une action ou une recherche."),
    _Term("VIGILANCE", "Attention soutenue face a un risque ou un changement."),
    _Term("ANALOGIE", "Rapprochement entre deux choses qui partagent des traits."),
    _Term("SYNTHESE", "Presentation concise des elements essentiels d'un sujet."),
    _Term("CLARTE", "Qualite de ce qui se comprend sans ambiguite."),
    _Term("ARCHIVE", "Ensemble d'informations conservees pour etre retrouvees."),
    _Term("SCRIPT", "Suite d'instructions automatisees executees par un programme."),
    _Term("REQUETE", "Demande adressee a un service ou a une base de donnees."),
    _Term("INDEX", "Structure qui accelere la recherche d'une information."),
    _Term("BOUCLE", "Structure qui repete une serie d'instructions."),
    _Term("FENETRE", "Zone d'une interface consacree a une application."),
    _Term("MATRICE", "Tableau de valeurs organisees en lignes et colonnes."),
    _Term("VECTEUR", "Suite ordonnee de valeurs representant une direction."),
    _Term("ROBUSTESSE", "Capacite d'un systeme a rester fiable face aux aleas."),
    _Term("ABSTRACTION", "Representation qui retient l'essentiel d'un objet complexe."),
    _Term("AUTOMATION", "Execution d'une tache avec peu d'intervention humaine."),
)

TECH_WORDS = (
    WordOfTheDay(word="Latence", definition="Temps ecoule entre une demande et sa reponse.", example="Une faible latence rend une interface vocale plus naturelle."),
    WordOfTheDay(word="Contexte", definition="Informations qui donnent du sens a une requete ou a une decision.", example="Le modele utilise le contexte de la conversation."),
    WordOfTheDay(word="Cache", definition="Memoire rapide qui conserve temporairement des donnees souvent reutilisees.", example="Le cache evite de refaire le meme calcul."),
    WordOfTheDay(word="Inference", definition="Etape pendant laquelle un modele produit un resultat a partir d'une entree.", example="L'inference locale garde les donnees sur la machine."),
    WordOfTheDay(word="Protocole", definition="Ensemble de regles permettant a des systemes de communiquer.", example="Le satellite audio suit un protocole commun avec Jarvis."),
    WordOfTheDay(word="Chiffrement", definition="Transformation qui rend une information illisible sans la cle adaptee.", example="Le chiffrement protege les echanges sensibles."),
    WordOfTheDay(word="Bande passante", definition="Quantite de donnees transmissible pendant un temps donne.", example="L'audio compresse economise de la bande passante."),
)

FRENCH_WORDS = (
    WordOfTheDay(word="Limpide", definition="D'une clarte telle qu'aucun effort n'est necessaire pour comprendre.", example="Son explication, limpide, a leve le doute."),
    WordOfTheDay(word="Serein", definition="Calme, sans agitation ni inquietude excessive.", example="Elle aborde la journee d'un esprit serein."),
    WordOfTheDay(word="Sagace", definition="Qui saisit rapidement ce qui est difficile a percevoir.", example="Une remarque sagace a revele le vrai probleme."),
    WordOfTheDay(word="Parcimonie", definition="Economie poussee, parfois excessive, dans l'usage de quelque chose.", example="Employer les notifications avec parcimonie."),
    WordOfTheDay(word="Nuance", definition="Distinction fine qui evite une affirmation trop tranchee.", example="Cette nuance change le sens de la phrase."),
    WordOfTheDay(word="Assidu", definition="Qui fait preuve de regularite et d'application.", example="Un apprentissage assidu produit des progres durables."),
    WordOfTheDay(word="Ephemere", definition="Qui existe pendant une duree tres courte.", example="Le succes ephemere ne remplace pas un travail solide."),
    WordOfTheDay(word="Pondere", definition="Qui reste mesure et reflechi dans son jugement.", example="Son avis pondere a apaise la discussion."),
    WordOfTheDay(word="Insolite", definition="Qui surprend parce qu'il sort de l'ordinaire.", example="Cette rencontre insolite a inspire son histoire."),
    WordOfTheDay(word="Meticuleux", definition="Qui apporte beaucoup de soin aux moindres details.", example="Un controle meticuleux a evite plusieurs erreurs."),
    WordOfTheDay(word="Taciturne", definition="Qui parle peu et demeure volontiers silencieux.", example="D'ordinaire taciturne, il a longuement raconte son voyage."),
    WordOfTheDay(word="Subtil", definition="Qui demande de la finesse pour etre percu ou compris.", example="Le texte repose sur un contraste subtil."),
    WordOfTheDay(word="Pragmatique", definition="Qui privilegie les solutions concretes et efficaces.", example="Elle a choisi une approche pragmatique du probleme."),
    WordOfTheDay(word="Conciliant", definition="Dispose a trouver un accord sans renoncer a l'essentiel.", example="Son ton conciliant a permis de reprendre le dialogue."),
    WordOfTheDay(word="Perenne", definition="Qui est concu pour durer longtemps.", example="Une organisation simple rend le projet perenne."),
)


def _math_challenge(date: dt.date, nonce: int = 0) -> MathChallenge:
    """Fait varier chaque jour la structure et les nombres du calcul mental."""
    seed = date.toordinal() + nonce * 1_000_003
    variant = seed % 7

    if variant == 0:
        left = 12 + seed % 17
        right = 3 + (seed // 5) % 8
        subtract = 4 + (seed // 11) % 13
        return MathChallenge(
            question=f"{left} x {right} - {subtract} = ?",
            answer=str(left * right - subtract),
            hint="Commence par la multiplication, puis effectue la soustraction.",
        )
    if variant == 1:
        divisor = 3 + seed % 6
        quotient = 7 + (seed // 3) % 13
        add = 5 + (seed // 7) % 16
        return MathChallenge(
            question=f"{divisor * quotient} / {divisor} + {add} = ?",
            answer=str(quotient + add),
            hint="Effectue d'abord la division exacte, puis ajoute le dernier nombre.",
        )
    if variant == 2:
        percent = (10, 20, 25, 50)[(seed // 7) % 4]
        base = 40 + 20 * (seed % 5)
        add = 3 + (seed // 5) % 12
        return MathChallenge(
            question=f"{percent} % de {base} + {add} = ?",
            answer=str(base * percent // 100 + add),
            hint="Calcule la fraction simple correspondant au pourcentage, puis ajoute.",
        )
    if variant == 3:
        left = 18 + seed % 23
        right = 8 + (seed // 2) % 14
        multiplier = 2 + (seed // 9) % 4
        return MathChallenge(
            question=f"({left} + {right}) x {multiplier} = ?",
            answer=str((left + right) * multiplier),
            hint="Additionne l'interieur des parentheses avant de multiplier.",
        )
    if variant == 4:
        start = 160 + seed % 141
        subtract = 30 + (seed // 3) % 71
        add = 7 + (seed // 13) % 24
        return MathChallenge(
            question=f"{start} - {subtract} + {add} = ?",
            answer=str(start - subtract + add),
            hint="Soustrais par dizaines, puis ajuste avec la derniere addition.",
        )
    if variant == 5:
        number = 7 + seed % 13
        add = 4 + (seed // 4) % 18
        return MathChallenge(
            question=f"{number} x {number} + {add} = ?",
            answer=str(number * number + add),
            hint="Retrouve d'abord le carre du nombre, puis ajoute.",
        )

    first = 6 + seed % 15
    step = 3 + (seed // 5) % 8
    values = (first, first + step, first + step * 2)
    return MathChallenge(
        question=f"{values[0]} + {values[1]} + {values[2]} = ?",
        answer=str(sum(values)),
        hint="Regroupe le premier et le dernier terme, puis ajoute celui du milieu.",
    )


def _normalise(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value.upper())
        if character.isascii() and character.isalpha()
    )


def _can_place(
    grid: dict[tuple[int, int], str], word: str, row: int, column: int,
    direction: str, size: int,
) -> tuple[bool, int]:
    dr, dc = (0, 1) if direction == "across" else (1, 0)
    end_row = row + dr * (len(word) - 1)
    end_column = column + dc * (len(word) - 1)
    if min(row, column, end_row, end_column) < 0 or max(row, column, end_row, end_column) >= size:
        return False, 0
    if grid.get((row - dr, column - dc)) or grid.get((end_row + dr, end_column + dc)):
        return False, 0
    intersections = 0
    for index, letter in enumerate(word):
        rr, cc = row + dr * index, column + dc * index
        current = grid.get((rr, cc))
        if current and current != letter:
            return False, 0
        if current == letter:
            intersections += 1
            continue
        neighbours = ((rr - 1, cc), (rr + 1, cc)) if direction == "across" else ((rr, cc - 1), (rr, cc + 1))
        if any(grid.get(point) for point in neighbours):
            return False, 0
    return intersections > 0, intersections


def _crossword(
    date: dt.date, nonce: int = 0, terms: list[_Term] | None = None,
) -> CrosswordPuzzle:
    size = 13
    seed = date.toordinal() + nonce * 1_000_003

    # Deux banques disjointes alternent d'un jour a l'autre. Ainsi, deux grilles
    # consecutives ne recyclent aucun mot, tout en restant entierement locales et
    # reproductibles pour une date donnee.
    pool = list(terms) if terms is not None else list(TERMS[seed % 2::2])
    if not pool:
        return CrosswordPuzzle(size=size, entries=[])
    best: list[tuple[_Term, str, int, int, str]] = []
    for attempt in range(12):
        rng = random.Random(seed * 7919 + 17 + attempt * 104729)
        selected = list(pool)
        rng.shuffle(selected)
        first = selected.pop(0)
        first_word = _normalise(first.answer)
        first_direction = "across" if (seed // 2 + attempt) % 2 == 0 else "down"
        centre_shift = rng.choice((-1, 0, 1))
        if first_direction == "across":
            first_row = size // 2 + centre_shift
            first_column = (size - len(first_word)) // 2
        else:
            first_row = (size - len(first_word)) // 2
            first_column = size // 2 + centre_shift
        dr, dc = (0, 1) if first_direction == "across" else (1, 0)
        grid = {
            (first_row + dr * index, first_column + dc * index): letter
            for index, letter in enumerate(first_word)
        }
        placed: list[tuple[_Term, str, int, int, str]] = [
            (first, first_word, first_row, first_column, first_direction)
        ]

        for term in selected:
            word = _normalise(term.answer)
            options: list[tuple[float, int, int, str]] = []
            for index, letter in enumerate(word):
                for (rr, cc), existing in grid.items():
                    if letter != existing:
                        continue
                    for direction in ("across", "down"):
                        row = rr if direction == "across" else rr - index
                        column = cc - index if direction == "across" else cc
                        valid, crossings = _can_place(
                            grid, word, row, column, direction, size,
                        )
                        if valid:
                            centre = abs(
                                (row + (len(word) if direction == "down" else 0) / 2)
                                - size / 2
                            )
                            centre += abs(
                                (column + (len(word) if direction == "across" else 0) / 2)
                                - size / 2
                            )
                            score = crossings * 100 - centre * 4 + rng.random() * 12
                            options.append((score, row, column, direction))
            if not options:
                continue
            _, row, column, direction = max(options, key=lambda option: option[0])
            dr, dc = (0, 1) if direction == "across" else (1, 0)
            for index, letter in enumerate(word):
                grid[(row + dr * index, column + dc * index)] = letter
            placed.append((term, word, row, column, direction))
            if len(placed) >= 6:
                break

        if len(placed) > len(best):
            best = placed
        if len(best) >= 6:
            break

    placed = best

    starts = sorted({(row, column) for _, _, row, column, _ in placed})
    numbers = {point: index + 1 for index, point in enumerate(starts)}
    entries = [CrosswordEntry(
        number=numbers[(row, column)], answer=word, clue=term.clue,
        row=row, column=column, direction=direction,
    ) for term, word, row, column, direction in placed]
    return CrosswordPuzzle(size=size, entries=entries)


def _crossword_signature(puzzle: CrosswordPuzzle) -> str:
    rows = sorted(
        (entry.answer, entry.row, entry.column, entry.direction)
        for entry in puzzle.entries
    )
    return json.dumps(rows, ensure_ascii=True, separators=(",", ":"))


def _empty_history() -> dict:
    return {"version": 1, "days": {}}


def _read_history(path: Path) -> dict:
    if not path.exists():
        return _empty_history()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("days"), dict):
            raise ValueError("schema inconnu")
        # Valider chaque entree evite de poursuivre avec une memoire partiellement
        # corrompue, ce qui pourrait reintroduire un ancien contenu.
        for learning in payload["days"].values():
            LearningPage.model_validate(learning)
        return payload
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError(
            f"Historique Signal Matin illisible ({path}) ; generation interrompue "
            "pour ne pas risquer un doublon."
        ) from error


def _write_history(path: Path, history: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _bootstrap_from_archive(history: dict, archive_dir: Path | None) -> bool:
    """Recupere les anciennes pages deja generees lors de la premiere migration."""
    if archive_dir is None or history["days"] or not archive_dir.is_dir():
        return False
    imported = False
    for path in sorted(archive_dir.glob("????-??-??-signal-matin.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            day = str((payload.get("edition") or {}).get("date") or "")
            learning = LearningPage.model_validate(payload.get("learning") or {})
            dt.date.fromisoformat(day)
        except (OSError, ValueError, TypeError):
            continue
        history["days"][day] = learning.model_dump(mode="json")
        imported = True
    return imported


def _history_sets(
    history: dict,
) -> tuple[set[str], set[str], set[str], set[str]]:
    french_words: set[str] = set()
    math_questions: set[str] = set()
    crosswords: set[str] = set()
    crossword_answers: set[str] = set()
    for raw in history["days"].values():
        page = LearningPage.model_validate(raw)
        if page.french_word:
            french_words.add(_normalise(page.french_word.word))
        if page.math:
            math_questions.add(page.math.question.strip())
        if page.crossword:
            crosswords.add(_crossword_signature(page.crossword))
            crossword_answers.update(
                _normalise(entry.answer) for entry in page.crossword.entries
            )
    return french_words, math_questions, crosswords, crossword_answers


def _unused_french_word(date: dt.date, used: set[str]) -> WordOfTheDay | None:
    start = date.toordinal() % len(FRENCH_WORDS)
    for offset in range(len(FRENCH_WORDS)):
        candidate = FRENCH_WORDS[(start + offset) % len(FRENCH_WORDS)]
        if _normalise(candidate.word) not in used:
            return candidate
    return None


def _unique_math(date: dt.date, used: set[str]) -> MathChallenge:
    for nonce in range(100_000):
        candidate = _math_challenge(date, nonce)
        if candidate.question.strip() not in used:
            return candidate
    raise RuntimeError("Impossible de produire un nouveau calcul mental unique.")


def _unique_crossword(
    date: dt.date,
    used_signatures: set[str],
    used_answers: set[str],
    term_generator: CrosswordTermGenerator | None,
) -> CrosswordPuzzle | None:
    available = [
        term for term in TERMS if _normalise(term.answer) not in used_answers
    ]
    # Demander assez tot une reserve generee : six mots quelconques ne
    # garantissent pas une grille connectee et lisible.
    if len(available) < 24 and term_generator is not None:
        try:
            generated = term_generator(date, frozenset(used_answers))
        except Exception as error:
            LOG.warning("Signal Matin : nouveaux mots croises indisponibles: %s", error)
            generated = []
        known = {_normalise(term.answer) for term in available} | used_answers
        for answer, clue in generated:
            normalized = _normalise(answer)
            if not 2 <= len(normalized) <= 18 or not clue.strip() or normalized in known:
                continue
            available.append(_Term(normalized, clue.strip()[:220]))
            known.add(normalized)

    if len(available) < 6:
        LOG.warning(
            "Signal Matin : moins de six reponses nouvelles disponibles ; "
            "mots croises omis plutot que recycles."
        )
        return None

    for nonce in range(100_000):
        candidate = _crossword(date, nonce, available)
        answers = {_normalise(entry.answer) for entry in candidate.entries}
        if (
            len(candidate.entries) == 6
            and answers.isdisjoint(used_answers)
            and _crossword_signature(candidate) not in used_signatures
        ):
            return candidate
    LOG.warning(
        "Signal Matin : aucune grille entierement nouvelle ; rubrique omise "
        "plutot que de reutiliser un ancien mot."
    )
    return None


def construire_apprentissage_du_jour(
    date: dt.date,
    *,
    history_path: Path | None = None,
    archive_dir: Path | None = None,
    word_generator: WordGenerator | None = None,
    crossword_term_generator: CrosswordTermGenerator | None = None,
) -> LearningPage:
    """Construit la page et, en production, memorise les contenus sans expiration.

    La garantie anti-doublon dure aussi longtemps que ``history_path`` est
    conserve. Supprimer ce fichier remet logiquement la memoire a zero.
    """
    seed = date.toordinal()
    if history_path is None:
        return LearningPage(
            crossword=_crossword(date),
            tech_word=TECH_WORDS[seed % len(TECH_WORDS)],
            french_word=FRENCH_WORDS[seed % len(FRENCH_WORDS)],
            math=_math_challenge(date),
        )

    history = _read_history(history_path)
    imported = _bootstrap_from_archive(history, archive_dir)
    key = date.isoformat()
    if key in history["days"]:
        if imported:
            _write_history(history_path, history)
        return LearningPage.model_validate(history["days"][key])

    used_words, used_math, used_crosswords, used_crossword_answers = _history_sets(history)
    french_word = _unused_french_word(date, used_words)
    if french_word is None and word_generator is not None:
        try:
            generated = word_generator(date, frozenset(used_words))
            if generated and _normalise(generated.word) not in used_words:
                french_word = generated
        except Exception as error:
            LOG.warning("Signal Matin : nouveau mot indisponible: %s", error)

    page = LearningPage(
        crossword=_unique_crossword(
            date,
            used_crosswords,
            used_crossword_answers,
            crossword_term_generator,
        ),
        tech_word=TECH_WORDS[seed % len(TECH_WORDS)],
        # Une rubrique absente vaut mieux qu'un doublon silencieux si aucun
        # generateur local/cloud n'est disponible apres epuisement du stock.
        french_word=french_word,
        math=_unique_math(date, used_math),
    )
    history["days"][key] = page.model_dump(mode="json")
    _write_history(history_path, history)
    return page
