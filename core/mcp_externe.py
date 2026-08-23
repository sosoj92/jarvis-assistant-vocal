"""Client MCP : Jarvis appelle les outils de serveurs MCP externes.

Le pendant de jarvis/mcp_server.py, qui EXPOSE les outils de Jarvis. Ici on fait
l'inverse : on branche des serveurs distants (infra, SaaS, domotique tierce) et
leurs outils apparaissent dans le registre a cote des outils natifs. Le modele
les appelle alors comme n'importe quel autre.

    mcp_externes:
      - nom: yorkhost
        url: "https://mcp.yorkhost.fr/mcp"
        entetes:
          Authorization: "Bearer TON_JETON"

DOCTRINE DE SECURITE — confirmation systematique. Un outil distant demande TOUJOURS
l'accord vocal avant d'agir, sauf s'il est nomme dans `sans_confirmation`. C'est
volontairement l'inverse du reglage par defaut des outils natifs : ces outils
touchent a de l'infra qu'on ne voit pas, leurs effets ne sont pas devinables
depuis leur nom, et une transcription approximative ne doit jamais suffire a
declencher un redemarrage de serveur.

TECHNIQUE — le SDK MCP est asynchrone, le registre de Jarvis est synchrone. On
tient donc une boucle asyncio dans un thread dedie, ou les sessions restent
ouvertes ; les appels d'outils y sont postes depuis le thread de l'assistant et
attendus avec un delai maximum.
"""
import asyncio
import logging
import threading

from core.config import reglage
from core import registre

LOG = logging.getLogger("jarvis")

_BOUCLE = None          # asyncio.AbstractEventLoop du thread dedie
_THREAD = None
_CLIENTS = {}           # nom du serveur -> client MCP connecte
_DELAI = 30             # secondes max pour un appel d'outil distant


def _serveurs():
    """Serveurs declares dans config.yaml, normalises."""
    bruts = reglage("mcp_externes", []) or []
    serveurs = []
    for i, s in enumerate(bruts):
        if not isinstance(s, dict) or not s.get("url"):
            continue
        serveurs.append({
            "nom": str(s.get("nom") or f"mcp{i}").strip().lower(),
            "url": s["url"],
            "entetes": s.get("entetes") or {},
            "sans_confirmation": {str(x) for x in (s.get("sans_confirmation") or [])},
            "prefixe": bool(s.get("prefixe", True)),
        })
    return serveurs


# ------------------------------------------------------------- boucle dediee

def _demarrer_boucle():
    """Lance (une fois) le thread qui heberge la boucle asyncio."""
    global _BOUCLE, _THREAD
    if _BOUCLE is not None:
        return _BOUCLE
    pret = threading.Event()

    def tourner():
        global _BOUCLE
        _BOUCLE = asyncio.new_event_loop()
        asyncio.set_event_loop(_BOUCLE)
        pret.set()
        _BOUCLE.run_forever()

    _THREAD = threading.Thread(target=tourner, daemon=True, name="mcp-externe")
    _THREAD.start()
    pret.wait(timeout=5)
    return _BOUCLE


def _executer(coroutine, delai=_DELAI):
    """Poste une coroutine sur la boucle dediee et attend son resultat."""
    boucle = _demarrer_boucle()
    if boucle is None:
        raise RuntimeError("boucle MCP indisponible")
    return asyncio.run_coroutine_threadsafe(coroutine, boucle).result(timeout=delai)


# ------------------------------------------------------------- connexion

async def _connecter(serveur):
    """Ouvre une session et renvoie (client, outils). La session reste ouverte."""
    from mcp import Client

    entetes = {str(k): str(v) for k, v in (serveur["entetes"] or {}).items()}
    if entetes:
        import httpx2 as httpx
        transport = httpx.AsyncClient(headers=entetes)
        client = Client(serveur["url"], read_timeout_seconds=_DELAI)
        client._httpx = transport            # garde une reference vivante
    else:
        client = Client(serveur["url"], read_timeout_seconds=_DELAI)

    await client.__aenter__()
    outils = await client.list_tools()
    return client, list(getattr(outils, "tools", outils) or [])


def _texte_resultat(resultat):
    """Extrait un texte lisible d'un CallToolResult, quel que soit son contenu."""
    if getattr(resultat, "isError", False):
        return f"Erreur de l'outil distant : {_contenu(resultat)}"
    return _contenu(resultat)


def _contenu(resultat):
    morceaux = []
    for bloc in getattr(resultat, "content", None) or []:
        texte = getattr(bloc, "text", None)
        if texte:
            morceaux.append(str(texte))
    if not morceaux:
        donnees = getattr(resultat, "structuredContent", None)
        if donnees:
            morceaux.append(str(donnees))
    return " ".join(morceaux).strip() or "(pas de reponse)"


# ------------------------------------------------------------- enregistrement

def _enregistrer(serveur, outil_distant):
    """Publie un outil distant dans le registre de Jarvis."""
    nom_court = outil_distant.name
    nom = f"{serveur['nom']}_{nom_court}" if serveur["prefixe"] else nom_court

    # Le SDK a renomme le champ entre la v1 (inputSchema) et la v2
    # (input_schema). Sans les deux, les outils distants arrivent SANS
    # parametres et le modele ne sait pas quoi leur passer — l'appel echoue
    # silencieusement, ce qui est le pire des cas.
    schema = (getattr(outil_distant, "input_schema", None)
              or getattr(outil_distant, "inputSchema", None)
              or {"type": "object", "properties": {}})
    description = (getattr(outil_distant, "description", "") or "").strip()
    confirmer = nom_court not in serveur["sans_confirmation"]

    def appeler(**arguments):
        try:
            client = _CLIENTS.get(serveur["nom"])
            if client is None:
                return f"Le serveur {serveur['nom']} n'est pas connecte."
            return _texte_resultat(
                _executer(client.call_tool(nom_court, arguments or {})))
        except TimeoutError:
            return (f"Le serveur {serveur['nom']} n'a pas repondu en "
                    f"{_DELAI} secondes.")
        except Exception as e:
            LOG.exception("mcp_externe: appel %s", nom)
            return f"Echec de l'outil {nom_court} : {str(e)[:160]}"

    def annonce(args):
        return f"Je vais lancer {nom_court} sur {serveur['nom']}."

    registre.outil(
        nom=nom,
        description=(f"[{serveur['nom']}] {description}"
                     if description else f"Outil {nom_court} de {serveur['nom']}."),
        parametres=schema,
        confirmation=confirmer,
        annonce=annonce if confirmer else None,
        lent=True,
        phrase_attente=f"Je contacte {serveur['nom']}.",
        mcp_expose=False,        # on ne re-expose jamais un outil distant
        affichage="toujours",
    )(appeler)
    return nom


# ------------------------------------------------------------- API publique

def charger():
    """Connecte les serveurs declares et publie leurs outils. Renvoie un resume."""
    serveurs = _serveurs()
    if not serveurs:
        return ""

    resumes = []
    for serveur in serveurs:
        try:
            client, outils = _executer(_connecter(serveur), delai=20)
        except Exception as e:
            LOG.warning("mcp_externe: %s injoignable (%s)", serveur["nom"], e)
            resumes.append(f"{serveur['nom']} injoignable ({str(e)[:60]})")
            continue

        _CLIENTS[serveur["nom"]] = client
        noms = []
        for outil_distant in outils:
            try:
                noms.append(_enregistrer(serveur, outil_distant))
            except Exception:
                LOG.exception("mcp_externe: enregistrement %s", outil_distant)
        libres = len(serveur["sans_confirmation"] & {o.name for o in outils})
        resumes.append(f"{serveur['nom']} : {len(noms)} outil(s), "
                       f"{len(noms) - libres} a confirmation")
    return " | ".join(resumes)


def arreter():
    """Ferme les sessions ouvertes (appele a la sortie)."""
    for nom, client in list(_CLIENTS.items()):
        try:
            _executer(client.__aexit__(None, None, None), delai=5)
        except Exception:
            pass
        _CLIENTS.pop(nom, None)
