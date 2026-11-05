"""Phrases que Whisper invente sur du silence ou du bruit de fond.

Partage par toutes les voies vocales (micro du PC, satellites, agent Windows) : une
telle « phrase » ne doit jamais etre traitee comme une demande.
"""
import re

from core.util import sans_accents

# Marqueurs propres aux hallucinations : la phrase est ecartee ou qu'ils apparaissent.
HALLUCINATIONS = (
    "amara.org", "sous-titres realises", "sous titres realises", "sous-titrage st",
    "societe radio-canada", "merci d'avoir regarde", "n'oubliez pas de vous abonner",
)

# Motifs generiques : une vraie demande peut les contenir (« active les
# sous-titres », « passe a la prochaine video »). Ils n'ecartent donc la phrase
# que lorsqu'elle commence par eux.
DEBUTS_HALLUCINATIONS = (
    "sous-titres", "sous titres", "sous-titrage", "abonnez-vous", "abonnez vous",
    "a la prochaine video",
)

# Mots entiers (« sous-titrage st' 501 » oui, « sous-titrage stp » non) ; les
# debuts sont cherches apres la ponctuation et les espaces de tete.
_MARQUEURS = re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(map(re.escape, HALLUCINATIONS)))
_DEBUTS = re.compile(r"^[\W_]*(?:%s)(?!\w)" % "|".join(map(re.escape, DEBUTS_HALLUCINATIONS)))


def est_hallucination(texte):
    """Vrai si la transcription ressemble a une hallucination connue de Whisper."""
    plat = sans_accents(str(texte or ""))
    return bool(_MARQUEURS.search(plat) or _DEBUTS.match(plat))
