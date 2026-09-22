"""Assistance sur TON vrai navigateur Chrome (Playwright via CDP).

Se connecte a un Chrome lance avec --remote-debugging-port (raccourci
"Chrome + Jarvis") pour t'assister pendant que tu surfes : ouvrir un onglet,
lire/resumer la page active, gerer les onglets, agir (clic/scroll/champ).

Distinct de la reservation (Partie A) qui, elle, tourne sur un profil Playwright
SEPARE. Ici c'est ton navigateur de tous les jours.

SECURITE (ton Chrome = toutes tes sessions connectees) :
  - Domaines proteges (banque, impots, sante... dans config.yaml) : LECTURE
    autorisee, mais AUCUNE action (clic/saisie) -> Jarvis te dit de le faire.
  - Jamais de saisie de mot de passe. Achat/paiement detecte -> il te laisse
    valider toi-meme.
  - Fermer des onglets passe par une confirmation vocale (action destructive).
"""
import logging
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, quote_plus

from core import plateforme
from core.config import reglage
from core.registre import outil
from core.util import sans_accents

LOG = logging.getLogger("jarvis")

_BROWSER = None   # navigateur Chrome connecte via CDP

_MSG_ABSENT = ("Je n'ai pas reussi a lancer Chrome connecte. Verifie que Google "
               "Chrome est installe (ou renseigne navigateur.chrome_exe dans "
               "config.yaml), ou lance le raccourci \"Chrome + Jarvis\" "
               "(chrome_jarvis.sh sur macOS/Linux).")

# Les noms usuels sont normalises ici, pas laisses au jugement du LLM. Cela rend
# « ouvre Netflix » aussi fiable avec un petit modele local qu'avec le cloud.
_SITES_CONNUS = {
    "navigateur": "https://www.google.com",
    "internet": "https://www.google.com",
    "netflix": "https://www.netflix.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "twitch": "https://www.twitch.tv",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com",
    "prime video": "https://www.primevideo.com",
    "disney plus": "https://www.disneyplus.com",
}
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?[a-z0-9](?:[a-z0-9-]*\.)+[a-z]{2,}(?:[/?#].*)?$",
    re.I,
)


def _sans_verbe(texte):
    brut = (texte or "").strip()
    normalise = sans_accents(brut).lower().strip()
    for prefixe in ("dans le navigateur ", "va sur ", "ouvre ", "lance ",
                    "le site ", "site ", "sur le site "):
        if normalise.startswith(prefixe):
            brut = brut[len(prefixe):].strip()
            normalise = sans_accents(brut).lower().strip()
    return brut, normalise


def est_demande_web(texte):
    """Vrai pour une URL, une recherche explicite ou un service web connu."""
    brut, normalise = _sans_verbe(texte)
    return (normalise in _SITES_CONNUS
            or normalise.startswith(("cherche ", "recherche "))
            or bool(_URL_RE.match(brut)))


def _resoudre_cible(url="", recherche=""):
    """Transforme une demande imparfaite du LLM en URL sure et exploitable."""
    if (recherche or "").strip():
        return f"https://www.google.com/search?q={quote_plus(recherche.strip())}"
    brut, normalise = _sans_verbe(url)
    if normalise.startswith(("cherche ", "recherche ")):
        termes = brut.split(" ", 1)[1].strip() if " " in brut else ""
        return f"https://www.google.com/search?q={quote_plus(termes)}" if termes else ""
    if normalise in _SITES_CONNUS:
        return _SITES_CONNUS[normalise]
    if _URL_RE.match(brut):
        return brut if "://" in brut else "https://" + brut
    # Si le modele place par erreur des mots-cles dans le champ URL, mieux vaut
    # une recherche Google qu'un faux domaine comme https://tests godox.
    return f"https://www.google.com/search?q={quote_plus(brut)}" if brut else ""


def _chrome_exe():
    """Chemin de l'executable Chrome (config, sinon emplacements standards de l'OS).

    Sur macOS, c'est le binaire DANS le bundle : « /Applications/Google Chrome.app
    /Contents/MacOS/Google Chrome » (on ne peut pas passer d'options a un .app
    via `open` sans -n --args, et le binaire direct est plus previsible).
    """
    p = reglage("navigateur.chrome_exe", "")
    if p and Path(p).exists():
        return p
    return plateforme.chrome_exe()


def _port_ouvert(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("localhost", port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _lancer_chrome(port):
    """Lance le Chrome dedie (profil « ChromeJarvis ») avec le port de debug.

    Chrome 136+ interdit le debug sur le profil par defaut -> profil separe, comme
    le raccourci « Chrome + Jarvis ». Renvoie True si le lancement est parti."""
    if _port_ouvert(port):          # deja lance par ailleurs
        return True
    exe = _chrome_exe()
    if not exe:
        LOG.warning("navigateur: executable Chrome introuvable")
        return False
    profil = reglage("navigateur.profil_dir", "") or \
        str(plateforme.dossier_donnees("ChromeJarvis"))
    try:
        subprocess.Popen([exe, f"--remote-debugging-port={port}",
                          f"--user-data-dir={profil}"],
                         **plateforme.detache())
        LOG.info("navigateur: Chrome dedie lance (port %s, profil %s)", port, profil)
        return True
    except Exception:
        LOG.exception("navigateur: lancement Chrome")
        return False


def _tenter_cdp(port):
    """Une tentative de connexion CDP. Renvoie le browser ou None."""
    global _BROWSER
    try:
        from core.playwright_partage import obtenir
        _BROWSER = obtenir().chromium.connect_over_cdp(f"http://localhost:{port}",
                                                       timeout=3000)
        return _BROWSER
    except Exception:
        _BROWSER = None
        return None

MOTS_ACHAT = ["acheter", "commander", "payer", "passer la commande",
              "valider la commande", "proceder au paiement", "checkout",
              "add to cart", "ajouter au panier"]


def _connexion(auto=True):
    """Retourne le navigateur Chrome connecte, ou None.

    Si aucun Chrome n'ecoute le port de debug, en lance un (profil dedie) et
    reessaie — plus besoin de lancer le raccourci a la main (auto=False pour
    desactiver ce comportement)."""
    global _BROWSER
    if _BROWSER is not None:
        try:
            _ = _BROWSER.contexts
            return _BROWSER
        except Exception:
            _BROWSER = None
    port = int(reglage("navigateur.cdp_port", 9222))
    # 1) Chrome deja lance avec le port de debug ?
    b = _tenter_cdp(port)
    if b is not None:
        return b
    # 2) Sinon, auto-lancer le Chrome dedie et attendre qu'il reponde (~8 s).
    if auto and _lancer_chrome(port):
        for _ in range(16):
            time.sleep(0.5)
            if _port_ouvert(port):
                b = _tenter_cdp(port)
                if b is not None:
                    return b
    return None


def _contexte(browser):
    return browser.contexts[0] if browser.contexts else browser.new_context()


def _pages(browser):
    pages = []
    for ctx in browser.contexts:
        pages.extend(ctx.pages)
    return pages


def _page_active(browser):
    """Meilleur effort : l'onglet visible/au premier plan."""
    pages = _pages(browser)
    visibles = []
    for p in pages:
        try:
            if p.evaluate("document.visibilityState") == "visible":
                visibles.append(p)
                if p.evaluate("document.hasFocus()"):
                    return p
        except Exception:
            continue
    return visibles[-1] if visibles else (pages[-1] if pages else None)


def _protege(url):
    hote = (urlparse(url).hostname or "").lower()
    for d in (reglage("navigateur.domaines_proteges", []) or []):
        if d.lower() in hote:
            return True
    return False


# ------------------------------------------------------------------- lecture

@outil(
    nom="browser_open",
    description="Ouvre un SITE WEB ou lance une RECHERCHE dans Chrome. C'est le "
                "SEUL outil a utiliser pour 'ouvre Netflix/YouTube', 'va sur le "
                "site X', une adresse en .com/.fr ou 'cherche X'. Ne jamais utiliser "
                "ouvrir_application pour un site. Donne soit une URL, soit recherche.",
    parametres={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL complete a ouvrir (https://...)."},
            "recherche": {"type": "string", "description": "Mots-cles a chercher sur le web."},
        },
    },
)
def browser_open(url: str = "", recherche: str = "") -> str:
    browser = _connexion()
    if browser is None:
        return _MSG_ABSENT
    try:
        cible = _resoudre_cible(url, recherche)
        if not cible:
            return "Dis-moi quoi ouvrir (une adresse ou une recherche)."
        page = _contexte(browser).new_page()
        page.goto(cible, wait_until="domcontentloaded", timeout=15000)
        try:
            page.bring_to_front()
        except Exception:
            pass
        return f"J'ai ouvert {page.title() or cible}."
    except Exception as e:
        LOG.exception("browser_open")
        return f"Je n'ai pas pu ouvrir ca ({e})."


@outil(
    nom="browser_current_page",
    description="Lit l'onglet actif de Chrome (titre, URL et texte) pour repondre a "
                "'resume cette page', 'qu'est-ce qu'ils disent sur les prix', 'traduis "
                "ca', 'de quoi parle cette page'. Autorise meme sur les sites proteges "
                "(lecture seule). Pour le visuel, combine avec capture_screen.",
    lent=True,
    phrase_attente="Je lis la page.",
)
def browser_current_page() -> str:
    browser = _connexion()
    if browser is None:
        return _MSG_ABSENT
    page = _page_active(browser)
    if page is None:
        return "Aucun onglet ouvert dans Chrome."
    try:
        titre = page.title()
        url = page.url
        try:
            texte = page.inner_text("body")
        except Exception:
            texte = ""
        texte = " ".join(texte.split())[:4000]
        return f"Titre : {titre}\nURL : {url}\n\n{texte}"
    except Exception as e:
        LOG.exception("browser_current_page")
        return f"Je n'ai pas pu lire la page ({e})."


@outil(
    nom="browser_tabs",
    description="Liste les onglets ouverts dans Chrome, ou bascule vers un onglet. "
                "Pour 'quels onglets sont ouverts', 'passe sur l'onglet YouTube'. "
                "Pour FERMER des onglets, utilise browser_close_tabs.",
    parametres={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["lister", "basculer"],
                       "description": "lister (defaut) ou basculer."},
            "filtre": {"type": "string",
                       "description": "Pour basculer : mot present dans le titre ou l'URL."},
        },
    },
)
def browser_tabs(action: str = "lister", filtre: str = "") -> str:
    browser = _connexion()
    if browser is None:
        return _MSG_ABSENT
    pages = _pages(browser)
    if not pages:
        return "Aucun onglet ouvert."
    if action == "basculer" and filtre:
        f = filtre.lower()
        for p in pages:
            try:
                if f in (p.title() or "").lower() or f in p.url.lower():
                    p.bring_to_front()
                    return f"Je suis passe sur : {p.title() or p.url}."
            except Exception:
                continue
        return f"Aucun onglet ne correspond a '{filtre}'."
    lignes = []
    for i, p in enumerate(pages, 1):
        try:
            lignes.append(f"{i}. {p.title() or '(sans titre)'} — {urlparse(p.url).hostname or p.url}")
        except Exception:
            continue
    return f"{len(pages)} onglet(s) :\n" + "\n".join(lignes)


# ------------------------------------------------------------------- actions

def _compter_onglets(filtre):
    browser = _connexion()
    if browser is None:
        return 0
    f = (filtre or "").lower()
    n = 0
    for p in _pages(browser):
        try:
            if not f or f in (p.title() or "").lower() or f in p.url.lower():
                n += 1
        except Exception:
            continue
    return n


def _annonce_fermeture(args):
    filtre = args.get("filtre", "")
    n = _compter_onglets(filtre)
    quoi = f"les {n} onglets" if not filtre else f"{n} onglet(s) '{filtre}'"
    return f"Je ferme {quoi}."


@outil(
    nom="browser_close_tabs",
    description="Ferme des onglets de Chrome. Pour 'ferme cet onglet', 'ferme tous "
                "les onglets YouTube'. Action destructive : confirmation demandee.",
    parametres={
        "type": "object",
        "properties": {
            "filtre": {"type": "string",
                       "description": "Mot present dans le titre/URL des onglets a fermer. "
                                      "Vide = l'onglet actif uniquement."},
        },
    },
    confirmation=True,
    annonce=_annonce_fermeture,
)
def browser_close_tabs(filtre: str = "") -> str:
    browser = _connexion()
    if browser is None:
        return _MSG_ABSENT
    f = (filtre or "").lower()
    fermes = 0
    if not f:
        page = _page_active(browser)
        if page:
            try:
                page.close()
                fermes = 1
            except Exception:
                pass
    else:
        for p in list(_pages(browser)):
            try:
                if f in (p.title() or "").lower() or f in p.url.lower():
                    p.close()
                    fermes += 1
            except Exception:
                continue
    return f"{fermes} onglet(s) ferme(s)."


@outil(
    nom="browser_interact",
    description="Agit sur l'onglet actif de Chrome selon une instruction : 'accepte "
                "les cookies', 'descends aux commentaires', 'mets la video en pause', "
                "'clique sur le premier resultat'. Le modele cloud regarde la page et fait UNE "
                "action. Refuse sur les sites proteges et pour les achats/paiements.",
    parametres={
        "type": "object",
        "properties": {
            "instruction": {"type": "string",
                            "description": "Ce qu'il faut faire sur la page active."},
        },
        "required": ["instruction"],
    },
    lent=True,
    phrase_attente="Je regarde la page.",
)
def browser_interact(instruction: str) -> str:
    browser = _connexion()
    if browser is None:
        return _MSG_ABSENT
    page = _page_active(browser)
    if page is None:
        return "Aucun onglet actif."
    if _protege(page.url):
        return ("On est sur un site protege (banque / impots / sante). Je peux le "
                "lire, mais je n'y fais aucune action : fais-le toi-meme.")

    from tools.reservation import _JS_ELEMENTS, _capture_b64
    from core import cloud
    if not cloud.disponible():
        return "Pas de cle cloud configuree."

    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["cliquer", "taper", "derouler", "toucheespace",
                                "achat", "fini", "bloque"]},
            "index": {"type": "integer"},
            "texte": {"type": "string"},
            "direction": {"type": "string", "enum": ["bas", "haut"]},
            "raison": {"type": "string"},
        },
        "required": ["action"],
    }
    try:
        elements = page.evaluate(_JS_ELEMENTS)
        liste = "\n".join(
            f"[{e['index']}] {e['tag']}{('/' + e['type']) if e['type'] else ''} : {e['label']}"
            for e in elements[:120])
        sys_prompt = (
            "Tu assistes l'utilisateur sur la page active de son navigateur. Realise "
            "l'instruction en UNE action via l'outil 'agir'. 'toucheespace' met une "
            "video en pause/lecture. Si l'instruction mene a un ACHAT ou un PAIEMENT : "
            "action 'achat' (l'utilisateur validera lui-meme). Ne tape jamais de mot de "
            "passe. Si impossible : 'bloque' avec raison.")
        act = cloud.decider_action_vision(
            sys_prompt, f"Instruction : {instruction}\n\nElements :\n{liste}",
            _capture_b64(page), schema, nom_outil="agir",
            description="Une action sur la page.",
            nom_modele=reglage("reservation.modele", "") or "")
        a = act.get("action")
        if a == "achat":
            return "Ca ressemble a un achat ou un paiement : je te laisse valider toi-meme."
        if a == "bloque":
            return f"Je n'y arrive pas : {act.get('raison', 'raison inconnue')}."
        if a == "fini":
            return "C'est fait."
        idx = act.get("index")
        cible = f'[data-jaridx="{idx}"]' if idx is not None else None
        if a == "cliquer" and cible:
            page.click(cible, timeout=8000)
            return "C'est clique."
        if a == "taper" and cible:
            el = page.query_selector(cible)
            if el and (el.get_attribute("type") or "").lower() == "password":
                return "C'est un champ mot de passe : je ne le remplis pas, fais-le toi-meme."
            page.fill(cible, act.get("texte", ""), timeout=8000)
            return "Saisi."
        if a == "derouler":
            page.mouse.wheel(0, 800 if act.get("direction") != "haut" else -800)
            return "Voila, j'ai defile."
        if a == "toucheespace":
            page.keyboard.press("Space")
            return "C'est fait."
        return "Je n'ai pas su quoi faire ici."
    except Exception as e:
        LOG.exception("browser_interact")
        return f"Souci sur la page ({e})."
