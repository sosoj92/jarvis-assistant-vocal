"""Configuration commune des tests.

Aucun test n'ecrit dans le vrai logs/jarvis.log (journal d'audit prive) : le
logger « jarvis » est preconfigure ici, avec les memes niveau et propagation que
core.journal.obtenir(), mais sans FileHandler. obtenir() le renvoie alors tel
quel au lieu d'ouvrir le fichier. assertLogs("jarvis") fonctionne toujours.
"""
import logging

from core import journal

_LOG = logging.getLogger("jarvis")
_LOG.setLevel(logging.INFO)
_LOG.handlers.clear()
_LOG.addHandler(logging.NullHandler())
_LOG.propagate = False
journal._LOG = _LOG
