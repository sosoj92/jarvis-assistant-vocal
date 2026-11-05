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

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------- reglages

PORT = 8770
_FICHIER_HTML = Path(__file__).parent / "hud.html"
# <title> de hud.html : sert a retrouver la fenetre du HUD parmi les autres.
TITRE_FENETRE = "JARVIS · Reacteur arc"
# Une fenetre fermee n'est rouverte qu'une fois par minute au plus.
_DELAI_REOUVERTURE = 60.0
# Secondes entre deux battements du flux (et verifications de version de la page).
_BATTEMENT = 15
_MODE_FENETRE = "navigateur"
_DERNIERE_OUVERTURE = 0.0
# Ecran ou ouvrir la fenetre : numero (meme numerotation que l'overlay) ou position
# par rapport a l'ecran principal ("haut", "bas", "gauche", "droite") ; None = libre.
_ECRAN = None
_POSITIONS_ECRAN = {"principal": "principal", "haut": "haut", "dessus": "haut",
                    "bas": "bas", "dessous": "bas", "gauche": "gauche",
                    "droite": "droite"}

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
    "tableau": [],
}

# Une file par onglet connecte. Le verrou protege l'ensemble.
_CLIENTS = set()
_VERROU = threading.Lock()

# Tuiles du tableau de bord par id, dans leur ordre d'arrivee.
_TABLEAU = {}
_VERROU_TABLEAU = threading.Lock()
_MAX_TUILES = 12

# Dernieres lignes de transcription, rejouees a la reconnexion d'un client.
_HISTORIQUE = deque(maxlen=40)

_SERVEUR = None


def _version_page(contenu=None):
    """Empreinte de hud.html. Une fenetre ouverte la compare a celle annoncee par le
    flux et se recharge seule quand la page a change (mise a jour deployee)."""
    try:
        contenu = _FICHIER_HTML.read_bytes() if contenu is None else contenu
    except OSError:
        return ""
    return hashlib.sha1(contenu).hexdigest()[:12]


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


def _client_actif(fil):
    """Faux si la file a ete evincee (ou le client parti) : son flux doit se fermer."""
    with _VERROU:
        return fil in _CLIENTS


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


def tableau(tuiles):
    """Tuiles du tableau de bord, affichees par la page au repos (etat veille).

    tuiles : liste de dicts portant chacun un "id" (voir core/tableau_de_bord.py).
    Elles sont fusionnees par id avec celles deja recues, si bien que plusieurs
    emetteurs (le poste local, plus tard le serveur) peuvent publier les leurs."""
    if not isinstance(tuiles, (list, tuple)):
        return
    with _VERROU_TABLEAU:
        for tuile in tuiles:
            if not isinstance(tuile, dict) or not str(tuile.get("id", "")).strip():
                continue
            cle = str(tuile["id"]).strip()
            if cle in _TABLEAU or len(_TABLEAU) < _MAX_TUILES:
                _TABLEAU[cle] = dict(tuile)
        _ETAT["tableau"] = list(_TABLEAU.values())
        instantane = list(_ETAT["tableau"])
    _diffuser({"t": "tableau", "tuiles": instantane})


def _demarrer_tableau():
    """Tableau de bord local (hud.tableau_de_bord.actif) : tuiles lues en fond.

    Lit la configuration du processus courant ; sans elle, ou si une dependance
    manque, la fenetre reste un reacteur classique."""
    try:
        from core import tableau_de_bord
        return tableau_de_bord.demarrer(tableau)
    except Exception as e:
        print(f"[hud] tableau de bord indisponible : {type(e).__name__}")
        return False


# ------------------------------------------------------ controles rapides HUD


def _libelle_modele_actif():
    """Libelle public du LLM actif, sans lire ni exposer aucune cle API."""
    from core.config import reglage
    from core.routage import mode_actuel

    mode = mode_actuel()
    if mode == "local":
        return f"Ollama · {reglage('ollama.modele', 'qwen2.5:7b')}"

    from core import cloud
    fournisseur = cloud.fournisseur()
    marque = "OpenAI" if fournisseur == "openai" else "Claude"
    return f"{marque} · {cloud.modele(qualite=(mode == 'qualite'))}"


def _synchroniser_controles():
    """Actualise le releve du HUD apres une bascule faite dans son tiroir."""
    from core.routage import mode_actuel

    config(_libelle_modele_actif(), _ETAT.get("stt", ""))
    routage(mode_actuel())


def _etat_controles():
    """Etat strictement non sensible utilise par le tiroir de configuration."""
    from core import cloud, panneau
    from core.config import reglage
    from core.routage import mode_actuel

    mode = mode_actuel()
    fournisseur = cloud.fournisseur()
    openai = panneau._openai_etat()
    eleven = panneau._elevenlabs_voix()
    installes = panneau._ollama_installes()

    modeles_openai = list(openai.get("catalogue", []))
    noms_openai = {m.get("nom") for m in modeles_openai}
    for nom in (reglage("openai.modele", cloud.modele_par_defaut("openai")),
                reglage("openai.modele_qualite",
                        cloud.modele_par_defaut("openai", qualite=True))):
        if nom and nom not in noms_openai:
            modeles_openai.append({"nom": nom, "role": "Configure manuellement",
                                    "accessible": None})
            noms_openai.add(nom)

    modeles_anthropic = []
    for nom in (reglage("anthropic.modele", cloud.modele_par_defaut("anthropic")),
                reglage("anthropic.modele_qualite",
                        cloud.modele_par_defaut("anthropic", qualite=True))):
        if nom and nom not in modeles_anthropic:
            modeles_anthropic.append(nom)

    locaux = [m.get("nom", "") for m in installes if m.get("nom")]
    local_actif = str(reglage("ollama.modele", "qwen2.5:7b"))
    if local_actif and local_actif not in locaux:
        locaux.insert(0, local_actif)

    return {
        "ok": True,
        "mode": mode,
        "modele_actif": _libelle_modele_actif(),
        "cloud": {
            "fournisseur": fournisseur,
            "configure": {
                "openai": bool(openai.get("configure")),
                "anthropic": bool(reglage("anthropic.cle", "")),
            },
            "courants": {
                "openai": {
                    "hybride": reglage(
                        "openai.modele", cloud.modele_par_defaut("openai")),
                    "qualite": reglage(
                        "openai.modele_qualite",
                        cloud.modele_par_defaut("openai", qualite=True)),
                },
                "anthropic": {
                    "hybride": reglage(
                        "anthropic.modele", cloud.modele_par_defaut("anthropic")),
                    "qualite": reglage(
                        "anthropic.modele_qualite",
                        cloud.modele_par_defaut("anthropic", qualite=True)),
                },
            },
            "modeles": {
                "openai": modeles_openai,
                "anthropic": [{"nom": n, "role": "Configure dans Jarvis",
                                "accessible": None} for n in modeles_anthropic],
            },
            "openai_joignable": bool(openai.get("joignable")),
        },
        "local": {
            "modele": local_actif,
            "modeles": locaux,
            "joignable": panneau._ollama_joignable(),
        },
        "voix": {
            "moteur": reglage("tts.moteur", "auto"),
            "elevenlabs_voix": reglage("elevenlabs.voix", ""),
            "elevenlabs_modele": reglage("elevenlabs.modele", "eleven_flash_v2_5"),
            "elevenlabs": eleven,
            "moteurs": ["auto", "elevenlabs", "piper", "kokoro", "windows"],
            "modeles_elevenlabs": ["eleven_flash_v2_5", "eleven_multilingual_v2"],
        },
        "panneau_url": f"http://127.0.0.1:{_port_serveur()}/panneau",
    }


def _port_serveur():
    """Port du serveur unifie, replis historiques compris (voir core.serveur)."""
    try:
        from core.serveur import port_effectif
        return port_effectif()
    except Exception:
        from core.config import reglage
        return int(reglage("serveur.port", 8790))


# Un seul test vocal a la fois : plusieurs clics ne lancent pas plusieurs voix.
_TEST_VOIX = threading.Lock()


def _tester_voix():
    """Lance un test vocal, ou dit honnetement qu'aucune voix n'est branchee ici."""
    from core import voix

    if not voix.disponible():
        # Cas de l'agent du bureau : il sert le HUD mais la voix est synthetisee
        # par le serveur Jarvis. Un « Test vocal lance » serait un faux succes, et
        # le test du panneau du serveur jouerait sur la sortie audio du serveur,
        # pas ici : on propose plutot un test a la voix depuis ce poste.
        return {"ok": False, "message": (
            "Aucune voix dans ce processus : le test vocal n'est pas disponible depuis "
            "ce HUD. Pour l'entendre ici, dis simplement « Jarvis, dis bonjour ».")}
    if not _TEST_VOIX.acquire(blocking=False):
        return {"ok": False, "message": "Un test vocal est deja en cours."}

    def _jouer():
        try:
            voix.parler("Test de la voix Jarvis. Tout fonctionne.")
        except Exception as e:
            print(f"[hud] test vocal en echec : {type(e).__name__}")
        finally:
            _TEST_VOIX.release()

    try:
        threading.Thread(target=_jouer, daemon=True, name="hud-test-voix").start()
    except Exception:
        _TEST_VOIX.release()
        raise
    return {"ok": True, "message": "Test vocal lance."}


def _appliquer_controle(donnees):
    """Applique une action whitelistée du HUD et renvoie un resultat JSON."""
    from core import panneau

    action = str((donnees or {}).get("action", "")).strip().lower()
    if action == "mode":
        resultat = panneau._definir_reglage("mode", donnees.get("valeur", ""))
    elif action == "modele_local":
        resultat = panneau._definir_actif("local", str(donnees.get("modele", "")).strip())
    elif action == "modele_cloud":
        resultat = panneau._definir_actif(
            "cloud", str(donnees.get("modele", "")).strip(),
            profil=str(donnees.get("profil", "hybride")).strip().lower(),
            fournisseur=str(donnees.get("fournisseur", "openai")).strip().lower())
    elif action == "moteur_voix":
        resultat = panneau._definir_reglage("tts.moteur", donnees.get("valeur", ""))
    elif action == "voix_elevenlabs":
        resultat = panneau._definir_reglage(
            "elevenlabs.voix", donnees.get("valeur", ""))
    elif action == "modele_elevenlabs":
        resultat = panneau._definir_reglage(
            "elevenlabs.modele", donnees.get("valeur", ""))
    elif action == "tester_voix":
        resultat = _tester_voix()
    else:
        return {"ok": False, "message": "Controle inconnu."}

    if resultat.get("ok") and action != "tester_voix":
        _synchroniser_controles()
    return resultat


# ---------------------------------------------------------------- serveur


class _Poignee(BaseHTTPRequestHandler):
    """Sert la page et le flux SSE. Le reste renvoie 404."""

    def log_message(self, *args):
        pass  # pas de bruit dans la console

    def _locale(self):
        """Poste local, Host local (anti DNS rebinding) : sinon 403. Vaut aussi pour
        le flux /flux, qui diffuse les phrases et reponses de Jarvis."""
        from core.http_local import requete_locale
        if requete_locale(self.client_address[0], self.headers):
            return True
        self._json({"ok": False, "message": "Acces local uniquement."}, 403)
        return False

    def do_GET(self):
        if not self._locale():
            return
        chemin = self.path.split("?", 1)[0]
        if chemin == "/flux":
            self._flux()
        elif chemin == "/api/controle":
            self._controle_etat()
        elif chemin in ("/", "/hud.html", "/index.html"):
            self._page()
        else:
            self.send_error(404)

    def do_POST(self):
        chemin = self.path.split("?", 1)[0]
        if chemin != "/api/controle":
            self.send_error(404)
            return
        if not self._locale():
            return
        # L'en-tete custom provoque un preflight pour toute page tierce : sans
        # reponse CORS, un site visite dans le navigateur ne peut pas modifier Jarvis.
        if self.headers.get("X-Jarvis-HUD") != "1":
            self._json({"ok": False, "message": "Requete HUD invalide."}, 403)
            return
        # Type exact (comme le panneau) : « text/plain; application/json » est refuse.
        type_corps = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if type_corps != "application/json":
            self._json({"ok": False, "message": "Corps JSON requis."}, 415)
            return
        try:
            taille = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            taille = 0
        if taille <= 0 or taille > 8192:
            self._json({"ok": False, "message": "Taille de requete invalide."}, 400)
            return
        try:
            donnees = json.loads(self.rfile.read(taille).decode("utf-8"))
            resultat = _appliquer_controle(donnees)
            self._json(resultat, 200 if resultat.get("ok") else 400)
        except Exception as e:
            self._json({"ok": False, "message": str(e)[:160]}, 500)

    def _controle_etat(self):
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            self._json({"ok": False, "message": "Acces local uniquement."}, 403)
            return
        try:
            self._json(_etat_controles())
        except Exception as e:
            self._json({"ok": False, "message": str(e)[:160]}, 500)

    def _json(self, donnees, statut=200):
        corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self.send_response(statut)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _page(self):
        try:
            corps = _FICHIER_HTML.read_bytes()
        except OSError:
            self.send_error(500, "hud.html introuvable")
            return
        corps = corps.replace(b"__VERSION_PAGE__", _version_page(corps).encode("ascii"))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("X-Frame-Options", "DENY")
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
            self._pousser({"t": "version", "v": _version_page()})
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
            if _ETAT.get("tableau"):
                self._pousser({"t": "tableau", "tuiles": list(_ETAT["tableau"])})
            for evenement in list(_HISTORIQUE):
                self._pousser(evenement)

            # Flux continu. Le timeout sert a envoyer un battement de coeur
            # qui garde la connexion (et detecte les clients partis). A chaque
            # battement, une page modifiee sur le disque est annoncee : la
            # fenetre ouverte se recharge sans redemarrage de Jarvis.
            # Un client evince par _diffuser (file pleine, lecteur gele) n'est
            # plus dans _CLIENTS : on ferme la connexion au lieu de l'entretenir
            # par des battements. EventSource se reconnecte alors et recoit un
            # instantane complet.
            version = _version_page()
            while _client_actif(fil):
                try:
                    donnees = fil.get(timeout=_BATTEMENT)
                    if not _client_actif(fil):
                        break
                    self._ecrire(donnees)
                except queue.Empty:
                    if not _client_actif(fil):
                        break
                    actuelle = _version_page()
                    if actuelle and actuelle != version:
                        version = actuelle
                        self._pousser({"t": "version", "v": version})
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
    """Serveur HUD silencieux sur les deconnexions clientes (onglet ferme/rechargé).

    Port exclusif : sous Windows, SO_REUSEADDR (herite de HTTPServer) laisserait un
    second HUD (demo, ancien agent) ecouter le meme port sans erreur. Poser a la
    fois SO_REUSEADDR et SO_EXCLUSIVEADDRUSE est refuse par Winsock : sous Windows
    seulement, on retire donc SO_REUSEADDR (ailleurs il evite d'attendre la fin de
    TIME_WAIT apres un redemarrage)."""
    daemon_threads = True

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionError, OSError)):
            return  # deconnexion normale : pas de traceback dans la console
        super().handle_error(request, client_address)


def demarrer(ouvrir=True, fenetre="navigateur", ecran=None, tableau_local=True):
    """Lance le serveur dans un thread daemon et ouvre l'affichage.

    fenetre="app" ouvre une fenetre dediee (Edge ou Chrome en mode application,
    sans onglets), que mettre_au_premier_plan() retrouve a coup sur ;
    "navigateur" ouvre un onglet classique. ecran (mode app) : ecran ou placer la
    fenetre, soit un index (0 = principal puis de gauche a droite, comme l'overlay),
    soit une position ("haut", "bas", "gauche", "droite"), qui reste juste meme si
    un autre ecran est eteint. tableau_local : lance aussi le tableau de bord si
    hud.tableau_de_bord.actif le demande. Sans effet si le serveur tourne deja.
    Renvoie l'instance du serveur.
    """
    global _SERVEUR, _MODE_FENETRE, _ECRAN
    if _SERVEUR is not None:
        return _SERVEUR
    _MODE_FENETRE = "app" if str(fenetre).lower() == "app" else "navigateur"
    _ECRAN = ecran_demande(ecran)

    try:
        _SERVEUR = _Serveur(("127.0.0.1", PORT), _Poignee)
    except OSError:
        # Les appelants gardent leur contrat (jarvis14 avale l'erreur, l'agent
        # affiche « [hud] indisponible ») ; le message dit enfin pourquoi.
        print(f"[hud] indisponible : port {PORT} occupe "
              "(autre HUD ou demo deja lance).")
        raise
    _SERVEUR.daemon_threads = True

    thread = threading.Thread(target=_SERVEUR.serve_forever, daemon=True)
    thread.start()

    print(f"HUD sur http://127.0.0.1:{PORT}/")
    if tableau_local:
        _demarrer_tableau()
    if ouvrir:
        ouvrir_fenetre()
    return _SERVEUR


# ---------------------------------------------------------------- fenetre


def _navigateur_application():
    """Edge (present sur Windows 11) ou Chrome, capables d'une fenetre --app."""
    candidats = [
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((c for c in candidats if c and os.path.isfile(c)), None)


def commande_fenetre_app(executable):
    """Ligne de commande d'une fenetre dediee, sans onglets ni barre d'adresse."""
    return [executable, f"--app=http://127.0.0.1:{PORT}/"]


def ouvrir_fenetre():
    """Ouvre l'affichage du HUD selon le mode choisi au demarrage."""
    global _DERNIERE_OUVERTURE
    _DERNIERE_OUVERTURE = time.monotonic()
    if _MODE_FENETRE == "app" and sys.platform == "win32":
        executable = _navigateur_application()
        if executable:
            try:
                subprocess.Popen(commande_fenetre_app(executable), close_fds=True)
                if _ECRAN is not None:
                    threading.Thread(target=_placer_apres_ouverture, daemon=True).start()
                return
            except OSError:
                pass
    try:
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
    except Exception:
        pass


def _user32():
    """API Windows des fenetres, avec des signatures 64 bits explicites."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return user32


def trouver_fenetres(titre=TITRE_FENETRE):
    """Fenetres visibles (y compris reduites) dont le titre contient `titre`. Lecture seule."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    user32 = _user32()
    trouvees = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def examiner(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            longueur = user32.GetWindowTextLengthW(hwnd)
            if longueur:
                tampon = ctypes.create_unicode_buffer(longueur + 1)
                user32.GetWindowTextW(hwnd, tampon, longueur + 1)
                if titre in tampon.value:
                    trouvees.append(hwnd)
        return True

    user32.EnumWindows(examiner, 0)
    return trouvees


def zones_ecrans():
    """Zones utiles (sans barre des taches) des ecrans, dans l'ordre de l'overlay :
    l'ecran principal d'abord, puis les autres de gauche a droite."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class InfosEcran(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = _user32()
    ecrans = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def examiner(hmon, _hdc, _rect, _donnee):
        infos = InfosEcran()
        infos.cbSize = ctypes.sizeof(InfosEcran)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(infos)):
            m, w = infos.rcMonitor, infos.rcWork
            ecrans.append(((m.left, m.top), (w.left, w.top, w.right, w.bottom)))
        return True

    user32.EnumDisplayMonitors(None, None, examiner, 0)
    ecrans.sort(key=lambda e: (e[0] != (0, 0), e[0][0], e[0][1]))
    return [zone for _, zone in ecrans]


def ecran_demande(valeur):
    """Reglage hud.ecran normalise : index entier, position connue, ou None (libre)."""
    if valeur is None:
        return None
    texte = str(valeur).strip().lower()
    try:
        return int(texte)
    except ValueError:
        return _POSITIONS_ECRAN.get(texte)


def index_ecran(cible, zones):
    """Index dans `zones` (zones_ecrans) de l'ecran voulu, None s'il n'existe pas.

    cible : un index, ou une position par rapport a l'ecran principal (zones[0]) ;
    s'il y a plusieurs candidats, le plus proche du principal l'emporte."""
    if isinstance(cible, int):
        return cible if 0 <= cible < len(zones) else None
    if not zones or cible not in _POSITIONS_ECRAN.values():
        return None
    if cible == "principal":
        return 0
    g0, h0, d0, b0 = zones[0]
    candidats = []
    for index, (g, h, d, b) in enumerate(zones[1:], start=1):
        x, y = (g + d) / 2, (h + b) / 2
        ecart = {"haut": h0 - y, "bas": y - b0, "gauche": g0 - x, "droite": x - d0}[cible]
        if ecart > 0:
            candidats.append((ecart, index))
    return min(candidats)[1] if candidats else None


def placer_sur_ecran(hwnd, cible):
    """Place la fenetre sur toute la zone utile de l'ecran demande, sans l'activer."""
    zones = zones_ecrans()
    index = index_ecran(cible, zones)
    if index is None:
        return False
    gauche, haut, droite, bas = zones[index]
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 4)                       # SW_SHOWNOACTIVATE
    sans_bouger_l_ordre = 0x0004 | 0x0010 | 0x0040       # NOZORDER|NOACTIVATE|SHOWWINDOW
    return bool(user32.SetWindowPos(hwnd, None, gauche, haut, droite - gauche,
                                    bas - haut, sans_bouger_l_ordre))


def _placer_apres_ouverture(delai_max=15.0):
    """Attend la fenetre qui vient d'etre ouverte puis la place sur l'ecran choisi.

    Le navigateur restaure parfois sa derniere position juste apres l'ouverture :
    le placement est refait une fois, deux secondes plus tard."""
    fin = time.monotonic() + delai_max
    while time.monotonic() < fin and not trouver_fenetres():
        time.sleep(0.25)
    for attente in (0.5, 2.0):
        time.sleep(attente)
        for hwnd in trouver_fenetres():
            placer_sur_ecran(hwnd, _ECRAN)


def cadre_fenetre(hwnd):
    """(gauche, haut, droite, bas) de la fenetre, None si inconnu. Lecture seule."""
    import ctypes
    from ctypes import wintypes
    cadre = wintypes.RECT()
    if not _user32().GetWindowRect(hwnd, ctypes.byref(cadre)):
        return None
    return cadre.left, cadre.top, cadre.right, cadre.bottom


def _replacer_si_deplacee(hwnd):
    """Ramene la fenetre sur l'ecran choisi si son centre n'y est plus.

    Windows deplace les fenetres d'un ecran mis en veille ou debranche vers le
    principal. Une fenetre deja sur le bon ecran garde la taille choisie."""
    zones = zones_ecrans()
    index = index_ecran(_ECRAN, zones)
    cadre = cadre_fenetre(hwnd)
    if index is None or cadre is None:
        return False
    x, y = (cadre[0] + cadre[2]) // 2, (cadre[1] + cadre[3]) // 2
    gauche, haut, droite, bas = zones[index]
    if gauche <= x < droite and haut <= y < bas:
        return False
    return placer_sur_ecran(hwnd, index)


def _plein_ecran_au_premier_plan(user32):
    """Vrai si la fenetre active occupe tout son ecran (jeu, video, presentation)."""
    import ctypes
    from ctypes import wintypes

    class InfosEcran(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    active = user32.GetForegroundWindow()
    if not active:
        return False
    classe = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(active, classe, 64)
    if classe.value in ("Progman", "WorkerW"):   # le bureau n'est pas du plein ecran
        return False
    cadre = wintypes.RECT()
    user32.GetWindowRect(active, ctypes.byref(cadre))
    infos = InfosEcran()
    infos.cbSize = ctypes.sizeof(InfosEcran)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(active, 2), ctypes.byref(infos))
    ecran = infos.rcMonitor
    return (cadre.left <= ecran.left and cadre.top <= ecran.top
            and cadre.right >= ecran.right and cadre.bottom >= ecran.bottom)


def mettre_au_premier_plan():
    """Fait passer la fenetre du HUD devant les autres, sans lui donner le clavier.

    Sert d'accuse visuel au mot d'activation. Ne s'affiche jamais par-dessus une
    application en plein ecran ; une fenetre fermee est rouverte (mode app, une
    fois par minute au plus) et une fenetre sortie de l'ecran choisi y revient.
    Renvoie True si une fenetre a ete mise devant.
    """
    if sys.platform != "win32":
        return False
    fenetres = trouver_fenetres()
    if not fenetres:
        if (_MODE_FENETRE == "app"
                and time.monotonic() - _DERNIERE_OUVERTURE > _DELAI_REOUVERTURE):
            ouvrir_fenetre()
        return False
    user32 = _user32()
    if _plein_ecran_au_premier_plan(user32):
        return False
    sans_activer = 0x0001 | 0x0002 | 0x0010 | 0x0040   # NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW
    for hwnd in fenetres:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 4)                   # SW_SHOWNOACTIVATE : restaure sans activer
        if _ECRAN is not None:
            _replacer_si_deplacee(hwnd)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, sans_activer)   # au-dessus de tout...
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, sans_activer)   # ...sans rester epinglee
    return True


# ---------------------------------------------------------------- demonstration


def _tuiles_demo():
    """Tuiles factices du scenario (aucune donnee reelle), datees a partir d'aujourd'hui."""
    import datetime as dt
    maintenant = dt.datetime.now().astimezone()
    minuit = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    jour = lambda n, h=0, m=0: (minuit + dt.timedelta(days=n, hours=h, minutes=m)).isoformat()
    maj = maintenant.strftime("%H:%M")

    def tuile(id_, titre, etat="ok", **champs):
        return {"id": id_, "titre": titre, "etat": etat, "maj": maj, "valeur": "",
                "legende": "", "lignes": [], "message": "", **champs}

    echeances = [(jour(1), "Marque A", "Publication"), (jour(1), "Marque A", "Rendu V1"),
                 (jour(2), "Marque B", "Publication"), (jour(3), "Marque C", "Script"),
                 (jour(6), "Marque B", "Tournage")]
    return [
        tuile("agenda", "Agenda", valeur="1", legende="aujourd'hui", donnees={"evenements": [
            {"debut": (maintenant + dt.timedelta(hours=3)).isoformat(), "tout_jour": False,
             "titre": "Point d'équipe"},
            {"debut": jour(2, 9), "tout_jour": False, "titre": "Dentiste"}]}),
        tuile("factures", "Factures", valeur="1 250 €", legende="à encaisser", donnees={
            "impayees": {"nombre": 3, "montant": 1250.0}, "retard": {"nombre": 1, "montant": 400.0},
            "aucun": False}),
        tuile("loopstr", "Loopstr", valeur="4", legende="sur 7 jours",
              donnees={"echeances": [{"debut": d, "marque": m, "tache": t} for d, m, t in echeances]}),
        tuile("instagram", "Instagram", valeur="+18", legende="abonnés", donnees={"comptes": [
            {"compte": "compte_demo", "abonnes": 4210, "delta": 18, "depuis": "hier",
             "serie": [4100, 4120, 4131, 4150, 4149, 4170, 4192, 4210]}]}),
        tuile("discord", "Discord", valeur="1", legende="mention(s) 24 h", donnees={
            "mentions": 1, "messages": 42, "salons": 3, "serveurs": [
                {"nom": "Serveur démo", "salons": [{"nom": "général", "messages": 30},
                                                  {"nom": "projets", "messages": 12}]}]}),
        tuile("meteo", "Météo", "indisponible", message="Indisponible pour le moment."),
    ]


def _scenario():
    """Joue une conversation type en boucle pour tester le rendu."""
    import math

    demo(True)                                   # badge DEMO : rien n'est reel
    config("Claude · claude-haiku-4-5 (demo)", "whisper medium")
    routage("hybride")
    budget(0.27, 3.0, 0.09)
    hermes(0, 48213)
    tableau(_tuiles_demo())

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
            # Veille : le fond respire doucement et le tableau de bord s'affiche.
            etat(VEILLE)
            for _ in range(140):
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
    try:
        demarrer(tableau_local=False)          # demo : tuiles factices uniquement
    except OSError:
        sys.exit(1)                            # message deja affiche par demarrer()
    print("Scenario de demonstration en boucle. Ctrl+C pour quitter.")
    try:
        _scenario()
    except KeyboardInterrupt:
        print("\nArret.")
