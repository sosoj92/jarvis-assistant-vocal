"""Signal Matin - journal personnel A4 genere localement par Jarvis.

Le paquet garde trois couches distinctes : les sources collectent, le modele
normalise et valide, puis le renderer compose l'edition sans appeler d'API.
"""

from .models import DensityMode, MorningEdition
from .normalizer import normaliser_edition

__all__ = ["DensityMode", "MorningEdition", "normaliser_edition"]
