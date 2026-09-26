"""Pause papier quotidienne, locale et deterministe.

Le contenu tourne avec la date : aucun appel reseau, aucun modele et aucune
donnee personnelle ne sont necessaires pour produire la page ludique.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass

from .models import (
    CrosswordEntry, CrosswordPuzzle, LearningPage, MathChallenge, WordOfTheDay,
)


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


def _crossword(date: dt.date) -> CrosswordPuzzle:
    size = 13
    offset = date.toordinal() % len(TERMS)
    selected = [TERMS[(offset + index * 3) % len(TERMS)] for index in range(10)]
    selected = sorted({term.answer: term for term in selected}.values(), key=lambda term: -len(term.answer))
    first = selected.pop(0)
    first_word = _normalise(first.answer)
    first_row = size // 2
    first_column = (size - len(first_word)) // 2
    grid = {(first_row, first_column + index): letter for index, letter in enumerate(first_word)}
    placed: list[tuple[_Term, str, int, int, str]] = [(first, first_word, first_row, first_column, "across")]

    for term in selected:
        word = _normalise(term.answer)
        options: list[tuple[int, int, int, str]] = []
        for index, letter in enumerate(word):
            for (rr, cc), existing in grid.items():
                if letter != existing:
                    continue
                for direction in ("across", "down"):
                    row = rr if direction == "across" else rr - index
                    column = cc - index if direction == "across" else cc
                    valid, crossings = _can_place(grid, word, row, column, direction, size)
                    if valid:
                        centre = abs((row + (len(word) if direction == "down" else 0) / 2) - size / 2)
                        centre += abs((column + (len(word) if direction == "across" else 0) / 2) - size / 2)
                        options.append((crossings * 100 - int(centre * 4), row, column, direction))
        if not options:
            continue
        _, row, column, direction = max(options, key=lambda option: option[0])
        dr, dc = (0, 1) if direction == "across" else (1, 0)
        for index, letter in enumerate(word):
            grid[(row + dr * index, column + dc * index)] = letter
        placed.append((term, word, row, column, direction))
        if len(placed) >= 6:
            break

    starts = sorted({(row, column) for _, _, row, column, _ in placed})
    numbers = {point: index + 1 for index, point in enumerate(starts)}
    entries = [CrosswordEntry(
        number=numbers[(row, column)], answer=word, clue=term.clue,
        row=row, column=column, direction=direction,
    ) for term, word, row, column, direction in placed]
    return CrosswordPuzzle(size=size, entries=entries)


def construire_apprentissage_du_jour(date: dt.date) -> LearningPage:
    seed = date.toordinal()
    left = 12 + seed % 17
    right = 3 + (seed // 3) % 8
    subtract = 4 + (seed // 7) % 13
    return LearningPage(
        crossword=_crossword(date),
        tech_word=TECH_WORDS[seed % len(TECH_WORDS)],
        french_word=FRENCH_WORDS[(seed // 2) % len(FRENCH_WORDS)],
        math=MathChallenge(
            question=f"{left} x {right} - {subtract} = ?",
            answer=str(left * right - subtract),
            hint="Commence par la multiplication, puis effectue la soustraction.",
        ),
    )
