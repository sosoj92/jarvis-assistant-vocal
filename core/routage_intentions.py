"""Décision commune des routes prioritaires et des domaines d'outils.

Ce module ne réalise aucune action : il choisit seulement le chemin. Le micro
principal et les satellites consomment ainsi exactement la même décision, sans
dupliquer les heuristiques Alexa/média/Astra/Hermes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re

from core.util import sans_accents

LOG = logging.getLogger("jarvis.routage_intentions")


@dataclass(frozen=True)
class Decision:
    """Route prioritaire à exécuter avant le LLM général."""

    type: str                         # "outil" | "vision" | "astra" | "hermes"
    outil: str = ""
    arguments: dict = field(default_factory=dict)
    tache: str = ""


def decider_prioritaire(phrase: str, piece: str = "") -> Decision | None:
    """Renvoie une route déterministe commune au PC et aux satellites."""
    phrase = str(phrase or "").strip()
    if not phrase:
        return None

    # Caméra/gestes : commandes locales explicites, avant toute interprétation
    # domotique ou média.
    try:
        from tools.gestes import (demande_calibration_gestes,
                                  demande_demo_gestes,
                                  demande_mode_regard,
                                  demande_mode_visio)
        regard = demande_mode_regard(phrase)
        visio = demande_mode_visio(phrase)
        if regard is True:
            return Decision("outil", "lancer_mode_regard")
        if regard is False:
            return Decision("outil", "quitter_mode_regard")
        if visio is True:
            return Decision("outil", "lancer_demo_gestes")
        if visio is False:
            return Decision("outil", "controler_gestes", {"actif": False})
        if demande_demo_gestes(phrase):
            return Decision("outil", "lancer_demo_gestes")
        if demande_calibration_gestes(phrase):
            return Decision("outil", "lancer_calibration_gestes")
    except Exception:
        LOG.exception("routage caméra et gestes")

    # Une invocation Astra explicite vaut autorisation pour la tâche sûre
    # demandée ; les garde-fous de l'opérateur restent appliqués ensuite.
    try:
        from tools.astra_pc import extraire_commande_explicite
        tache = extraire_commande_explicite(phrase)
        if tache is not None:
            return Decision("astra", tache=tache)
    except Exception:
        LOG.exception("routage Astra explicite")

    if est_demande_vision_ecran(phrase):
        return Decision("vision", tache=phrase)

    for module, fonction in (
        ("tools.alexa", "router_commande"),
        ("tools.media", "router_commande_media"),
        ("tools.apps", "router_ouverture_simple"),
    ):
        try:
            mod = __import__(module, fromlist=[fonction])
            route = getattr(mod, fonction)(phrase, piece=piece)
            if route:
                nom, arguments = route
                return Decision("outil", nom, arguments or {})
        except Exception:
            LOG.exception("routage prioritaire %s", module)

    try:
        from tools.deleguer_a_hermes import extraire_tache_contenu
        tache = extraire_tache_contenu(phrase)
        if tache is not None:
            return Decision("hermes", tache=tache)
    except Exception:
        LOG.exception("routage Hermes contenu")

    return None


_REFERENCES_ECRAN = (
    "ecran", "affiche", "cette erreur", "ce message", "cette fenetre",
    "cette page", "ce texte", "ce qui est ouvert", "ce que tu vois",
)
_INTENTIONS_VISION = (
    "lis", "lire", "regarde", "voir", "decris", "decrire", "explique",
    "expliquer", "traduis", "traduire", "c est quoi", "qu est ce que",
    "que vois tu", "qu est ce qui",
)
_ACTIONS_ECRAN = (
    "clique", "double clique", "tape ", "saisis", "ouvre", "ferme", "deplace",
    "active", "desactive", "selectionne", "configure", "installe", "supprime",
)


def est_demande_vision_ecran(phrase: str) -> bool:
    """Vrai pour une lecture visuelle sans action sur l'interface."""
    p = " ".join(re.sub(
        r"[^a-z0-9]+", " ", sans_accents(str(phrase or "").lower())
    ).split())
    if any(action in p for action in _ACTIONS_ECRAN):
        return False
    return (any(ref in p for ref in _REFERENCES_ECRAN)
            and any(intent in p for intent in _INTENTIONS_VISION))


# Groupes utilisés uniquement pour réduire le catalogue d'outils transmis au
# LLM. Une action inconnue conserve le catalogue complet : le filtrage améliore
# les cas clairs sans rendre les formulations nouvelles impossibles.
_DOMAINES = (
    (("heure", "date", "minuteur", "chronometre", "alarme", "rappel"),
     {"temps", "notes"}),
    (("meteo", "temperature", "pleut", "pluie", "temps fait"), {"meteo"}),
    (("mail", "mails", "email", "emails", "courriel", "gmail"),
     {"mail", "factures", "brief"}),
    (("agenda", "calendrier", "rendez vous", "evenement", "deadline"),
     {"agenda", "loopstr", "suivi"}),
    (("spotify", "playlist", "musique", "chanson", "morceau", "netflix",
      "volume", "pause", "lecture", "piste", "sortie audio"),
     {"spotify", "media", "musique", "audio", "systeme"}),
    (("lumiere", "lampe", "hue", "amaran", "clim", "climatisation",
      "ventilateur", "prise", "alexa", "echo", "domotique"),
     {"lumieres", "amaran", "alexa", "google_home", "modes", "scenes"}),
    (("mode visio", "mode vision", "controle gestuel", "controle par gestes",
      "gestes visibles", "regarde mes mains", "webcam"), {"gestes"}),
    (("ecran", "fenetre", "souris", "clique", "clic", "ordinateur", " pc ",
      "application", "logiciel", "dossier", "telechargements", "parametre"),
     {"ecran", "souris", "apps", "systeme", "astra_pc", "gestes", "stats"}),
    (("chrome", "navigateur", "onglet", "site", "page web", "internet",
      "cherche sur le web", "recherche web", "reserve", "reservation"),
     {"navigateur", "web", "reservation"}),
    (("script", "hook", "accroche", "storyboard", "contenu", "video",
      "youtube", "tiktok", "reel", "publication", "inspiration"),
     {"contenu", "suivi", "deleguer_a_hermes"}),
    (("hermes", "recherche de fond", "analyse approfondie", "compare",
      "comparaison", "synthese", "veille"), {"deleguer_a_hermes", "web"}),
    (("discord", "mention", "salon discord"), {"discord_bot"}),
    (("instagram", "abonne", "followers", "vues"), {"instagram"}),
    (("appel", "appelle", "telephone", "raccroche"), {"appels", "appel_direct"}),
    (("obs", "stream", "direct", "replay", "scene"), {"obs", "scenes"}),
    (("memoire", "souviens", "rappelle toi", "oublie"), {"memoire"}),
    (("note", "notes", "idee", "pense bete"), {"notes"}),
    (("mode hybride", "mode qualite", "mode local", "mode cloud"),
     {"budget", "modes"}),
    (("budget", "cout", "depense", "consommation api"), {"budget"}),
    (("abonnement", "transaction", "releve", "finance"), {"finances", "factures"}),
    (("gpu", "cpu", "ram", "memoire vive", "statistiques pc"), {"stats"}),
    (("personnalite", "mode neutre", "mode concis", "sarcastique"),
     {"personnalite", "modes"}),
    (("presence", "je suis rentre", "je pars", "retour maison"),
     {"presence", "scenes"}),
)

_VERBES_ACTION_GENERIQUES = {
    "active", "activer", "affiche", "afficher", "ajoute", "ajouter",
    "baisse", "baisser", "change",
    "changer", "controle", "controler", "corrige", "corriger", "cree", "creer",
    "demarre", "demarrer", "envoie", "envoyer", "eteins", "eteindre", "ferme",
    "fermer", "fais", "faire", "lance", "lancer", "lis", "lire", "mets",
    "mettre", "modifie", "modifier", "montre", "montrer", "note", "noter",
    "ouvre", "ouvrir", "planifie", "planifier", "prepare", "preparer",
    "programme", "programmer", "cherche", "chercher", "supprime", "supprimer",
}


def modules_pour_phrase(phrase: str) -> set[str] | None:
    """Modules utiles au LLM, ensemble vide pour une réponse sans outil.

    ``None`` signifie « catalogue complet » : repli conservateur lorsqu'une action
    est demandée mais que son domaine n'est pas reconnu.
    """
    normalise = " ".join(re.sub(
        r"[^a-z0-9]+", " ", sans_accents(str(phrase or "").lower())
    ).split())
    enveloppe = f" {normalise} "
    modules = set()
    for expressions, candidats in _DOMAINES:
        if any(expr in enveloppe for expr in expressions):
            modules.update(candidats)
    if modules:
        # Ces outils transverses sont petits et fréquemment nécessaires après une
        # action spécialisée (réponse, changement de mode, état des tâches).
        modules.update({"reponses"})
        return modules

    mots = set(normalise.split())
    if mots & _VERBES_ACTION_GENERIQUES:
        return None
    return set()
