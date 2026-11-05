"""Serveur web unifie de Jarvis : UN seul FastAPI / UN seul port pour tout.

Regroupe, sous un unique tunnel ngrok :
  - le pont iPhone      -> POST /api/inbox        (core.pont_iphone)
  - le webhook Twilio   -> WebSocket /stream      (tools.appel_direct, appels V2)
  - les futures PWA     -> a monter ici (routes /...)

Ainsi ton domaine ngrok statique sert TOUT. Config : section `serveur`
(actif/port/public_url/ngrok_authtoken). Les anciennes cles (pont_iphone.port,
twilio.public_url/ngrok_authtoken, appels.port_stream) restent lues en repli.
"""
import logging
import socket
import threading

# Magasin de certificats Windows : indispensable AVANT pyngrok, dont l'installeur
# telecharge le binaire ngrok en TLS (Malwarebytes intercepte -> sinon "certificate
# verify failed" et le tunnel ne s'ouvre jamais).
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from core.config import reglage

LOG = logging.getLogger("jarvis")

_APP = None
_SERVEUR = None
_URL = None
_UVICORN = None     # instance uvicorn.Server du serveur unifie (cf. _ecoute)
# Demarrage et url_publique() (appels Twilio) peuvent ouvrir le tunnel depuis deux
# threads : un seul a la fois, et un echec n'efface jamais une URL valide.
_VERROU_TUNNEL = threading.Lock()


def port_effectif():
    """Port d'ecoute du serveur unifie : serveur.port, puis les replis historiques
    pont_iphone.port et appels.port_stream, puis 8790. A reutiliser partout (HUD,
    panneau, gestes) pour ne jamais viser un autre port que celui ecoute."""
    return int(reglage("serveur.port",
                       reglage("pont_iphone.port", reglage("appels.port_stream", 8790))))


def _port():
    return port_effectif()


def app():
    """Construit (une fois) l'app FastAPI avec toutes les routes montees."""
    global _APP
    if _APP is None:
        from fastapi import FastAPI
        # Pas de /docs, /redoc ni /openapi.json : l'app est joignable par le tunnel
        # public, inutile d'y publier la carte des routes.
        _APP = FastAPI(title="Jarvis", docs_url=None, redoc_url=None, openapi_url=None)
        from core.pont_iphone import monter_routes
        monter_routes(_APP)                       # /api/inbox, /api/ping
        try:
            from core.panneau import monter_routes as monter_panneau
            monter_panneau(_APP)                  # /panneau + /api/panneau/* (LOCAL uniquement)
        except Exception:
            LOG.exception("montage du panneau de configuration")
        try:
            from core.gestes import monter_routes as monter_gestes
            monter_gestes(_APP)                   # /api/gestes (loopback + token)
        except Exception:
            LOG.exception("montage des routes gestes")
        try:
            from core.cockpit import monter_routes as monter_cockpit
            monter_cockpit(_APP)                  # /cockpit + /api/cockpit/* (LOCAL uniquement)
        except Exception:
            LOG.exception("montage du cockpit")
        try:
            from tools.appel_direct import monter_ws
            monter_ws(_APP)                        # /stream (Twilio Media Streams)
        except Exception:
            LOG.exception("montage du websocket /stream")
        try:
            from core.satellite import monter_routes as monter_satellite
            monter_satellite(_APP)                 # /satellite (LAN, token par satellite)
        except Exception:
            LOG.exception("montage du websocket /satellite")
    return _APP


def _port_ouvert(port, timeout=0.3):
    try:
        socket.create_connection(("127.0.0.1", port), timeout).close()
        return True
    except OSError:
        return False


def _ecoute():
    """Vrai seulement si NOTRE uvicorn ecoute. _port_ouvert() ne suffit pas : un autre
    processus qui tiendrait deja le port y repondrait a sa place, et le tunnel ngrok
    publierait alors ce processus etranger."""
    return bool(_UVICORN is not None and getattr(_UVICORN, "started", False)
                and _SERVEUR is not None and _SERVEUR.is_alive())


def demarrer():
    """Lance le serveur unifie en tache de fond (idempotent). Attend qu'il ecoute."""
    global _SERVEUR, _UVICORN
    port = _port()
    if _SERVEUR and _SERVEUR.is_alive():
        return
    import time
    import uvicorn
    # SÉCURITÉ : loopback par défaut. Le tunnel ngrok se connecte en 127.0.0.1
    # (aucun impact) ; le panneau/cockpit/gestes ne sont donc PAS exposés au LAN.
    # Ne passe à "0.0.0.0" que si tu SAIS ce que tu fais (accès réseau local).
    hote = reglage("serveur.host", "127.0.0.1")
    config = uvicorn.Config(app(), host=hote, port=port, log_level="warning")
    serveur = uvicorn.Server(config)

    def run():
        try:
            serveur.run()   # uvicorn n'installe pas les handlers de signaux hors main thread
        except BaseException:
            # Port deja pris : uvicorn fait sys.exit(STARTUP_FAILURE). Ce SystemExit
            # n'est pas une Exception : sans ce filet, le thread mourait sans trace.
            LOG.exception("serveur web : uvicorn n'a pas pu ecouter sur %s:%s", hote, port)

    _UVICORN = serveur
    _SERVEUR = threading.Thread(target=run, daemon=True, name="serveur-web")
    _SERVEUR.start()
    for _ in range(40):                # attend que NOTRE uvicorn ecoute (max ~6 s)
        if serveur.started or not _SERVEUR.is_alive():
            break
        time.sleep(0.15)
    # Listener LAN séparé : il ne contient QUE /satellite et /desktop-agent. Le serveur unifié
    # reste en loopback, donc panneau/cockpit/inbox/Twilio ne gagnent aucun accès
    # réseau lorsqu'un Raspberry Pi est configuré. Il est indépendant du port ci-dessus :
    # on le lance même si le serveur unifié n'a pas démarré.
    try:
        from core.satellite import demarrer_lan
        demarrer_lan()
    except Exception:
        LOG.exception("demarrage du listener satellite LAN")
    if not _ecoute():
        LOG.error("serveur web NON demarre sur le port %s (port deja utilise ou erreur "
                  "de demarrage) : tunnel ngrok non ouvert", port)
        print(f"Serveur web NON demarre : port {port} deja utilise ou erreur de "
              "demarrage (voir le journal). Tunnel ngrok non ouvert.")
        return
    # Ouvre le tunnel ngrok automatiquement (si authtoken configure et pas d'URL
    # manuelle) pour que l'endpoint soit joignable des le demarrage.
    try:
        _ouvrir_tunnel()
    except Exception:
        LOG.exception("ouverture du tunnel ngrok")
    print(f"Serveur web : port {port} (iPhone /api/inbox, Twilio /stream).")


def _ouvrir_tunnel():
    """Ouvre le tunnel ngrok en mode AUTO : authtoken configure, pas d'URL manuelle.
    Utilise ton domaine STATIQUE si serveur.ngrok_domaine est renseigne.
    Degrade proprement (message clair) si l'antivirus bloque ngrok."""
    global _URL
    if reglage("serveur.public_url", "") or reglage("twilio.public_url", ""):
        return                          # tu geres ton tunnel toi-meme (CLI)
    if not _ecoute():
        # Notre serveur n'ecoute pas : ne jamais publier ce qui tiendrait le port
        # (couvre aussi l'appel paresseux de url_publique()).
        return
    if _URL:
        return
    tok = reglage("serveur.ngrok_authtoken", "") or reglage("twilio.ngrok_authtoken", "")
    if not tok:
        return
    from pyngrok import ngrok
    with _VERROU_TUNNEL:
        if _URL:
            return                      # un autre thread vient de l'ouvrir
        try:
            ngrok.set_auth_token(tok)
            domaine = reglage("serveur.ngrok_domaine", "")
            options = {"domain": domaine} if domaine else {}
            # Adresse explicite : un port seul devient « localhost:port », que Windows
            # peut resoudre en IPv6 (::1) alors que le serveur n'ecoute qu'en 127.0.0.1
            # (ngrok repond alors ERR_NGROK_8012 / HTTP 502).
            _URL = ngrok.connect(f"127.0.0.1:{_port()}", "http", **options).public_url
            LOG.info("tunnel ngrok ouvert : %s", _URL)
            print(f"Tunnel ngrok ouvert : {_URL}")
        except Exception as e:
            # Pas de « _URL = None » : dans ce chemin _URL n'a jamais ete rempli, et
            # l'ecraser effacerait une URL ouverte entre-temps par un autre thread.
            msg = str(e)
            if "certificate" in msg or "x509" in msg or "unknown authority" in msg:
                # Cas connu : un antivirus (Avast Web Shield) intercepte et BLOQUE ngrok
                # avec un certificat "Untrusted Root" -> l'agent ne peut pas s'authentifier.
                LOG.error("tunnel ngrok bloque par l'antivirus (certificat non fiable). "
                          "Ajoute une exception Avast pour connect.ngrok-agent.com et *.ngrok-free.app, "
                          "ou utilise un tunnel lance a la main (serveur.public_url). Voir docs/iphone.md.")
                print("ATTENTION : le tunnel ngrok est bloque par l'antivirus (Avast). "
                      "Le serveur local tourne mais n'est pas joignable de l'exterieur. "
                      "Ajoute une exception Avast (voir docs/iphone.md) puis relance.")
            else:
                LOG.exception("ouverture du tunnel ngrok")
                print(f"Tunnel ngrok indisponible : {msg[:120]}")


def url_publique():
    """Base publique https:// : URL manuelle, sinon le tunnel ngrok auto."""
    manuel = reglage("serveur.public_url", "") or reglage("twilio.public_url", "")
    if manuel:
        return manuel.rstrip("/")
    if not _URL:
        _ouvrir_tunnel()
    return _URL or ""


def url_ws():
    """Base wss:// (pour l'URL du <Stream> de Twilio)."""
    return url_publique().replace("https://", "wss://").replace("http://", "ws://")
