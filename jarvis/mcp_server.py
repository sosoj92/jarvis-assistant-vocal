"""Serveur MCP exposant les outils de Jarvis a n'importe quel client MCP.

Reutilise le registre d'outils (dossier tools/) : chaque outil marque
mcp_expose=True est expose automatiquement, avec son nom, sa description et le
schema de parametres derive de sa signature. Aucune logique dupliquee : ajouter
un outil expose dans tools/ suffit a le publier ici.

Tourne independamment de l'assistant vocal (les deux peuvent coexister) :

    uv run python -m jarvis.mcp_server

Transport stdio par defaut (standard des clients desktop) ; HTTP/SSE possible via
config.yaml (mcp.transport: http). Tous les appels externes vont dans logs/mcp.log.

Securite : seuls les outils domotique/PC sont exposes par defaut. Les outils a
confirmation exigent un argument confirm=true, sinon ils renvoient une demande de
confirmation au lieu d'agir (pas d'action irreversible silencieuse).
"""
import functools
import inspect
import logging
from pathlib import Path

# Magasin de certificats Windows (pour les outils reseau exposes, ex. meteo).
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from mcp.server import MCPServer

from core import registre
from core.config import reglage

# --- journal dedie aux appels externes -------------------------------------
_DOSSIER = Path(__file__).resolve().parent.parent / "logs"
_DOSSIER.mkdir(exist_ok=True)
LOG = logging.getLogger("jarvis.mcp")
LOG.setLevel(logging.INFO)
_handler = logging.FileHandler(_DOSSIER / "mcp.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
LOG.handlers.clear()
LOG.addHandler(_handler)
LOG.propagate = False

registre.charger_outils()

# Charge les pieces Hue pour que "allume la chambre" fonctionne, comme l'assistant
# vocal a son demarrage. En stdio, stdout EST le canal du protocole : on redirige
# les impressions vers stderr pour ne pas le corrompre.
import contextlib
import sys
try:
    from tools.lumieres import charger_pieces_hue
    with contextlib.redirect_stdout(sys.stderr):
        charger_pieces_hue()
except Exception:
    LOG.exception("chargement des pieces Hue impossible")

server = MCPServer("jarvis")


def _executer(outil, kwargs):
    try:
        resultat = outil.fonction(**kwargs)
    except Exception as e:
        LOG.exception("erreur outil %s", outil.nom)
        resultat = f"Erreur : {e}"
    LOG.info("appel %s args=%s -> %s", outil.nom, kwargs, str(resultat)[:200])
    # Les outils exposes renvoient du texte ; on aplati un eventuel dict image.
    if isinstance(resultat, dict) and resultat.get("image"):
        resultat = resultat.get("apercu", "(image)")
    return str(resultat)


def _enregistrer(outil):
    fonction = outil.fonction
    sig = inspect.signature(fonction)

    if outil.confirmation:
        @functools.wraps(fonction)
        def wrapper(*a, **k):
            confirm = k.pop("confirm", False)
            if not confirm:
                annonce = outil.annonce(k) if outil.annonce else f"Confirmer {outil.nom} ?"
                LOG.info("confirmation requise : %s args=%s", outil.nom, k)
                return (f"{annonce} Rappelle cet outil avec confirm=true "
                        "pour executer.")
            return _executer(outil, k)

        params = list(sig.parameters.values()) + [inspect.Parameter(
            "confirm", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool)]
        wrapper.__signature__ = sig.replace(parameters=params)
    else:
        @functools.wraps(fonction)
        def wrapper(*a, **k):
            return _executer(outil, {**dict(zip(
                [p.name for p in sig.parameters.values()], a)), **k})

    server.add_tool(wrapper, name=outil.nom, description=outil.description)


for _o in registre.exposes_mcp():
    _enregistrer(_o)


def _lancer_http(kind):
    host = reglage("mcp.host", "127.0.0.1")
    port = int(reglage("mcp.port", 8765))
    if host not in ("127.0.0.1", "::1", "localhost"):
        # Le transport HTTP n'a PAS d'authentification : hors loopback, n'importe
        # quelle machine du réseau pourrait appeler les outils exposés (domotique,
        # OBS...). À ne faire que sur un réseau de confiance, en connaissance de cause.
        print(f"[MCP] ATTENTION : écoute sur {host} (hors loopback) SANS auth — "
              f"exposé au réseau. Repasse mcp.host à 127.0.0.1 si non voulu.")
    print(f"Serveur MCP {kind} sur http://{host}:{port}")
    try:
        server.run(kind, host=host, port=port)
    except TypeError:
        server.run(kind)


def main():
    import os
    # JARVIS_MCP_TRANSPORT (env) prime sur config.yaml : permet au raccourci Bureau
    # de lancer un serveur HTTP autonome sans changer le defaut stdio (Claude Desktop).
    transport = (os.environ.get("JARVIS_MCP_TRANSPORT")
                 or reglage("mcp.transport", "stdio") or "stdio").lower()
    exposes = [o.nom for o in registre.exposes_mcp()]
    LOG.info("demarrage MCP (transport=%s) ; %d outils exposes : %s",
             transport, len(exposes), ", ".join(exposes))
    if transport in ("http", "streamable-http"):
        _lancer_http("streamable-http")
    elif transport == "sse":
        _lancer_http("sse")
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
