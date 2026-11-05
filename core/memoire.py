"""Memoire long terme structuree, dans memory.json.

Structure : { "preferences": {}, "people": {}, "projects": {}, "facts": [] }
Fichier volontairement lisible et editable a la main.

Migre automatiquement l'ancien memoire.json (liste de faits) au premier chargement.

Les copies de securite (avant un forget, ou avant de remplacer un fichier
illisible) vont dans logs/, ignore par git : la memoire est personnelle.
"""
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

LOG = logging.getLogger("jarvis")

RACINE = Path(__file__).resolve().parent.parent
FICHIER = RACINE / "memory.json"
ANCIEN = RACINE / "memoire.json"

_CLES = ("preferences", "people", "projects", "facts")

# Une seule sequence charger -> modifier -> sauver a la fois (voix, satellites, pont).
VERROU = threading.RLock()


def _lire(chemin):
    # utf-8-sig : un BOM (ajoute par certains outils Windows) ne rend pas le fichier illisible.
    return json.loads(chemin.read_text(encoding="utf-8-sig"))


def _vide():
    return {"preferences": {}, "people": {}, "projects": {}, "facts": []}


def _normaliser(donnees):
    """Garantit les 4 cles avec le bon type."""
    m = _vide()
    if isinstance(donnees, dict):
        for cle in ("preferences", "people", "projects"):
            v = donnees.get(cle)
            if isinstance(v, dict):
                m[cle] = v
        faits = donnees.get("facts")
        if isinstance(faits, list):
            m["facts"] = faits
    return m


def _migrer_ancien():
    """Recupere les faits de l'ancien memoire.json, s'il existe."""
    if ANCIEN.exists():
        try:
            faits = _lire(ANCIEN).get("faits", [])
            if faits:
                return {"facts": list(faits)}
        except (ValueError, OSError):
            pass
    return {}


def charger():
    """Lit la memoire structuree. Migre l'ancien format au besoin.

    Un fichier illisible donne une memoire vide, sans planter ; sauver() le
    copie dans logs/ avant de le remplacer."""
    with VERROU:
        if FICHIER.exists():
            try:
                return _normaliser(_lire(FICHIER))
            except (ValueError, OSError) as e:     # ValueError : JSON ou encodage invalide
                LOG.warning("memory.json illisible (%s) : memoire vide en attendant",
                            type(e).__name__)
                return _vide()
        memoire = _normaliser(_migrer_ancien())
        if any(memoire[c] for c in _CLES):
            sauver(memoire)     # persiste la migration
        return memoire


def _illisible():
    """Vrai si memory.json existe mais ne se relit pas en dictionnaire."""
    try:
        return not isinstance(_lire(FICHIER), dict)
    except FileNotFoundError:
        return False
    except (ValueError, OSError):
        return True


def _copier(nom):
    """Copie memory.json dans logs/<nom> ; leve OSError si la copie echoue."""
    dossier = FICHIER.parent / "logs"
    dossier.mkdir(exist_ok=True)
    copie = dossier / nom
    shutil.copy2(FICHIER, copie)
    return copie


def sauvegarder():
    """Copie memory.json dans logs/memory.json.bak (avant un effacement)."""
    with VERROU:
        if FICHIER.exists():
            return _copier("memory.json.bak")
    return None


def _ecrire(texte):
    """Remplace memory.json d'un coup : un arret en pleine ecriture laisse l'ancien intact."""
    descripteur, temporaire = tempfile.mkstemp(
        dir=FICHIER.parent, prefix=f".{FICHIER.name}.", suffix=".tmp")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            f.write(texte)
            f.flush()
            os.fsync(f.fileno())
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


def sauver(memoire):
    texte = json.dumps(_normaliser(memoire), ensure_ascii=False, indent=2)
    with VERROU:
        if _illisible():
            # Sans cette copie, le prochain remember automatique effacerait
            # toute la memoire sans retour possible.
            copie = _copier(f"memory.json.corrompu-{time.strftime('%Y%m%d-%H%M%S')}")
            LOG.warning("memory.json illisible : copie conservee dans logs/%s", copie.name)
        _ecrire(texte)


def texte_pour_systeme(memoire):
    """Resume la memoire pour l'injecter dans la consigne systeme."""
    parties = []
    if memoire.get("preferences"):
        parties.append("Preferences : " + " ; ".join(
            f"{k} = {v}" for k, v in memoire["preferences"].items()))
    if memoire.get("people"):
        parties.append("Personnes : " + " ; ".join(
            f"{k} = {v}" for k, v in memoire["people"].items()))
    if memoire.get("projects"):
        parties.append("Projets : " + " ; ".join(
            f"{k} = {v}" for k, v in memoire["projects"].items()))
    if memoire.get("facts"):
        parties.append("Faits : " + " ; ".join(memoire["facts"]))
    if not parties:
        return ""
    return ("\n\nCe que tu sais deja sur l'utilisateur "
            "(ne le recite pas spontanement, sers-t'en) :\n" + "\n".join(parties))
