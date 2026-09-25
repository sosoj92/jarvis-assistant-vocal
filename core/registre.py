"""Registre d'outils : decorateur @outil, auto-decouverte, confirmation vocale.

Chaque outil est une fonction decoree par @outil dans un fichier de tools/.
Au demarrage, charger_outils() importe tous les modules de tools/ pour peupler
le registre. Le reste de l'assistant n'a plus a connaitre les outils un par un.
"""
import importlib
import logging
import pkgutil

LOG = logging.getLogger("jarvis.registre")

_REGISTRE = {}      # nom -> Outil
_EN_ATTENTE = None  # (Outil, args) en attente d'une confirmation vocale


class Outil:
    """Metadonnees + fonction d'un outil."""

    def __init__(self, fonction, nom, description, parametres, confirmation,
                 lent, phrase_attente, annonce, mcp_expose, affichage="auto"):
        self.fonction = fonction
        self.nom = nom
        self.description = description
        self.parametres = parametres
        self.confirmation = confirmation      # demande "tu confirmes ?" avant d'agir
        self.lent = lent                      # accuse de reception pendant l'execution
        self.phrase_attente = phrase_attente  # phrase d'attente si lent
        self.annonce = annonce                # fn(args) -> phrase de confirmation
        self.mcp_expose = mcp_expose          # visible via le serveur MCP externe ?
        self.affichage = affichage            # overlay : "toujours" | "jamais" | "auto"
        # Domaine déduit du module (tools.mail -> mail). Il permet de ne transmettre
        # au LLM que les outils utiles à la demande courante.
        self.module = fonction.__module__.rsplit(".", 1)[-1]


def outil(nom, description, parametres=None, confirmation=False, lent=False,
          phrase_attente=None, annonce=None, mcp_expose=False, affichage="auto"):
    """Decorateur : enregistre une fonction comme outil de l'assistant.

    mcp_expose : par securite, un outil n'est PAS expose au serveur MCP par
    defaut (un agent externe ne doit voir que ce qu'on autorise explicitement).
    affichage : routage de l'overlay de reponses. "toujours" (musique, stats,
    listes, minuteurs, retours Hermes), "jamais" (acquittement ephemere), ou
    "auto" (defaut : heuristique cote core selon le contenu de la reponse).
    """
    def deco(fonction):
        _REGISTRE[nom] = Outil(
            fonction, nom, description,
            parametres or {"type": "object", "properties": {}},
            confirmation, lent, phrase_attente, annonce, mcp_expose, affichage)
        return fonction
    return deco


def affichage(nom):
    """Hint d'affichage overlay d'un outil : 'toujours' | 'jamais' | 'auto'."""
    o = _REGISTRE.get(nom)
    return getattr(o, "affichage", "auto") if o else "auto"


def charger_outils():
    """Importe tous les modules de tools/ pour remplir le registre.

    Chaque module est isolé : si l'un rate son import (dépendance optionnelle
    absente sur la machine de l'utilisateur), on le loggue et on CONTINUE — les
    autres outils se chargent quand même. Sans ça, un seul import cassé faisait
    disparaître silencieusement tous les outils suivants."""
    import tools
    echecs = []
    for module in pkgutil.iter_modules(tools.__path__):
        try:
            importlib.import_module(f"tools.{module.name}")
        except Exception as e:
            echecs.append(module.name)
            LOG.warning("outil « %s » non chargé (dépendance manquante ?) : %s",
                        module.name, e, exc_info=True)
    if echecs:
        LOG.warning("%d outil(s) ignoré(s) : %s", len(echecs), ", ".join(echecs))


def get(nom):
    return _REGISTRE.get(nom)


def executer(outil_obj, args=None):
    """Exécute un outil sur le bon corps, sans contourner ses confirmations.

    La confirmation est volontairement gérée par les appelants AVANT cette
    fonction. Le poste distant ne reçoit donc une action N2/N3 qu'une fois
    l'accord obtenu côté cerveau Jarvis.
    """
    arguments = args or {}
    from core.poste_distant import executer_outil_principal
    distant = executer_outil_principal(outil_obj.nom, arguments)
    if distant is not None:
        return distant
    return outil_obj.fonction(**arguments)


def tous():
    return list(_REGISTRE.values())


# Outils NON exposes au modele local : soit ils exigent de la vision/un raisonnement
# agentique cloud, soit ils noieraient un petit modele. `browser_open` reste permis :
# ouvrir explicitement une URL ne demande aucune vision ni intelligence cloud.
_NON_LOCAUX = {
    "capture_screen", "faire_brief",
    "lire_mails", "lire_mail", "preparer_mail", "envoyer_mail", "mettre_a_la_corbeille",
    "get_events", "create_event", "delete_event", "get_deadlines",
    "chercher_web",
    "book_appointment", "confirmer_reservation",
    "browser_current_page", "browser_tabs", "browser_close_tabs",
    "browser_interact",
    "lire_netflix",
    "controle_pc_astra",
    "call_with_message", "call_and_book", "cout_appels",
    "instagram_resume", "rafraichir_instagram",
    "get_mentions_summary", "get_channel_summary",
}


def schemas_api(local_seulement=False, modules=None):
    """Schemas au format Anthropic (name, description, input_schema).

    local_seulement=True : ne renvoie que les outils utilisables par un modele
    local (mode Ollama), en excluant les outils internet/vision (_NON_LOCAUX).
    modules : ensemble optionnel de domaines (noms de fichiers dans tools/).
    None conserve tout le catalogue ; un ensemble vide n'expose aucun outil.
    """
    return [{"name": o.nom, "description": o.description, "input_schema": o.parametres}
            for o in _REGISTRE.values()
            if not (local_seulement and o.nom in _NON_LOCAUX)
            and (modules is None or o.module in modules)]


def noms_lents():
    return {o.nom for o in _REGISTRE.values() if o.lent}


def exposes_mcp():
    """Liste des outils autorises a etre exposes via le serveur MCP externe."""
    return [o for o in _REGISTRE.values() if o.mcp_expose]


# ---------------------------------------------------- niveaux de permission (N8)
#
# N1 (sur)      : pas de confirmation -> execute direct, EN LOCAL ET a distance.
# N2 (sensible) : confirmation ; l'utilisateur peut memoriser "toujours autoriser"
#                 (revocable) -> plus de question EN LOCAL ; jamais en auto a distance.
# N3 (critique) : confirmation TOUJOURS ; "toujours" REFUSE ; jamais a distance.
#                 Verrouille ici. (Le pont iPhone refuse deja tout outil a confirmation,
#                 quel que soit le store : le "toujours autoriser" n'ouvre RIEN a distance.)
_N3 = frozenset({
    "envoyer_mail", "mettre_a_la_corbeille",
    "call_with_message", "call_and_book",
    "book_appointment", "confirmer_reservation",
    "delete_event",
    "eteindre_pc",
    "controle_pc_astra",
})


def niveau(nom):
    """Niveau de permission d'un outil : N1 / N2 / N3 (ou '?' si inconnu)."""
    o = _REGISTRE.get(nom)
    if o is None:
        return "?"
    if not o.confirmation:
        return "N1"
    return "N3" if nom in _N3 else "N2"


def est_n3(nom):
    return nom in _N3


def autorisations():
    """Outils N2 memorises 'toujours autoriser' (config securite.toujours)."""
    from core.config import reglage
    return [n for n in (reglage("securite.toujours", []) or []) if niveau(n) == "N2"]


def est_autorise(nom):
    """Vrai si on SAUTE la confirmation EN LOCAL (N2 memorise). Jamais un N3 ni un N1."""
    return niveau(nom) == "N2" and nom in autorisations()


def autoriser_toujours(nom):
    """Memorise 'toujours autoriser' pour un N2. Renvoie True si effectif (N2 uniquement,
    jamais un N3)."""
    if niveau(nom) != "N2":
        return False
    from core.config import reglage, definir
    cur = list(reglage("securite.toujours", []) or [])
    if nom not in cur:
        cur.append(nom)
        definir("securite.toujours", cur)
    return True


def revoquer(nom):
    """Retire un outil du 'toujours autoriser'. Renvoie True si quelque chose a ete retire."""
    from core.config import reglage, definir
    cur = list(reglage("securite.toujours", []) or [])
    if nom in cur:
        cur.remove(nom)
        definir("securite.toujours", cur)
        return True
    return False


def phrase_attente(noms):
    """Phrase d'accuse de reception pour le premier outil lent appele."""
    for o in _REGISTRE.values():
        if o.nom in noms and o.lent and o.phrase_attente:
            return o.phrase_attente
    return "D'accord, je m'en occupe."


# ---------------------------------------------------------------- confirmation

def mettre_en_attente(outil_obj, args):
    """Range une action a confirmer. Renvoie un resultat neutre pour Claude."""
    global _EN_ATTENTE
    _EN_ATTENTE = (outil_obj, args)
    return "En attente de la confirmation vocale de l'utilisateur."


def annonce_en_attente():
    """Phrase a prononcer pour demander l'accord, ou None si rien en attente."""
    if _EN_ATTENTE is None:
        return None
    outil_obj, args = _EN_ATTENTE
    if outil_obj.annonce:
        try:
            return outil_obj.annonce(args)
        except Exception:
            pass
    return f"Je vais executer {outil_obj.nom}."


def nom_en_attente():
    """Nom de l'outil en attente de confirmation (ou None)."""
    return _EN_ATTENTE[0].nom if _EN_ATTENTE else None


def executer_confirme(memoriser=False):
    """Execute l'action en attente et renvoie son resultat.

    memoriser=True (l'utilisateur a dit "oui, toujours") : si l'outil est N2, on
    l'ajoute au 'toujours autoriser' (revocable) ; un N3 REFUSE la memorisation et
    on le lui dit, mais l'action de ce tour est quand meme executee.
    """
    global _EN_ATTENTE
    if _EN_ATTENTE is None:
        return ""
    outil_obj, args = _EN_ATTENTE
    _EN_ATTENTE = None
    suffixe = ""
    if memoriser:
        if autoriser_toujours(outil_obj.nom):
            suffixe = " Je ne te le redemanderai plus pour cette action."
        else:
            suffixe = " Mais c'est une action critique : je te demanderai toujours confirmation."
    try:
        res = executer(outil_obj, args)
    except Exception:
        LOG.exception("outil confirmé « %s » a échoué", outil_obj.nom)
        return "Desole, je n'ai pas reussi a faire ca."
    return (str(res) + suffixe) if suffixe else res


def annuler_confirme():
    global _EN_ATTENTE
    _EN_ATTENTE = None
