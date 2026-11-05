"""Alexa (Amazon Echo) — via alexapy (lib communautaire, non officielle).

⚠️ Honnêteté : Amazon n'a AUCUNE API officielle pour piloter tes appareils Alexa
depuis un tiers. La voie viable (celle de Home Assistant) est `alexapy` : connexion
au compte Amazon par cookie (login + 2FA), puis :
  - faire parler un Echo (TTS / annonce),
  - contrôler le média (play/pause/volume),
  - **déclencher une Routine** Alexa par son énoncé -> contrôle INDIRECT des appareils
    (crée une routine « lumière salon on » dans l'app Alexa, Jarvis la déclenche),
  - lister les Echo + leur état.

Fragile par nature (Amazon change/casse l'accès non officiel). L'auth se fait UNE fois
en interactif : `python scripts/alexa_login.py` (gère captcha/2FA), le cookie est
réutilisé ensuite. Credentials dans config.yaml (jamais en dur). Voir docs/alexa.md.

Niveaux : etat/media/annoncer = N1 ; routine = N2 (une routine peut être impactante).
"""
import asyncio
import concurrent.futures
import json
import logging
import re
import threading
import time
from pathlib import Path

from core.config import reglage
from core.registre import outil
from core.util import sans_accents

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent
_LOOP = None
_LOGIN = None            # AlexaLogin connecté (réutilisé)
_VERROU = threading.Lock()
_ROUTINES_CACHE = []
_ROUTINES_CACHE_A = 0.0
_ROUTINES_CHARGEMENT = False


# ------------------------------------------------------ pont async -> sync

def _boucle():
    global _LOOP
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        threading.Thread(target=_LOOP.run_forever, daemon=True, name="alexa-loop").start()
    return _LOOP


_MSG_DELAI = ("Alexa ne répond pas à temps. L'action a peut-être quand même été "
              "prise en compte : vérifie avant de répéter.")


def _run(coro, timeout=40):
    fut = asyncio.run_coroutine_threadsafe(coro, _boucle())
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # result(timeout) arrête seulement d'attendre : sans cancel(), la coroutine
        # continuerait sur alexa-loop et déclencherait la routine après l'échec
        # annoncé. L'annulation ne rattrape pas une requête déjà partie, d'où un
        # message prudent plutôt que « rien n'a été fait ».
        fut.cancel()
        raise TimeoutError(_MSG_DELAI) from None


# ------------------------------------------------------ config / login

def _configure():
    return bool(reglage("alexa.email", "") and reglage("alexa.password", ""))


def _msg_config():
    return ("Alexa n'est pas configuré. Renseigne alexa.email / alexa.password "
            "(et alexa.otp_secret pour le 2FA) dans config.yaml, puis lance "
            "« python scripts/alexa_login.py » — voir docs/alexa.md.")


def _cookie_path(fichier):
    d = _RACINE / (reglage("alexa.dossier", "logs/alexa"))
    p = d / fichier
    p.parent.mkdir(parents=True, exist_ok=True)   # crée « .storage/ » si besoin
    return str(p)


# Tokens OAuth durables (refresh_token/mac_dms), sauvés par scripts/alexa_login.py.
# C'est la voie réutilisable : le cookie seul ne réauthentifie pas l'API Alexa.
_OAUTH_CLES = ("access_token", "refresh_token", "mac_dms", "expires_in")


def _oauth_path():
    d = _RACINE / (reglage("alexa.dossier", "logs/alexa")) / ".storage"
    return d / f"alexa_media.{reglage('alexa.email', '')}.oauth.json"


def _charger_oauth():
    p = _oauth_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _sauver_oauth(login):
    try:
        p = _oauth_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({k: getattr(login, k, None) for k in _OAUTH_CLES}),
                     encoding="utf-8")
    except Exception:
        pass


async def _assurer_login():
    """Renvoie un AlexaLogin connecté (via les tokens OAuth sauvés). Lève sinon."""
    global _LOGIN
    if _LOGIN is not None:
        try:
            if await _LOGIN.test_loggedin():
                return _LOGIN
        except Exception:
            _LOGIN = None
    from alexapy import AlexaLogin
    oauth = _charger_oauth()
    login = AlexaLogin(
        url=reglage("alexa.url", "amazon.fr"),
        email=reglage("alexa.email", ""), password=reglage("alexa.password", ""),
        outputpath=_cookie_path, otp_secret=(reglage("alexa.otp_secret", "") or ""),
        oauth=oauth)
    # login() : voie refresh_token en priorité (rebuild silencieux), cookie en repli.
    cookies = await login.load_cookie()
    await login.login(cookies=cookies)
    if await login.test_loggedin():
        _sauver_oauth(login)   # persiste le token éventuellement rafraîchi
        _LOGIN = login
        return login
    raise RuntimeError("Connexion Alexa requise : lance « python scripts/alexa_login.py ».")


async def _devices(login):
    from alexapy import AlexaAPI
    return await AlexaAPI.get_devices(login) or []


class _Appareil:
    """Enveloppe le dict de get_devices en OBJET attendu par AlexaAPI.

    alexapy accède à ._device_type / .device_serial_number / ._locale / etc. sur
    l'appareil (Home Assistant lui passe sa propre classe). get_devices() ne renvoie
    que des dicts → sans cette enveloppe : « 'dict' object has no attribute _locale ».
    """

    def __init__(self, d):
        self._device_type = d.get("deviceType")
        self.device_serial_number = d.get("serialNumber")
        self._device_family = d.get("deviceFamily")
        self._cluster_members = d.get("clusterMembers") or []
        self._locale = d.get("locale")   # absent chez Amazon → None → défaut alexapy


def _api(dev, login):
    from alexapy import AlexaAPI
    return AlexaAPI(_Appareil(dev), login)


# Familles qui ne « parlent » pas (annonce/TTS) : Fire TV, l'app, tablettes, groupe.
_FAMILLES_NON_PARLANTES = {"FIRE_TV", "VOX", "TABLET", "MOBILE_DEVICE", "WHA"}


def _est_haut_parleur(d):
    return str(d.get("deviceFamily", "")).upper() not in _FAMILLES_NON_PARLANTES


def _choisir(devices, cible, parlant=False):
    en_ligne = [d for d in devices if d.get("online")]
    if cible:
        c = sans_accents(cible.lower())
        for d in devices:
            if c in sans_accents(str(d.get("accountName", "")).lower()):
                return d
    if parlant:   # annonce/TTS sans cible → privilégier un vrai Echo (ex. Echo Show)
        parleurs = [d for d in en_ligne if _est_haut_parleur(d)]
        if parleurs:
            return parleurs[0]
    return en_ligne[0] if en_ligne else (devices[0] if devices else None)


# ------------------------------------------------------ coroutines d'action

async def _etat():
    login = await _assurer_login()
    devices = await _devices(login)
    if not devices:
        return "Aucun appareil Alexa trouvé sur le compte."
    lignes = [f"{d.get('accountName','?')} ({'en ligne' if d.get('online') else 'hors ligne'})"
              for d in devices]
    return "Appareils Alexa : " + " ; ".join(lignes) + "."


async def _annoncer(texte, cible):
    login = await _assurer_login()
    devices = await _devices(login)
    dev = _choisir(devices, cible, parlant=True)
    if dev is None:
        return "Aucun Echo disponible pour parler."
    api = _api(dev, login)
    if cible:
        await api.send_tts(texte)
        return f"C'est dit sur {dev.get('accountName','')}."
    await api.send_announcement(texte)
    return "Annonce diffusée sur tes Echo."


def _trouver_exact(autos, nom):
    """Routine dont le nom OU un énoncé == nom (insensible casse/accents)."""
    cible = sans_accents(nom).lower().strip()
    for a in autos:
        if not isinstance(a, dict):
            continue
        if any(sans_accents(p).lower().strip() == cible for p in _phrases_routine(a)):
            return _nom_routine(a)
    return None


async def _routine(nom):
    login = await _assurer_login()
    autos = await _automations(login)
    # run_routine() échoue EN SILENCE si rien ne matche → on vérifie d'abord,
    # sinon on annoncerait un faux succès (« déclenchée » alors que rien ne bouge).
    trouve = _trouver_exact(autos, nom)
    if trouve is None:
        return (f"Je ne trouve pas la routine Alexa « {nom} ». Vérifie son nom "
                "dans l'app Alexa.")
    dev = _choisir(await _devices(login), "")
    await _api(dev, login).run_routine(trouve)
    return f"Routine « {trouve} » déclenchée."


# ---- contrôle naturel : « allume la clim » -> routine Alexa correspondante ----

_MOTS_ON = {"on", "allume", "allumes", "allumez", "allumer", "active", "actives",
            "activez", "activer", "marche", "ouvre", "ouvres", "ouvrez", "ouvrir",
            "demarre", "demarres", "demarrez", "demarrer", "lance", "lances",
            "lancez", "monte", "rallume", "rallumes", "rallumer", "reactive",
            "reactives", "reactiver"}
_MOTS_OFF = {"off", "eteins", "eteignez", "eteindre", "eteint", "coupe", "coupes",
             "coupez", "couper", "arrete", "arretes", "arretez", "arreter",
             "desactive", "desactives", "desactivez", "desactiver", "ferme", "fermes",
             "fermez", "fermer", "stop", "baisse"}


async def _automations(login):
    global _ROUTINES_CACHE, _ROUTINES_CACHE_A
    from alexapy import AlexaAPI
    autos = await AlexaAPI.get_automations(login) or []
    with _VERROU:
        _ROUTINES_CACHE = list(autos)
        _ROUTINES_CACHE_A = time.monotonic()
    return autos


def _phrases_routine(a):
    """Tous les libellés d'une routine : son nom + ses énoncés vocaux."""
    ph = []
    nom = a.get("name")
    if isinstance(nom, str) and nom.strip():
        ph.append(nom)
    trigs = a.get("triggers")
    if isinstance(trigs, list) and trigs and isinstance(trigs[0], dict):
        pay = trigs[0].get("payload")
        if isinstance(pay, dict):
            if isinstance(pay.get("utterance"), str):
                ph.append(pay["utterance"])
            for x in (pay.get("utterances") or []):
                if isinstance(x, str):
                    ph.append(x)
    return ph


def _nom_routine(a):
    for p in _phrases_routine(a):
        return p            # le nom en priorité, sinon le 1er énoncé
    return None


def _normaliser_commande(texte):
    return " ".join(re.sub(
        r"[^a-z0-9]+", " ", sans_accents(str(texte or "").lower())
    ).split())


def _mot_present(mot, blob, blob_mots):
    """Présence tolérante (sous-chaîne, ou même préfixe 4+ : lumiere ~ lumieres)."""
    if mot in blob:
        return True
    return any(len(w) >= 4 and (w.startswith(mot[:4]) or mot.startswith(w[:4]))
               for w in blob_mots)


# Synonymes courants d'appareils (sans accents) : « télé » doit matcher « tv », etc.
_SYNONYMES = [
    {"tv", "tele", "television", "televiseur"},
    {"clim", "climatisation", "climatiseur", "clime"},
    {"lumiere", "lumieres", "lampe", "lampes", "eclairage", "lumieres"},
    {"ventilateur", "ventilo"},
    {"volet", "volets", "store", "stores"},
    {"prise", "prises"},
]

_MOTS_APPAREILS = {mot for groupe in _SYNONYMES for mot in groupe} | {
    "chauffage", "radiateur", "thermostat", "portail", "garage", "serrure",
    "aspirateur", "robot", "bouilloire", "cafetiere", "four", "hotte",
    "humidificateur", "purificateur", "diffuseur", "rideau", "rideaux",
}
_IGNORES_APPAREIL = {
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "au", "aux",
    "mon", "ma", "mes", "notre", "nos", "stp", "svp", "s", "il", "te", "plait",
    "jarvis", "alexa", "sur", "suis", "moi", "pour", "peux", "tu", "peut", "vous",
}
_MOTS_DISCUSSION = {
    "je", "j", "aimerais", "voudrais", "parle", "parlais", "expliquer",
    "explique", "video", "idee", "hook", "pourquoi", "comment", "question",
    "remplace", "remplacer", "raconte", "resume",
}
_PREFIXES_ROUTINE = {
    "lance", "lances", "lancez", "active", "actives", "activez", "declenche",
    "declenches", "declenchez", "execute", "executes", "executez", "demarre",
    "demarres", "demarrez", "joue", "fais", "lancer", "activer",
    "declencher", "executer", "demarrer", "jouer", "faire",
}

_PREFIXES_DEMANDE = (
    ("est", "ce", "que", "tu", "peux"),
    ("est", "ce", "que", "tu", "pourrais"),
    ("s", "il", "te", "plait"),
    ("s", "il", "vous", "plait"),
    ("je", "voudrais", "que", "tu"),
    ("je", "veux", "que", "tu"),
    ("j", "aimerais", "que", "tu"),
    ("peux", "tu"), ("peut", "tu"), ("tu", "peux"),
    ("pourrais", "tu"), ("tu", "pourrais"),
    ("pouvez", "vous"), ("vas", "y"),
    ("demande", "a", "alexa", "de"),
    ("demande", "a", "alexa", "d"),
    ("dis", "a", "alexa", "de"),
    ("dis", "a", "alexa", "d"),
    ("stp",), ("svp",),
)


def _mots_demande(mots):
    """Retire seulement les amorces qui expriment clairement une demande.

    Une phrase discursive (« j'aimerais savoir si Alexa peut allumer... ») reste
    intacte et ne peut donc pas être confondue avec un ordre domotique.
    """
    sortie = list(mots)
    change = True
    while sortie and change:
        change = False
        for prefixe in _PREFIXES_DEMANDE:
            if tuple(sortie[:len(prefixe)]) == prefixe:
                del sortie[:len(prefixe)]
                change = True
                break
    return sortie


def _routine_explicite(mots):
    """Nom après un véritable ordre de routine placé au début, sinon None."""
    commande = _mots_demande(mots)
    if not commande:
        return None
    if commande[0] == "routine":
        return " ".join(commande[1:]).strip() or None
    if commande[0] not in _PREFIXES_ROUTINE:
        return None
    i = 1
    while i < len(commande) and commande[i] in {
            "la", "le", "une", "un", "ma", "mon", "cette", "moi"}:
        i += 1
    if i >= len(commande) or commande[i] != "routine":
        return None
    return " ".join(commande[i + 1:]).strip() or None


def _cible_alexa_plausible(texte, limite_mots):
    """Dernier garde-fou contre une phrase de discussion envoyée comme cible."""
    mots = _normaliser_commande(texte).split()
    return bool(mots and len(mots) <= limite_mots
                and not (set(mots) & _MOTS_DISCUSSION))


def _vise_amaran(phrase, piece_amaran="", noms_amaran=()):
    """Vrai si la phrase cible la lumière vidéo locale plutôt qu'Alexa."""
    p = _normaliser_commande(phrase)
    mots = set(p.split())
    if "alexa" in mots:  # « sur Alexa » reste une demande explicite d'Alexa
        return False
    aliases = ["amaran", "key light", "lumiere video", "projecteur"]
    aliases.extend(str(n) for n in (noms_amaran or ()))
    cadre = f" {p} "
    if any(f" {_normaliser_commande(alias)} " in cadre
           for alias in aliases if _normaliser_commande(alias)):
        return True
    piece = _normaliser_commande(piece_amaran)
    mots_lumiere = {"lumiere", "lumieres", "lampe", "lampes", "eclairage"}
    return bool(piece and f" {piece} " in cadre and mots & mots_lumiere)


def _analyser_commande(phrase, piece="", automations=(),
                       piece_amaran="", noms_amaran=()):
    """Traduit une phrase naturelle en appel Alexa déterministe, ou None.

    Cette fonction est pure : elle ne se connecte pas à Amazon et sert aussi aux
    tests. Le LLM ne décide donc plus entre Hue et Alexa pour ces formulations.
    """
    p = _normaliser_commande(phrase)
    if not p:
        return None
    mots = p.split()
    while mots and mots[0] in {"hey", "jarvis"}:
        mots.pop(0)
    if not mots:
        return None

    # « lance la routine bonne nuit » / « routine bonne nuit », uniquement si
    # c'est réellement un ordre. Une simple discussion contenant « routine »
    # ne doit jamais détourner toute la phrase vers Alexa.
    nom_routine = _routine_explicite(mots)
    if nom_routine:
        return "alexa_routine", {"nom": nom_routine}

    # L'Amaran est un équipement local prioritaire. Sa pièce et ses alias ne
    # doivent jamais être capturés par le routage Alexa générique.
    if _vise_amaran(phrase, piece_amaran=piece_amaran, noms_amaran=noms_amaran):
        return None

    # Commande domestique : action claire + appareil connecté connu, ou mention
    # explicite d'Alexa. Les commandes PC/musique ne sont donc pas détournées.
    commande = _mots_demande(mots)

    # « mets la clim en marche », « passe les lumières sur off » et leurs
    # formulations inversées (« mets en route la clim ») expriment l'état à la
    # fin ou juste après le verbe plutôt qu'avec « allume/éteins ».
    verbes_etat = {"mets", "met", "mettre", "passe", "passer"}
    suffixes_etat = (
        (("en", "marche"), "allumer"), (("en", "route"), "allumer"),
        (("sur", "on"), "allumer"), (("en", "arret"), "eteindre"),
        (("a", "l", "arret"), "eteindre"), (("sur", "off"), "eteindre"),
    )
    if commande and commande[0] in verbes_etat:
        appareil_brut, action_formule = None, None
        for suffixe, action_candidate in suffixes_etat:
            if tuple(commande[-len(suffixe):]) == suffixe:
                appareil_brut = commande[1:-len(suffixe)]
                action_formule = action_candidate
                break
            if tuple(commande[1:1 + len(suffixe)]) == suffixe:
                appareil_brut = commande[1 + len(suffixe):]
                action_formule = action_candidate
                break
        appareil_mots = [m for m in (appareil_brut or [])
                          if m not in _IGNORES_APPAREIL]
        if (action_formule and appareil_mots
                and bool(set(appareil_mots) & _MOTS_APPAREILS)):
            appareil = " ".join(appareil_mots)
            mots_lumiere = {"lumiere", "lumieres", "lampe", "lampes", "eclairage"}
            if piece and all(m in mots_lumiere for m in appareil_mots):
                piece_norm = _normaliser_commande(piece)
                if piece_norm and piece_norm not in appareil:
                    appareil += " " + piece_norm
            return "alexa_appareil", {
                "appareil": appareil,
                "action": action_formule,
            }

    action_i = next((i for i, mot in enumerate(commande)
                     if mot in _MOTS_ON or mot in _MOTS_OFF), None)
    if action_i is not None:
        # L'action doit ouvrir la demande (« allume... »), éventuellement après
        # « Alexa ». Un verbe perdu au milieu d'une explication n'est pas un ordre.
        debut_valide = action_i == 0 or (
            action_i == 1 and commande[0] == "alexa")
        voisinage = commande[max(0, action_i - 2):action_i + 3]
        if debut_valide and "pas" not in voisinage:
            appareil_mots = [m for m in commande[action_i + 1:]
                              if m not in _IGNORES_APPAREIL
                              and m not in _MOTS_ON and m not in _MOTS_OFF]
            connu = bool(set(commande) & _MOTS_APPAREILS)
            if appareil_mots and (connu or "alexa" in commande):
                appareil = " ".join(appareil_mots)
                mots_lumiere = {"lumiere", "lumieres", "lampe", "lampes", "eclairage"}
                # La pièce du satellite ne complète que « allume la lumière ».
                # Si « salon » ou une autre pièce est déjà dite, elle gagne.
                if piece and appareil_mots and all(m in mots_lumiere for m in appareil_mots):
                    piece_norm = _normaliser_commande(piece)
                    if piece_norm and piece_norm not in appareil:
                        appareil += " " + piece_norm
                action = "eteindre" if commande[action_i] in _MOTS_OFF else "allumer"
                return "alexa_appareil", {"appareil": appareil, "action": action}

    # Une routine peut aussi être prononcée directement (« bonne nuit ») ou avec
    # un verbe (« lance bonne nuit »). Le cache est préchargé au démarrage.
    candidats = [" ".join(commande)]
    if commande and commande[0] in _PREFIXES_ROUTINE and len(commande) > 1:
        candidats.append(" ".join(commande[1:]))
    for a in automations or ():
        if not isinstance(a, dict):
            continue
        libelles = {_normaliser_commande(x) for x in _phrases_routine(a)}
        if any(c in libelles for c in candidats):
            nom = _nom_routine(a)
            if nom:
                return "alexa_routine", {"nom": nom}
    return None


async def _charger_cache_routines():
    login = await _assurer_login()
    await _automations(login)


def precharger_routines():
    """Rafraîchit les noms de routines en arrière-plan, sans ralentir la voix."""
    global _ROUTINES_CHARGEMENT
    if not _configure() or not bool(reglage("alexa.routage_prioritaire", True)):
        return
    with _VERROU:
        frais = _ROUTINES_CACHE and time.monotonic() - _ROUTINES_CACHE_A < 300
        if frais or _ROUTINES_CHARGEMENT:
            return
        _ROUTINES_CHARGEMENT = True

    def travail():
        global _ROUTINES_CHARGEMENT
        try:
            _run(_charger_cache_routines())
        except Exception:
            LOG.debug("préchargement des routines Alexa impossible", exc_info=True)
        finally:
            with _VERROU:
                _ROUTINES_CHARGEMENT = False

    threading.Thread(target=travail, daemon=True, name="alexa-routines").start()


def router_commande(phrase, piece=""):
    """Route prioritairement une commande domestique vers Alexa si configuré."""
    if not _configure() or not bool(reglage("alexa.routage_prioritaire", True)):
        return None
    precharger_routines()
    with _VERROU:
        autos = list(_ROUTINES_CACHE)
    return _analyser_commande(
        phrase,
        piece=piece,
        automations=autos,
        piece_amaran=reglage("amaran.piece", ""),
        noms_amaran=reglage("amaran.noms", []) or [],
    )


def _variantes(mot):
    for grp in _SYNONYMES:
        if mot in grp:
            return grp
    return {mot}


def _appareil_present(mot, blob, blob_mots):
    return any(_mot_present(v, blob, blob_mots) for v in _variantes(mot))


def _resoudre_routine(automations, appareil, on):
    """Trouve la routine correspondant à (appareil, on/off). Renvoie (nom, message)."""
    app_mots = [m for m in sans_accents(appareil).lower().split() if len(m) >= 2]
    cible = _MOTS_ON if on else _MOTS_OFF
    opposee = _MOTS_OFF if on else _MOTS_ON
    exact, appareil_seul, inverse = [], [], []
    for a in automations:
        if not isinstance(a, dict):
            continue
        nom = _nom_routine(a)
        if not nom:
            continue
        blob = sans_accents(" ".join(_phrases_routine(a))).lower()
        blob_mots = blob.replace("-", " ").split()
        if app_mots and not all(_appareil_present(m, blob, blob_mots) for m in app_mots):
            continue                                   # pas le bon appareil
        if set(blob_mots) & cible:
            exact.append(nom)
        elif set(blob_mots) & opposee:
            inverse.append(nom)                        # fait l'inverse : jamais lancée
        else:
            appareil_seul.append(nom)
    if exact:
        return exact[0], None
    # Une routine Alexa fixe un état, elle n'inverse rien : seule une routine
    # neutre (sans mot on/off) peut servir quand le sens demandé n'existe pas.
    if len(appareil_seul) == 1:
        return appareil_seul[0], None
    if appareil_seul:
        return None, ("Plusieurs routines Alexa pourraient correspondre. Précise "
                      "l'appareil ou la pièce, ou dis « lance la routine <nom> ».")
    if inverse:
        voulue = " ".join(app_mots or ["appareil"]) + (" on" if on else " off")
        return None, (f"Je n'ai que la routine « {inverse[0]} », qui fait l'inverse : "
                      f"je n'ai rien déclenché. Crée « {voulue} » dans l'app Alexa.")
    return None, ""


async def _appareil(appareil, action):
    login = await _assurer_login()
    autos = await _automations(login)
    if not autos:
        return ("Aucune routine Alexa n'existe. Crée-en une dans l'app Alexa "
                "(ex. « clim on » / « clim off ») — voir docs/alexa.md.")
    on = not (set(sans_accents(action or "").lower().split()) & _MOTS_OFF)
    nom, msg = _resoudre_routine(autos, appareil, on)
    if nom is None:
        if msg:
            return msg
        premier = (sans_accents(appareil).lower().split() or ["appareil"])[0]
        return (f"Je ne trouve pas de routine Alexa pour « {appareil} ». Vérifie "
                f"son nom, ou crée « {premier} on » et « {premier} off » dans "
                "l'app Alexa.")
    dev = _choisir(await _devices(login), "")
    await _api(dev, login).run_routine(nom)
    return f"C'est fait — routine « {nom} » déclenchée."


async def _media(action, cible, niveau):
    login = await _assurer_login()
    dev = _choisir(await _devices(login), cible)
    if dev is None:
        return "Aucun Echo disponible."
    api = _api(dev, login)
    a = (action or "").lower().strip()
    if a in ("pause", "stop"):
        await api.pause()
        return "En pause."
    if a in ("play", "lecture", "reprend"):
        await api.play()
        return "Lecture."
    if a in ("volume",):
        await api.set_volume(max(0.0, min(1.0, (niveau or 50) / 100.0)))
        return f"Volume à {niveau}%."
    return f"Action média inconnue : {action} (play, pause, volume)."


# ------------------------------------------------------ outils

def _err(e):
    if isinstance(e, TimeoutError):
        return _MSG_DELAI           # jamais « Alexa a échoué (). » sur un délai
    return f"Alexa a échoué ({(str(e) or type(e).__name__)[:140]})."


@outil(
    nom="alexa_etat",
    description="Liste tes appareils Alexa (Echo) et leur état. Pour 'mes appareils "
                "Alexa', 'quels Echo sont en ligne'.",
    lent=True, phrase_attente="Je regarde tes appareils Alexa.",
)
def alexa_etat() -> str:
    if not _configure():
        return _msg_config()
    try:
        return _run(_etat())
    except Exception as e:
        return _err(e)


@outil(
    nom="alexa_annoncer",
    description="Fait parler un Echo (annonce / TTS). Pour 'annonce sur Alexa ...', "
                "'fais dire à Alexa ...', 'préviens la maison que ...'.",
    parametres={
        "type": "object",
        "properties": {
            "texte": {"type": "string", "description": "Le message à annoncer."},
            "cible": {"type": "string", "description": "Nom d'un Echo précis (optionnel ; "
                                                       "vide = annonce sur tous)."},
        },
        "required": ["texte"],
    },
)
def alexa_annoncer(texte: str, cible: str = "") -> str:
    if not _configure():
        return _msg_config()
    try:
        return _run(_annoncer(texte, cible))
    except Exception as e:
        return _err(e)


@outil(
    nom="alexa_routine",
    description="Déclenche une Routine Alexa par son énoncé (le contrôle des appareils "
                "Google/Alexa passe par des routines que tu crées dans l'app Alexa, ex. "
                "'lumière salon on'). UNIQUEMENT pour un ordre explicite comme 'lance "
                "la routine ...'. Ne jamais appeler cet outil si l'utilisateur parle "
                "d'Alexa, explique un projet, pose une question ou demande une idée.",
    parametres={
        "type": "object",
        "properties": {
            "nom": {"type": "string", "description": "L'énoncé de la routine (comme dans "
                                                     "l'app Alexa, ex. 'bonne nuit')."}
        },
        "required": ["nom"],
    },
    confirmation=True,
    annonce=lambda a: f"Je vais déclencher la routine Alexa « {a.get('nom','')} ».",
)
def alexa_routine(nom: str) -> str:
    if not _cible_alexa_plausible(nom, 10):
        return "Ce n'est pas un nom de routine Alexa clair ; je n'ai rien déclenché."
    if not _configure():
        return _msg_config()
    try:
        return _run(_routine(nom))
    except Exception as e:
        return _err(e)


@outil(
    nom="alexa_appareil",
    description="Allume ou éteint un appareil connecté de la maison (clim, télé, "
                "lumières, prise, ventilateur…) en déclenchant la routine Alexa qui "
                "porte ce nom. Pour « allume la clim », « éteins la télé », « allume "
                "les lumières du salon », « coupe le ventilateur ». Retrouve la bonne "
                "routine parmi les tiennes (tolérant aux accents/pluriels). UNIQUEMENT "
                "pour un ordre domotique direct. Ne jamais utiliser cet outil pour une "
                "discussion sur Alexa, un contenu, une vidéo, une idée ou une question.",
    parametres={
        "type": "object",
        "properties": {
            "appareil": {"type": "string", "description": "L'appareil ou la pièce, "
                         "ex. 'clim', 'télé', 'lumières salon', 'ventilateur'."},
            "action": {"type": "string", "enum": ["allumer", "eteindre"],
                       "description": "allumer (on) ou eteindre (off)."},
        },
        "required": ["appareil", "action"],
    },
    lent=True,
    phrase_attente="Je passe par Alexa.",
)
def alexa_appareil(appareil: str, action: str = "allumer") -> str:
    if not _cible_alexa_plausible(appareil, 8):
        return "Ce n'est pas une commande domotique claire ; je n'ai rien déclenché."
    if not _configure():
        return _msg_config()
    try:
        return _run(_appareil(appareil, action))
    except Exception as e:
        return _err(e)


@outil(
    nom="alexa_media",
    description="Contrôle la lecture sur un Echo : play, pause, ou volume. Pour 'mets "
                "en pause sur Alexa', 'reprends la musique sur l'Echo', 'volume Alexa à 30'.",
    parametres={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["play", "pause", "volume"]},
            "cible": {"type": "string", "description": "Nom d'un Echo précis (optionnel)."},
            "niveau": {"type": "integer", "description": "Volume 0-100 (si action=volume)."},
        },
        "required": ["action"],
    },
)
def alexa_media(action: str, cible: str = "", niveau: int = 50) -> str:
    if not _configure():
        return _msg_config()
    try:
        return _run(_media(action, cible, niveau))
    except Exception as e:
        return _err(e)
