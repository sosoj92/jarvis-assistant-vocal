"""Serveur MCP exposant les outils de Jarvis a n'importe quel client MCP.

Reutilise le registre d'outils (dossier tools/) : chaque outil marque
mcp_expose=True est expose automatiquement, avec son nom, sa description et le
schema de parametres derive de sa signature. Aucune logique dupliquee : ajouter
un outil expose dans tools/ suffit a le publier ici.

Tourne independamment de l'assistant vocal (les deux peuvent coexister) :

    uv run python -m jarvis.mcp_server

Transport stdio par defaut (standard des clients desktop) ; HTTP/SSE possible via
config.yaml (mcp.transport: http). Tous les appels externes vont dans logs/mcp.log.

Securite : seuls des outils N1 explicitement marques sont exposes (lectures sures,
minuteur...). Aucun outil a confirmation ni N3 ne l'est jamais, et ni lumieres, ni
camera, ni micro, ni OBS (doctrine de CLAUDE.md).
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
        resultat = registre.executer(outil, kwargs)
    except Exception as e:
        LOG.exception("erreur outil %s", outil.nom)
        resultat = f"Erreur : {e}"
    LOG.info("appel %s args=%s -> %s", outil.nom, kwargs, str(resultat)[:200])
    # Les outils exposes renvoient du texte ; on aplati un eventuel dict image.
    if isinstance(resultat, dict) and resultat.get("image"):
        resultat = resultat.get("apercu", "(image)")
    # Defense en profondeur pour Hermes : un contenu de tiers (ex. chercher_inspiration)
    # arrive balise comme donnees non fiables, jamais comme consignes.
    return registre.baliser_externe(outil.nom, str(resultat))


def _enregistrer(outil):
    # registre.exposes_mcp() ne renvoie jamais d'outil a confirmation : un client
    # MCP ne peut pas confirmer a la place de l'utilisatrice (plus de confirm=true).
    if outil.confirmation or registre.est_n3(outil.nom):
        raise ValueError(f"{outil.nom} demande une confirmation : jamais expose au MCP")
    fonction = outil.fonction
    sig = inspect.signature(fonction)

    @functools.wraps(fonction)
    def wrapper(*a, **k):
        return _executer(outil, {**dict(zip(
            [p.name for p in sig.parameters.values()], a)), **k})

    server.add_tool(wrapper, name=outil.nom, description=outil.description)


for _o in registre.exposes_mcp():
    _enregistrer(_o)


class _ExigerJeton:
    """Enveloppe ASGI : refuse toute requete HTTP sans « Authorization: Bearer <jeton> »."""

    def __init__(self, app, jeton):
        self.app = app
        self.attendu = f"Bearer {jeton}".encode()

    async def __call__(self, scope, receive, send):
        import secrets
        if scope.get("type") == "http":
            fourni = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not secrets.compare_digest(fourni, self.attendu):
                LOG.warning("requete MCP refusee : jeton absent ou invalide")
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"jeton MCP requis"})
                return
        await self.app(scope, receive, send)


def _jeton_mcp():
    import os
    return str(os.environ.get("JARVIS_MCP_TOKEN") or reglage("mcp.token", "") or "").strip()


def _lancer_http(kind):
    host = reglage("mcp.host", "127.0.0.1")
    port = int(reglage("mcp.port", 8765))
    jeton = _jeton_mcp()
    if host not in ("127.0.0.1", "::1", "localhost") and not jeton:
        # Hors loopback, la protection anti DNS rebinding du SDK est coupee et
        # n'importe quelle machine du reseau pourrait appeler les outils : refus.
        raise SystemExit(f"[MCP] refus d'ecouter sur {host} sans jeton : renseigne "
                         "mcp.token (ou JARVIS_MCP_TOKEN), ou garde mcp.host: 127.0.0.1.")
    print(f"Serveur MCP {kind} sur http://{host}:{port}"
          + (" (jeton exige)" if jeton else ""))
    if not jeton:
        try:
            server.run(kind, host=host, port=port)
        except TypeError:
            server.run(kind)
        return
    import uvicorn
    app = (server.sse_app(host=host) if kind == "sse"
           else server.streamable_http_app(host=host))
    uvicorn.run(_ExigerJeton(app, jeton), host=host, port=port, log_level="warning")


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
