"""
Interface visuelle facon reacteur arc pour l'assistant vocal.

Sert une petite page web en local et lui pousse l'etat en temps reel
via Server-Sent Events. Bibliotheque standard uniquement : aucun paquet
a installer. Le serveur tourne dans un thread daemon, donc importer ce
module et appeler demarrer() n'empeche jamais le programme de quitter.

Exemple :

    import hud
    hud.demarrer()
    hud.config("qwen3.5:4b", "whisper medium")
    hud.etat("ecoute")
    hud.niveau(0.6)
    hud.dire_vous("allume la lumiere de la chambre")
    hud.outil("allumer_lumiere", "chambre -> on")
    hud.dire_jarvis("C'est fait, la chambre est allumee.")

Lance directement (python hud.py) il joue un scenario en boucle pour
voir le rendu sans le reste de l'assistant.
"""

import json
import queue
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------- reglages

def _port_configure():
    """Port du HUD (config hud.port), 8770 par defaut."""
    try:
        from core.config import reglage
        return int(reglage("hud.port", 8770))
    except Exception:
        return 8770


PORT = _port_configure()
_FICHIER_HTML = Path(__file__).parent / "hud.html"

# Etats possibles, envoyes tels quels a la page.
VEILLE = "veille"
ECOUTE = "ecoute"
REFLEXION = "reflexion"
PAROLE = "parole"

# ---------------------------------------------------------------- etat partage

# Instantane courant, renvoye a chaque nouveau client pour qu'il affiche
# tout de suite le bon etat sans attendre le prochain evenement.
_ETAT = {
    "etat": VEILLE,
    "niveau": 0.0,
    "modele": "",
    "stt": "",
    "routage": "",
    "budget": None,
    "hermes": None,
    "micro": False,
}

# Une file par onglet connecte. Le verrou protege l'ensemble.
_CLIENTS = set()
_VERROU = threading.Lock()

# Dernieres lignes de transcription, rejouees a la reconnexion d'un client.
_HISTORIQUE = deque(maxlen=40)

_SERVEUR = None


def _diffuser(evenement):
    """Envoie un evenement (dict) a tous les clients connectes."""
    donnees = json.dumps(evenement, ensure_ascii=False)
    with _VERROU:
        morts = []
        for fil in _CLIENTS:
            try:
                fil.put_nowait(donnees)
            except queue.Full:
                # Client qui ne lit plus : on l'abandonne.
                morts.append(fil)
        for fil in morts:
            _CLIENTS.discard(fil)


# ---------------------------------------------------------------- API publique


def etat(nom):
    """Change l'etat visuel : veille, ecoute, reflexion ou parole."""
    _ETAT["etat"] = nom
    _diffuser({"t": "etat", "v": nom})


def niveau(valeur):
    """Regle le niveau du micro, entre 0 et 1. Fait enfler le coeur."""
    v = max(0.0, min(float(valeur), 1.0))
    _ETAT["niveau"] = v
    _diffuser({"t": "niveau", "v": v})


def dire_vous(texte):
    """Ajoute une ligne de transcription cote utilisateur."""
    evenement = {"t": "vous", "texte": str(texte)}
    _HISTORIQUE.append(evenement)
    _diffuser(evenement)


def dire_jarvis(texte):
    """Ajoute une ligne de transcription cote assistant."""
    evenement = {"t": "jarvis", "texte": str(texte)}
    _HISTORIQUE.append(evenement)
    _diffuser(evenement)


def outil(nom, detail=""):
    """Signale un appel d'outil dans la transcription."""
    evenement = {"t": "outil", "nom": str(nom), "detail": str(detail)}
    _HISTORIQUE.append(evenement)
    _diffuser(evenement)


def config(modele, stt):
    """Renseigne le releve d'etat : modele de langage et moteur d'ecoute."""
    _ETAT["modele"] = modele
    _ETAT["stt"] = stt
    _diffuser({"t": "config", "modele": modele, "stt": stt})


def routage(mode):
    """Mode de routage courant (local / hybride / qualite)."""
    _ETAT["routage"] = mode
    _diffuser({"t": "routage", "v": mode})


def budget(cout_jour, plafond=None, pct=0.0):
    """Budget consomme du jour (cout $, plafond $, fraction 0..1)."""
    _ETAT["budget"] = {"cout": cout_jour, "plafond": plafond, "pct": pct}
    _diffuser({"t": "budget", "cout": cout_jour, "plafond": plafond, "pct": pct})


def hermes(taches, tokens=None):
    """Activite Hermes : nb de taches en cours + tokens consommes (part Hermes)."""
    _ETAT["hermes"] = {"taches": taches, "tokens": tokens}
    _diffuser({"t": "hermes", "taches": taches, "tokens": tokens})


def confirmation(actif):
    """Indicateur d'attente d'une confirmation vocale (bandeau)."""
    _diffuser({"t": "confirmation", "v": bool(actif)})


def micro(muet):
    """Micro coupe (wake word en pause) ou non."""
    _ETAT["micro"] = bool(muet)
    _diffuser({"t": "micro", "v": bool(muet)})


def demo(actif):
    """Affiche un badge DEMO (scenario de demonstration, rien de reel)."""
    _diffuser({"t": "demo", "v": bool(actif)})


# ---------------------------------------------------------------- serveur


class _Poignee(BaseHTTPRequestHandler):
    """Sert la page et le flux SSE. Le reste renvoie 404."""

    def log_message(self, *args):
        pass  # pas de bruit dans la console

    def do_GET(self):
        if self.path == "/flux":
            self._flux()
        elif self.path in ("/", "/hud.html", "/index.html"):
            self._page()
        else:
            self.send_error(404)

    def _page(self):
        try:
            corps = _FICHIER_HTML.read_bytes()
        except OSError:
            self.send_error(500, "hud.html introuvable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _flux(self):
        """Une connexion SSE = une file dediee, videe jusqu'a la deconnexion."""
        fil = queue.Queue(maxsize=200)
        with _VERROU:
            _CLIENTS.add(fil)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            # Instantane : etat courant puis historique recent, pour qu'un
            # onglet qui arrive (ou revient) soit tout de suite a jour.
            self._pousser({"t": "etat", "v": _ETAT["etat"]})
            self._pousser({"t": "niveau", "v": _ETAT["niveau"]})
            self._pousser({"t": "config", "modele": _ETAT["modele"],
                           "stt": _ETAT["stt"]})
            if _ETAT.get("routage"):
                self._pousser({"t": "routage", "v": _ETAT["routage"]})
            if _ETAT.get("budget"):
                b = _ETAT["budget"]
                self._pousser({"t": "budget", "cout": b["cout"],
                               "plafond": b["plafond"], "pct": b["pct"]})
            if _ETAT.get("hermes"):
                h = _ETAT["hermes"]
                self._pousser({"t": "hermes", "taches": h["taches"],
                               "tokens": h["tokens"]})
            self._pousser({"t": "micro", "v": _ETAT.get("micro", False)})
            for evenement in list(_HISTORIQUE):
                self._pousser(evenement)

            # Flux continu. Le timeout sert a envoyer un battement de coeur
            # qui garde la connexion (et detecte les clients partis).
            while True:
                try:
                    donnees = fil.get(timeout=15)
                    self._ecrire(donnees)
                except queue.Empty:
                    self.wfile.write(b": battement\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # l'onglet a ete ferme
        finally:
            with _VERROU:
                _CLIENTS.discard(fil)

    def _pousser(self, evenement):
        self._ecrire(json.dumps(evenement, ensure_ascii=False))

    def _ecrire(self, donnees):
        self.wfile.write(b"data: " + donnees.encode("utf-8") + b"\n\n")
        self.wfile.flush()


class _Serveur(ThreadingHTTPServer):
    """Serveur HUD silencieux sur les deconnexions clientes (onglet ferme/rechargé)."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionError, OSError)):
            return  # deconnexion normale : pas de traceback dans la console
        super().handle_error(request, client_address)


def demarrer(ouvrir=True):
    """Lance le serveur dans un thread daemon et ouvre le navigateur.

    Sans effet si le serveur tourne deja. Renvoie l'instance du serveur.
    """
    global _SERVEUR
    if _SERVEUR is not None:
        return _SERVEUR

    _SERVEUR = _Serveur(("127.0.0.1", PORT), _Poignee)
    _SERVEUR.daemon_threads = True

    thread = threading.Thread(target=_SERVEUR.serve_forever, daemon=True)
    thread.start()

    print(f"HUD sur http://127.0.0.1:{PORT}/")
    if ouvrir:
        try:
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
        except Exception:
            pass
    return _SERVEUR


# ---------------------------------------------------------------- demonstration


def _scenario():
    """Joue une conversation type en boucle pour tester le rendu."""
    import math

    demo(True)                                   # badge DEMO : rien n'est reel
    config("Claude · claude-haiku-4-5 (demo)", "whisper medium")
    routage("hybride")
    budget(0.27, 3.0, 0.09)
    hermes(0, 48213)

    tours = [
        ("allume la lumiere de la chambre",
         "allumer_lumiere", "chambre -> on",
         "C'est fait, la chambre est allumee."),
        ("mets le salon en bleu",
         "changer_couleur", "salon -> bleu",
         "Voila, le salon passe en bleu."),
        ("quelle heure est-il",
         "heure_et_date", "",
         "Il est vingt-deux heures dix, le mardi cinq aout."),
        ("baisse la chambre a trente pour cent",
         "regler_luminosite", "chambre -> 30%",
         "La chambre est reglee a trente pour cent."),
    ]

    pas = 0
    while True:
        for question, nom_outil, detail, reponse in tours:
            # Veille : le fond respire doucement.
            etat(VEILLE)
            for _ in range(24):
                pas += 1
                niveau(0.04 + 0.03 * (0.5 + 0.5 * math.sin(pas * 0.15)))
                time.sleep(0.05)

            # Ecoute : le niveau du micro grimpe pendant que l'on parle.
            etat(ECOUTE)
            dire_vous(question)
            for i in range(36):
                pas += 1
                base = 0.35 + 0.35 * abs(math.sin(i * 0.35))
                niveau(base + 0.1 * math.sin(pas * 0.9))
                time.sleep(0.045)
            niveau(0.05)

            # Reflexion : appel d'outil.
            etat(REFLEXION)
            if nom_outil:
                time.sleep(0.4)
                outil(nom_outil, detail)
            time.sleep(0.9)

            # Parole : reponse en ambre.
            etat(PAROLE)
            dire_jarvis(reponse)
            for i in range(30):
                pas += 1
                niveau(0.3 + 0.25 * abs(math.sin(pas * 0.6)))
                time.sleep(0.05)
            niveau(0.05)
            time.sleep(0.5)


if __name__ == "__main__":
    demarrer()
    print("Scenario de demonstration en boucle. Ctrl+C pour quitter.")
    try:
        _scenario()
    except KeyboardInterrupt:
        print("\nArret.")
