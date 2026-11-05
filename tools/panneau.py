"""Ouvre le panneau de configuration web local dans le navigateur.

Commande vocale : « ouvre le tableau de configuration », « ouvre le tableau de
bord », « ouvre le panneau », « montre la config ». C'est du Jarvis pur (action
locale) : lance le navigateur par défaut sur http://localhost:<port>/panneau.

N1 (sans danger) et **non exposé au MCP** : Hermes ne peut pas l'appeler. Il reste
appelable depuis un satellite (cuisine, bureau…), mais le panneau n'est servi qu'en
local sur la machine qui fait tourner Jarvis. En topologie « serveur sans
périphériques » (poste_principal.serveur_sans_peripheriques), il n'ouvre donc rien
sur le serveur et dit honnêtement où se trouve le panneau.
"""
from core import serveur
from core.config import reglage
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
    if (reglage("poste_principal.actif", False)
            and reglage("poste_principal.serveur_sans_peripheriques", False)):
        # Jarvis tourne sur un serveur sans écran : ouvrir un navigateur ici ne
        # montrerait rien à personne, et le panneau refuse tout accès non local.
        return ("Le panneau de configuration est sur le serveur, pas sur ce poste : "
                "il ne s'ouvre qu'en local là-bas, par le bureau à distance ou un "
                f"tunnel SSH vers 127.0.0.1:{port}. Je n'ouvre rien ici.")
    if not serveur._port_ouvert(port):
        return ("Le serveur local n'est pas démarré, je ne peux pas ouvrir le "
                "panneau. Active « serveur.actif » (ou le pont iPhone / les gestes) "
                "dans config.yaml, puis redémarre-moi.")
    try:
        ouvrir_url(url)
    except Exception as e:
        return f"Je n'ai pas réussi à ouvrir le navigateur ({str(e)[:80]}). Va sur {url}."
    return f"J'ouvre le panneau de configuration dans ton navigateur ({url})."
