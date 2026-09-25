"""Satellites — Jarvis dans une AUTRE pièce (Raspberry Pi, futur ESP32).

Un satellite est une extension du CORPS de Jarvis (oreilles + bouche + visage
déportés). Le CERVEAU reste sur le PC : le satellite capte l'audio, le PC
transcrit (Whisper) → LLM + outils → TTS, et renvoie l'audio + des événements
d'état pour le visage/HUD du boîtier. Hermes n'est pas concerné.

PROTOCOLE (volontairement simple et transport-agnostique -> un ESP32 l'utilise
À L'IDENTIQUE) : un WebSocket /satellite, deux types de trames :
  • TRAMES TEXTE = messages de CONTRÔLE, JSON (voir docs/satellite.md) ;
  • TRAMES BINAIRES = audio PCM brut 16 bits little-endian, mono, 16 kHz.

Client -> serveur :
  {"type":"hello","satellite":"cuisine","token":"..."}   (auth + identité)
  <frames binaires PCM>                                   (pendant une phrase)
  {"type":"reveil","score":0.84}                         (arbitrage multi-micros)
  {"type":"fin_parole"}                                   (fin d'énoncé -> traiter)
  {"type":"ping"}
Serveur -> client :
  {"type":"pret","piece":"cuisine"}
  <audio court « Oui ? » si le réveil est accepté>
  {"type":"reveil_accepte|reveil_refuse","id":1,"accuse_vocal":true}
  {"type":"etat","etat":"ecoute|reflexion|parole|attente_confirmation|veille"}
  {"type":"texte","texte":"..."}                          (réponse affichable)
  {"type":"audio_debut","freq":24000}                     (puis frames binaires)
  {"type":"audio_fin"}
  {"type":"relance","secondes":8}                          (suivi sans wake word)
  {"type":"veille_forcee"}                                  (wake word requis)
  {"type":"erreur","message":"..."}

SÉCURITÉ : LAN-only (jamais exposé via ngrok — cf. la garde X-Forwarded), un
TOKEN par satellite (config satellites[].token, comparé en timing-safe). Les
actions marquées sensibles demandent la même CONFIRMATION vocale qu'au bureau :
N2 peut être mémorisé, N3 doit être reconfirmé à chaque fois.

MULTI-PIÈCES : chaque satellite a une `piece` (config) injectée en contexte -> «
allume la lumière » depuis la cuisine cible la cuisine par défaut.

MODE NUIT (prévu, PAS implémenté) : le protocole et la config laissent la place à
un satellite Pi qui, PC éteint, assurerait la domotique en autonomie et
réveillerait le PC via la Tapo (cf. wol.md). Rien ici ne le rend impossible :
le dispatch est isolé (_traiter), la détection « PC éteint » se ferait côté Pi.
"""
import asyncio
import json
import ipaddress
import logging
import secrets
import socket
import threading
import time

from core.config import reglage
from core.util import nettoyer_reponse_vocale, sans_accents

LOG = logging.getLogger("jarvis.satellite")

TAUX = 16000                      # PCM entrant : 16 kHz mono 16-bit LE (comme le micro PC)
_MAX_UTTERANCE = TAUX * 2 * 30    # garde-fou : 30 s d'audio max par énoncé (octets)
_APP_LAN = None
_SERVEUR_LAN = None
_RESEAU_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")


def _origine_locale_ou_lan(ws) -> bool:
    """Refuse les reverse proxies et les clients hors du réseau local.

    Le tunnel ngrok termine sa connexion sur le PC en loopback, donc l'adresse
    socket seule ne suffit pas : ses en-têtes ``Forwarded``/``X-Forwarded-*``
    sont également bloqués. Un satellite réel arrive directement avec une
    adresse privée du LAN.
    """
    entetes = getattr(ws, "headers", {}) or {}
    for nom in ("forwarded", "x-forwarded-for", "x-forwarded-host",
                "x-forwarded-proto", "x-real-ip"):
        if entetes.get(nom):
            return False
    client = getattr(ws, "client", None)
    hote = str(getattr(client, "host", "") or "").split("%", 1)[0]
    try:
        adresse = ipaddress.ip_address(hote)
    except ValueError:
        return False
    return (adresse.is_loopback or adresse.is_private or adresse.is_link_local
            or adresse in _RESEAU_TAILSCALE_V4)


def _satellites():
    """Dict id -> {piece, token, wake} depuis config.yaml (section satellites)."""
    out = {}
    for s in (reglage("satellites", []) or []):
        if isinstance(s, dict) and s.get("id"):
            out[str(s["id"])] = {
                "piece": str(s.get("piece", "") or ""),
                "token": str(s.get("token", "") or ""),
                "wake": str(s.get("wake", "appareil") or "appareil"),  # "appareil" | "serveur"
                "priorite_micro": float(s.get("priorite_micro", 1.0) or 1.0),
                "brief_au_demarrage": bool(s.get("brief_au_demarrage", False)),
            }
    return out


def _systeme(piece):
    """Prompt système du satellite : Jarvis, avec le contexte de pièce."""
    base = ("Tu es Jarvis, assistant vocal, répondant depuis un satellite dans une "
            "pièce de la maison. Réponds en UNE à deux phrases courtes, en français, "
            "avec ta personnalité. Ne commence jamais une réponse finale par "
            "« attends », « un instant », « je regarde » ou « je cherche » : le "
            "système annonce lui-même les vraies recherches lentes. Utilise les "
            "outils quand c'est utile. Si une tâche "
            "exige plusieurs clics ou saisies sur le PC et qu'aucun outil direct ne "
            "suffit, appelle controle_pc_astra afin de demander l'autorisation. Pour "
            "un titre ou une playlist Spotify, utilise lire_spotify ; pour une série "
            "ou un film Netflix, utilise lire_netflix ; pour pause/suivant/précédent, "
            "utilise controler_media, sans Astra. Pour "
            "un vrai travail de création de contenu — script, hooks, idées vidéo, "
            "analyse ou réécriture — confie la réflexion à Hermes.")
    if piece:
        base += (f" CONTEXTE : ce satellite est dans « {piece} ». Si l'utilisateur "
                 f"parle d'une lumière/pièce SANS préciser laquelle, utilise « {piece} » "
                 "par défaut.")
    return base


class _Session:
    """État d'une connexion satellite : identité, pièce, audio en cours, et une
    éventuelle action N3 en attente de confirmation vocale."""
    def __init__(self):
        self.satellite = None
        self.piece = ""
        self.audio = bytearray()
        self.historique = []
        self.en_attente = None     # (Outil, args) N3 à confirmer, ou None
        self.relances_restantes = 0

    def nouveau_reveil(self, maximum):
        """Ouvre un nombre borné de fenêtres sans nouveau wake word."""
        try:
            maximum = int(maximum)
        except (TypeError, ValueError):
            maximum = 2
        self.relances_restantes = max(0, min(maximum, 10))

    def autoriser_relance(self, obligatoire=False):
        """Consomme une relance normale ; les confirmations N3 restent possibles."""
        if obligatoire:
            return True
        if self.relances_restantes <= 0:
            return False
        self.relances_restantes -= 1
        return True

    def mettre_en_veille(self):
        self.relances_restantes = 0


def _transcrire(pcm_bytes):
    """PCM 16-bit LE mono 16 kHz -> texte (faster-whisper, modèle partagé lazy)."""
    import numpy as np
    audio = (np.frombuffer(bytes(pcm_bytes), dtype=np.int16).astype(np.float32) / 32768.0)
    if audio.size < TAUX * 0.3:
        return ""
    modele = _whisper()
    if modele is None:
        return ""
    segments, _ = modele.transcribe(audio, language="fr", beam_size=1)
    return " ".join(s.text for s in segments).strip()


_WHISPER = None


def _whisper():
    """Whisper dédié au satellite.

    Le Jarvis principal utilise déjà le GPU. Charger un second modèle dessus peut
    faire échouer CTranslate2 avec ``CUDA failed`` ; le satellite privilégie donc
    un petit modèle CPU/int8, stable et suffisamment rapide pour de courtes phrases.
    """
    global _WHISPER
    if _WHISPER is None:
        try:
            from faster_whisper import WhisperModel
            nom = reglage("satellite_lan.whisper_modele", "small")
            appareil = reglage("satellite_lan.whisper_device", "cpu")
            calcul = reglage("satellite_lan.whisper_compute_type", "int8")
            _WHISPER = WhisperModel(nom, device=appareil, compute_type=calcul)
            LOG.info(
                "satellite: Whisper %s sur %s (%s)", nom, appareil, calcul
            )
        except Exception:
            LOG.exception("satellite: chargement Whisper")
            _WHISPER = None
    return _WHISPER


def _tts_pcm(texte):
    """Synthétise `texte` -> (pcm_bytes 16-bit LE mono, frequence_hz) ou (b"", 0)."""
    try:
        from core.tts import tts
        res = tts().synthetiser(texte)
        if not res:
            return b"", 0
        import numpy as np
        audio, freq = res
        pcm = np.asarray(audio, dtype=np.int16).tobytes()
        return pcm, int(freq)
    except Exception:
        LOG.exception("satellite: TTS")
        return b"", 0


_TTS_COURT = {}
_TTS_COURT_LOCK = threading.Lock()


def _tts_pcm_court(texte):
    """TTS mis en cache pour les accusés répétés du satellite.

    Le premier passage utilise le moteur vocal configuré ; les suivants évitent
    un nouvel appel cloud et partent presque immédiatement.
    """
    with _TTS_COURT_LOCK:
        if texte in _TTS_COURT:
            return _TTS_COURT[texte]
        resultat = _tts_pcm(texte)
        if resultat[0]:
            _TTS_COURT[texte] = resultat
        return resultat


def _progression_initiale(phrase):
    """Accusé contextuel uniquement si la demande annonce un travail lent.

    Les échanges simples (salutation, heure, conversation) renvoient None : ils
    ne doivent jamais être précédés d'un « attends » ou d'un « je cherche ».
    """
    p = sans_accents((phrase or "").lower())
    if any(m in p for m in ("mail", "mails", "email", "courriel", "boite de reception")):
        return "Je regarde tes mails."
    if "recette" in p and any(m in p for m in (
            "cherche", "trouve", "propose", "donne-moi", "donne moi", "recommande")):
        return "Je cherche une recette adaptée."
    if any(m in p for m in (
            "cherche", "recherche", "sur internet", "sur le web", "trouve-moi",
            "trouve moi", "actualite", "derniere nouvelle", "compare")):
        return "Je lance la recherche."
    if any(m in p for m in ("agenda", "calendrier", "rendez-vous", "rendez vous")):
        return "Je regarde ton agenda."
    if any(m in p for m in ("ecran", "cette erreur", "ce message", "ce qui est affiche")):
        return "Je regarde ton écran."
    if "meteo" in p or "temps fait" in p or "prevision" in p:
        return "Je regarde la météo."
    if any(m in p for m in ("facture", "recu", "recus", "depense", "budget")):
        return "Je vérifie tes informations."
    return None


def _phrase_progression(phrase):
    """Seconde étape, seulement pour une intention lente déjà reconnue."""
    p = sans_accents((phrase or "").lower())
    if any(m in p for m in ("mail", "mails", "email", "courriel", "boite de reception")):
        return "Je parcours les messages."
    if "recette" in p and any(m in p for m in (
            "cherche", "trouve", "propose", "donne-moi", "donne moi", "recommande")):
        return "Je vérifie les propositions."
    if any(m in p for m in (
            "cherche", "recherche", "sur internet", "sur le web", "trouve-moi",
            "trouve moi", "actualite", "derniere nouvelle", "compare")):
        return "Je vérifie les résultats."
    if any(m in p for m in ("agenda", "calendrier", "rendez-vous", "rendez vous")):
        return "Je vérifie les événements."
    if "meteo" in p or "temps fait" in p:
        return "Je vérifie les prévisions."
    if any(m in p for m in ("facture", "recu", "recus", "depense", "budget")):
        return "Je termine la vérification."
    if any(m in p for m in (
            "allume", "eteins", "éteins", "ouvre", "ferme", "augmente", "baisse")):
        return "La commande est en cours."
    return None


def _demande_veille(phrase):
    """Détecte une demande explicite de retour au mot d'activation."""
    import re
    from core.util import sans_accents
    p = " ".join(re.sub(
        r"[^a-z0-9]+", " ", sans_accents((phrase or "").lower())
    ).split())
    expressions = (
        "mets toi en veille",
        "met toi en veille",
        "active le mode veille",
        "passe en mode veille",
        "retourne en veille",
        "passe en veille",
        "va en veille",
        "dors",
        "endors toi",
        "rendors toi",
        "retourne dormir",
        "arrete d ecouter",
        "arrete de m ecouter",
        "ne m ecoute plus",
        "arrete de repondre",
        "ne reponds plus",
        "tais toi jusqu a ce que je te rappelle",
    )
    return any(expression in p for expression in expressions)


def _adresse_a_alexa(phrase):
    """Vrai lorsque la phrase est clairement destinée à l'assistant Alexa.

    Pendant la courte fenêtre de conversation suivie, le satellite écoute sans
    nouveau mot d'activation. Une commande commençant par « Alexa » appartient
    alors à l'autre assistant de la pièce : Jarvis doit se taire et refermer sa
    fenêtre d'écoute au lieu de répondre à sa place.

    On ne filtre volontairement que le début de phrase. Une question adressée à
    Jarvis telle que « Est-ce qu'Alexa est connectée ? » reste donc valide.
    """
    import re
    p = " ".join(re.sub(
        r"[^a-z0-9]+", " ", sans_accents((phrase or "").lower())
    ).split())
    return p == "alexa" or p.startswith("alexa ") or p.startswith("hey alexa ")


def _executer_outil(nom, args):
    """Exécute un outil après application de la politique de confirmation."""
    from core import registre
    outil = registre.get(nom)
    if outil is None:
        return f"Outil inconnu : {nom}"
    try:
        return str(registre.executer(outil, args or {}))
    except Exception:
        LOG.exception("satellite: outil %s", nom)
        return "Erreur pendant l'action."


def _executer_decision_prioritaire(session, decision):
    """Exécute sur un satellite une décision du routeur partagé."""
    from core import registre

    if decision.type == "astra":
        from tools.astra_pc import executer_controle
        texte = (executer_controle(decision.tache) if decision.tache else
                 "Dis-moi quelle tâche tu veux que je fasse sur le PC avec Astra.")
    elif decision.type == "vision":
        from tools.ecran import analyser_ecran
        texte = analyser_ecran(decision.tache)
    elif decision.type == "hermes":
        from tools.deleguer_a_hermes import deleguer_en_fond
        texte = deleguer_en_fond(
            decision.tache,
            intro="Hermes a terminé le travail de contenu. ",
            nom_thread="contenu-hermes",
        )
    else:
        nom, args = decision.outil, decision.arguments
        o = registre.get(nom)
        if o is None:
            return None
        if o.confirmation and not registre.est_autorise(nom):
            session.en_attente = (nom, args)
            try:
                annonce = o.annonce(args) if o.annonce else None
            except Exception:
                annonce = None
            niveau = registre.niveau(nom)
            suffixe = " Tu confirmes ? (oui / non)"
            if niveau == "N2":
                suffixe += " Tu peux aussi dire oui, toujours."
            return {"reponse": (annonce or f"Je vais exécuter {nom}.") + suffixe,
                    "attente_confirmation": True}
        texte = _executer_outil(nom, args)

    session.historique.append({"role": "assistant", "content": texte})
    return {"reponse": texte, "attente_confirmation": False}


def traiter_texte(session, phrase):
    """Fait tourner la phrase dans le LLM + outils, avec contexte pièce et droits
    maison (N2 confirmable/mémorisable, N3 toujours confirmée). Renvoie un dict
    {reponse, attente_confirmation(bool)}."""
    from core import registre
    session.historique.append({"role": "user", "content": phrase})

    from core.routage_intentions import decider_prioritaire
    decision = decider_prioritaire(phrase, piece=session.piece)
    if decision is not None:
        resultat = _executer_decision_prioritaire(session, decision)
        if resultat is not None:
            return resultat

    from core.llm import llm
    P = llm()
    if not P.disponible():
        return {"reponse": "Le cerveau de Jarvis n'est pas disponible.", "attente_confirmation": False}

    from core.routage_intentions import modules_pour_phrase
    modules_outils = modules_pour_phrase(phrase)
    faits = []
    max_tours = max(1, min(int(reglage("assistant.max_tours_outils", 6) or 6), 12))
    max_appels = max(1, min(int(reglage("assistant.max_appels_outils", 12) or 12), 30))
    timeout_tour = max(15.0, min(
        float(reglage("assistant.timeout_tour", 120) or 120), 300.0))
    debut_tour = time.monotonic()
    appels = 0
    for numero_tour in range(max_tours + 1):
        if time.monotonic() - debut_tour > timeout_tour:
            LOG.warning("satellite: tour interrompu après %.1fs",
                        time.monotonic() - debut_tour)
            return {"reponse": "J'arrête cette demande : elle prend trop de temps.",
                    "attente_confirmation": False}
        try:
            debut_llm = time.monotonic()
            rep = P.repondre(_systeme(session.piece), session.historique,
                             registre.schemas_api(local_seulement=(P.nom == "Ollama"),
                                                  modules=modules_outils))
            LOG.info("satellite %s: latence LLM %s %.3fs (tour=%s)",
                     session.piece or session.satellite or "?", P.nom,
                     time.monotonic() - debut_llm, numero_tour + 1)
        except Exception as e:
            LOG.exception("satellite: appel modèle")
            return {"reponse": f"Erreur du cerveau ({e}).", "attente_confirmation": False}

        if getattr(rep, "stop_reason", None) != "tool_use":
            texte = " ".join(b.text for b in rep.content
                             if getattr(b, "type", None) == "text").strip()
            texte = nettoyer_reponse_vocale(texte)
            session.historique.append({"role": "assistant", "content": texte or "C'est fait."})
            return {"reponse": texte or ("C'est fait." if faits else "D'accord."),
                    "attente_confirmation": False}

        session.historique.append({"role": "assistant", "content": rep.content})
        nouveaux = [b for b in rep.content if getattr(b, "type", None) == "tool_use"]
        if numero_tour >= max_tours or appels + len(nouveaux) > max_appels:
            LOG.warning("satellite: limite d'outils atteinte (tours=%s, appels=%s)",
                        numero_tour, appels)
            return {"reponse": "J'arrête ici pour éviter une boucle d'actions.",
                    "attente_confirmation": False}
        appels += len(nouveaux)
        resultats = []
        for b in rep.content:
            if getattr(b, "type", None) != "tool_use":
                continue
            # Toute action marquée sensible suit la même politique qu'au bureau.
            # N2 mémorisé peut passer ; N3 ne l'est jamais.
            o = registre.get(b.name)
            if o is not None and o.confirmation and not registre.est_autorise(b.name):
                session.en_attente = (b.name, b.input or {})
                q = None
                if o is not None and getattr(o, "annonce", None):
                    try:
                        q = o.annonce(b.input or {})
                    except Exception:
                        q = None
                suffixe = " Tu confirmes ? (oui / non)"
                if registre.niveau(b.name) == "N2":
                    suffixe += " Tu peux aussi dire oui, toujours."
                return {"reponse": (q or "C'est une action sensible.") + suffixe,
                        "attente_confirmation": True}
            res = _executer_outil(b.name, b.input or {})
            faits.append(b.name)
            resultats.append({"type": "tool_result", "tool_use_id": b.id, "content": str(res)})
        session.historique.append({"role": "user", "content": resultats})
    return {"reponse": "Commande trop longue à traiter.", "attente_confirmation": False}


def _resoudre_confirmation(session, phrase):
    """L'utilisateur répond oui/non à une action sensible en attente."""
    from core import registre
    from core.util import sans_accents
    nom, args = session.en_attente
    session.en_attente = None
    p = sans_accents(phrase.lower())
    oui = any(m in p for m in ("oui", "ok", "vas-y", "vas y", "confirme", "d'accord", "daccord", "fais"))
    if not oui:
        return "D'accord, j'annule."
    resultat = _executer_outil(nom, args)
    if "toujours" in p:
        if registre.autoriser_toujours(nom):
            resultat += " Je ne te le redemanderai plus pour cette action."
        else:
            resultat += (" Mais c'est une action critique : je te demanderai "
                         "toujours confirmation.")
    return resultat


# ---------------------------------------------------------------- WebSocket

def monter_routes(app):
    """Monte le WebSocket /satellite sur le serveur unifié (appelé par core.serveur)."""
    from fastapi import WebSocket, WebSocketDisconnect

    @app.websocket("/satellite")
    async def satellite(ws: WebSocket):
        if not _origine_locale_ou_lan(ws):
            LOG.warning("satellite: connexion hors LAN refusee")
            await ws.close(code=1008, reason="satellite accessible uniquement sur le LAN")
            return
        await ws.accept()
        cfg = _satellites()
        sess = _Session()

        async def envoyer(obj):
            await ws.send_text(json.dumps(obj, ensure_ascii=False))

        async def etat(e):
            await envoyer({"type": "etat", "etat": e})

        async def envoyer_audio(texte, court=False):
            synthese = _tts_pcm_court if court else _tts_pcm
            pcm, freq = await asyncio.to_thread(synthese, texte)
            if pcm:
                await envoyer({"type": "audio_debut", "freq": freq})
                for i in range(0, len(pcm), 4096):
                    await ws.send_bytes(pcm[i:i + 4096])
                await envoyer({"type": "audio_fin"})
                return True
            return False

        async def parler(texte):
            """Envoie le texte (affichage) puis l'audio TTS (frames binaires)."""
            await envoyer({"type": "texte", "texte": texte})
            await etat("parole")
            await envoyer_audio(texte)

        async def progresser(texte):
            """Parle brièvement sans ajouter l'accusé à l'historique LLM."""
            await envoyer({"type": "progression", "texte": texte})
            await etat("parole")
            await envoyer_audio(texte, court=True)
            await etat("reflexion")

        async def proposer_relance(secondes=None, obligatoire=False):
            if not bool(reglage("satellite_lan.conversation_suivie", True)):
                return
            if not sess.autoriser_relance(obligatoire=obligatoire):
                # Ferme aussi une éventuelle fenêtre devenue obsolète côté
                # client. Un bruit de cuisine ne peut ainsi pas renouveler
                # indéfiniment l'écoute sans nouveau « Hey Jarvis ».
                await envoyer({"type": "veille_forcee"})
                return
            try:
                duree = float(secondes if secondes is not None else reglage(
                    "satellite_lan.fenetre_relance", 8.0))
            except (TypeError, ValueError):
                duree = 8.0
            duree = max(0.0, min(duree, 30.0))
            if duree:
                await envoyer({"type": "relance", "secondes": duree})

        try:
            while True:
                msg = await ws.receive()
                # 1) trame binaire = audio PCM
                if "bytes" in msg and msg["bytes"] is not None:
                    if sess.satellite is None:      # pas encore authentifié
                        continue
                    sess.audio.extend(msg["bytes"])
                    if len(sess.audio) > _MAX_UTTERANCE:
                        sess.audio = sess.audio[-_MAX_UTTERANCE:]
                    continue
                # 2) trame texte = contrôle
                if "text" not in msg or msg["text"] is None:
                    if msg.get("type") == "websocket.disconnect":
                        break
                    continue
                try:
                    data = json.loads(msg["text"])
                except Exception:
                    continue
                typ = data.get("type")

                if typ == "hello":
                    sid = str(data.get("satellite", ""))
                    conf = cfg.get(sid)
                    if not conf or not conf["token"] or not secrets.compare_digest(
                            str(data.get("token", "")), conf["token"]):
                        await envoyer({"type": "erreur", "message": "satellite inconnu ou token invalide"})
                        await ws.close(code=1008)
                        return
                    sess.satellite, sess.piece = sid, conf["piece"]
                    LOG.info("satellite connecté : %s (pièce %s)", sid, sess.piece or "?")
                    await envoyer({"type": "pret", "piece": sess.piece})
                    await etat("veille")

                elif typ == "reveil" and sess.satellite:
                    from core.arbitrage_micro import reserver_reveil
                    try:
                        score = float(data.get("score", 0.0))
                    except (TypeError, ValueError):
                        score = 0.0
                    priorite = cfg[sess.satellite].get("priorite_micro", 1.0)
                    accepte = await asyncio.to_thread(
                        reserver_reveil,
                        f"satellite:{sess.satellite}",
                        score * priorite,
                    )
                    if accepte:
                        sess.nouveau_reveil(reglage(
                            "satellite_lan.max_relances", 2))
                    accuse_vocal = False
                    if accepte and bool(reglage(
                            "satellite_lan.accuse_reveil_vocal", True)):
                        texte_accuse = str(reglage(
                            "satellite_lan.texte_accuse_reveil", "Oui ?") or "").strip()
                        try:
                            delai_accuse = float(reglage(
                                "satellite_lan.delai_accuse_reveil", 2.5))
                        except (TypeError, ValueError):
                            delai_accuse = 2.5
                        if texte_accuse:
                            try:
                                # L'audio part AVANT l'autorisation de capture :
                                # le Pi le joue pendant que son thread micro attend,
                                # puis commence seulement à enregistrer la question.
                                accuse_vocal = await asyncio.wait_for(
                                    envoyer_audio(texte_accuse, court=True),
                                    timeout=max(0.5, min(delai_accuse, 5.0)),
                                )
                            except asyncio.TimeoutError:
                                LOG.warning(
                                    "satellite: accusé vocal trop lent, repli sur le bip")
                    await envoyer({
                        "type": "reveil_accepte" if accepte else "reveil_refuse",
                        "id": data.get("id"),
                        "accuse_vocal": accuse_vocal,
                    })

                elif typ == "scene_demarrage" and sess.satellite:
                    # Seul le poste principal explicitement configuré peut demander
                    # le brief. Le marqueur quotidien est conservé côté serveur.
                    if not cfg[sess.satellite].get("brief_au_demarrage", False):
                        continue
                    from tools.scenes import texte_scene_au_demarrage
                    texte = await asyncio.to_thread(texte_scene_au_demarrage)
                    if texte:
                        await parler(texte)
                    await etat("veille")

                elif typ == "fin_parole" and sess.satellite:
                    audio = bytes(sess.audio)
                    sess.audio = bytearray()
                    await etat("reflexion")
                    # On ne connaît pas encore l'intention pendant Whisper : toute
                    # phrase d'attente ici serait nécessairement générique et peut
                    # parasiter une simple salutation. La progression ne commence
                    # qu'après transcription, lorsque la demande le justifie.
                    phrase = await asyncio.to_thread(_transcrire, audio)
                    if not phrase:
                        await parler("Je n'ai rien entendu.")
                        await proposer_relance()
                        await etat("veille")
                        continue
                    await envoyer({"type": "transcription", "texte": phrase})
                    if _adresse_a_alexa(phrase):
                        # Ne jamais lutter avec un Echo présent dans la pièce.
                        # Le silence est intentionnel : la demande ne visait pas
                        # Jarvis et ne doit pas rouvrir la conversation suivie.
                        sess.en_attente = None
                        sess.mettre_en_veille()
                        await envoyer({"type": "veille_forcee"})
                        await etat("veille")
                        continue
                    if _demande_veille(phrase):
                        # Une mise en veille annule aussi une éventuelle action N3
                        # encore en attente : elle ne doit jamais être confirmée plus tard.
                        sess.en_attente = None
                        sess.mettre_en_veille()
                        await parler("D'accord, je me mets en veille.")
                        await envoyer({"type": "veille_forcee"})
                        await etat("veille")
                        continue
                    if sess.en_attente:                         # réponse à une confirmation N3
                        rep = _resoudre_confirmation(sess, phrase)
                        await parler(rep)
                        await proposer_relance()
                        await etat("veille")
                        continue
                    traitement = asyncio.create_task(
                        asyncio.to_thread(traiter_texte, sess, phrase))
                    progression_initiale = None
                    if bool(reglage("satellite_lan.accuse_immediat", True)):
                        progression_initiale = _progression_initiale(phrase)
                    if progression_initiale:
                        await progresser(progression_initiale)
                    try:
                        attente_llm = float(reglage(
                            "satellite_lan.progression_traitement_apres", 4.0))
                    except (TypeError, ValueError):
                        attente_llm = 4.0
                    try:
                        r = await asyncio.wait_for(
                            asyncio.shield(traitement), timeout=max(0.1, attente_llm))
                    except asyncio.TimeoutError:
                        suite = _phrase_progression(phrase)
                        if suite:
                            await progresser(suite)
                        r = await traitement
                    if r["attente_confirmation"]:
                        await envoyer({"type": "texte", "texte": r["reponse"]})
                        await etat("attente_confirmation")
                        await envoyer_audio(r["reponse"])
                        await proposer_relance(12.0, obligatoire=True)
                    else:
                        await parler(r["reponse"])
                        await proposer_relance()
                        await etat("veille")

                elif typ == "ping":
                    await envoyer({"type": "pong"})

        except WebSocketDisconnect:
            pass
        except Exception:
            LOG.exception("satellite: boucle WS")
        finally:
            LOG.info("satellite déconnecté : %s", sess.satellite)

    LOG.info("satellite: route /satellite montée (LAN, token par satellite)")


def _app_lan():
    """Application FastAPI minimale exposée au LAN : audio + agent Windows."""
    global _APP_LAN
    if _APP_LAN is None:
        from fastapi import FastAPI
        _APP_LAN = FastAPI(
            title="Jarvis Satellite LAN",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
        monter_routes(_APP_LAN)
        from core.poste_distant import monter_routes as monter_poste_distant
        monter_poste_distant(_APP_LAN)
    return _APP_LAN


def demarrer_lan():
    """Démarre le listener satellite dédié sans exposer le serveur unifié.

    Le port n'est ouvert que lorsqu'un satellite ou agent Windows est configuré.
    Le panneau, le cockpit, l'inbox iPhone et Twilio restent sur le listener
    loopback principal.
    """
    global _SERVEUR_LAN
    from core.poste_distant import agents_configures
    if (not _satellites() and not agents_configures()) or not bool(
            reglage("satellite_lan.actif", True)):
        return
    if _SERVEUR_LAN and _SERVEUR_LAN.is_alive():
        return

    import uvicorn
    hote = str(reglage("satellite_lan.host", "0.0.0.0") or "0.0.0.0")
    port = int(reglage("satellite_lan.port", 8791))
    serveur = uvicorn.Server(uvicorn.Config(
        _app_lan(), host=hote, port=port, log_level="warning"))

    def run():
        try:
            serveur.run()
        except Exception:
            LOG.exception("satellite: serveur LAN")

    _SERVEUR_LAN = threading.Thread(
        target=run, daemon=True, name="satellite-lan")
    _SERVEUR_LAN.start()

    # Prépare le très court « Oui ? » dès le démarrage. Le premier wake word ne
    # paie ainsi normalement ni la latence réseau ni la synthèse cloud.
    if bool(reglage("satellite_lan.accuse_reveil_vocal", True)):
        texte_accuse = str(reglage(
            "satellite_lan.texte_accuse_reveil", "Oui ?") or "").strip()
        if texte_accuse:
            threading.Thread(
                target=_tts_pcm_court,
                args=(texte_accuse,),
                daemon=True,
                name="satellite-accuse-reveil",
            ).start()
    for _ in range(40):
        try:
            socket.create_connection(("127.0.0.1", port), 0.15).close()
            break
        except OSError:
            time.sleep(0.15)
    LOG.info("satellite: listener LAN actif sur %s:%d", hote, port)
