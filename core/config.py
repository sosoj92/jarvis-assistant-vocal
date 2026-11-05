"""Chargement de config.yaml : tous les secrets et reglages, au meme endroit.

Aucune cle en dur dans le code : tout passe par reglage("section.cle").
Le fichier config.yaml n'est pas versionne (voir .gitignore).

definir() ne reecrit jamais le fichier depuis le seul cache : il relit le disque,
refuse d'ecrire si le YAML est illisible (sinon tous les secrets seraient perdus)
et remplace le fichier de facon atomique (fichier temporaire puis os.replace).
"""
import copy
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import yaml

LOG = logging.getLogger("jarvis")

_CONFIG = None
# Echec de lecture au demarrage (type et position seulement, jamais le contenu).
_ERREUR_CHARGEMENT = None
_VERROU = threading.RLock()
FICHIER = Path(__file__).resolve().parent.parent / "config.yaml"


class ConfigIllisible(RuntimeError):
    """config.yaml existe mais ne peut pas etre lu : aucune ecriture n'est faite."""


def _decrire(exc):
    """Type de l'erreur et ligne YAML, sans citer le fichier (il peut contenir une cle)."""
    marque = getattr(exc, "problem_mark", None)
    if marque is not None:
        return f"{type(exc).__name__} ligne {marque.line + 1}, colonne {marque.column + 1}"
    return type(exc).__name__


def _lire_disque():
    """Contenu actuel de FICHIER ; None s'il n'existe pas. Leve ConfigIllisible sinon."""
    try:
        donnees = yaml.safe_load(FICHIER.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as e:
        raise ConfigIllisible(f"{FICHIER.name} illisible ({_decrire(e)})") from e
    if donnees is None:
        return {}
    if not isinstance(donnees, dict):
        raise ConfigIllisible(
            f"{FICHIER.name} illisible (racine {type(donnees).__name__}, dictionnaire attendu)")
    return donnees


def _charger():
    global _CONFIG, _ERREUR_CHARGEMENT
    if _CONFIG is None:
        with _VERROU:
            if _CONFIG is None:
                try:
                    _CONFIG = _lire_disque() or {}
                except ConfigIllisible as e:
                    # Demarrage sur les valeurs par defaut ; definir() refusera
                    # d'ecrire tant que le fichier restera illisible.
                    _ERREUR_CHARGEMENT = str(e)
                    LOG.error("%s : reglages par defaut en attendant", e)
                    _CONFIG = {}
    return _CONFIG


def reglage(chemin, defaut=None):
    """Lit une valeur imbriquee, ex. reglage("hue.pont").

    Renvoie `defaut` si le chemin n'existe pas ; renvoie la valeur telle quelle
    si elle vaut explicitement null (ex. audio.haut_parleur: null -> None).
    """
    valeur = _charger()
    for cle in chemin.split("."):
        if not isinstance(valeur, dict) or cle not in valeur:
            return defaut
        valeur = valeur[cle]
    return valeur


def _poser(conf, cles, valeur):
    noeud = conf
    for cle in cles[:-1]:
        noeud = noeud.setdefault(cle, {})
    noeud[cles[-1]] = valeur


def _ecrire(texte):
    """Remplace FICHIER d'un coup : un arret en pleine ecriture laisse l'ancien intact."""
    descripteur, temporaire = tempfile.mkstemp(
        dir=FICHIER.parent, prefix=f".{FICHIER.name}.", suffix=".tmp")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            f.write(texte)
            f.flush()
            os.fsync(f.fileno())
        if os.name != "nt" and FICHIER.exists():
            try:
                shutil.copymode(FICHIER, temporaire)    # garde les droits d'origine
            except OSError:
                pass
        for essai in range(5):
            try:
                os.replace(temporaire, FICHIER)
                return
            except PermissionError:
                # Sous Windows, un lecteur qui tient le fichier ouvert bloque
                # le remplacement un court instant.
                if essai == 4:
                    raise
                time.sleep(0.1)
    finally:
        try:
            os.unlink(temporaire)
        except OSError:
            pass


def definir(chemin, valeur):
    """Modifie une valeur (ex. 'assistant.personnalite') et reecrit config.yaml.

    Part du fichier relu sur disque, pas du cache (perime si le fichier a ete
    edite depuis le demarrage, vide si sa lecture avait echoue). Leve
    ConfigIllisible sans rien ecrire si le YAML ne peut pas etre lu.
    """
    cles = chemin.split(".")
    with _VERROU:
        conf = _charger()
        frais = _lire_disque()
        if frais is None:       # fichier absent (premiere installation) : on part du cache
            frais = copy.deepcopy(conf)
        _poser(frais, cles, valeur)
        # Serialise avant d'ouvrir quoi que ce soit : une valeur refusee ne touche pas le fichier.
        _ecrire(yaml.safe_dump(frais, allow_unicode=True, sort_keys=False))
        # Mise a jour en place : l'agent du bureau partage ce dictionnaire.
        _poser(conf, cles, valeur)
