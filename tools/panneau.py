"""Ouvre le panneau de configuration web local dans le navigateur.

Commande vocale : « ouvre le tableau de configuration », « ouvre le tableau de
bord », « ouvre le panneau », « montre la config ». C'est du Jarvis pur (action
locale) : lance le navigateur par défaut sur http://localhost:<port>/panneau.

N1 (sans danger) et **non exposé au MCP** : ouvrir une fenêtre sur la machine est
une action physique locale — jamais à distance ni via Hermes.
"""
from core import serveur
from core.ouvrir_web import ouvrir_url
from core.registre import outil


@outil(
    nom="ouvrir_panneau",
    description="Ouvre le panneau de configuration web local (onglets Modèles, "
                "Réglages, État, Permissions) dans le navigateur, sur ce PC. Pour "
                "« ouvre le tableau de configuration », « ouvre le tableau de bord », "
                "« ouvre le panneau », « montre-moi la configuration ».",
    mcp_expose=False,
)
def ouvrir_panneau() -> str:
    port = serveur._port()
    url = f"http://localhost:{port}/panneau"
    if not serveur._port_ouvert(port):
        return ("Le serveur local n'est pas démarré, je ne peux pas ouvrir le "
                "panneau. Active « serveur.actif » (ou le pont iPhone / les gestes) "
                "dans config.yaml, puis redémarre-moi.")
    try:
        ouvrir_url(url)
    except Exception as e:
        return f"Je n'ai pas réussi à ouvrir le navigateur ({str(e)[:80]}). Va sur {url}."
    return f"J'ouvre le panneau de configuration dans ton navigateur ({url})."
