"""Pont iPhone : endpoint HTTP pour envoyer notes et commandes depuis le telephone.

Sert POST /api/inbox (FastAPI). Tu l'exposes via ton domaine ngrok statique et tu
l'appelles depuis l'app Raccourcis d'iOS (voir docs/iphone.md).

  { "type": "note",     "contenu": "...", "categorie": "..."(optionnel) }
  { "type": "commande", "contenu": "eteins les lumieres" }

Authentification : un token secret (config pont_iphone.token) dans l'en-tete
X-Jarvis-Token.

SECURITE (essentiel) : une commande a distance ne peut declencher QUE les outils
reellement surs a distance -> ceux de la liste `pont_iphone.domotique_distante`,
ou les outils N1 exposes au MCP (mcp_expose=True, sans confirmation). Un N3
(mail, appel, reservation, suppression, extinction PC) est TOUJOURS refuse a
distance. Le LLM distant ne recoit d'ailleurs QUE les schemas de ces outils-la
(cf. _outils_distants) : la surface est reduite au strict executable.

Perimetre reel d'un token vole : domotique (lumieres, clim, musique, volume,
scenes) + quelques outils N1 exposes (OBS, budget/stats en lecture, ingestion
YouTube validee). Rien de sensible (pas de mail/appel/argent/suppression), tout
reversible. Garde ton token secret et regenere-le au moindre doute.
"""
import logging
import secrets
from pathlib import Path

from core.config import reglage

LOG = logging.getLogger("jarvis")

# Journal dedie au pont iPhone : une trace par requete -> logs/inbox.log. Permet de
# diagnostiquer un POST qui echoue cote iOS (content-type, corps, erreur) sans jamais
# fermer la connexion en silence.
_LOGI = logging.getLogger("jarvis.inbox")
if not _LOGI.handlers:
    _d = Path(__file__).resolve().parent.parent / "logs"
    _d.mkdir(exist_ok=True)
    _h = logging.FileHandler(_d / "inbox.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                      "%Y-%m-%d %H:%M:%S"))
    _LOGI.addHandler(_h)
    _LOGI.setLevel(logging.INFO)
    _LOGI.propagate = False


def _token_ok(fourni):
    attendu = reglage("pont_iphone.token", "")
    return bool(attendu) and secrets.compare_digest(str(fourni or ""), str(attendu))


def _outils_distants(local_seulement=False):
    """Schémas des SEULS outils exécutables à distance (surface réduite) : jamais
    un N3 ; et soit dans domotique_distante, soit N1 exposé au MCP (mcp_expose
    sans confirmation). Le LLM distant ne voit que ceux-là -> il ne peut même pas
    tenter d'appeler un outil sensible."""
    from core import registre
    domo = set(reglage("pont_iphone.domotique_distante", []) or [])
    ok = []
    for s in registre.schemas_api(local_seulement=local_seulement):
        o = registre.get(s["name"])
        if o is None or registre.est_n3(s["name"]):
            continue
        if s["name"] in domo or (o.mcp_expose and not o.confirmation):
            ok.append(s)
    return ok


def traiter_commande(phrase):
    """Execute une commande a distance, mais UNIQUEMENT via les outils surs
    (mcp_expose=True et sans confirmation). Renvoie {ok, reponse, faits}."""
    from core.llm import llm
    from core import registre
    P = llm()
    if not P.disponible():
        return {"ok": False, "reponse": "Le modele de Jarvis n'est pas disponible."}
    systeme = ("Tu es Jarvis, pilote a distance. Execute la commande de l'utilisateur "
               "via les outils. Reponds en UNE phrase tres courte, en francais.")
    messages = [{"role": "user", "content": phrase}]
    faits = []
    for _ in range(4):
        try:
            rep = P.repondre(systeme, messages,
                             _outils_distants(local_seulement=(P.nom == "Ollama")))
        except Exception as e:
            LOG.exception("pont: appel modele")
            return {"ok": False, "reponse": f"Erreur du modele ({e})."}
        if getattr(rep, "stop_reason", None) != "tool_use":
            texte = " ".join(b.text for b in rep.content
                             if getattr(b, "type", None) == "text").strip()
            return {"ok": True, "faits": faits,
                    "reponse": texte or ("C'est fait." if faits else "Rien a faire.")}
        messages.append({"role": "assistant", "content": rep.content})
        resultats = []
        for b in rep.content:
            if getattr(b, "type", None) != "tool_use":
                continue
            outil = registre.get(b.name)
            # Domotique explicitement ouverte a distance (config pont_iphone.domotique_distante) :
            # outils physiques REVERSIBLES (lumieres, clim, aspirateur, scenes...) que
            # l'utilisateur accepte de piloter depuis l'iPhone. Contourne la confirmation ET
            # mcp_expose, MAIS jamais un N3 (mail/appel/suppression/extinction/reservation
            # restent bloques a distance, quoi qu'il arrive). mcp_expose reste False sur ces
            # outils -> ils ne sont PAS exposes a Hermes (exposes_mcp filtre sur mcp_expose).
            domo_distante = set(reglage("pont_iphone.domotique_distante", []) or [])
            if outil is None:
                res = f"Outil inconnu : {b.name}"
            elif registre.est_n3(b.name):
                res = "Action critique : a faire a la voix a la maison (refusee a distance)."
            elif b.name in domo_distante:
                try:
                    res = str(outil.fonction(**(b.input or {})))
                    faits.append(b.name)
                except Exception:
                    LOG.exception("pont: outil %s", b.name)
                    res = "Erreur pendant l'action."
            elif outil.confirmation or not outil.mcp_expose:
                res = "Action sensible : a faire a la voix a la maison (refusee a distance)."
            else:
                try:
                    res = str(outil.fonction(**(b.input or {})))
                    faits.append(b.name)
                except Exception:
                    LOG.exception("pont: outil %s", b.name)
                    res = "Erreur pendant l'action."
            LOG.info("pont commande : %s(%s) -> %s", b.name, b.input, str(res)[:100])
            resultats.append({"type": "tool_result", "tool_use_id": b.id, "content": str(res)})
        messages.append({"role": "user", "content": resultats})
    return {"ok": True, "faits": faits, "reponse": "Commande trop longue a traiter."}


def _inspiration_async(url, commentaire):
    """Pipeline hub de contenu en tache de fond ; notif vocale a la fin."""
    from core import hub_contenu, voix
    try:
        res = hub_contenu.ingerer_inspiration(url, commentaire or "")
        if res.get("ok"):
            voix.parler(res.get("message") or "Inspiration ajoutee au vault.")
        else:
            voix.parler("Je n'ai pas pu ajouter l'inspiration. " + (res.get("message") or ""))
    except Exception:
        LOG.exception("pont: inspiration")
        voix.parler("Erreur en ajoutant l'inspiration au vault.")


def monter_routes(app):
    """Ajoute les routes du pont iPhone (/api/inbox, /api/ping) au serveur unifie.

    Le handler POST est volontairement TOLERANT (iOS Raccourcis peut envoyer un
    content-type inattendu) : on lit le corps brut et on le parse en JSON, avec repli
    form-urlencoded. Toute erreur est LOGGEE (logs/inbox.log) et renvoyee proprement
    en JSON, jamais en fermeture de connexion.
    """
    import json as _json
    import threading
    from urllib.parse import parse_qs

    from fastapi import Request
    from fastapi.responses import JSONResponse
    from tools.notes import ajouter_note

    @app.post("/api/inbox")
    async def inbox(request: Request):
        try:
            raw = await request.body()
        except Exception:
            raw = b""
        ct = request.headers.get("content-type", "")
        ua = request.headers.get("user-agent", "")
        _LOGI.info("POST /api/inbox | ct=%r | len=%d | ua=%r", ct, len(raw or b""), ua[:60])

        if not _token_ok(request.headers.get("x-jarvis-token", "")):
            _LOGI.warning("  -> token invalide")
            return JSONResponse({"ok": False, "message": "Token invalide."}, status_code=401)

        # Parsing tolerant : JSON quel que soit le content-type, sinon form-urlencoded.
        data, texte = {}, (raw or b"").decode("utf-8", "ignore").strip()
        if texte:
            try:
                data = _json.loads(texte)
            except Exception:
                try:
                    data = {k: v[0] for k, v in parse_qs(texte).items()}
                except Exception:
                    data = {}
        if not isinstance(data, dict):
            data = {}
        typ = str(data.get("type", "")).strip().lower()

        try:
            if typ == "note":
                contenu = str(data.get("contenu", "")).strip()
                if not contenu:
                    return JSONResponse({"ok": False, "message": "Contenu vide."}, status_code=400)
                cat, _ = ajouter_note(contenu, data.get("categorie"), source="iPhone")
                _LOGI.info("  -> note rangee dans %s : %s", cat, contenu[:60])
                return {"ok": True, "action": "note", "categorie": cat,
                        "message": f"Note ajoutee dans {cat}."}

            if typ == "commande":
                contenu = str(data.get("contenu", "")).strip()
                if not contenu:
                    return JSONResponse({"ok": False, "message": "Contenu vide."}, status_code=400)
                r = traiter_commande(contenu)
                _LOGI.info("  -> commande : %s", str(r.get("reponse"))[:80])
                return {"ok": r["ok"], "action": "commande",
                        "message": r["reponse"], "faits": r.get("faits", [])}

            if typ == "inspiration":
                url = (str(data.get("url", "")) or str(data.get("contenu", ""))).strip()
                if not url:
                    return JSONResponse({"ok": False, "message": "url manquante."}, status_code=400)
                threading.Thread(target=_inspiration_async,
                                 args=(url, data.get("commentaire")), daemon=True,
                                 name="inspiration").start()
                _LOGI.info("  -> inspiration en tache de fond : %s", url)
                return {"ok": True, "action": "inspiration",
                        "message": "Inspiration recue, je l'ajoute au vault et je te previens."}

            _LOGI.warning("  -> type inconnu : %r (corps: %s)", typ, texte[:120])
            return JSONResponse(
                {"ok": False, "message": "type inconnu (note, commande ou inspiration)."},
                status_code=400)
        except Exception as e:
            # On LOGGE et on renvoie proprement (200) : jamais de connexion coupee cote iOS.
            _LOGI.exception("  -> ERREUR handler inbox")
            return JSONResponse(
                {"ok": False, "message": f"Erreur interne ({type(e).__name__}), voir logs/inbox.log."},
                status_code=200)

    @app.get("/api/ping")
    def ping():
        return {"ok": True, "service": "jarvis"}
