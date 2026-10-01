"""Generation sobre de nouveaux mots lorsque la reserve locale est epuisee."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata

from core import cloud
from core.config import reglage
from core.llm import OllamaProvider

from .models import WordOfTheDay

LOG = logging.getLogger("jarvis.signal_matin")


def _normalise(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value.upper())
        if character.isascii() and character.isalpha()
    )


def _json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _request_text(system: str, prompt: str) -> str:
    """Essaie le modele local gratuit, puis le cloud deja configure."""
    try:
        local = OllamaProvider()
        if local.disponible():
            response = local.repondre(
                system,
                [{"role": "user", "content": prompt}],
                [],
            )
            text = " ".join(
                block.text for block in response.content
                if getattr(block, "type", None) == "text" and block.text
            ).strip()
            if text:
                return text
    except Exception as error:
        LOG.info("Signal Matin : generation locale indisponible: %s", error)

    if not cloud.disponible():
        return ""
    return cloud.repondre_texte(
        system,
        [{"role": "user", "content": prompt}],
        max_tokens=1024,
        nom_modele=str(reglage("signal_matin.modele_apprentissage", "") or ""),
    )


def generer_mot_francais(
    date: dt.date, used_words: frozenset[str],
) -> WordOfTheDay | None:
    """Produit un mot valide ; l'historique local reste l'autorite anti-doublon."""
    # Il n'est pas necessaire, ni souhaitable, d'envoyer tout l'historique au
    # modele. Le code appelant compare toujours la reponse a la memoire complete.
    recent = sorted(used_words)[-120:]
    system = (
        "Tu es lexicographe francais. Propose un mot utile, correct et assez peu "
        "banal pour une rubrique quotidienne. Reponds uniquement avec un objet "
        "JSON ayant les champs word, definition et example. Aucun nom propre, "
        "aucune marque, aucun commentaire hors JSON."
    )
    prompt = (
        f"Edition du {date.isoformat()}. Choisis un mot francais different de "
        f"ceux-ci : {', '.join(recent) or '(aucun)'}. La definition doit faire "
        "une phrase breve et l'exemple une phrase naturelle."
    )
    for _ in range(3):
        try:
            payload = _json_object(_request_text(system, prompt))
            candidate = WordOfTheDay.model_validate(payload)
        except Exception as error:
            LOG.warning("Signal Matin : mot genere invalide: %s", error)
            continue
        normalized = _normalise(candidate.word)
        if normalized and normalized not in used_words:
            return candidate
        prompt += f" Le mot {candidate.word!r} est deja utilise : propose-en un autre."
    return None


def generer_termes_mots_croises(
    date: dt.date, used_answers: frozenset[str],
) -> list[tuple[str, str]]:
    """Prepare une reserve de termes neufs pour plusieurs grilles futures."""
    recent = sorted(used_answers)[-180:]
    system = (
        "Tu crees des mots croises francais pedagogiques. Reponds uniquement par "
        "un objet JSON {\"terms\":[{\"answer\":\"...\",\"clue\":\"...\"}]}. "
        "Chaque reponse est un mot francais courant ou un terme tech utile, sans "
        "nom propre, sans espace ni tiret, de 3 a 14 lettres. Les definitions sont "
        "courtes, exactes et ne contiennent pas la reponse."
    )
    prompt = (
        f"Edition du {date.isoformat()}. Propose 36 termes distincts qui ne sont "
        f"pas dans cette liste : {', '.join(recent) or '(aucun)'}. Varie les "
        "lettres et les longueurs afin de permettre une grille bien croisee."
    )
    try:
        payload = _json_object(_request_text(system, prompt))
    except Exception as error:
        LOG.warning("Signal Matin : generation des mots croises impossible: %s", error)
        return []

    terms: list[tuple[str, str]] = []
    seen = set(used_answers)
    for row in payload.get("terms") or []:
        if not isinstance(row, dict):
            continue
        answer = _normalise(str(row.get("answer") or ""))
        clue = " ".join(str(row.get("clue") or "").split())
        if not 3 <= len(answer) <= 18 or not clue or answer in seen:
            continue
        terms.append((answer, clue[:220]))
        seen.add(answer)
    return terms
