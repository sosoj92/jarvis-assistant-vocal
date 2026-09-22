"""Mode operateur Windows pilote par GPT-6 Astra, uniquement sur demande locale.

Deux entrees :
- demande explicite (« utilise Astra pour... », « prends le controle du PC... »)
  -> l'enonce vaut autorisation pour la tache sure demandee ;
- appel par le LLM quotidien quand une tache exige vraiment l'interface graphique
  -> outil N3, donc confirmation vocale obligatoire a chaque fois.

Astra ne recoit PAS de shell. Il choisit une action structuree, Jarvis l'execute,
reprend une capture, puis recommence. Echap arrete la boucle. Les achats, secrets,
envois, suppressions et commandes systeme restent hors de ce mode.
"""
from __future__ import annotations

import logging
import time

from core import cloud, plateforme
from core.config import reglage
from core.registre import outil
from core.util import sans_accents
from tools.ecran import capture_screen
from tools.souris import cliquer_ecran

LOG = logging.getLogger("jarvis.astra_pc")

_MARQUEURS_EXPLICITES = (
    "utilise astra",
    "utilises astra",
    "lance astra",
    "active astra",
    "passe par astra",
    "demande a astra de",
    "laisse astra",
    "prends le controle de mon pc",
    "prend le controle de mon pc",
    "prends le controle du pc",
    "prend le controle du pc",
    "prends le controle de l ordinateur",
    "prend le controle de l ordinateur",
    "prends le controle de mon ordinateur",
    "prend le controle de mon ordinateur",
    "prends la main sur mon pc",
    "prend la main sur mon pc",
    "prends la main sur l ordinateur",
    "prend la main sur l ordinateur",
)

_SUFFIXES_EXPLICITES = (
    " avec astra",
    " via astra",
    " en utilisant astra",
)

_PREFIXES_TACHE = ("pour ", "afin de ", "et ", ":", ",")

_RISQUES = {
    "un mot de passe ou un code secret": (
        "mot de passe", "password", "code pin", "code secret", "code 2fa",
        "code de verification", "code de securite", "otp", "cle api",
    ),
    "un achat ou un paiement": (
        "achete", "acheter", "commande-le", "commander", "paye", "payer",
        "paiement", "checkout", "carte bancaire", "virement", "iban",
    ),
    "un envoi ou une publication": (
        "envoie le mail", "envoie un mail", "envoie le message", "envoie un message",
        "publie", "publier", "poste sur", "poster sur", "televerse", "upload",
    ),
    "une suppression ou une action systeme destructive": (
        "supprime", "supprimer", "efface", "effacer", "desinstalle", "desinstaller",
        "formate", "formater", "reinitialise le pc", "eteins le pc",
        "redemarre le pc", "powershell", "invite de commandes", "cmd.exe", "regedit",
    ),
    "une installation ou un telechargement executable": (
        "installe", "installer", "telecharge et lance", "telecharger et lancer",
        "fichier exe", ".exe",
    ),
}

_TOUCHES_AUTORISEES = {
    "tab", "shift+tab", "enter", "esc", "escape", "backspace",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
    "ctrl+a", "ctrl+c", "ctrl+l", "alt+tab",
}

_SCHEMA_ACTION = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["cliquer", "double_cliquer", "taper", "touche", "defiler",
                     "attendre", "termine", "bloque"],
        },
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "texte": {"type": "string"},
        "touche": {"type": "string"},
        "direction": {"type": "string", "enum": ["haut", "bas"]},
        "raison": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["action"],
}

_SYSTEME_OPERATEUR = (
    "Tu pilotes UNE interface Windows visible afin d'accomplir exactement la tache "
    "autorisee. Observe la capture et choisis UNE seule action avec l'outil agir_pc. "
    "Les coordonnees x,y sont celles de l'image, origine en haut a gauche. Verifie "
    "l'ecran apres chaque action. Si la tache est terminee, action=termine. "
    "GARDE-FOUS ABSOLUS : ne saisis jamais mot de passe, code, token ni donnee "
    "bancaire ; n'achete et ne paie rien ; n'envoie, ne publie et ne soumets rien ; "
    "ne supprime aucun fichier ou contenu ; ne lance ni terminal ni commande systeme ; "
    "ne modifie pas les reglages de securite ; ne ferme pas un document qui pourrait "
    "contenir des changements non sauvegardes. Arrete-toi AVANT toute etape de ce type "
    "avec action=bloque et une raison courte. N'invente jamais qu'une action a reussi."
)


def extraire_commande_explicite(phrase: str):
    """Renvoie la tache explicite, '' si elle manque, ou None si pas d'invocation."""
    original = str(phrase or "").strip()
    normalise = sans_accents(original.lower().replace("’", "'").replace("-", " "))
    for suffixe in _SUFFIXES_EXPLICITES:
        pos = normalise.rfind(suffixe)
        if pos >= 0 and not normalise[pos + len(suffixe):].strip(" .,!?:;"):
            return original[:pos].strip(" .,!?:;")
    for marqueur in _MARQUEURS_EXPLICITES:
        pos = normalise.find(marqueur)
        if pos < 0:
            continue
        # sans_accents conserve la longueur des caracteres : l'index reste valable.
        tache = original[pos + len(marqueur):].strip()
        bas = sans_accents(tache.lower())
        for prefixe in _PREFIXES_TACHE:
            if bas.startswith(prefixe):
                tache = tache[len(prefixe):].strip()
                break
        return tache
    return None


def _raison_blocage(tache: str):
    texte = " " + sans_accents(str(tache or "").lower()) + " "
    for raison, expressions in _RISQUES.items():
        if any(expr in texte for expr in expressions):
            return raison
    return None


def _echap_presse():
    return plateforme.touche_pressee("escape")


def _taper(texte: str):
    plateforme.taper_texte(str(texte or "")[:500])


def _touche(nom: str):
    touche = sans_accents(str(nom or "").strip().lower())
    if touche == "escape":
        touche = "esc"
    if touche not in _TOUCHES_AUTORISEES:
        raise ValueError(f"touche non autorisee : {touche or '?'}")
    plateforme.envoyer_touches(touche)


def _defiler(direction: str):
    delta = 720 if str(direction).lower() == "haut" else -720
    plateforme.souris_defiler(vertical=delta)


def _executer_action(action: dict) -> str:
    nom = str(action.get("action", "")).lower()
    if nom in {"cliquer", "double_cliquer"}:
        return cliquer_ecran(
            int(action.get("x", -1)), int(action.get("y", -1)),
            double=(nom == "double_cliquer"))
    if nom == "taper":
        _taper(action.get("texte", ""))
        return "texte saisi"
    if nom == "touche":
        _touche(action.get("touche", ""))
        return "touche envoyee"
    if nom == "defiler":
        _defiler(action.get("direction", "bas"))
        return "ecran defile"
    if nom == "attendre":
        time.sleep(1.0)
        return "attente terminee"
    raise ValueError(f"action non executable : {nom or '?'}")


def executer_controle(tache: str) -> str:
    """Boucle bornee capture -> decision Astra -> action locale -> verification."""
    tache = str(tache or "").strip()
    if not tache:
        return "Dis-moi quelle tache tu veux que je fasse sur le PC."
    if not bool(reglage("astra_pc.actif", True)):
        return "Le mode operateur Astra est desactive dans la configuration."
    bloque = _raison_blocage(tache)
    if bloque:
        return ("Je ne prends pas le controle pour cette demande, car elle implique "
                f"{bloque}. Utilise l'outil specialise avec sa confirmation.")
    if cloud.client_openai() is None:
        return "La cle OpenAI n'est pas configuree, donc Astra n'est pas disponible."

    modele = str(reglage("astra_pc.modele", "gpt-6-astra") or "gpt-6-astra")
    max_actions = max(1, min(int(reglage("astra_pc.max_actions", 12) or 12), 25))
    delai = max(15.0, min(float(reglage("astra_pc.timeout", 90) or 90), 180.0))
    debut = time.monotonic()
    historique = []

    for etape in range(1, max_actions + 1):
        if _echap_presse():
            return "J'ai arrete le controle du PC."
        if time.monotonic() - debut > delai:
            return "J'ai arrete Astra : la limite de temps est atteinte."

        capture = capture_screen()
        if not isinstance(capture, dict) or not capture.get("image"):
            return f"Je ne peux pas voir l'ecran : {capture}"
        image_b64 = capture["image"]["data"]
        trace = " ; ".join(historique[-6:]) or "aucune action encore"
        demande = (f"Tache autorisee : {tache}\nEtape {etape}/{max_actions}. "
                   f"Actions deja realisees : {trace}. Choisis l'action suivante.")
        try:
            action = cloud.decider_action_vision(
                _SYSTEME_OPERATEUR, demande, image_b64, _SCHEMA_ACTION,
                nom_outil="agir_pc", description="Une action locale bornee sur Windows.",
                nom_modele=modele, qualite=True, fournisseur_force="openai")
        except Exception as exc:
            LOG.exception("astra_pc: decision")
            return f"Astra n'est pas joignable pour le moment ({str(exc)[:100]})."

        nom = str(action.get("action", "")).lower()
        if nom == "termine":
            return str(action.get("message") or "C'est fait avec Astra.")
        if nom == "bloque":
            return ("Je me suis arrete avant une etape non autorisee : "
                    + str(action.get("raison") or "action sensible"))
        try:
            resultat = _executer_action(action)
        except Exception as exc:
            LOG.warning("astra_pc: action %s refusee/echec: %s", nom, exc)
            return f"J'ai arrete le controle : {str(exc)[:120]}."
        # Ne journalise jamais le texte saisi, seulement le type d'action.
        LOG.info("astra_pc: etape %s/%s action=%s", etape, max_actions, nom)
        historique.append(f"{nom}: {resultat}")
        time.sleep(0.35)

    return "J'ai arrete Astra : la limite d'actions est atteinte."


def _annonce(args):
    return ("Cette tache necessite que je voie et pilote ton ecran avec Astra. "
            "Je vais prendre le controle du PC ; Echap permet de m'arreter.")


@outil(
    nom="controle_pc_astra",
    description=(
        "Demande a GPT-6 Astra d'accomplir une tache multi-etapes dans l'interface "
        "Windows quand les outils directs ne suffisent pas : cliquer, taper, naviguer "
        "dans une application. Utilise cet outil si la demande necessite reellement "
        "de voir et piloter l'ecran. Le systeme demandera l'autorisation avant de "
        "prendre le controle. Ne l'utilise pas pour une question, une lecture d'ecran "
        "simple, la domotique, ou lorsqu'un outil direct existe."),
    parametres={
        "type": "object",
        "properties": {
            "tache": {"type": "string", "description": "Objectif precis a realiser sur le PC."},
        },
        "required": ["tache"],
    },
    confirmation=True,
    lent=True,
    phrase_attente="D'accord, Astra prend le relais sur le PC.",
    annonce=_annonce,
    mcp_expose=False,
)
def controle_pc_astra(tache: str) -> str:
    return executer_controle(tache)
