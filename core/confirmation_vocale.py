"""Interpretation stricte d'une reponse vocale a une demande de confirmation.

Une action N2/N3 n'est executee que sur un accord explicite, reconnu en mot
entier, et jamais si la reponse contient une negation ou une hesitation : dans le
doute, Jarvis annule. « Non, ne le fais pas » ou « toujours pas » ne valident
donc rien, contrairement a une simple recherche de sous-chaine.

Partage par le PC (jarvis14) et les satellites, pour qu'une meme phrase donne
partout la meme decision.
"""
from __future__ import annotations

import re

from core.util import sans_accents

# Accords reconnus en mot entier (apres minuscules, sans accents, ponctuation
# remplacee par des espaces : « vas-y » -> « vas y », « d'accord » -> « d accord »).
_ACCORDS = frozenset({
    "oui", "ouais", "ouep", "ok", "okay", "yes", "confirme", "confirmer",
    "valide", "valider", "parfait", "carrement", "daccord", "envoie", "fais", "go",
})
_ACCORDS_EXPRESSIONS = ("vas y", "d accord", "bien sur", "c est bon")

# Le moindre refus ou la moindre hesitation l'emporte sur un accord.
_NEGATIONS = frozenset({
    "non", "nan", "no", "nope", "pas", "ne", "n", "jamais", "rien", "aucun", "aucune",
    "annule", "annuler", "annulez", "arrete", "arreter", "stop", "attends", "attend",
    "attendez",
})
_NEGATIONS_EXPRESSIONS = ("laisse tomber", "plus tard", "je sais pas", "sais pas")

# Formules affirmatives qui contiennent « pas » sans etre un refus.
_IDIOMES_POSITIFS = re.compile(r" pas de (?:souci|soucis|probleme|problemes) ")

OUI = "oui"
TOUJOURS = "toujours"
NON = "non"


def interpreter_confirmation(texte: str | None) -> str:
    """Renvoie OUI, TOUJOURS (oui + memoriser) ou NON. Une reponse vide vaut NON."""
    if not texte:
        return NON
    plat = sans_accents(str(texte).replace("’", "'").replace("‘", "'"))
    plat = " " + re.sub(r"[^a-z0-9]+", " ", plat).strip() + " "
    plat = _IDIOMES_POSITIFS.sub(" ", plat)
    mots = set(plat.split())
    if mots & _NEGATIONS or any(f" {e} " in plat for e in _NEGATIONS_EXPRESSIONS):
        return NON
    if "toujours" in mots:
        # « Oui, toujours » ou « toujours » seul, comme le propose la question vocale.
        return TOUJOURS
    if mots & _ACCORDS or any(f" {e} " in plat for e in _ACCORDS_EXPRESSIONS):
        return OUI
    return NON
