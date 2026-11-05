"""Spotify : ajoute la musique reconnue à une playlist « Jarvis Finds ».

« ajoute-la à ma playlist » (la dernière musique reconnue), et option d'ajout
AUTOMATIQUE à chaque reconnaissance (spotify.auto_ajout). Auth OAuth : login une
fois (scripts/spotify_login.py), refresh_token réutilisé ensuite.

N1/N2 (écriture dans TA playlist). Non exposé au MCP par défaut. Voir docs/spotify.md.
"""
import base64
import json
import os
import random
import threading
import time
from pathlib import Path
from urllib.parse import quote

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import requests

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

_RACINE = Path(__file__).resolve().parent.parent
_API = "https://api.spotify.com/v1"
_TOKEN = {"access": None, "exp": 0.0}
_PLAYLIST_ID = None
_VERROU = threading.Lock()


# ------------------------------------------------------ auth

def _fichier_token():
    return _RACINE / (reglage("spotify.dossier", "logs/spotify")) / "token.json"


def _refresh_token():
    f = _fichier_token()
    if f.exists():
        try:
            return (json.loads(f.read_text(encoding="utf-8")) or {}).get("refresh_token")
        except Exception:
            pass
    return reglage("spotify.refresh_token", "") or None


def _configure():
    return bool(reglage("spotify.client_id", "") and reglage("spotify.client_secret", "")
                and _refresh_token())


def _msg_config():
    return ("Spotify n'est pas connecté. Crée une app sur developer.spotify.com, mets "
            "client_id/secret dans config.yaml, puis lance "
            "« python scripts/spotify_login.py » — voir docs/spotify.md.")


def _access():
    if _TOKEN["access"] and time.time() < _TOKEN["exp"] - 30:
        return _TOKEN["access"]
    cid = reglage("spotify.client_id", "")
    secret = reglage("spotify.client_secret", "")
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token",
                      data={"grant_type": "refresh_token",
                            "refresh_token": _refresh_token()},
                      headers={"Authorization": f"Basic {auth}"}, timeout=15)
    r.raise_for_status()
    d = r.json()
    _TOKEN["access"] = d["access_token"]
    _TOKEN["exp"] = time.time() + int(d.get("expires_in", 3600))
    return _TOKEN["access"]


def _h():
    return {"Authorization": f"Bearer {_access()}",
            "Content-Type": "application/json"}


# ------------------------------------------------------ playlist / recherche

def _me():
    return requests.get(f"{_API}/me", headers=_h(), timeout=15).json()


def _playlist_id(nom=None, creer=True):
    """Id d'une playlist par son nom. nom=None -> playlist par defaut (spotify.playlist,
    creee si absente). Un nom explicite n'est PAS cree s'il n'existe pas (creer=False
    conseille) -> renvoie None pour eviter une playlist creee par erreur de dictee."""
    global _PLAYLIST_ID
    par_defaut = nom is None
    cible = nom or reglage("spotify.playlist", "Jarvis Finds")
    if par_defaut and _PLAYLIST_ID:
        return _PLAYLIST_ID
    with _VERROU:
        url = f"{_API}/me/playlists?limit=50"
        while url:
            d = requests.get(url, headers=_h(), timeout=15).json()
            for pl in d.get("items", []):
                if sans_accents((pl.get("name") or "").lower()) == sans_accents(cible.lower()):
                    if par_defaut:
                        _PLAYLIST_ID = pl["id"]
                    return pl["id"]
            url = d.get("next")
        if not creer:
            return None
        uid = _me()["id"]
        r = requests.post(f"{_API}/users/{uid}/playlists", headers=_h(),
                          data=json.dumps({"name": cible, "public": False,
                                           "description": "Trouvailles de Jarvis."}),
                          timeout=15)
        r.raise_for_status()
        pid = r.json()["id"]
        if par_defaut:
            _PLAYLIST_ID = pid
        return pid


def _chercher_uri(titre, artiste):
    q = f"track:{titre} artist:{artiste}" if artiste else f"track:{titre}"
    r = requests.get(f"{_API}/search", headers=_h(),
                     params={"q": q, "type": "track", "limit": 1}, timeout=15)
    items = (r.json().get("tracks", {}) or {}).get("items", [])
    return items[0]["uri"] if items else None


def _chercher_media(recherche, type_media):
    """Premier titre/playlist Spotify correspondant à la recherche."""
    type_api = "playlist" if type_media == "playlist" else "track"
    if type_api == "playlist":
        # Une demande « ma playlist X » doit privilégier une playlist exacte du
        # compte. La recherche publique renvoie souvent une playlist populaire
        # au nom approchant avant celle de l'utilisateur.
        personnelle = _playlist_id(recherche, creer=False)
        if personnelle:
            return {
                "uri": f"spotify:playlist:{personnelle}",
                "name": str(recherche).strip(),
            }
    r = requests.get(f"{_API}/search", headers=_h(), params={
        "q": recherche, "type": type_api, "limit": 1,
    }, timeout=15)
    r.raise_for_status()
    bloc = r.json().get(f"{type_api}s", {}) or {}
    items = [item for item in (bloc.get("items", []) or []) if item]
    return items[0] if items else None


def _demarrer_lecture(uri, type_media, device_id=None):
    corps = ({"context_uri": uri} if type_media == "playlist"
             else {"uris": [uri]})
    params = {"device_id": device_id} if device_id else None
    return requests.put(f"{_API}/me/player/play", headers=_h(),
                        params=params, data=json.dumps(corps), timeout=15)


def _etat_lecture():
    """État Spotify Connect courant, ou {} lorsqu'aucun lecteur n'est actif."""
    r = requests.get(f"{_API}/me/player", headers=_h(), timeout=15)
    if r.status_code == 204:
        return {}
    r.raise_for_status()
    return r.json() or {}


def _reprendre_lecture(device_id=None):
    """Reprend la file Spotify courante sans imposer de titre."""
    params = {"device_id": device_id} if device_id else None
    return requests.put(f"{_API}/me/player/play", headers=_h(),
                        params=params, timeout=15)


def _nom_appareil_piece(piece):
    """Nom Spotify Connect d'une pièce, configurable avec un défaut lisible."""
    piece = str(piece or "").strip()
    if not piece:
        return ""
    appareils = reglage("spotify.appareils", {}) or {}
    cible = sans_accents(piece).lower()
    for nom_piece, nom_appareil in appareils.items():
        if sans_accents(str(nom_piece)).lower() == cible and nom_appareil:
            return str(nom_appareil).strip()
    return f"Jarvis {piece.title()}"


def _appareil_piece(piece):
    """Renvoie (appareil Spotify, nom attendu) pour une pièce donnée."""
    attendu = _nom_appareil_piece(piece)
    if not attendu:
        return None, ""
    r = requests.get(f"{_API}/me/player/devices", headers=_h(), timeout=15)
    r.raise_for_status()
    cible = sans_accents(attendu).lower()
    for appareil in (r.json().get("devices", []) or []):
        if sans_accents(str(appareil.get("name", ""))).lower() == cible:
            return appareil, attendu
    return None, attendu


def _transferer_lecture(device_id, lecture=True):
    """Transfère la file Spotify vers un appareil Connect précis."""
    return requests.put(f"{_API}/me/player", headers=_h(), data=json.dumps({
        "device_ids": [device_id], "play": bool(lecture),
    }), timeout=15)


def _jouer_corps(device_id, corps):
    """Lance /me/player/play avec un corps précis sur un appareil Connect."""
    return requests.put(f"{_API}/me/player/play", headers=_h(),
                        params={"device_id": device_id},
                        data=json.dumps(corps), timeout=15)


def _activer_aleatoire(device_id):
    """Active le mode aléatoire de Spotify sur un appareil Connect."""
    return requests.put(f"{_API}/me/player/shuffle", headers=_h(),
                        params={"state": "true", "device_id": device_id}, timeout=15)


def _nombre_titres(uri_playlist):
    """Nombre de titres d'une playlist, None si inconnu.

    Spotify refuse désormais /playlists/{id}/tracks (403) : seul /items répond."""
    pid = str(uri_playlist).rsplit(":", 1)[-1]
    try:
        r = requests.get(f"{_API}/playlists/{pid}/items", headers=_h(),
                         params={"fields": "total", "limit": 1}, timeout=15)
        if _requete_reussie(r):
            return int((r.json() or {}).get("total") or 0) or None
    except Exception:
        pass
    return None


def _commande_lecture(device_id, action):
    """Pause, piste suivante ou précédente sur un appareil Spotify précis."""
    chemins = {
        "pause": ("put", "pause"),
        "suivant": ("post", "next"),
        "precedent": ("post", "previous"),
    }
    methode, chemin = chemins[action]
    appel = requests.put if methode == "put" else requests.post
    return appel(f"{_API}/me/player/{chemin}", headers=_h(),
                 params={"device_id": device_id}, timeout=15)


def _requete_reussie(reponse):
    """Spotify répond généralement 204, mais tout statut 2xx est un succès."""
    try:
        return 200 <= int(reponse.status_code) < 300
    except (AttributeError, TypeError, ValueError):
        return False


def _joue_sur(device_id, attente=4.0):
    """Vrai si Spotify joue réellement sur cet appareil (vérifié pendant ~attente s).

    Un 204 de l'API veut seulement dire « demande transmise » : l'enceinte peut
    ensuite refuser de jouer (vu sur Raspotify : « context is not available »)."""
    fin = time.monotonic() + attente
    while True:
        if _joue_la(_etat_ou_vide(), device_id):
            return True
        if time.monotonic() >= fin:
            return False
        time.sleep(0.5)


def _etat_ou_vide():
    """État Spotify Connect courant, {} si l'API ne répond pas."""
    try:
        return _etat_lecture()
    except Exception:
        return {}


def _joue_la(etat, device_id):
    """Vrai si cet état Spotify montre une lecture en cours sur cet appareil."""
    return bool((etat or {}).get("is_playing")) and \
        ((etat or {}).get("device") or {}).get("id") == device_id


def _playlist_lancement():
    """(URI, nom) de la playlist jouée par « lance Spotify » dans une pièce.

    Nom lu dans spotify.playlist_lancement ; URI None si le réglage est vide ou si
    la playlist n'existe pas sur le compte (jamais créée par erreur)."""
    nom = str(reglage("spotify.playlist_lancement", "") or "").strip()
    if not nom:
        return None, ""
    pid = _playlist_id(nom, creer=False)
    return (f"spotify:playlist:{pid}" if pid else None), nom


def _lancement_aleatoire():
    """La playlist de lancement démarre-t-elle en aléatoire (spotify.lancement_aleatoire) ?"""
    return bool(reglage("spotify.lancement_aleatoire", True))


def _lancer_playlist(device_id, uri):
    """Joue une playlist sur un appareil et vérifie que ça joue.

    En aléatoire : départ sur un titre au hasard (sinon Spotify commence toujours
    par le premier), puis mode aléatoire activé une fois l'enceinte active.
    Renvoie (lecture démarrée, aléatoire activé)."""
    aleatoire = _lancement_aleatoire()
    corps = {"context_uri": uri}
    if aleatoire:
        total = _nombre_titres(uri)
        if total:
            corps["offset"] = {"position": random.randrange(total)}
    if not (_requete_reussie(_jouer_corps(device_id, corps))
            and _joue_sur(device_id, attente=6.0)):
        return False, False
    if not aleatoire:
        return True, False
    try:
        return True, _requete_reussie(_activer_aleatoire(device_id))
    except Exception:
        return True, False


def _corps_reprise(etat):
    """Corps de /me/player/play qui rejoue le morceau courant à la même position,
    dans un contexte que l'enceinte sait charger : la playlist ou l'album d'origine,
    à défaut l'album du titre (un titre « isolé » n'a pas de contexte chargeable)."""
    item = (etat or {}).get("item") or {}
    uri = item.get("uri")
    if not uri:
        return None
    corps = {"position_ms": int((etat or {}).get("progress_ms") or 0)}
    contexte = ((etat or {}).get("context") or {}).get("uri")
    album = (item.get("album") or {}).get("uri")
    if contexte:
        corps.update(context_uri=contexte, offset={"uri": uri})
    elif album and item.get("type", "track") == "track":
        corps.update(context_uri=album, offset={"uri": uri})
    else:
        corps["uris"] = [uri]
    return corps


def _demarrer_sur_appareil(device_id, etat_avant=None):
    """Fait jouer Spotify sur un appareil Connect et vérifie que ça joue.

    1. Rien à faire si la musique joue déjà là.
    2. Bascule de la lecture en cours (cas normal).
    3. Si l'enceinte reste muette : relance explicite du morceau courant dans son
       album ou sa playlist.
    Renvoie True seulement si la lecture a réellement démarré."""
    if etat_avant is None:
        etat_avant = _etat_ou_vide()
    if _joue_la(etat_avant, device_id):
        return True
    # Attente courte après la bascule (la relance est sans risque), plus longue
    # après la relance : c'est elle qui décide du message annoncé.
    if (_requete_reussie(_transferer_lecture(device_id, lecture=True))
            and _joue_sur(device_id, attente=3.0)):
        return True
    corps = _corps_reprise(etat_avant)
    if corps is None:
        return False
    return (_requete_reussie(_jouer_corps(device_id, corps))
            and _joue_sur(device_id, attente=6.0))


def _ouvrir_application_spotify():
    """Ouvre Spotify avec le chemin configuré, sinon via son protocole Windows."""
    from core.poste_distant import executer_principal
    distant = executer_principal("spotify_open", {"uri": "spotify:"})
    if distant is not None:
        return distant
    cible = "spotify:"
    for nom, chemin in (reglage("apps", {}) or {}).items():
        if sans_accents(str(nom).strip()) == "spotify":
            cible = chemin
            break
    os.startfile(cible)
    return None


def _deja_present(pid, uri):
    """Évite les doublons : l'URI est-elle déjà dans la playlist ?

    Spotify refuse désormais /playlists/{id}/tracks (403) : seul /items répond, par
    pages de 50 au plus. Chaque élément porte le titre sous « item » (« track » est
    l'ancien nom, encore lu par prudence)."""
    try:
        url = (f"{_API}/playlists/{pid}/items"
               "?fields=items(item(uri),track(uri)),next&limit=50")
        while url:
            d = requests.get(url, headers=_h(), timeout=15).json()
            for it in d.get("items", []):
                if (it.get("item") or it.get("track") or {}).get("uri") == uri:
                    return True
            url = d.get("next")
    except Exception:
        pass
    return False


def _ajouter_titre(titre, artiste, playlist=None):
    """Ajoute (titre, artiste) à la playlist voulue (None = celle par défaut)."""
    if not (titre and str(titre).strip()):
        return "Je ne sais pas quelle musique ajouter."
    uri = _chercher_uri(titre, artiste)
    if not uri:
        return f"Je n'ai pas trouvé « {titre} » sur Spotify."
    demande = playlist.strip() if (playlist and playlist.strip()) else None
    pid = _playlist_id(demande, creer=(demande is None))
    if not pid:
        return (f"Je n'ai pas trouvé la playlist « {demande} » chez toi. "
                "Crée-la d'abord dans Spotify, ou dis-la sans préciser (j'utilise "
                f"{reglage('spotify.playlist', 'Jarvis Finds')}).")
    if _deja_present(pid, uri):
        return f"« {titre} » est déjà dans la playlist."
    r = requests.post(f"{_API}/playlists/{pid}/items", headers=_h(),
                      data=json.dumps({"uris": [uri]}), timeout=15)
    r.raise_for_status()
    nom = demande or reglage("spotify.playlist", "Jarvis Finds")
    return f"Ajoutée à {nom} : {titre}" + (f" de {artiste}." if artiste else ".")


# ------------------------------------------------------ auto-ajout (depuis musique)

def auto_ajouter(titre, artiste):
    """Appelé après une reconnaissance : ajoute en fond si spotify.auto_ajout."""
    if not reglage("spotify.auto_ajout", False) or not _configure():
        return
    def worker():
        try:
            _ajouter_titre(titre, artiste)
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True, name="spotify-auto").start()


# ------------------------------------------------------ outils

@outil(
    nom="lancer_spotify",
    description="Ouvre Spotify puis reprend immédiatement la lecture en cours. "
                "Pour « lance Spotify » ou « ouvre Spotify ». Dans une pièce satellite, "
                "joue la playlist par défaut si elle est configurée. N'utilise pas Astra.",
    parametres={
        "type": "object",
        "properties": {
            "piece": {"type": "string", "description": "Pièce du satellite audio."},
        },
    },
    mcp_expose=False,
    affichage="jamais",
)
def lancer_spotify(piece: str = "") -> str:
    """Ouvre l'app et reprend la lecture, sans basculer une musique déjà active."""
    configure = _configure()
    etat_avant = {}

    if piece:
        if not configure:
            return _msg_config()
        try:
            appareil, attendu = _appareil_piece(piece)
            if not appareil:
                return (f"Je ne vois pas encore {attendu}. Dans Spotify, sélectionne-le "
                        "une première fois dans Appareils disponibles.")
            # On n'annonce « je lance » que si la musique joue vraiment.
            etat = _etat_ou_vide()
            if _joue_la(etat, appareil["id"]):
                return f"Spotify joue déjà sur {attendu}."
            uri, nom = _playlist_lancement()
            if uri:
                # Playlist par défaut de l'utilisatrice : un contexte explicite, que
                # l'enceinte sait toujours charger (contrairement à une simple bascule).
                joue, aleatoire = _lancer_playlist(appareil["id"], uri)
                if joue:
                    mode = " en aléatoire" if aleatoire else ""
                    return f"Je lance ta playlist {nom}{mode} sur {attendu}."
                return f"Ta playlist {nom} n'a pas démarré sur {attendu}."
            if _demarrer_sur_appareil(appareil["id"], etat):
                if nom:
                    return (f"Je n'ai pas trouvé ta playlist {nom}, alors je reprends "
                            f"ta dernière musique sur {attendu}.")
                return f"Je lance Spotify sur {attendu}."
            return (f"Spotify n'a pas démarré sur {attendu} : l'enceinte a reçu la demande "
                    "mais ne joue rien. Demande-moi une playlist précise, par exemple "
                    "« mets ma playlist Chill ».")
        except Exception as e:
            return f"Spotify a échoué ({str(e)[:120]})."

    if configure:
        try:
            etat_avant = _etat_lecture()
        except Exception:
            # L'ouverture locale reste possible même si Spotify Connect répond mal.
            etat_avant = {}

    try:
        ouverture = _ouvrir_application_spotify()
        if ouverture and ("n'est pas connecté" in ouverture or "ne répond pas" in ouverture):
            return ouverture
    except Exception as e:
        return f"Impossible de lancer Spotify : {str(e)[:120]}."

    if etat_avant.get("is_playing"):
        return "Spotify est ouvert et déjà en lecture."

    # Si un lecteur est déjà connu, la reprise est immédiate. Sinon Spotify doit
    # d'abord avoir le temps d'enregistrer l'application comme appareil actif.
    if configure and (etat_avant.get("device") or {}).get("id"):
        try:
            r = _reprendre_lecture()
            if _requete_reussie(r):
                return "Spotify est lancé et la lecture a repris."
        except Exception:
            pass

    delai = float(reglage(
        "spotify.lancement_delai", reglage("scenes.spotify_delai", 3.0)
    ))
    time.sleep(max(0.5, min(delai, 8.0)))

    if configure:
        try:
            etat = _etat_lecture()
            if etat.get("is_playing"):
                return "Spotify est lancé et déjà en lecture."
            if (etat.get("device") or {}).get("id"):
                r = _reprendre_lecture()
                if _requete_reussie(r):
                    return "Spotify est lancé et la lecture a repris."
        except Exception:
            pass

    # Mode sans OAuth (ou Spotify Connect indisponible) : le raccourci média est
    # le seul repli universel. Il n'est utilisé qu'après l'ouverture et le délai.
    try:
        from tools.systeme import controler_media
        res = str(controler_media("pause") or "")
    except Exception:
        res = ""
    # controler_media ne lève pas quand le poste principal échoue : il renvoie
    # un texte. Liste blanche des succès : touche pressée en local (« Fait »)
    # ou commande relayée par l'agent du poste (« … envoyée au poste principal »).
    if res.startswith(("Fait", "C'est fait")) or "envoyée" in res:
        return "Spotify est lancé et j'ai envoyé la commande lecture."
    return "Spotify est lancé, mais je n'ai pas pu démarrer la lecture."


@outil(
    nom="controler_spotify",
    description="Contrôle Spotify sur l'enceinte de la pièce du satellite : pause, "
                "reprendre, morceau suivant ou précédent.",
    parametres={
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["pause", "reprendre", "suivant", "precedent"]},
            "piece": {"type": "string"},
        },
        "required": ["action", "piece"],
    },
    mcp_expose=False,
    affichage="jamais",
)
def controler_spotify(action: str, piece: str) -> str:
    if not _configure():
        return _msg_config()
    if action not in {"pause", "reprendre", "suivant", "precedent"}:
        return "Commande Spotify inconnue."
    try:
        appareil, attendu = _appareil_piece(piece)
        if not appareil:
            return (f"Je ne vois pas encore {attendu}. Sélectionne-le une première "
                    "fois dans les appareils Spotify.")
        actif = bool(appareil.get("is_active"))
        if action == "reprendre":
            # Même vérification que « lance Spotify » : annoncer seulement ce qui joue.
            if _demarrer_sur_appareil(appareil["id"]):
                return "Je reprends la musique."
            return (f"La musique n'a pas repris sur {attendu}. Demande-moi une playlist "
                    "précise, par exemple « mets ma playlist Chill ».")
        if action == "pause":
            # Raspotify peut publier is_active=False avec un léger retard alors
            # que le son joue encore. Ne jamais déduire « déjà en pause » de ce
            # seul drapeau : envoyer réellement la pause à l'appareil demandé.
            r = _commande_lecture(appareil["id"], "pause")
            if _requete_reussie(r):
                return "Musique en pause."
            # Certaines implémentations Connect appliquent la commande avant de
            # renvoyer un statut non-2xx. Vérifie l'état obtenu avant d'annoncer
            # un faux échec.
            time.sleep(0.25)
            try:
                etat = _etat_lecture()
                nom_etat = sans_accents(str(
                    (etat.get("device") or {}).get("name", ""))).lower()
                if (not etat or
                        (nom_etat == sans_accents(attendu).lower()
                         and not etat.get("is_playing", False))):
                    return "Musique en pause."
            except Exception:
                pass
            return f"Spotify n'a pas pu mettre en pause sur {attendu}."
        if not actif:
            # Un appareil Connect connu peut rester visible tout en étant inactif.
            # Les commandes /play, next et previous échouent alors souvent avec
            # 404 : on transfère d'abord la session vers la pièce demandée.
            r = _transferer_lecture(appareil["id"], lecture=True)
            if not _requete_reussie(r):
                return f"Spotify n'a pas pu activer {attendu}."
            time.sleep(0.2)
        r = _commande_lecture(appareil["id"], action)
        if not _requete_reussie(r):
            return f"Spotify n'a pas pu exécuter la commande sur {attendu}."
        messages = {
            "pause": "Musique en pause.",
            "suivant": "Je passe au morceau suivant.",
            "precedent": "Je reviens au morceau précédent.",
        }
        return messages[action]
    except Exception as e:
        return f"Spotify a échoué ({str(e)[:120]})."

@outil(
    nom="ajouter_a_playlist",
    description="Ajoute la DERNIÈRE musique reconnue (ou un titre donné) à une playlist "
                "Spotify. Par défaut « Jarvis Finds » ; précise une playlist avec le "
                "paramètre playlist. Pour « ajoute-la à ma playlist », « mets cette "
                "chanson dans ma playlist Chill », « ajoute ça à Spotify ».",
    parametres={
        "type": "object",
        "properties": {
            "titre": {"type": "string", "description": "Titre (optionnel ; vide = la "
                      "dernière musique reconnue)."},
            "artiste": {"type": "string", "description": "Artiste (optionnel)."},
            "playlist": {"type": "string", "description": "Nom d'une playlist précise "
                         "(optionnel ; vide = la playlist par défaut). Doit déjà exister."},
        },
    },
    lent=True,
    phrase_attente="J'ajoute ça à ta playlist.",
    mcp_expose=False,
    affichage="jamais",
)
def ajouter_a_playlist(titre: str = "", artiste: str = "", playlist: str = "") -> str:
    if not _configure():
        return _msg_config()
    if not (titre and titre.strip()):
        try:
            from tools import musique
            derniere = musique.derniere_reconnaissance()
        except Exception:
            derniere = None
        if not derniere:
            return "Je n'ai pas de musique récente à ajouter. Dis d'abord « c'est quoi cette musique ? »."
        titre, artiste = derniere
    try:
        return _ajouter_titre(titre, artiste, playlist)
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", 0)
        if code == 403:
            return ("Spotify refuse l'accès (403) : soit le droit d'écriture des "
                    "playlists n'est pas accordé, soit l'app est en mode développement "
                    "avec un autre compte. Relance « python scripts/spotify_login.py » "
                    "et clique bien « Agree » sur l'écran des permissions.")
        return f"Spotify a échoué ({str(e)[:120]})."
    except Exception as e:
        return f"Spotify a échoué ({str(e)[:120]})."


@outil(
    nom="lire_spotify",
    description="Recherche puis lance directement un morceau ou une playlist Spotify. "
                "Pour « joue Blinding Lights sur Spotify », « lance ma playlist Chill ». "
                "Ne sert pas à ajouter un morceau à une playlist.",
    parametres={
        "type": "object",
        "properties": {
            "recherche": {"type": "string", "description": "Nom du titre ou de la playlist."},
            "type_media": {"type": "string", "enum": ["titre", "playlist"]},
            "piece": {"type": "string", "description": "Pièce du satellite audio."},
        },
        "required": ["recherche"],
    },
    lent=True,
    phrase_attente="Je cherche ça sur Spotify.",
    mcp_expose=False,
    affichage="jamais",
)
def lire_spotify(recherche: str, type_media: str = "titre", piece: str = "") -> str:
    """Lance via Spotify Connect, avec repli sur l'application de bureau."""
    recherche = str(recherche or "").strip()
    type_media = "playlist" if type_media == "playlist" else "titre"
    if not recherche:
        return "Dis-moi quel titre ou quelle playlist lancer."

    if not _configure():
        if piece:
            return _msg_config()
        try:
            from core.poste_distant import executer_principal
            distant = executer_principal("spotify_search", {"recherche": recherche})
            if distant is not None:
                return distant
            os.startfile("spotify:search:" + quote(recherche, safe=""))
            return f"J'ai ouvert la recherche Spotify pour « {recherche} »."
        except Exception:
            return _msg_config()

    try:
        device_id = None
        attendu = ""
        if piece:
            appareil, attendu = _appareil_piece(piece)
            if not appareil:
                return (f"Je ne vois pas encore {attendu}. Dans Spotify, sélectionne-le "
                        "une première fois dans Appareils disponibles.")
            device_id = appareil["id"]

        item = None
        if type_media == "playlist":
            pid = _playlist_id(recherche, creer=False)
            if pid:
                item = {"uri": f"spotify:playlist:{pid}", "name": recherche}
        if item is None:
            item = _chercher_media(recherche, type_media)
        if not item or not item.get("uri"):
            return f"Je n'ai pas trouvé « {recherche} » sur Spotify."

        nom = item.get("name") or recherche
        reponse = _demarrer_lecture(item["uri"], type_media, device_id=device_id)
        if _requete_reussie(reponse):
            destination = f" sur {attendu}" if attendu else " sur Spotify"
            return f"Je lance « {nom} »{destination}."

        if piece:
            return f"Spotify n'a pas pu lancer « {nom} » sur {attendu}."

        # Sans appareil Spotify Connect actif, sans Premium ou avec un ancien
        # jeton OAuth, le lien profond reste une action sûre et sans Astra.
        from core.poste_distant import executer_principal
        distant = executer_principal("spotify_open", {"uri": item["uri"]})
        if distant is None:
            os.startfile(item["uri"])
        elif "n'est pas connecté" in distant or "ne répond pas" in distant:
            return distant
        if reponse.status_code == 403:
            return (f"J'ai ouvert « {nom} » dans Spotify. Pour la lecture automatique, "
                    "reconnecte Spotify une fois afin d'autoriser le contrôle de lecture.")
        return f"J'ai ouvert « {nom} » dans Spotify."
    except requests.HTTPError as e:
        return f"Spotify a échoué ({str(e)[:120]})."
    except Exception as e:
        return f"Spotify a échoué ({str(e)[:120]})."
