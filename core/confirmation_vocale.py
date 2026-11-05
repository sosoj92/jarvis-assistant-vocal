"""Interpretation stricte d'une reponse vocale a une demande de confirmation.

Une action N2/N3 n'est executee que sur un accord explicite, reconnu en mot
entier, et jamais si la reponse contient une negation ou une hesitation : dans le
doute, Jarvis annule. « Non, ne le fais pas » ou « toujours pas » ne valident
donc rien, contrairement a une simple recherche de sous-chaine.

Partage par le PC (jarvis14) et les satellites, pour qu'une meme phrase donne
partout la meme decision.

Mode strict (actions N3 : mail, appel, reservation, suppression, extinction) :
une reponse qui pose une condition (« oui, mais mets Marie en copie »), une
question (« c'est bon ? », « tu fais quoi ») ou un « toujours » hors d'un accord
explicite (« c'est toujours pareil ») vaut refus, et « fais »/« envoie » seuls
ne comptent plus comme accord. Tout mot hors d'une courte liste blanche (accords,
politesse) vaut aussi refus : « oui, et mets Marie en copie » n'est pas un oui.
Le mode normal (N1/N2) reste inchange.
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

# Mode strict (N3) seulement.
# Un connecteur restrictif annonce une condition ou un report : ce n'est pas un
# accord sans reserve (« oui, mais mets Paul en copie », « envoie-le plutot demain »).
_RESTRICTIONS = frozenset({"mais", "sauf", "plutot", "avant", "apres", "si"})
_RESTRICTIONS_EXPRESSIONS = ("d abord",)
# Une question n'est pas une reponse (« c'est bon ? », « qu'est-ce que tu fais »,
# « est-ce que c'est bon » transcrit sans « ? »).
_INTERROGATIFS = frozenset({"quoi", "comment", "pourquoi"})
_INTERROGATIFS_EXPRESSIONS = ("qu est ce", "est ce")
# Liste blanche : seuls ces mots peuvent entourer un accord. Tout autre mot peut
# porter une condition ou une demande sans connecteur restrictif (« oui, et mets
# Marie en copie », « oui, mets Marie en copie ») : la reponse vaut alors refus.
_VOCABULAIRE_STRICT = _ACCORDS | frozenset({
    "toujours", "vas", "y", "d", "accord", "bien", "sur", "c", "est", "bon", "ca",
    "je", "tu", "peux", "le", "la", "les", "l", "maintenant", "exactement",
    "absolument", "jarvis", "merci", "s", "il", "te", "vous", "plait", "stp", "svp",
})
# Imperatifs trop courants pour valoir accord sur une action critique.
_ACCORDS_STRICTS = _ACCORDS - {"fais", "envoie"}
# « toujours » ne vaut accord que s'il accompagne un accord explicite (« oui, toujours »).
_ACCORDS_EXPLICITES = frozenset({"oui", "ouais", "ouep", "confirme", "confirmer", "daccord"})
_ACCORDS_EXPLICITES_EXPRESSIONS = ("vas y", "d accord")

OUI = "oui"
TOUJOURS = "toujours"
NON = "non"


def interpreter_confirmation(texte: str | None, strict: bool = False) -> str:
    """Renvoie OUI, TOUJOURS (oui + memoriser) ou NON. Une reponse vide vaut NON.

    strict=True pour une action N3 : condition, question ou « toujours » hors
    accord explicite annulent (voir l'en-tete du module)."""
    if not texte:
        return NON
    plat = sans_accents(str(texte).replace("’", "'").replace("‘", "'"))
    plat = " " + re.sub(r"[^a-z0-9]+", " ", plat).strip() + " "
    plat = _IDIOMES_POSITIFS.sub(" ", plat)
    mots = set(plat.split())
    if mots & _NEGATIONS or any(f" {e} " in plat for e in _NEGATIONS_EXPRESSIONS):
        return NON
    if strict:
        if mots & _RESTRICTIONS or any(f" {e} " in plat for e in _RESTRICTIONS_EXPRESSIONS):
            return NON
        # Le « ? » se lit sur le texte brut : « plat » a perdu la ponctuation.
        if (str(texte).rstrip().endswith("?") or mots & _INTERROGATIFS
                or any(f" {e} " in plat for e in _INTERROGATIFS_EXPRESSIONS)):
            return NON
        if mots - _VOCABULAIRE_STRICT:
            return NON
    if "toujours" in mots:
        if strict and not (mots & _ACCORDS_EXPLICITES or any(
                f" {e} " in plat for e in _ACCORDS_EXPLICITES_EXPRESSIONS)):
            # « c'est toujours pareil » n'est pas un accord.
            return NON
        # « Oui, toujours » ou « toujours » seul, comme le propose la question vocale.
        return TOUJOURS
    accords = _ACCORDS_STRICTS if strict else _ACCORDS
    if mots & accords or any(f" {e} " in plat for e in _ACCORDS_EXPRESSIONS):
        return OUI
    return NON
