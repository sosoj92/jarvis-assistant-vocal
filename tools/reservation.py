"""Reservation sur le WEB, pilotee par le modele cloud (boucle agentique Playwright).

Un navigateur Chromium **visible** et **persistant** (profil garde entre les
sessions -> tu restes connecte a Doctolib/TheFork) est piloté par Claude : a
chaque etape il recoit une capture de la page + la liste des elements
cliquables, et decide de l'action (cliquer, taper, derouler...) jusqu'a avoir
rempli le formulaire.

SECURITE (le coeur du dispositif) :
  - book_appointment ne valide JAMAIS tout seul. Il remplit le formulaire, puis
    s'ARRETE devant le bouton final, arme une confirmation vocale (mecanisme de
    la Phase 0) et resume l'action. Rien n'est valide sans ton "oui".
  - Aucun paiement : si une page reclame une carte bancaire, il s'arrete et te
    passe la main (la fenetre reste ouverte).
  - Aucun mot de passe tape : les champs "password" ne sont jamais remplis. Pour
    les sites a login, il ouvre la page et te laisse te connecter dans le profil
    persistant (une fois pour toutes).

Tes infos perso (nom, tel, mail) viennent de config.yaml (utilisateur.*) ;
jamais de mot de passe stocke en clair.
"""
import base64
import logging

from core.config import reglage
from core import registre
from core.registre import outil

LOG = logging.getLogger("jarvis")

_SITE_DEPART = [""]      # URL de depart de la reservation en cours


def _site(url):
    """Domaine enregistrable approximatif : www.doctolib.fr -> doctolib.fr."""
    from urllib.parse import urlparse
    morceaux = urlparse(str(url or ""))
    if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
        return ""
    return ".".join(morceaux.hostname.lower().split(".")[-2:])


def _meme_site(url, depart):
    return bool(_site(url)) and _site(url) == _site(depart)

# --- etat du navigateur persistant (garde entre les appels/tours) ------------
_PW = None      # instance Playwright
_CTX = None     # contexte persistant (le navigateur)
_PAGE = None    # onglet actif
_CLIENT = None  # conserve pour compatibilite avec les anciens imports

# --- action de reservation en attente de confirmation vocale -----------------
_RESUME_RESA = ""   # resume lu par l'annonce de confirmation

MOTS_PAIEMENT = [
    "numero de carte", "carte bancaire", "cvv", "cvc", "code de securite",
    "iban", "titulaire de la carte", "date d'expiration", "card number",
]

# Schema de l'action que Claude renvoie a chaque etape (sortie forcee par outil).
_ACTION = {
    "type": "object",
    "properties": {
        "reflexion": {"type": "string", "description": "Une phrase : ou en es-tu, que fais-tu."},
        "action": {
            "type": "string",
            "enum": ["cliquer", "taper", "choisir", "derouler", "aller",
                     "attendre", "pret_a_confirmer", "paiement", "fini", "bloque"],
        },
        "index": {"type": "integer", "description": "Index de l'element (cliquer/taper/choisir)."},
        "texte": {"type": "string", "description": "Texte a taper, valeur a choisir, ou URL pour 'aller'."},
        "direction": {"type": "string", "enum": ["bas", "haut"]},
        "resume": {"type": "string",
                   "description": "Pour pret_a_confirmer/fini : resume court et clair de la reservation."},
        "raison": {"type": "string", "description": "Pour 'bloque' : ce qui coince."},
    },
    "required": ["action"],
}

_SYSTEME = """Tu pilotes un navigateur pour effectuer une reservation a la place de l'utilisateur.
A chaque etape tu recois une capture de la page et la liste numerotee des elements cliquables/saisissables.
Tu choisis UNE action via l'outil 'agir'.

Regles :
- Avance vers l'objectif : accepter les cookies si un bandeau bloque, chercher le praticien/resto, choisir date/heure/nombre, remplir nom/tel/mail avec les infos fournies.
- 'taper' : donne l'index du champ et le 'texte'. 'choisir' : index d'un menu deroulant + 'texte' = option. 'cliquer' : index. 'derouler' : 'direction' bas/haut. 'aller' : 'texte' = URL.
- Ne tape JAMAIS de mot de passe ni de donnee bancaire. Si la page demande un login, action 'bloque' (l'utilisateur se connectera lui-meme).
- Si une page de PAIEMENT (carte bancaire) apparait : action 'paiement'.
- Quand le formulaire est rempli et qu'il ne reste plus qu'a cliquer le bouton FINAL de validation (ex. "Confirmer la reservation", "Valider le rendez-vous") : NE clique PAS. Action 'pret_a_confirmer' avec un 'resume' clair (ex. "table pour 2 le vendredi 12 a 20h chez Le Bistrot"). C'est l'utilisateur qui validera a la voix.
- Si tu as atteint une page de CONFIRMATION (reservation deja enregistree) : action 'fini' avec 'resume'.
- Si tu es coince (element introuvable, site qui resiste) apres plusieurs essais : action 'bloque' avec 'raison'.
Sois efficace : le but est d'aller au formulaire rempli le plus directement possible."""

_JS_ELEMENTS = r"""() => {
  const sel = 'a,button,input,textarea,select,[role=button],[role=link],[role=option],[role=menuitem],[role=combobox]';
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    el.setAttribute('data-jaridx', i);
    let label = (el.innerText || el.value || el.placeholder ||
                 el.getAttribute('aria-label') || el.getAttribute('name') || '').trim();
    out.push({
      index: i,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      label: label.slice(0, 90),
      enVue: r.top >= -5 && r.top < (window.innerHeight + 5),
    });
    i++;
  }
  return out;
}"""


def _client():
    """Compatibilite interne : client du fournisseur cloud actif."""
    from core import cloud
    return cloud.client_openai() if cloud.fournisseur() == "openai" \
        else cloud.client_anthropic()


def _demarrer_navigateur():
    """Ouvre (ou reutilise) le navigateur persistant visible. Renvoie la page."""
    global _PW, _CTX, _PAGE
    if _CTX is not None:
        try:
            _ = _PAGE.title()  # le navigateur est-il encore vivant ?
            return _PAGE
        except Exception:
            _fermer_navigateur()

    from pathlib import Path
    from core.playwright_partage import obtenir

    profil = reglage("reservation.profil", ".profil_reservation")
    profil = str((Path(__file__).resolve().parent.parent / profil).resolve())

    visible = bool(reglage("reservation.navigateur_visible", True))
    canal = reglage("reservation.navigateur_canal", "chrome")
    _PW = obtenir()
    base = dict(
        user_data_dir=profil,
        headless=not visible,
        viewport={"width": 1280, "height": 900},
        locale="fr-FR",
        args=["--window-position=1920,40"],  # best-effort : 2e ecran a droite
    )
    # On privilegie le Chrome SYSTEME (signe, stable) ; le Chromium livre par
    # Playwright est parfois mis en quarantaine par l'antivirus. Repli sur lui sinon.
    essais = ([dict(base, channel=canal)] if canal else []) + [base]
    _CTX = None
    derniere = None
    for options in essais:
        try:
            _CTX = _PW.chromium.launch_persistent_context(**options)
            break
        except Exception as e:
            derniere = e
            _CTX = None
    if _CTX is None:
        raise derniere
    _PAGE = _CTX.pages[0] if _CTX.pages else _CTX.new_page()
    _PAGE.set_default_timeout(15000)
    return _PAGE


def _fermer_navigateur():
    # On ferme seulement le contexte de reservation ; l'instance Playwright est
    # partagee (module navigateur) et ne doit pas etre arretee ici.
    global _CTX, _PAGE
    try:
        if _CTX:
            _CTX.close()
    except Exception:
        pass
    _CTX = _PAGE = None


def _capture_b64(page):
    brut = page.screenshot(type="jpeg", quality=70)
    return base64.b64encode(brut).decode("ascii")


def _paiement_present(page):
    try:
        texte = (page.inner_text("body") or "").lower()
    except Exception:
        return False
    from core.util import sans_accents
    texte = sans_accents(texte)
    return any(m in texte for m in MOTS_PAIEMENT)


def _demander_action(page, objectif, dernier):
    """Un tour de la boucle vision : renvoie le dict d'action du modele cloud."""
    from core import cloud
    if not cloud.disponible():
        return {"action": "bloque", "raison": "pas de cle cloud configuree"}
    elements = page.evaluate(_JS_ELEMENTS)
    liste = "\n".join(
        f"[{e['index']}] {e['tag']}{('/' + e['type']) if e['type'] else ''} "
        f"{'(visible)' if e['enVue'] else '(hors vue)'} : {e['label']}"
        for e in elements[:120])
    infos = (f"Objectif : {objectif}\n"
             f"Infos utilisateur -> nom: {reglage('utilisateur.nom', '')}, "
             f"tel: {reglage('utilisateur.telephone', '')}, "
             f"mail: {reglage('utilisateur.email', '')}\n"
             f"URL actuelle : {page.url}\n"
             f"{('Resultat de la derniere action : ' + dernier) if dernier else ''}\n\n"
             f"Elements de la page :\n{liste}")
    return cloud.decider_action_vision(
        _SYSTEME, infos, _capture_b64(page), _ACTION,
        nom_outil="agir", description="Decide de la prochaine action.",
        nom_modele=reglage("reservation.modele", "") or "")


def _executer_action(page, act):
    """Applique l'action sur la page. Renvoie (texte_resultat, champ_password?)."""
    a = act.get("action")
    idx = act.get("index")
    cible = f'[data-jaridx="{idx}"]' if idx is not None else None
    if a == "cliquer":
        page.click(cible, timeout=8000)
        page.wait_for_timeout(1200)
        return f"clic sur [{idx}]"
    if a == "taper":
        el = page.query_selector(cible)
        if el and (el.get_attribute("type") or "").lower() == "password":
            return "REFUS : champ mot de passe, on ne le remplit pas."
        page.fill(cible, act.get("texte", ""), timeout=8000)
        return f"saisi '{act.get('texte','')}' dans [{idx}]"
    if a == "choisir":
        try:
            page.select_option(cible, label=act.get("texte", ""))
        except Exception:
            page.select_option(cible, value=act.get("texte", ""))
        return f"choisi '{act.get('texte','')}' dans [{idx}]"
    if a == "derouler":
        page.mouse.wheel(0, 700 if act.get("direction") != "haut" else -700)
        page.wait_for_timeout(600)
        return "deroule"
    if a == "aller":
        cible = str(act.get("texte", "") or "")
        # Le modele suit le contenu des pages : il ne peut pas emmener tes
        # coordonnees vers un autre site que celui de depart.
        if not _meme_site(cible, _SITE_DEPART[0]):
            return "navigation refusee : on reste sur le site de la reservation"
        page.goto(cible, wait_until="domcontentloaded")
        return f"navigue vers {cible}"
    if a == "attendre":
        page.wait_for_timeout(1500)
        return "attendu"
    return a


@outil(
    nom="book_appointment",
    description="Effectue une reservation sur le web a la place de l'utilisateur "
                "(rendez-vous, table de restaurant, tout formulaire de reservation "
                "simple). Ouvre un navigateur visible et pilote la page jusqu'au "
                "formulaire rempli, PUIS s'arrete pour demander confirmation avant de "
                "valider. Pour 'prends-moi un rdv chez...', 'reserve une table...'.",
    parametres={
        "type": "object",
        "properties": {
            "site": {"type": "string",
                     "description": "Site cible : 'thefork', 'doctolib', ou une URL complete."},
            "quoi": {"type": "string",
                     "description": "Ce qu'on reserve : praticien/specialite, ou nom du restaurant."},
            "quand": {"type": "string",
                      "description": "Dates/heures voulues ('mardi 14h30', 'vendredi 20h')."},
            "details": {"type": "string",
                        "description": "Precisions : nombre de personnes, motif, contraintes."},
        },
        "required": ["site", "quoi", "quand"],
    },
    lent=True,
    phrase_attente="Je m'occupe de la reservation, ca peut prendre un moment. Je te previens avant de valider.",
    # N3 (core/registre._N3) : le navigateur pilote saisit ton nom, ton telephone et
    # ton e-mail sur le site. On confirme le site et l'objet AVANT de commencer.
    confirmation=True,
    annonce=lambda args: (f"Je vais remplir une reservation sur {str(args.get('site', '?'))[:80]} "
                          f"pour {str(args.get('quoi', '?'))[:80]}, {str(args.get('quand', '?'))[:60]}, "
                          "avec tes coordonnees."),
)
def book_appointment(site: str, quoi: str, quand: str, details: str = "") -> str:
    global _RESUME_RESA
    sites = reglage("reservation.sites", {}) or {}
    url = sites.get(site.strip().lower())
    if not url:
        url = site if site.startswith("http") else f"https://www.google.com/search?q={site}"
    objectif = (f"Reserver sur {site}. Quoi : {quoi}. Quand : {quand}."
                + (f" Details : {details}." if details else ""))
    _SITE_DEPART[0] = url

    try:
        page = _demarrer_navigateur()
        page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        LOG.exception("book_appointment: ouverture")
        return (f"Je n'ai pas pu ouvrir le navigateur ({e}). J'utilise ton Chrome "
                "systeme ; s'il n'est pas installe, mets reservation.navigateur_canal "
                "a vide dans config.yaml et lance : uv run playwright install chromium.")

    dernier = ""
    max_etapes = int(reglage("reservation.max_etapes", 22))
    for etape in range(max_etapes):
        if _paiement_present(page):
            return ("Une page de paiement est apparue : je m'arrete et te laisse la "
                    "main, la fenetre reste ouverte. Je ne saisis jamais de carte bancaire.")
        try:
            act = _demander_action(page, objectif, dernier)
        except Exception as e:
            LOG.exception("book_appointment: etape %d", etape)
            return f"J'ai eu un souci en analysant la page : {e}. La fenetre reste ouverte."
        a = act.get("action")
        LOG.info("resa etape %d : %s %s", etape, a, act.get("resume") or act.get("raison") or "")

        if a == "paiement":
            return ("On arrive au paiement : je te laisse la main, la fenetre reste "
                    "ouverte. Je ne paie jamais a ta place.")
        if a == "bloque":
            return (f"Je bloque : {act.get('raison', 'raison inconnue')}. La fenetre "
                    "reste ouverte si tu veux prendre la main.")
        if a == "fini":
            return f"C'est deja confirme a l'ecran : {act.get('resume', '')}"
        if a == "pret_a_confirmer":
            _RESUME_RESA = act.get("resume", f"{quoi}, {quand}")
            # Arme la confirmation vocale (mecanisme Phase 0) : rien n'est valide
            # sans le "oui" de l'utilisateur.
            registre.mettre_en_attente(registre.get("confirmer_reservation"), {})
            return f"Formulaire pret : {_RESUME_RESA}."
        try:
            dernier = _executer_action(page, act)
        except Exception as e:
            dernier = f"echec de l'action ({e})"

    return ("Je n'ai pas reussi a finaliser dans le temps imparti. La fenetre reste "
            "ouverte pour que tu prennes le relais, dis-moi ou ca coince.")


def _annonce_validation(_args):
    return f"Je vais valider la reservation : {_RESUME_RESA}."


@outil(
    nom="confirmer_reservation",
    description="Valide (clique le bouton final) la reservation preparee par "
                "book_appointment. N'est appele qu'apres l'accord vocal de l'utilisateur.",
    confirmation=True,
    annonce=_annonce_validation,
)
def confirmer_reservation() -> str:
    page = _PAGE
    if page is None:
        return "Il n'y a pas de reservation en cours a valider."
    if _paiement_present(page):
        return "La page demande un paiement : je te laisse valider toi-meme."
    try:
        act = _demander_action(
            page,
            "Le formulaire est rempli et confirme par l'utilisateur. Clique "
            "MAINTENANT le bouton final de validation de la reservation.", "")
        if act.get("action") == "cliquer":
            _executer_action(page, act)
            page.wait_for_timeout(2500)
            return f"Reservation validee : {_RESUME_RESA}. Verifie la confirmation a l'ecran."
        return ("Je n'ai pas trouve le bouton de validation avec certitude ; je "
                "prefere te laisser cliquer toi-meme, la fenetre est ouverte.")
    except Exception as e:
        LOG.exception("confirmer_reservation")
        return f"Souci a la validation : {e}. La fenetre reste ouverte."
