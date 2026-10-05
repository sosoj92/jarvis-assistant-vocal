"""Controle d'OBS Studio via le WebSocket integre (OBS 28+, port 4455, protocole v5).

Utilise obsws-python (client v5). Mot de passe dans config.yaml (obs.mot_de_passe :
OBS -> Outils -> Parametres du serveur WebSocket).
"""
import contextlib
import io

from core.config import reglage
from core.registre import outil
from core.util import sans_accents


def _client():
    """Ouvre une connexion au WebSocket d'OBS. Leve si OBS/WebSocket indisponible."""
    import obsws_python as obs
    # obsws imprime une traceback sur stderr quand la connexion echoue : on la tait
    # (l'outil renvoie deja un message clair a l'utilisateur).
    with contextlib.redirect_stderr(io.StringIO()):
        return obs.ReqClient(
            host=reglage("obs.host", "localhost"),
            port=reglage("obs.port", 4455),
            password=reglage("obs.mot_de_passe", ""),
            timeout=3,
        )


def _erreur_obs(e):
    return (f"OBS ne repond pas ({e}). Verifie qu'OBS est lance et que le serveur "
            "WebSocket est active.")


# Camera, micro et ecran : rien d'OBS n'est expose au MCP sauf l'arret d'un
# enregistrement. Lancer un direct public est une action externe difficile a
# annuler -> N3 (confirmation a chaque fois, jamais a distance).
@outil(
    nom="start_stream",
    description="Demarre le direct (streaming) dans OBS. Pour 'lance le stream', "
                "'demarre le direct', 'on stream'.",
    confirmation=True,
    annonce=lambda args: "Je vais lancer le direct public sur OBS.",
)
def start_stream() -> str:
    try:
        _client().start_stream()
        return "Direct lance."
    except Exception as e:
        return _erreur_obs(e)


@outil(
    nom="stop_stream",
    description="Coupe le direct (streaming) dans OBS. Pour 'coupe le stream', "
                "'arrete le direct'.",
    confirmation=True,
    annonce=lambda args: "Je vais couper le direct.",
)
def stop_stream() -> str:
    try:
        _client().stop_stream()
        return "Direct coupe."
    except Exception as e:
        return _erreur_obs(e)


@outil(
    nom="start_record",
    description="Demarre l'enregistrement local dans OBS. Pour 'lance "
                "l'enregistrement', 'enregistre'.",
    confirmation=True,
    annonce=lambda args: "Je vais lancer l'enregistrement OBS.",
)
def start_record() -> str:
    try:
        _client().start_record()
        return "Enregistrement lance."
    except Exception as e:
        return _erreur_obs(e)


@outil(
    nom="stop_record",
    mcp_expose=True,
    description="Arrete l'enregistrement local dans OBS. Pour 'arrete "
                "l'enregistrement', 'stop l'enregistrement'.",
)
def stop_record() -> str:
    try:
        _client().stop_record()
        return "Enregistrement arrete."
    except Exception as e:
        return _erreur_obs(e)


@outil(
    nom="switch_scene",
    description="Change la scene active dans OBS. La liste des scenes est recuperee "
                "dynamiquement. Pour 'scene jeu', 'passe sur la scene pause', 'mets "
                "la scene webcam'.",
    parametres={
        "type": "object",
        "properties": {
            "nom": {"type": "string", "description": "Nom (ou partie du nom) de la scene."}
        },
        "required": ["nom"],
    },
)
def switch_scene(nom: str) -> str:
    try:
        cl = _client()
        reponse = cl.get_scene_list()
        scenes = [s.get("sceneName", "") for s in reponse.scenes if isinstance(s, dict)]
        cible = sans_accents(nom.strip())
        choix = None
        for s in scenes:
            if sans_accents(s) == cible:
                choix = s
                break
        if choix is None:
            for s in scenes:
                if cible in sans_accents(s) or sans_accents(s) in cible:
                    choix = s
                    break
        if choix is None:
            return f"Scene inconnue : {nom}. Scenes disponibles : {', '.join(scenes)}."
        cl.set_current_program_scene(choix)
        return f"Scene {choix}."
    except Exception as e:
        return _erreur_obs(e)


@outil(
    nom="save_replay",
    description="Sauvegarde le replay buffer (les dernieres secondes de jeu). Pour "
                "'clippe ca', 'sauvegarde le replay', 'garde ce moment'. Si le buffer "
                "n'est pas actif, le demarre et previent l'utilisateur.",
)
def save_replay() -> str:
    try:
        cl = _client()
        statut = cl.get_replay_buffer_status()
        if not getattr(statut, "output_active", False):
            cl.start_replay_buffer()
            return ("Le buffer de replay n'etait pas actif, je viens de le demarrer. "
                    "Redemande dans quelques secondes pour sauvegarder le moment.")
        cl.save_replay_buffer()
        return "Replay sauvegarde."
    except Exception as e:
        return _erreur_obs(e)
