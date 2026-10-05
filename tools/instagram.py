"""Instagram : resume des nouveautes (abonnes, vues des dernieres videos) vs la veille.

API GRAPH officielle de Meta (aucun scraping). Prerequis : compte(s) Instagram
Business ou Createur + token(s). Voir docs/instagram.md.

Gere PLUSIEURS comptes (config instagram.comptes). instagram_resume() compare
chaque compte a son instantane de la veille (stocke en local dans logs/instagram/)
et te dit ce qui a bouge : abonnes, vues des dernieres videos, nouvelles publis.

Donnees perso -> mcp_expose=False.
"""
import datetime as dt
import json
import logging
import re
from pathlib import Path

from core.config import reglage
from core.registre import outil

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent
_HOTE = None   # hote qui fonctionne (graph.facebook.com ou graph.instagram.com)


def _erreur_sans_secret(erreur):
    """Retire les jetons places dans les URL avant toute ecriture dans les logs."""
    return re.sub(
        r"(?i)(access_token=)[^&\s)]+",
        r"\1<masque>",
        str(erreur),
    )


def _comptes():
    """Liste des comptes a suivre : [{nom, user_id, token}]. Supporte le multi-compte
    (instagram.comptes) et l'ancien format simple (instagram.access_token/user_id)."""
    liste = reglage("instagram.comptes", None)
    out = []
    if liste:
        for c in liste:
            if isinstance(c, dict) and c.get("user_id") and c.get("access_token"):
                out.append({"nom": str(c.get("nom") or c["user_id"]),
                            "user_id": str(c["user_id"]), "token": c["access_token"]})
    else:
        tok, uid = reglage("instagram.access_token", ""), reglage("instagram.user_id", "")
        if tok and uid:
            out.append({"nom": "principal", "user_id": str(uid), "token": tok})
    # Applique le token rafraichi (auto-refresh) s'il est plus recent que la config.
    for c in out:
        c["token"] = _token_actif(c["user_id"], c["token"])
    return out


def _configure():
    return bool(_comptes())


def _get(chemin, token, **params):
    """GET API Graph. Marche avec un token Facebook OU Instagram-login : on essaie
    graph.facebook.com puis graph.instagram.com, et on retient le bon."""
    global _HOTE
    import requests
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    version = reglage("instagram.version_api", "v21.0")
    params["access_token"] = token
    hotes = [_HOTE] if _HOTE else ["graph.facebook.com", "graph.instagram.com"]
    derniere = None
    for hote in hotes:
        try:
            r = requests.get(f"https://{hote}/{version}/{chemin}", params=params, timeout=20)
            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                derniere = RuntimeError(data["error"].get("message", "erreur API"))
                continue
            _HOTE = hote
            return data
        except Exception as e:
            derniere = e
    raise derniere or RuntimeError("appel API impossible")


def _vues_media(media_id, token):
    """Nombre de vues d'un media (essaie 'views' puis 'plays')."""
    for metric in ("views", "plays"):
        try:
            d = _get(f"{media_id}/insights", token, metric=metric)
            for item in d.get("data", []):
                vals = item.get("values", [])
                if vals:
                    return int(vals[0].get("value", 0))
        except Exception:
            continue
    return None


# ------------------------------------------------------------- instantanes

def _dossier():
    d = _RACINE / (reglage("instagram.dossier", "logs/instagram"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fichier():
    return _dossier() / "instantanes.json"


def _charger_historique():
    f = _fichier()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _sauver_historique(hist):
    _fichier().write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")


def _veille(par_jour, aujourd):
    passes = [j for j in sorted(par_jour) if j < aujourd]
    return par_jour[passes[-1]] if passes else None


# ------------------------------------------------ auto-refresh des tokens (60j)

_REFRESH_JOURS = 10   # les tokens durent ~60j ; on les prolonge tous les 10j


def _fichier_tokens():
    return _dossier() / "tokens.json"


def _charger_tokens():
    f = _fichier_tokens()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _token_actif(user_id, token_config):
    """Renvoie le token rafraichi si la config n'a pas change, sinon celui de la config."""
    e = _charger_tokens().get(str(user_id))
    if e and e.get("base") == token_config and e.get("token"):
        return e["token"]
    return token_config


def _rafraichir_un(token):
    """Prolonge un token Instagram-login de 60 jours. Renvoie le nouveau token ou None."""
    try:
        d = _get("refresh_access_token", token, grant_type="ig_refresh_token")
        return d.get("access_token")
    except Exception as e:
        LOG.info("instagram: refresh impossible (%s)", _erreur_sans_secret(e))
        return None


def rafraichir_tokens():
    """Prolonge les tokens trop vieux (>= _REFRESH_JOURS) et memorise les nouveaux.
    N'ecrit jamais dans config.yaml : les tokens vivent dans logs/instagram/tokens.json."""
    liste = reglage("instagram.comptes", None)
    bruts = []
    if liste:
        for c in liste:
            if isinstance(c, dict) and c.get("user_id") and c.get("access_token"):
                bruts.append((str(c["user_id"]), c["access_token"]))
    else:
        t, u = reglage("instagram.access_token", ""), reglage("instagram.user_id", "")
        if t and u:
            bruts.append((str(u), t))
    if not bruts:
        return
    store = _charger_tokens()
    auj = dt.date.today().isoformat()
    for uid, conf_token in bruts:
        e = store.get(uid)
        if not e or e.get("base") != conf_token:
            # nouveau compte, ou token change a la main dans config.yaml -> on repart de la
            store[uid] = {"token": conf_token, "base": conf_token, "date": auj}
            continue
        try:
            age = (dt.date.today() - dt.date.fromisoformat(e.get("date", auj))).days
        except Exception:
            age = 999
        if age < _REFRESH_JOURS:
            continue
        nouveau = _rafraichir_un(e["token"])
        if nouveau:
            store[uid] = {"token": nouveau, "base": conf_token, "date": auj}
            LOG.info("instagram: token prolonge pour %s", uid)
    _fichier_tokens().write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def demarrer_refresh_instagram():
    """Lance la verification/prolongation des tokens en tache de fond (au demarrage)."""
    if not _configure():
        return
    import threading

    def run():
        try:
            rafraichir_tokens()
        except Exception as e:
            # Pas de trace complete : l'URL de l'erreur contient le jeton.
            LOG.warning("instagram: auto-refresh (%s)", _erreur_sans_secret(e))
    threading.Thread(target=run, daemon=True).start()


def _instantane(compte):
    """Releve du jour pour un compte : abonnes + vues des videos recentes."""
    uid, token = compte["user_id"], compte["token"]
    infos = _get(uid, token, fields="username,followers_count,media_count")
    medias = _get(f"{uid}/media", token,
                  fields="id,media_type,caption,timestamp,like_count,comments_count",
                  limit=8).get("data", [])
    vues, titres = {}, {}
    for m in medias:
        titres[m["id"]] = (m.get("caption", "") or "").replace("\n", " ")[:40]
        if m.get("media_type") in ("VIDEO", "REELS"):
            v = _vues_media(m["id"], token)
            if v is not None:
                vues[m["id"]] = v
    return {"abonnes": infos.get("followers_count"),
            "username": infos.get("username"), "vues": vues, "titres": titres}


def _phrase(compte, snap, veille):
    qui = f"@{snap.get('username')}" if snap.get("username") else compte["nom"]
    ab = snap.get("abonnes")
    if veille is None:
        return f"{qui} : {ab} abonnes (premier releve, les variations arrivent demain)."
    delta = (ab or 0) - (veille.get("abonnes") or 0)
    if delta > 0:
        p_ab = f"+{delta} abonnes depuis hier (total {ab})"
    elif delta < 0:
        p_ab = f"{delta} abonnes depuis hier (total {ab})"
    else:
        p_ab = f"abonnes stables ({ab})"
    gains = []
    for mid, v in snap.get("vues", {}).items():
        avant = (veille.get("vues") or {}).get(mid)
        titre = (snap.get("titres", {}).get(mid, "") or "").strip() or "une video"
        if avant is None:
            gains.append(f"nouvelle video \"{titre}\" a {v} vues")
        elif v - avant > 0:
            gains.append(f"\"{titre}\" +{v - avant} vues (total {v})")
    p_vues = (" Videos : " + " ; ".join(gains[:3]) + ".") if gains else ""
    return f"{qui} : {p_ab}.{p_vues}"


@outil(
    nom="instagram_resume",
    description="Resume les nouveautes de tes comptes Instagram par rapport a la veille "
                "(abonnes gagnes/perdus, vues des dernieres videos, nouvelles publis). "
                "Pour 'quoi de neuf sur Instagram', 'mes stats Insta'. Precise un compte "
                "avec 'compte' (ex. son nom ou pseudo) ; sinon tous les comptes.",
    parametres={
        "type": "object",
        "properties": {
            "compte": {"type": "string",
                       "description": "Nom ou pseudo d'un compte precis (optionnel ; vide = tous)."}
        },
    },
    lent=True,
    phrase_attente="Je regarde tes comptes Instagram.",
    mcp_expose=False,
)
def instagram_resume(compte: str = "") -> str:
    try:
        rafraichir_tokens()   # prolonge les tokens si besoin (cheap si pas necessaire)
    except Exception:
        pass
    comptes = _comptes()
    if not comptes:
        return ("Instagram n'est pas configure (instagram.comptes ou access_token/user_id "
                "dans config.yaml). Voir docs/instagram.md.")
    if compte:
        filtres = [c for c in comptes if compte.lower() in c["nom"].lower()]
        comptes = filtres or comptes

    hist = _charger_historique()
    aujourd = dt.date.today().isoformat()
    phrases = []
    for c in comptes:
        try:
            snap = _instantane(c)
        except Exception as e:
            # Ni trace complete ni message brut : l'URL de l'erreur contient le jeton,
            # et ce texte part dans les journaux, le HUD et le modele cloud.
            erreur = _erreur_sans_secret(e)
            LOG.warning("instagram_resume %s : %s", c["nom"], erreur)
            phrases.append(f"{c['nom']} : lecture impossible ({erreur}).")
            continue
        par_jour = hist.get(c["nom"], {})
        veille = _veille(par_jour, aujourd)
        par_jour[aujourd] = snap
        for vieux in sorted(par_jour)[:-30]:   # garde ~30 jours
            par_jour.pop(vieux, None)
        hist[c["nom"]] = par_jour
        phrases.append(_phrase(c, snap, veille))
    _sauver_historique(hist)
    return " ".join(phrases)


@outil(
    nom="rafraichir_instagram",
    description="Prolonge tout de suite les tokens d'acces Instagram (ils durent ~60j "
                "et sont renouveles automatiquement). Pour 'rafraichis mes tokens "
                "Instagram', 'renouvelle l'acces Instagram'.",
    mcp_expose=False,
)
def rafraichir_instagram() -> str:
    if not _configure():
        return "Aucun compte Instagram configure."
    try:
        rafraichir_tokens()
    except Exception as e:
        return f"Souci pendant le renouvellement ({_erreur_sans_secret(e)})."
    return "Tokens Instagram verifies et prolonges si necessaire."
