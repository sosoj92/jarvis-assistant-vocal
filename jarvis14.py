"""
Assistant vocal local, avec mot d'activation et actions.

Dites « Hey Jarvis », parlez, taisez-vous. Il repond et agit.
Chaine : openWakeWord -> faster-whisper -> Claude (+ outils) -> ElevenLabs/Piper
(repli sur la voix integree a l'OS : SAPI, `say` sur macOS, espeak sur Linux)

Architecture : les outils vivent dans tools/ (auto-decouverts via core.registre),
les reglages et secrets dans config.yaml (via core.config).

Usage : uv run python jarvis14.py
"""

import datetime as dt
import os
import queue
import re
import threading
import time
import wave
from collections import deque
from pathlib import Path

# Magasin de certificats Windows (comme git) au lieu du bundle certifi.
# Indispensable si un antivirus/proxy intercepte le TLS, sinon les appels HTTPS
# (Claude, Gmail) echouent avec "certificate verify failed". Avant tout reseau.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import numpy as np
import openwakeword
import sounddevice as sd
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeModel

from core import config, journal, memoire, personnalite, plateforme, registre, voix
from core.util import sans_accents
from tools.lumieres import allumer_si_nuit, charger_pieces_hue

# ---------------------------------------------------------------- reglages

# Index (ou nom) du micro. Par defaut : 1 sur Windows (historique), l'entree
# systeme sur macOS/Linux, ou l'index 1 designe souvent une SORTIE.
MICRO = plateforme.peripherique_audio(
    config.reglage("audio.micro", plateforme.micro_defaut()))
# None = sortie audio par defaut de l'OS (suit l'enceinte/casque actif).
HAUT_PARLEUR = plateforme.peripherique_audio(config.reglage("audio.haut_parleur", None))


def _haut_parleur():
    """Peripherique de sortie TTS COURANT (lu en direct : changeable a la voix via
    l'outil sortie_audio -> config.definir). None = sortie par defaut de l'OS."""
    return plateforme.peripherique_audio(config.reglage("audio.haut_parleur", None))

# Le choix du modele LLM (Claude/Ollama) et de la voix (ElevenLabs/Piper) est gere
# par les providers (core/llm.py, core/tts.py), selon config.yaml (mode: cloud|local).
MODELE_WHISPER = config.reglage("whisper.modele", "medium")


def _amorce_whisper():
    """Phrase d'amorce donnee a Whisper pour ancrer le vocabulaire attendu.

    Whisper transcrit par probabilite : sans contexte, « Uber Eats » devient
    « hubveritz », « OBS » devient « eaubéesse ». L'amorce (initial_prompt) est
    le levier prevu pour ca : les mots qu'elle contient deviennent nettement
    plus probables. On y met le vocabulaire de config.yaml, plus les noms que
    Jarvis connait deja (applications configurees, pieces de la maison).
    """
    mots = list(config.reglage("whisper.vocabulaire", []) or [])
    try:                                    # les apps que l'utilisateur a declarees
        mots += [str(k) for k in (config.reglage("apps", {}) or {})]
    except Exception:
        pass
    vus, propres = set(), []
    for m in mots:
        m = str(m).strip()
        if m and m.lower() not in vus:
            vus.add(m.lower())
            propres.append(m)
    if not propres:
        return None
    return ("Conversation en francais avec un assistant vocal nomme Jarvis. "
            "Vocabulaire attendu : " + ", ".join(propres) + ".")


AMORCE_WHISPER = _amorce_whisper()

TAUX = 16000
BLOC = 1280

SEUIL_REVEIL = config.reglage("assistant.seuil_reveil", 0.5)   # sensibilite du mot d'activation
# Mot d'activation redit PAR-DESSUS Jarvis : plus strict que l'eveil normal, car
# le micro entend aussi l'enceinte. Reglable : sur un micro peu sensible ou en
# casque (pas d'echo), 0.7 est inatteignable et couper devient impossible.
SEUIL_INTERRUPTION = config.reglage("interruption.seuil_reveil", 0.7)
SEUIL_PAROLE_SUR = 0.025
# Parole continue requise avant de transcrire ce qui est dit PAR-DESSUS Jarvis.
# 3 x 80 ms = 0,24 s. C'etait 5 (0,4 s), mais un « stop » sec dure ~0,25 s : le
# seuil ne pouvait mathematiquement jamais etre atteint pour le mot d'arret le
# plus utilise.
BLOCS_AVANT_VERIF = 3
# Blocs faibles toleres sans remettre le compteur a zero. La plosive de « stop »
# ou de « attends » cree une micro-coupure naturelle qui, sans cette tolerance,
# annulait la detection juste avant qu'elle aboutisse.
BLOCS_CREUX_TOLERES = 2
DELAI_ENTRE_VERIFS = 1.0
SEUIL_SILENCE = 0.010
SILENCE_FIN = 1.2
DUREE_MAX = 20

# Fenetre de suivi : apres une reponse, Jarvis reste a l'ecoute ce nombre de
# secondes pour enchainer une nouvelle demande sans redire "Hey Jarvis".
DUREE_SUITE = config.reglage("assistant.duree_suite", 10)

LOG = journal.obtenir()

# Sentinel renvoye par repondre() quand une action attend une confirmation vocale.
SENTINEL_CONFIRM = "\x00confirmation\x00"

# Regles de base (format vocal, outils). La personnalite (persona) est ajoutee
# devant, et la memoire derriere, par _refaire_systeme.
SYSTEME_BASE = (
    "Tes reponses sont lues a voix haute : reponds en une a deux phrases maximum "
    "(une seule si possible), sans listes, sans titres, sans asterisques ni emoji. "
    "Parle naturellement, en francais. Va a l'essentiel. Ne pose jamais deux fois "
    "la meme question et ne redemande pas une confirmation deja demandee. "
    "Tu disposes d'outils pour agir sur l'ordinateur : utilise-les quand "
    "l'utilisateur demande une action, et confirme brievement ce que tu as fait. "
    "Quand l'utilisateur exprime une preference, mentionne un proche ou parle d'un "
    "projet en cours, appelle remember pour t'en souvenir, sans le commenter. "
    "Pour les mails : prepare un brouillon avec preparer_mail et lis-le ; appelle "
    "envoyer_mail quand l'utilisateur veut envoyer (le systeme demandera confirmation). "
    "Si la question fait reference a ce qui est affiche (qu'est-ce que c'est, lis "
    "ca, cette erreur, mon ecran, ce message), appelle capture_screen puis reponds "
    "d'apres l'image."
)

# Consigne systeme courante (persona + regles + memoire). Passee a chaque appel
# Claude via le parametre `system`, distinct de la liste des messages.
SYSTEME_COURANT = SYSTEME_BASE


def _refaire_systeme(memoire_courante):
    """Recompose la consigne systeme : personnalite + regles + memoire."""
    global SYSTEME_COURANT
    persona = personnalite.persona(
        config.reglage("assistant.personnalite", personnalite.DEFAUT))
    SYSTEME_COURANT = (persona + "\n\n" + SYSTEME_BASE
                       + memoire.texte_pour_systeme(memoire_courante))


_JOURS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS_FR = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
            "aout", "septembre", "octobre", "novembre", "decembre")


def _ancrage_temporel():
    """Rappelle au modele la date et l'heure — recalcule a CHAQUE tour.

    Sans cela, le modele ne sait pas quel jour on est : il interprete « cette
    semaine » ou « la semaine qui vient » au hasard, ne peut pas verifier ce
    que l'agenda lui rend, et doit appeler un outil rien que pour donner la
    date. C'est la cause d'une famille entiere d'erreurs.

    Recalcule a chaque tour, et pas une fois au demarrage : Jarvis tourne des
    jours d'affilee, et une date figee serait pire que pas de date du tout.
    """
    d = dt.datetime.now().astimezone()
    return (f"\n\nDate et heure actuelles : {_JOURS_FR[d.weekday()]} "
            f"{d.day} {_MOIS_FR[d.month - 1]} {d.year}, {d.hour}h{d.minute:02d}. "
            "Sers-t'en pour interpreter « aujourd'hui », « cette semaine », "
            "« la semaine prochaine » : n'appelle pas d'outil pour connaitre la "
            "date. Si un resultat d'agenda semble incoherent avec cette date, "
            "dis-le au lieu de le lire tel quel.")


def systeme_courant():
    """Consigne systeme complete, horodatee a l'instant de l'appel."""
    return SYSTEME_COURANT + _ancrage_temporel()


# ---------------------------------------------------------------- HUD (option)

try:
    import hud
except Exception as _e:
    hud = None
    _ERREUR_HUD = _e
else:
    _ERREUR_HUD = None

try:
    import overlay as _overlay
except Exception:
    _overlay = None

_dernier_etat_hud = None
_DERNIER_OUTIL = None                                   # pour la carte overlay
_OUTILS_MUSIQUE = {"identifier_musique", "identifier_musique_fichier",
                   "derniere_musique"}


_RE_NOMBRE = re.compile(r"\d[\d .,:h]*\d|\d")


def _consultable(texte):
    """Heuristique (mode 'auto') : la reponse contient-elle des donnees a CONSULTER
    (=> fenetre + voix) ou est-ce un simple acquittement ephemere (=> voix seule) ?"""
    t = (texte or "").strip()
    if len(t) > 200:
        return True
    if "\n" in t:                              # liste / plusieurs lignes
        return True
    if len(_RE_NOMBRE.findall(t)) >= 2:        # plusieurs nombres (stats, prix, horaires)
        return True
    if "«" in t or '"' in t:                   # entite citee (titre, nom, lieu)
        return True
    return False


def _afficher_overlay(texte):
    """Route la reponse vers l'overlay selon un HINT d'outil (affichage: toujours/
    jamais/auto) puis, en 'auto', une heuristique de contenu. Memorise toujours la
    derniere reponse pour la surcharge vocale « affiche-le »."""
    global _DERNIER_OUTIL
    outil_nom = _DERNIER_OUTIL
    _DERNIER_OUTIL = None
    if _overlay is None or not texte:
        return
    typ = "musique" if outil_nom in _OUTILS_MUSIQUE else "reponse"
    try:
        _overlay.memoriser(texte, typ)         # pour « affiche-le »
    except Exception:
        pass
    hint = registre.affichage(outil_nom) if outil_nom else "auto"
    montrer = (hint == "toujours") or (hint != "jamais" and _consultable(texte))
    if montrer:
        try:
            _overlay.afficher(texte, type=typ)
        except Exception:
            pass


def _hud(methode, *args):
    """Relaie un appel au HUD sans jamais interrompre l'assistant."""
    if hud is None:
        return
    global _dernier_etat_hud
    if methode == "etat":
        if args and args[0] == _dernier_etat_hud:
            return
        _dernier_etat_hud = args[0] if args else None
    try:
        getattr(hud, methode)(*args)
    except Exception:
        pass


def _demarrer_hud():
    """Lance le HUD et DIT pourquoi si ca rate.

    C'est la seule interface visuelle sur macOS : la noyer dans le `except:
    pass` de _hud() laissait l'utilisateur sans aucune trace de l'echec.
    """
    if not config.reglage("hud.actif", True):
        return
    if hud is None:
        print(f"HUD indisponible : {_ERREUR_HUD}")
        return
    try:
        hud.demarrer(ouvrir=bool(config.reglage("hud.ouvrir_navigateur", True)))
    except OSError as e:
        print(f"HUD non demarre : le port {hud.PORT} est deja pris ({e}).")
        print(f"  Ferme l'autre Jarvis, ou change hud.port dans config.yaml.")
    except Exception as e:
        print(f"HUD non demarre ({type(e).__name__} : {e}).")


def _niv_hud(bloc):
    """Convertit le niveau brut du micro en une valeur 0..1 pour le coeur."""
    return min(1.0, niveau(bloc) / 0.2)


def _hud_status():
    """Pousse au HUD le mode de routage et le budget du jour (part Hermes gérée par
    tools.deleguer_a_hermes qui pousse hud.hermes)."""
    try:
        from core.routage import mode_actuel
        _hud("routage", mode_actuel())
    except Exception:
        pass
    try:
        from core import budget
        e = budget.etat()
        _hud("budget", round(e["total_jour"], 2), e["plafond_jour"],
             round(e["pct_jour"], 3))
    except Exception:
        pass


# ---------------------------------------------------------------- audio


def niveau(bloc_float):
    return float(np.sqrt(np.mean(bloc_float**2)))


def jouer(chemin_wav):
    with wave.open(str(chemin_wav), "rb") as f:
        taux = f.getframerate()
        donnees = f.readframes(f.getnframes())
    audio = np.frombuffer(donnees, dtype=np.int16)
    sd.play(audio, samplerate=taux, device=_haut_parleur())
    sd.wait()


def bip(frequence=880, duree=0.12):
    t = np.linspace(0, duree, int(TAUX * duree), endpoint=False)
    onde = (0.25 * np.sin(2 * np.pi * frequence * t)).astype(np.float32)
    sd.play(onde, samplerate=TAUX, device=_haut_parleur())
    sd.wait()


_PROCESSUS_PAROLE = None
_INTERRUPTION = threading.Event()
_PARLE = threading.Event()   # vrai UNIQUEMENT pendant que Jarvis joue de l'audio :
                             # c'est la seule fenetre ou on ecoute une interruption.
_CAPTURE_MUSIQUE = threading.Event()   # vrai pendant la capture Shazam : la boucle de
                                       # surveillance lache alors flux (le micro est pris).
_MICRO_MUET = threading.Event()        # vrai = wake word coupe (mute micro) : stream/call.


def basculer_micro(force=None):
    """Coupe/reactive l'ecoute du mot d'activation. force=True mute, False reactive,
    None bascule. Feedback bip + HUD. Renvoie True si desormais muet."""
    if force is True or (force is None and not _MICRO_MUET.is_set()):
        _MICRO_MUET.set()
    else:
        _MICRO_MUET.clear()
    muet = _MICRO_MUET.is_set()
    try:
        bip(400 if muet else 900, 0.10)
    except Exception:
        pass
    _hud("micro", muet)
    print("  [micro] " + ("coupe (mute)" if muet else "reactive"))
    return muet


def couper_parole():
    """Arrete immediatement la synthese en cours (ElevenLabs, Piper ou voix OS)."""
    _INTERRUPTION.set()
    try:
        sd.stop()          # coupe la lecture ElevenLabs sur le haut-parleur
    except Exception:
        pass
    processus = _PROCESSUS_PAROLE
    if processus is not None and processus.poll() is None:
        try:
            processus.terminate()
        except OSError:
            pass


def _enveloppe_voix(audio, frequence, seconde):
    """Niveau 0..1 de la voix a l'instant `seconde` de la lecture.

    Sert a faire pulser le coeur du HUD au rythme reel de ce que Jarvis dit,
    au lieu d'un etat « parole » figé. Fenetre de 40 ms, comme un vumetre.
    """
    try:
        debut = int(seconde * frequence)
        fenetre = audio[debut:debut + max(1, int(frequence * 0.04))]
        if fenetre.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean((fenetre.astype(np.float32) / 32768.0) ** 2)))
        return float(min(1.0, rms * 3.2))     # la parole depasse rarement 0.3 en RMS
    except Exception:
        return 0.0


def _jouer_audio(audio, frequence):
    """Joue un tableau int16 mono sur le haut-parleur, interruptible.

    Pousse au passage l'enveloppe de la voix au HUD : le reacteur bat au rythme
    de la phrase prononcee.
    """
    if _INTERRUPTION.is_set():
        return
    sd.play(audio, samplerate=frequence, device=_haut_parleur())
    debut = time.monotonic()
    while not _INTERRUPTION.is_set():
        courant = sd.get_stream()
        if courant is None or not courant.active:
            break
        _hud("niveau", _enveloppe_voix(audio, frequence, time.monotonic() - debut))
        time.sleep(0.03)
    if _INTERRUPTION.is_set():
        sd.stop()
    _hud("niveau", 0.0)          # le coeur retombe des la fin de la phrase


def dire(texte, interruptible=True):
    """Prononce un texte via le provider TTS courant (ElevenLabs en cloud, Piper en
    local) ; repli sur la voix integree a l'OS si le provider est indisponible.

    interruptible=False : le barge-in est desactive pendant cette phrase (utilise
    pour la question de confirmation : la reponse de l'utilisateur est un oui/non,
    pas une interruption)."""
    if _overlay is not None and _overlay.est_muet():   # mode "silencieux visuel" :
        return                                          # la reponse s'affiche, pas de TTS.
    if _INTERRUPTION.is_set():
        return
    from core.tts import tts
    resultat = tts().synthetiser(texte)
    if interruptible:
        _PARLE.set()      # a partir d'ici Jarvis parle : on peut l'interrompre
    try:
        if resultat is not None:
            _jouer_audio(*resultat)
        else:
            _dire_voix_systeme(texte)
    finally:
        _PARLE.clear()    # fin de la parole : plus d'interruption possible


def _dire_voix_systeme(texte):
    """Voix integree a l'OS : SAPI (Windows), `say` (macOS), espeak (Linux).

    C'est le dernier recours quand ElevenLabs ou Piper ne rendent rien. Le texte
    est envoye au moteur par l'entree standard, jamais sur la ligne de commande :
    une apostrophe francaise ne peut donc pas casser le littoral. L'appel est
    interruptible via couper_parole().
    """
    global _PROCESSUS_PAROLE

    if _INTERRUPTION.is_set():
        return

    processus = plateforme.parler_systeme(texte)
    if processus is None:
        print(f"  [voix] aucune voix systeme disponible ({plateforme.SYSTEME}).")
        return

    _PROCESSUS_PAROLE = processus
    try:
        _, erreurs = processus.communicate(input=texte.encode("utf-8"))
        if processus.returncode and not _INTERRUPTION.is_set():
            details = (erreurs or b"").decode("utf-8", "replace").strip()
            print(f"  [{plateforme.nom_voix_systeme()}] echec "
                  f"(code {processus.returncode}) : {details}")
    finally:
        _PROCESSUS_PAROLE = None


# ---------------------------------------------------------------- nettoyage

# Ce que Whisper entend a la place de "Hey Jarvis" quand le tampon
# glissant en rattrape la fin.
RESIDUS = (
    "avis", "service", "jarvis", "hey jarvis", "harvis", "arvis",
    "javis", "charvis", "chavis", "davis", "y a vis", "a vis",
    "la vis", "et vis", "ervice", "servi", "sers vis",
)

# Ce que Whisper invente quand il n'entend que du silence.
HALLUCINATIONS = (
    "amara.org", "sous-titres", "sous titres", "merci d'avoir regarde",
    "abonnez-vous", "abonnez vous", "a la prochaine video",
    "n'oubliez pas de vous abonner", "sous-titrage",
)

# Mots qui coupent la parole PUIS relancent l'ecoute (tu veux redire quelque chose).
MOTS_RELANCE = (
    "attends", "attend", "arrete", "arrete-toi", "arrete toi", "stop",
    "une seconde", "deux secondes", "minute", "pardon", "non non",
)

# Mots qui coupent la parole et terminent (tu as fini, il se tait).
MOTS_FIN = (
    "tais-toi", "tais toi", "chut", "silence", "ferme-la", "la ferme",
    "c'est bon", "ok merci", "d'accord merci", "laisse tomber",
)

# Mots d'accord pour une confirmation vocale.
MOTS_OUI = (
    "oui", "ouais", "ouep", "vas-y", "vas y", "confirme", "confirmer",
    "d'accord", "daccord", "ok", "okay", "envoie", "envoi", "fais",
    "yes", "carrement", "bien sur", "parfait", "valide", "valider",
)


def type_arret(texte):
    """Renvoie 'relance', 'fin' ou None selon l'ordre d'arret detecte."""
    plat = sans_accents(texte)
    plat = "".join(c if c.isalnum() or c in " '-" else " " for c in plat)
    if any(m in plat for m in MOTS_RELANCE):
        return "relance"
    if any(m in plat for m in MOTS_FIN):
        return "fin"
    return None


def _est_oui(texte):
    """Vrai si la transcription exprime un accord (oui/vas-y/confirme...)."""
    if not texte:
        return False
    plat = sans_accents(texte)
    plat = "".join(c if c.isalnum() or c in " '-" else " " for c in plat)
    return any(m in plat for m in MOTS_OUI)


def _est_toujours(texte):
    """Vrai si l'utilisateur ajoute 'toujours' (memoriser l'autorisation, N2)."""
    return bool(texte) and "toujours" in sans_accents(texte)


def _corrections():
    """Table de corrections phonetiques, depuis config.yaml (whisper.corrections).

    L'amorce (initial_prompt) suffit pour les noms a plusieurs syllabes — elle
    corrige « UB et ITS » en « Uber Eats ». Elle NE suffit PAS pour les sigles
    courts : « OBS » reste entendu « au bas », « Hue » devient « rues ». Trop
    peu de matiere sonore pour que le contexte tranche. D'ou cette table, qui
    remplace sur le texte final ce que le modele ne peut pas deviner.
    """
    brut = config.reglage("whisper.corrections", {}) or {}
    return {sans_accents(str(k).lower()): str(v) for k, v in brut.items() if k}


CORRECTIONS = _corrections()


def corriger_vocabulaire(texte):
    """Remplace les confusions connues, en respectant les frontieres de mots."""
    if not CORRECTIONS or not texte:
        return texte
    for faux, vrai in CORRECTIONS.items():
        motif = re.compile(r"\b" + re.escape(faux) + r"\b", re.IGNORECASE)
        # sans_accents pour comparer, mais on remplace dans le texte d'origine :
        # on cherche donc aussi la forme accentuee telle qu'elle a ete entendue.
        texte = motif.sub(vrai, texte)
    return texte


def nettoyer(texte):
    """Retire le residu du mot d'activation, puis corrige le vocabulaire connu."""
    t = corriger_vocabulaire(texte.strip())

    plat = sans_accents(t)
    if any(h in plat for h in HALLUCINATIONS):
        return ""

    # Cas "Avis, ouvre YouTube" ou "Jarvis : ouvre YouTube"
    tete = None
    for sep in (",", ":", ".", "!", "?"):
        if sep in t[:20]:
            avant, _, apres = t.partition(sep)
            if len(avant.split()) <= 3:
                tete, reste = avant, apres
                break

    if tete is not None:
        if tete.strip().lower().strip("'’") in RESIDUS:
            t = reste.strip()

    # Cas sans ponctuation : "Jarvis ouvre YouTube"
    mots = t.split()
    if mots and mots[0].lower().strip(",.:;!?") in RESIDUS:
        t = " ".join(mots[1:])

    return t.strip()


# ---------------------------------------------------------------- parole en flux

FIN_PHRASE = re.compile(r"(.+?[.!?…]+[\s ]*|.+?\n)", re.S)


def _parleur(fil):
    """Thread qui lit les phrases au fur et a mesure qu'elles arrivent."""
    while True:
        phrase = fil.get()
        if phrase is None:
            break
        if _INTERRUPTION.is_set():
            continue
        texte = phrase.strip()
        if texte:
            dire(texte)


def dire_en_flux(morceaux):
    """Consomme un generateur de fragments et les dit phrase par phrase."""
    fil = queue.Queue()
    thread = threading.Thread(target=_parleur, args=(fil,), daemon=True)
    thread.start()

    tampon = ""
    complet = []
    try:
        for fragment in morceaux:
            if _INTERRUPTION.is_set():
                break
            if not fragment:
                continue
            tampon += fragment
            complet.append(fragment)
            while True:
                trouve = FIN_PHRASE.match(tampon)
                if not trouve:
                    break
                phrase = trouve.group(1)
                tampon = tampon[len(phrase):]
                if len(phrase.strip()) >= 2:
                    fil.put(phrase)
        if tampon.strip():
            fil.put(tampon)
    finally:
        fil.put(None)
        thread.join()

    return "".join(complet).strip()


# ---------------------------------------------------------------- dialogue


def _executer_outils(blocs):
    """Execute les outils demandes par Claude et renvoie leurs resultats.

    S'appuie sur le registre. Logge chaque appel, ne crashe jamais (une
    exception d'outil devient une reponse comprehensible), et met les outils a
    confirmation en attente au lieu de les executer tout de suite.
    """
    resultats = []
    for bloc in blocs:
        if getattr(bloc, "type", None) != "tool_use":
            continue
        nom = bloc.name
        arguments = bloc.input or {}
        outil = registre.get(nom)

        if outil is None:
            resultat = f"Outil inconnu : {nom}"
        elif outil.confirmation and not registre.est_autorise(nom):
            # N2 memorise "toujours autoriser" -> on n'attend pas (est_autorise True).
            # Un N3 n'est jamais autorise d'avance : il repasse toujours par ici.
            resultat = registre.mettre_en_attente(outil, arguments)
        else:
            try:
                resultat = outil.fonction(**arguments)
            except Exception:
                LOG.exception("outil %s a plante (args=%s)", nom, arguments)
                resultat = "Desole, je n'ai pas reussi a faire ca."

        LOG.info("outil %s args=%s -> %s", nom, arguments, str(resultat)[:200])
        global _DERNIER_OUTIL
        _DERNIER_OUTIL = nom

        # Cas image (capture d'ecran) : bloc image dans le tool_result.
        if isinstance(resultat, dict) and resultat.get("image"):
            img = resultat["image"]
            apercu = resultat.get("apercu", "Capture d'ecran envoyee.")
            print(f"  [outil] {nom}({arguments}) -> {apercu}")
            _hud("outil", nom, apercu[:60])
            contenu = [{
                "type": "image",
                "source": {"type": "base64", "media_type": img["media_type"],
                           "data": img["data"]},
            }]
        else:
            print(f"  [outil] {nom}({arguments}) -> {str(resultat)[:80]}")
            _hud("outil", nom, str(resultat)[:60])
            contenu = str(resultat)

        resultats.append({
            "type": "tool_result",
            "tool_use_id": bloc.id,
            "content": contenu,
        })

        if nom in ("remember", "forget", "changer_personnalite"):
            _refaire_systeme(memoire.charger())

    return resultats


def repondre(historique):
    """Interroge Claude et boucle sur les appels d'outils jusqu'a la reponse.

    Pour les outils lents, prononce un accuse de reception en parallele. Pour
    les outils a confirmation, prononce l'annonce et renvoie SENTINEL_CONFIRM
    (la suite est geree par traiter, qui capture la reponse oui/non).
    """
    from core.llm import llm
    fournisseur = llm()
    if not fournisseur.disponible():
        mode = config.reglage("mode", "cloud")
        if mode == "local":
            return ("Le modele local (Ollama) n'est pas joignable. Verifie qu'Ollama "
                    "tourne et que le modele est telecharge.")
        return "Ma cle Claude n'est pas configuree."

    fil_accuse = None
    accuse_donne = False

    while True:
        if _INTERRUPTION.is_set():
            if fil_accuse:
                fil_accuse.join(timeout=2)
            return ""
        try:
            reponse = fournisseur.repondre(
                systeme_courant(), historique,
                registre.schemas_api(local_seulement=(fournisseur.nom == "Ollama")))
        except Exception as e:
            print(f"  [{fournisseur.nom}] erreur : {e}")
            LOG.exception("appel LLM en echec")
            return "Je n'arrive pas a joindre le modele pour le moment."

        if reponse.stop_reason == "tool_use":
            _hud("etat", "reflexion")
            noms = [b.name for b in reponse.content
                    if getattr(b, "type", None) == "tool_use"]
            if (not accuse_donne and not _INTERRUPTION.is_set()
                    and any(n in registre.noms_lents() for n in noms)):
                accuse_donne = True
                _hud("etat", "parole")
                fil_accuse = threading.Thread(
                    target=dire, args=(registre.phrase_attente(noms),), daemon=True)
                fil_accuse.start()

            historique.append({"role": "assistant", "content": reponse.content})
            resultats = _executer_outils(reponse.content)
            historique.append({"role": "user", "content": resultats})

            annonce = registre.annonce_en_attente()
            if annonce:
                if fil_accuse:
                    fil_accuse.join()
                _hud("etat", "parole")
                phrase = annonce + " Tu confirmes ?"
                # Pour un outil N2, rappeler qu'on peut memoriser l'autorisation.
                if registre.niveau(registre.nom_en_attente() or "") == "N2":
                    phrase += " Tu peux dire oui, toujours."
                if not _INTERRUPTION.is_set():
                    dire(phrase, interruptible=False)
                return SENTINEL_CONFIRM
            continue

        # Reponse finale. On attend la fin de l'accuse pour ne pas parler dessus.
        if fil_accuse:
            fil_accuse.join()
        texte = " ".join(
            b.text for b in reponse.content if getattr(b, "type", None) == "text"
        ).strip()
        historique.append({"role": "assistant", "content": texte})
        _hud("etat", "parole")
        if texte and not _INTERRUPTION.is_set():
            dire(texte)
        return texte


# ---------------------------------------------------------------- whisper


def _ajouter_dll_nvidia():
    """Rend les DLL cuBLAS et cuDNN visibles pour faster-whisper (Windows/Linux)."""
    if plateforme.EST_MAC:
        return                      # pas de CUDA sur Mac : rien a rendre visible
    racines = []
    try:
        import nvidia
        racines = [Path(p) for p in getattr(nvidia, "__path__", [])]
    except ImportError:
        pass

    if not racines:
        import sysconfig
        base = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
        if base.exists():
            racines = [base]

    dossiers = []
    for racine in racines:
        dossiers.extend(racine.glob("*/bin"))
        dossiers.extend(racine.glob("*/lib"))

    for dossier in dossiers:
        chemin = str(dossier)
        if chemin not in os.environ["PATH"]:
            os.environ["PATH"] = chemin + os.pathsep + os.environ["PATH"]
        try:
            os.add_dll_directory(chemin)
        except (OSError, AttributeError):
            pass


def charger_whisper():
    """Charge Whisper sur GPU si possible, sinon sur CPU.

    Sur Mac, CTranslate2 (moteur de faster-whisper) ne gere pas Metal : on va
    directement au CPU, tres correct sur Apple Silicon en int8. Inutile donc
    d'afficher un message d'echec CUDA qui inquiete pour rien.
    """
    _ajouter_dll_nvidia()

    accelerateur, precision = plateforme.accelerateur_whisper()
    if accelerateur == "cpu":
        puce = "Apple Silicon" if plateforme.est_apple_silicon() else "CPU"
        print(f"Whisper sur {puce} (pas de CUDA sur ce systeme).")
    else:
        try:
            modele = WhisperModel(MODELE_WHISPER, device=accelerateur,
                                  compute_type=precision)
            modele.transcribe(np.zeros(TAUX, dtype=np.float32), language="fr")
            print(f"Whisper {MODELE_WHISPER} sur GPU.")
            return modele
        except Exception as e:
            print(f"GPU indisponible ({type(e).__name__}), bascule sur CPU.")

    for taille in (MODELE_WHISPER, "small"):
        try:
            modele = WhisperModel(taille, device="cpu", compute_type="int8")
            print(f"Whisper {taille} sur CPU.")
            return modele
        except Exception:
            continue

    raise RuntimeError("Impossible de charger Whisper.")


# ---------------------------------------------------------------- principal


def capturer(flux, tampon):
    """Enregistre depuis le micro jusqu'au silence. Renvoie l'audio ou None."""
    morceaux = list(tampon)
    debut = time.time()
    dernier_son = time.time()

    while True:
        bloc, _ = flux.read(BLOC)
        bloc = bloc.flatten()
        morceaux.append(bloc)
        _hud("niveau", _niv_hud(bloc))

        if niveau(bloc) > SEUIL_SILENCE:
            dernier_son = time.time()
        if time.time() - dernier_son > SILENCE_FIN:
            break
        if time.time() - debut > DUREE_MAX:
            print("  (trop long, je coupe)")
            break

    tampon.clear()
    audio = np.concatenate(morceaux)
    return audio if len(audio) >= TAUX * 0.6 else None


def attendre_suite(flux, tampon, duree=DUREE_SUITE):
    """Ecoute quelques secondes apres une reponse, sans mot d'activation.

    Renvoie True si l'utilisateur recommence a parler, False si silence.
    """
    _hud("etat", "ecoute")
    tampon.clear()
    debut = time.time()
    blocs_voix = 0
    while time.time() - debut < duree:
        try:
            bloc, _ = flux.read(BLOC)
        except Exception:
            return False
        bloc = bloc.flatten()
        tampon.append(bloc)
        _hud("niveau", _niv_hud(bloc))
        if niveau(bloc) > SEUIL_PAROLE_SUR:
            blocs_voix += 1
            if blocs_voix >= 3:
                return True
        else:
            blocs_voix = 0
    return False


def repondre_en_ecoutant(historique, flux, reveil, whisper):
    """Repond tout en surveillant le micro (mot d'activation ou ordre d'arret).

    Renvoie (texte, interrompu, relancer).
    """
    _INTERRUPTION.clear()
    resultat = {}

    def travail():
        try:
            resultat["texte"] = repondre(historique)
        except Exception as e:
            resultat["erreur"] = e

    thread = threading.Thread(target=travail, daemon=True)
    thread.start()

    interrompu = False
    relancer = False

    # Detection d'un ordre ("attends", "stop"...) prononce PAR-DESSUS Jarvis. Le micro
    # entend aussi l'enceinte : on suit en continu le niveau de reference (l'echo de
    # Jarvis) et on ne reagit que si tu parles nettement PLUS FORT que cet echo. On
    # transcrit alors seulement TON extrait (pas les 2 s dominees par la voix de Jarvis).
    facteur = float(config.reglage("interruption.facteur", 1.8))
    seuil_min = float(config.reglage("interruption.seuil", SEUIL_PAROLE_SUR))
    blocs_requis = int(config.reglage("interruption.blocs", BLOCS_AVANT_VERIF))
    creux_toleres = int(config.reglage("interruption.creux", BLOCS_CREUX_TOLERES))
    debug = bool(config.reglage("interruption.debug", False))

    base = None            # niveau moyen de l'echo de Jarvis (suivi en continu)
    tampon = []            # audio de TA parole par-dessus
    blocs_sur = 0
    creux = 0              # blocs faibles consecutifs, toleres jusqu'a un seuil
    derniere_verif = 0.0

    while thread.is_alive():
        # Pendant une capture musicale, l'outil prend le micro (flux stoppe) : on ne
        # lit pas flux (sinon read leve), mais on RESTE dans la boucle pour ne pas
        # declencher le join anticipe -> la reponse pourra bien etre dite ensuite.
        if _CAPTURE_MUSIQUE.is_set():
            time.sleep(0.05)
            continue
        try:
            bloc, _ = flux.read(BLOC)
        except Exception:
            if _CAPTURE_MUSIQUE.is_set():
                time.sleep(0.05)
                continue
            break
        bloc = bloc.flatten()
        _hud("niveau", _niv_hud(bloc))

        # On ne surveille l'interruption QUE pendant que Jarvis parle vraiment.
        # Pendant qu'il reflechit (appel LLM, outils), on ne coupe rien : la reponse
        # ne peut donc pas etre "perdue" par une fausse detection avant d'etre dite.
        if not _PARLE.is_set():
            base = None
            blocs_sur = 0
            creux = 0
            tampon = []
            continue

        # voie 1 : le mot d'activation
        scores = reveil.predict((bloc * 32767).astype(np.int16))
        score_reveil = max(scores.values())
        if debug and score_reveil > 0.2:
            print(f"  [micro debug] mot-cle par-dessus : {score_reveil:.2f} "
                  f"(seuil {SEUIL_INTERRUPTION})")
        if score_reveil >= SEUIL_INTERRUPTION:
            couper_parole()
            interrompu, relancer = True, True
            print("  [micro] Je me tais.")
            break

        # voie 2 : un ordre d'arret prononce par-dessus
        niv = niveau(bloc)
        if base is None:
            base = niv
        seuil_sur = max(seuil_min, base * facteur)
        base = 0.97 * base + 0.03 * niv    # suit lentement l'echo de Jarvis

        if niv > seuil_sur:
            tampon.append(bloc)
            blocs_sur += 1
            creux = 0
        else:
            if blocs_sur:
                creux += 1
                if creux <= creux_toleres:
                    tampon.append(bloc)    # micro-coupure : on garde le fil
                else:
                    if blocs_sur < blocs_requis:
                        tampon = []        # trop court : simple bruit, on oublie
                    blocs_sur = 0
                    creux = 0

        # On ne coupe QUE si on reconnait un mot d'arret ("attends", "stop"...)
        # dans ce que tu dis par-dessus. Ainsi Jarvis ne peut jamais se couper
        # lui-meme (sa propre voix n'est pas un mot d'arret) : pas de boucle.
        maintenant = time.time()
        if (blocs_sur >= blocs_requis
                and maintenant - derniere_verif > DELAI_ENTRE_VERIFS):
            derniere_verif = maintenant
            extrait = np.concatenate(tampon[-30:])
            tampon = []
            blocs_sur = 0
            creux = 0
            try:
                segments, _ = whisper.transcribe(extrait, language="fr", beam_size=1,
                                              initial_prompt=AMORCE_WHISPER)
                dit = " ".join(s.text for s in segments).strip()
            except Exception:
                dit = ""
            if debug:
                print(f"  [micro debug] niv={niv:.3f} base={base:.3f} "
                      f"seuil={seuil_sur:.3f} -> entendu={dit!r}")
            categorie = type_arret(dit) if dit else None
            if categorie:
                couper_parole()
                interrompu = True
                relancer = (categorie == "relance")
                action = "Je t'ecoute" if relancer else "Compris"
                print(f"  [micro] {action} : {dit}")
                break

    thread.join(timeout=10)
    reveil.reset()

    if "erreur" in resultat:
        raise resultat["erreur"]

    return resultat.get("texte", ""), interrompu, relancer


def _confirmer(interrompu, relancer, whisper, historique, flux):
    """Capture la reponse oui/non a une demande de confirmation et agit."""
    if interrompu:
        registre.annuler_confirme()
        return "", relancer

    _INTERRUPTION.clear()
    _hud("etat", "ecoute")
    audio_conf = capturer(flux, deque())
    reponse = ""
    if audio_conf is not None:
        seg, _ = whisper.transcribe(audio_conf, language="fr", beam_size=5,
                                initial_prompt=AMORCE_WHISPER)
        reponse = nettoyer(" ".join(s.text for s in seg).strip())
    print(f"  [confirmation] {reponse or '(rien)'}")

    memoriser = _est_toujours(reponse)
    if _est_oui(reponse) or memoriser:
        res = registre.executer_confirme(memoriser=memoriser)
    else:
        registre.annuler_confirme()
        res = "D'accord, j'annule."

    _hud("etat", "parole")
    if res and not _INTERRUPTION.is_set():
        dire(res)
    historique.append({"role": "assistant", "content": res})
    return res, False


def _tronquer(historique):
    if len(historique) > 40:
        del historique[:len(historique) - 40]
        # Claude exige que la conversation commence par un vrai tour utilisateur.
        while historique and not (
            historique[0]["role"] == "user"
            and isinstance(historique[0]["content"], str)
        ):
            historique.pop(0)


def traiter(audio, whisper, historique, flux, reveil):
    """Transcrit, repond, parle. Renvoie True si on doit enchainer (relance)."""
    segments, _ = whisper.transcribe(audio, language="fr", beam_size=5,
                                 initial_prompt=AMORCE_WHISPER)
    question = nettoyer(" ".join(s.text for s in segments).strip())

    if not question or len(question) < 3:
        print("  (rien compris)\n")
        return False

    print(f"  Vous : {question}")
    _hud("dire_vous", question)
    _hud("etat", "reflexion")
    historique.append({"role": "user", "content": question})

    texte, interrompu, relancer = repondre_en_ecoutant(historique, flux, reveil, whisper)

    if texte == SENTINEL_CONFIRM:
        _hud("confirmation", True)
        texte, relancer = _confirmer(interrompu, relancer, whisper, historique, flux)
        _hud("confirmation", False)
    elif not texte:
        texte = "C'est fait."
        if not interrompu:
            _hud("etat", "parole")
            dire(texte)

    _hud("dire_jarvis", texte)
    _afficher_overlay(texte)
    _hud_status()
    print(f"  Jarvis : {texte}\n")
    _tronquer(historique)
    return relancer


def _feedback_geste(geste):
    """Feedback discret quand un geste est reconnu : petit bip + flash HUD. Non bloquant."""
    freq = 1200 if geste == "armement" else 900
    try:
        threading.Thread(target=lambda: bip(freq, 0.05), daemon=True).start()
    except Exception:
        pass
    _hud("outil", "geste", geste)


def _raccourcis_possibles():
    """Vrai si les raccourcis clavier GLOBAUX sont installables sur ce systeme.

    La lib `keyboard` lit le clavier au niveau du pilote : elle exige les droits
    root sur macOS et Linux. Plutot que de faire planter Jarvis (ou d'exiger
    sudo), on saute proprement les raccourcis et on le dit une fois.
    """
    if plateforme.EST_WINDOWS:
        return True
    return getattr(os, "geteuid", lambda: 1)() == 0


_RACCOURCIS_ANNONCES = False


def _annoncer_raccourcis_indispo():
    global _RACCOURCIS_ANNONCES
    if _RACCOURCIS_ANNONCES:
        return
    _RACCOURCIS_ANNONCES = True
    print("Raccourcis clavier globaux desactives : ils demandent les droits root "
          f"sur {plateforme.SYSTEME}. Utilise la voix, le panneau web, ou un "
          "raccourci Automator/Raccourcis (voir TROUBLESHOOTING_MAC.md).")


def _installer_raccourci_gestes():
    """Raccourci clavier global pour basculer les gestes (optionnel, via 'keyboard')."""
    combo = config.reglage("gestes.raccourci", "ctrl+alt+g")
    if not combo:
        return
    if not _raccourcis_possibles():
        _annoncer_raccourcis_indispo()
        return
    try:
        import keyboard
    except Exception:
        return  # lib absente : le raccourci est optionnel, on continue sans
    from core import gestes

    def _toggle():
        print(gestes.arreter() if gestes.actif() else gestes.demarrer())

    try:
        keyboard.add_hotkey(combo, _toggle)
        print(f"Raccourci gestes : {combo}")
    except Exception:
        LOG.exception("gestes: raccourci clavier")


def _installer_raccourci_micro():
    """Raccourci clavier global pour couper/reactiver le wake word (mute micro)."""
    combo = config.reglage("audio.raccourci_mute", "ctrl+alt+m")
    if not combo:
        return
    if not _raccourcis_possibles():
        _annoncer_raccourcis_indispo()
        return
    try:
        import keyboard
    except Exception:
        return  # lib optionnelle
    try:
        keyboard.add_hotkey(combo, basculer_micro)
        print(f"Raccourci mute micro : {combo}")
    except Exception:
        LOG.exception("micro: raccourci clavier")


def _entrees_audio():
    """[(index, nom)] des peripheriques d'ENTREE, ou [] si aucun."""
    try:
        return [(i, d.get("name", "?")) for i, d in enumerate(sd.query_devices())
                if d.get("max_input_channels", 0) > 0]
    except Exception:
        return []


def _ouvrir_micro():
    """Ouvre le flux du micro, ou explique precisement ce qui manque.

    PortAudio leve « Error querying device -1 » quand AUCUNE entree n'existe :
    trace illisible pour un message qui veut juste dire « pas de micro ». Les
    deux causes sur Mac sont l'autorisation Microphone non accordee au terminal,
    et le Mac mini / Mac Studio, qui n'ont pas de micro integre du tout.
    """
    entrees = _entrees_audio()
    if not entrees:
        print("\nAucun peripherique d'ENTREE audio detecte : Jarvis ne peut pas ecouter.")
        if plateforme.EST_MAC:
            print("  1. Autorise le Microphone pour ton terminal : Reglages Systeme >")
            print("     Confidentialite et securite > Microphone, puis RELANCE le terminal.")
            print("  2. Les Mac mini et Mac Studio n'ont pas de micro integre : branche")
            print("     un micro USB, un casque, ou connecte des AirPods.")
            print("  Detail : TROUBLESHOOTING_MAC.md")
        else:
            print("  Branche un micro, puis relance.")
        raise SystemExit(1)

    try:
        return sd.InputStream(samplerate=TAUX, channels=1, dtype="float32",
                              device=MICRO, blocksize=BLOC)
    except Exception as e:
        print(f"\nImpossible d'ouvrir le micro configure (audio.micro = {MICRO!r}) : {e}")
        print("Entrees disponibles :")
        for i, nom in entrees:
            print(f"  {i} : {nom}")
        print("Mets l'index voulu dans config.yaml (audio.micro), ou null pour "
              "laisser le systeme choisir.")
        raise SystemExit(1)


def main():
    print("Chargement des modeles...")

    registre.charger_outils()

    # Serveurs MCP externes : leurs outils rejoignent le registre, a confirmation.
    try:
        from core import mcp_externe
        resume = mcp_externe.charger()
        if resume:
            print(f"MCP externe : {resume}")
        import atexit
        atexit.register(mcp_externe.arreter)
    except Exception:
        LOG.exception("mcp externe: chargement")

    voix.definir_parleur(dire)

    reveil = WakeModel(wakeword_model_paths=[str(
        Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
    )])

    whisper = charger_whisper()

    # Les appels telephoniques reutilisent ce Whisper pour transcrire les reponses.
    from tools.appels import definir_transcripteur
    definir_transcripteur(lambda chemin: " ".join(
        s.text for s in whisper.transcribe(chemin, language="fr", beam_size=5,
                           initial_prompt=AMORCE_WHISPER)[0]).strip())
    # V2 (conversation temps reel) : transcription d'un tableau audio (16kHz float32).
    from tools.appel_direct import definir_transcripteur_direct
    definir_transcripteur_direct(lambda audio: " ".join(
        s.text for s in whisper.transcribe(audio, language="fr", beam_size=1,
                           initial_prompt=AMORCE_WHISPER)[0]).strip())

    charger_pieces_hue()
    allumer_si_nuit()

    from tools.presence import demarrer_presence
    demarrer_presence()

    from tools.discord_bot import demarrer_discord
    demarrer_discord()

    from tools.instagram import demarrer_refresh_instagram
    demarrer_refresh_instagram()

    # Serveur web unifie (pont iPhone + webhook Twilio + panneau + gestes en loopback).
    if (config.reglage("serveur.actif", False) or config.reglage("pont_iphone.actif", False)
            or config.reglage("gestes.actif", False) or config.reglage("cockpit.actif", False)):
        from core.serveur import demarrer as demarrer_serveur_web
        demarrer_serveur_web()
        # Cockpit : ouvre l'app web en fenetre dediee (--app) sur l'ecran choisi.
        if config.reglage("cockpit.actif", False):
            try:
                from core import cockpit
                threading.Thread(target=cockpit.ouvrir_fenetre, daemon=True).start()
            except Exception:
                LOG.exception("cockpit: ouverture fenetre")

    # Controle par gestes (webcam, sous-process isole 3.11) : hooks + demarrage optionnel.
    try:
        import atexit
        from core import gestes
        gestes.definir_hooks(couper_tts=couper_parole, feedback=_feedback_geste)
        atexit.register(gestes.arreter)          # libere la webcam a la sortie
        if config.reglage("gestes.actif", False):
            print(gestes.demarrer())
        _installer_raccourci_gestes()
        _installer_raccourci_micro()
    except Exception:
        LOG.exception("gestes: initialisation")

    from core.llm import llm
    _fournisseur = llm()
    print(f"Mode : {config.reglage('mode', 'cloud')} — LLM {_fournisseur.nom}, "
          f"TTS {__import__('core.tts', fromlist=['tts']).tts().nom}.")
    if not _fournisseur.disponible():
        if config.reglage("mode", "cloud") == "local":
            print("ATTENTION : Ollama injoignable. Lance 'ollama serve' et verifie le "
                  "modele (config ollama.modele).")
        else:
            print("ATTENTION : aucune cle Claude dans config.yaml (anthropic.cle). "
                  "L'assistant ne pourra pas repondre.")

    _demarrer_hud()
    _modele_hud = getattr(_fournisseur, "modele", "")
    _hud("config", f"{_fournisseur.nom} · {_modele_hud}" if _modele_hud
         else _fournisseur.nom, f"whisper {MODELE_WHISPER}")
    _hud_status()
    try:                                   # part Hermes (tokens) au HUD, en fond
        from tools import deleguer_a_hermes as _dh
        threading.Thread(target=_dh.rafraichir_hud, daemon=True).start()
    except Exception:
        pass

    faits = memoire.charger()
    if faits:
        print(f"Memoire : {len(faits)} information(s).")
    _refaire_systeme(faits)
    historique = []

    flux = _ouvrir_micro()
    flux.start()

    # Reconnaissance musicale : capture depuis le micro en SUSPENDANT proprement le
    # wake word (micro partage). Un bip signale l'ecoute AVANT la capture, pour ne
    # pas polluer l'empreinte envoyee a Shazam.
    try:
        from tools import musique as _musique

        def _capturer_musique(secondes):
            # Signale la capture : la boucle de surveillance (thread principal) lache
            # flux AVANT qu'on le stoppe, sinon son flux.read planterait et couperait
            # la reponse a mi-chemin.
            _CAPTURE_MUSIQUE.set()
            time.sleep(0.15)
            actif = flux.active
            try:
                flux.stop()
            except Exception:
                pass
            try:
                bip(880, 0.12)
                audio = sd.rec(int(secondes * TAUX), samplerate=TAUX, channels=1,
                               dtype="float32", device=MICRO)
                sd.wait()
                return audio.reshape(-1), TAUX
            finally:
                try:
                    if actif:
                        flux.start()
                except Exception:
                    pass
                _CAPTURE_MUSIQUE.clear()

        _musique.definir_capture_micro(_capturer_musique)
    except Exception:
        LOG.exception("musique: hook capture micro")

    # Overlay de reponses (fenetre flottante) : demarre masque, cout nul au
    # repos ; pilotable par config overlay.* et a la voix ("affiche les reponses").
    if _overlay is not None and config.reglage("overlay.actif", True):
        try:
            _overlay.demarrer({
                "actif": True,
                "muet": config.reglage("overlay.muet_visuel", False),
                "ecran": config.reglage("overlay.ecran", 1),
                "coin": config.reglage("overlay.coin", "bas-droite"),
                "opacite": config.reglage("overlay.opacite", 0.92),
                "largeur": config.reglage("overlay.largeur", 420),
                "duree_min": config.reglage("overlay.duree_min", 4.0),
                "duree_max": config.reglage("overlay.duree_max", 14.0),
                "marge": config.reglage("overlay.marge", 24),
                "exclure_obs": config.reglage("overlay.exclure_obs", True),
            })
        except Exception:
            LOG.exception("overlay: demarrage")

    print('\nPret. Dites "Hey Jarvis". Ctrl+C pour quitter.\n')
    print('Vous pouvez le couper en redisant "Hey Jarvis" pendant qu\'il parle.\n')

    tampon = deque(maxlen=6)
    enchainer = False

    try:
        while True:
            suite = enchainer
            if not enchainer:
                bloc, _ = flux.read(BLOC)
                bloc = bloc.flatten()
                tampon.append(bloc)

                if _MICRO_MUET.is_set():        # wake word coupe (raccourci mute)
                    _hud("etat", "muet")
                    continue

                _hud("etat", "veille")
                _hud("niveau", _niv_hud(bloc))

                scores = reveil.predict((bloc * 32767).astype(np.int16))
                if max(scores.values()) < SEUIL_REVEIL:
                    continue
                reveil.reset()

            enchainer = False
            _hud("etat", "ecoute")
            if not suite:
                print("  [micro] Oui ?")
                bip()

            audio = capturer(flux, tampon)
            if audio is None:
                print("  (rien entendu)\n")
                continue

            if traiter(audio, whisper, historique, flux, reveil):
                enchainer = True
                continue

            print(f"  [micro] J'ecoute encore {int(DUREE_SUITE)} s...")
            enchainer = attendre_suite(flux, tampon)
            if not enchainer:
                _hud("etat", "veille")

    except KeyboardInterrupt:
        print("\nAu revoir.")
    finally:
        couper_parole()
        flux.stop()
        flux.close()


if __name__ == "__main__":
    main()
