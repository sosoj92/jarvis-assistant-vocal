"""Reconnaitre une requete vraiment locale (panneau, cockpit, gestes, HUD).

Trois conditions, toutes necessaires :
  - la socket vient du poste lui-meme (127.0.0.1 / ::1), adresse non falsifiable ;
  - aucun en-tete X-Forwarded-* : ngrok les ajoute, le trafic du tunnel est refuse ;
  - l'en-tete Host designe la machine (127.0.0.1, localhost, ::1). Sans ce dernier
    controle, un site web pourrait faire pointer son propre domaine vers 127.0.0.1
    (« DNS rebinding ») et lire ou piloter les pages locales depuis le navigateur.
Pour les ecritures, l'Origin eventuelle doit elle aussi etre locale.
"""
from urllib.parse import urlsplit

_NOMS_LOCAUX = {"127.0.0.1", "localhost", "::1"}
_ADRESSES_LOCALES = {"127.0.0.1", "::1"}


def _nom_hote(valeur):
    """Nom d'hote sans le port : 'localhost:8790' -> 'localhost', '[::1]:8790' -> '::1'."""
    v = str(valeur or "").strip().lower()
    if v.startswith("["):
        return v[1:v.find("]")] if "]" in v else v[1:]
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def hote_local(valeur_host):
    return _nom_hote(valeur_host) in _NOMS_LOCAUX


def origine_locale(valeur_origin):
    """Vrai si l'Origin est absente (outil local, curl) ou designe la machine."""
    if not valeur_origin:
        return True
    try:
        morceaux = urlsplit(str(valeur_origin))
    except ValueError:
        return False
    return morceaux.scheme in {"http", "https"} and (morceaux.hostname or "") in _NOMS_LOCAUX


def requete_locale(adresse_client, entetes):
    """adresse_client : IP de la socket ; entetes : objet a la .get() (insensible a la casse)."""
    if entetes.get("x-forwarded-for") or entetes.get("x-forwarded-host"):
        return False
    if str(adresse_client or "").strip().lower() not in _ADRESSES_LOCALES:
        return False
    return hote_local(entetes.get("host"))
