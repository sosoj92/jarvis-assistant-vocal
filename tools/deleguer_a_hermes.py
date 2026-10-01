"""Delegation d'une ou PLUSIEURS taches a Hermes Agent (cerveau delibératif).

Flux : Jarvis envoie la tache a l'API d'Hermes (gateway loopback 8642), repond
TOUT DE SUITE "je delegue, je te previens", puis - en tache de fond - recupere le
resultat, le passe au FILTRE DE CONFIDENTIALITE, et l'annonce a voix haute (resume
court). Plusieurs delegations peuvent tourner EN PARALLELE, chacune dans sa propre
session nommee (`session`) -> conversations Hermes independantes.

COMMAND CENTER (N11) : chaque delegation est suivie comme une TACHE (statut, duree,
tokens) -> visible dans le panneau « Etat » et listable vocalement (« Jarvis, ou en
sont les taches ? » -> outil taches_hermes). Aucune nouvelle infra : juste de la
visibilite sur le mecanisme existant.

Securite :
- NON expose via MCP (mcp_expose defaut False) : un agent externe ne peut pas
  declencher de delegation.
- lancement local sans confirmation, pour le routage automatique des taches de fond.
- le resultat lu a voix haute passe par core.confidentialite.filtrer().
Voir docs/hermes.md.
"""
import threading
import time
import uuid
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from core import voix, confidentialite
from core.config import reglage
from core.registre import outil
from core.util import sans_accents

# Magasin de certificats Windows (Malwarebytes/AV) puis requests.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import requests

# ---- Registre des taches Hermes (COMMAND CENTER) + part Hermes (tokens totaux) ----
_LOCK = threading.Lock()
_MAX_TACHES = 50
_TOKENS = None               # tokens Hermes cumules (30 j), pour le HUD/panneau
_FICHIER_TACHES = Path(__file__).resolve().parent.parent / "logs" / "hermes" / "taches.json"

# Marqueur qu'Hermes peut poser dans son resume pour demander ta validation.
_MARQUEUR_VALIDATION = "[A VALIDER]"

# Routage deterministe des vrais travaux de creation. On exige a la fois un
# objet de contenu et une intention de le fabriquer/ameliorer : une simple
# conversation qui contient « script » ou « video » reste ainsi chez Jarvis.
_OBJETS_CONTENU = {
    "script", "scripts", "hook", "hooks", "accroche", "accroches",
    "storyboard", "storyboards", "contenu", "contenus", "video", "videos",
    "reel", "reels", "short", "shorts", "tiktok", "youtube", "post", "posts",
    "instagram", "idee", "idees", "angle", "angles", "publication",
    "publications", "carrousel", "carrousels", "legende",
    "legendes", "caption", "captions", "voix-off", "createur", "createurs",
    "inspiration", "inspirations",
}
_ACTIONS_CONTENU = {
    "ecris", "ecrire", "redige", "rediger", "cree", "creer", "prepare",
    "preparer", "propose", "proposer", "trouve", "trouver", "donne", "donner",
    "genere", "generer", "imagine", "imaginer", "analyse", "analyser", "etudie",
    "etudier", "corrige", "corriger", "reecris", "reecrire", "ameliore",
    "ameliorer", "optimise", "optimiser", "adapte", "adapter", "structure",
    "structurer", "developpe", "developper", "cherche", "chercher", "compare",
    "comparer", "travaille", "travailler", "brainstorme", "brainstormer", "fais",
    "faire", "copie", "copier", "inspire", "inspirer", "reprends", "reprendre",
    "utilise", "utiliser", "imite", "imiter", "apprends", "apprendre", "connais",
    "connaitre", "veux", "voudrais", "aimerais",
}
_ACTIONS_PHYSIQUES = {
    "allume", "allumer", "eteins", "eteindre", "ouvre", "ouvrir", "ferme",
    "fermer", "augmente", "baisse",
}
_OBJETS_PHYSIQUES = {
    "lumiere", "lumieres", "lampe", "lampes", "clim", "climatisation",
    "tele", "television", "prise", "ventilateur", "musique", "volume",
}


def extraire_tache_contenu(phrase: str):
    """Transforme une demande creative explicite en tache Hermes, sinon None.

    Les mises a jour de suivi (« j'ai tourne ma video »), les questions meta et
    les actions physiques faites *pour* filmer ne sont volontairement pas routees.
    """
    original = (phrase or "").strip()
    normalise = " ".join(re.sub(
        r"[^a-z0-9]+", " ", sans_accents(original.lower())
    ).split())
    mots = set(normalise.split())
    if not original or not (mots & _OBJETS_CONTENU):
        return None
    if not (mots & _ACTIONS_CONTENU):
        return None
    if (mots & _ACTIONS_PHYSIQUES) and (mots & _OBJETS_PHYSIQUES):
        return None
    return (
        original
        + "\n\nTraite cette demande comme un travail de creation de contenu. "
          "Appuie-toi d'abord sur les inspirations, scripts et contexte disponibles "
          "dans le Vault afin de respecter le ton de l'utilisatrice. Produis un "
          "livrable concret, pas seulement des conseils generiques."
    )


def _charger_taches():
    try:
        taches = json.loads(_FICHIER_TACHES.read_text(encoding="utf-8"))
        if not isinstance(taches, list):
            return []
        modifie = False
        maintenant = time.time()
        retention_jours = max(0, int(reglage("hermes.retention_jours", 30) or 0))
        if retention_jours:
            limite = maintenant - retention_jours * 86400
            conservees = [t for t in taches
                           if float(t.get("debut") or maintenant) >= limite]
            modifie = len(conservees) != len(taches)
            taches = conservees
        for t in taches:
            if t.get("statut") == "en_cours":
                t.update(statut="echouee", fin=maintenant,
                         duree=round(maintenant - float(t.get("debut") or maintenant), 1),
                         resume="Interrompue par un redemarrage de Jarvis.")
                modifie = True
        recentes = taches[-_MAX_TACHES:]
        if modifie or len(recentes) != len(taches):
            _FICHIER_TACHES.write_text(
                json.dumps(recentes, ensure_ascii=False, indent=2),
                encoding="utf-8")
        return recentes
    except (OSError, ValueError, TypeError):
        return []


_TACHES = _charger_taches()


def _sauver_taches_verrouille():
    try:
        _FICHIER_TACHES.parent.mkdir(parents=True, exist_ok=True)
        _FICHIER_TACHES.write_text(
            json.dumps(_TACHES[-_MAX_TACHES:], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass


def taches_en_cours() -> int:
    with _LOCK:
        return sum(1 for t in _TACHES if t["statut"] == "en_cours")


def taches_liste():
    """Copie des taches (pour le panneau Etat et l'outil taches_hermes)."""
    with _LOCK:
        return [dict(t) for t in _TACHES]


def _ajouter_tache(session, tache):
    identifiant = uuid.uuid4().hex[:8]
    if session:
        nom_session = session
    else:
        base = re.sub(r"[^a-z0-9]+", "-", (tache or "tache").lower()).strip("-")[:24]
        nom_session = f"jarvis-{base or 'tache'}-{identifiant[:4]}"
    t = {"id": identifiant, "session": nom_session,
         "tache": (tache or "")[:140], "statut": "en_cours",
         "debut": time.time(), "fin": None, "duree": None,
         "tokens": None, "cout": None, "modele": "", "resume": ""}
    with _LOCK:
        _TACHES.append(t)
        del _TACHES[:-_MAX_TACHES]
        _sauver_taches_verrouille()
    _pousser_hud()
    return t


def _finir_tache(t, statut, resume="", tokens=None, cout=None, modele=""):
    with _LOCK:
        t["statut"] = statut
        t["fin"] = time.time()
        t["duree"] = round(t["fin"] - t["debut"], 1)
        t["resume"] = resume
        if tokens is not None:
            t["tokens"] = tokens
        if cout is not None:
            t["cout"] = cout
        if modele:
            t["modele"] = modele
        _sauver_taches_verrouille()
    _pousser_hud()


def _pousser_hud():
    try:
        import hud
        hud.hermes(taches_en_cours(), _TOKENS)
    except Exception:
        pass


def _maj_tokens():
    global _TOKENS
    try:
        import re
        import shutil
        import subprocess
        exe = shutil.which("hermes")
        if not exe:
            return
        p = subprocess.run([exe, "insights", "--days", "30"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        m = re.search(r"Total tokens:\s+([\d,]+)", (p.stdout or "") + (p.stderr or ""))
        if m:
            _TOKENS = int(m.group(1).replace(",", ""))
    except Exception:
        pass


def rafraichir_hud():
    """Rafraichit la part Hermes (tokens) puis pousse au HUD. Appele au demarrage."""
    _maj_tokens()
    _pousser_hud()


def _cle_api() -> str:
    """Cle API du serveur Hermes : config.yaml hermes.api_key, sinon fichier."""
    cle = reglage("hermes.api_key", "")
    if cle:
        return cle
    chemin = reglage("hermes.api_key_file", "")
    if chemin:
        try:
            contenu = Path(chemin).read_text(encoding="utf-8").strip()
            return contenu.split("=", 1)[-1].strip()   # gere "API_SERVER_KEY=xxx"
        except Exception:
            pass
    return ""


def _prompt_hermes(tache):
    return (
        f"{tache}\n\n"
        "IMPORTANT : effectue la tache MAINTENANT et renvoie la reponse COMPLETE et "
        "definitive dans CE meme message. N'annonce PAS que tu vas le faire, ne dis "
        "pas 'un instant'. Reponds en francais. Termine IMPERATIVEMENT par une "
        "derniere ligne commencant par 'RESUME:' suivie de 2 phrases maximum, "
        "claires et actionnables, redigees pour une lecture a voix haute. Si (et "
        "SEULEMENT si) la tache demande MON accord avant d'agir, prefixe le RESUME "
        f"par {_MARQUEUR_VALIDATION}."
    )


def _usage_tuple(usage, modele_repli=""):
    usage = usage if isinstance(usage, dict) else {}
    entree = int(usage.get("input_tokens") or 0)
    sortie = int(usage.get("output_tokens") or 0)
    tokens = usage.get("total_tokens") or (entree + sortie) or None
    cout = usage.get("estimated_cost_usd")
    try:
        cout = round(float(cout), 4) if cout is not None else None
    except (TypeError, ValueError):
        cout = None
    return tokens, cout, str(usage.get("model") or modele_repli or "")


def _appeler_hermes_cli(prompt, timeout=None):
    """Hermes recent : exécute une tâche one-shot via son CLI officiel."""
    exe = shutil.which("hermes")
    if not exe:
        raise RuntimeError("CLI Hermes introuvable")
    timeout = int(timeout or reglage("hermes.timeout", 900))
    dossier = Path(reglage("hermes.workspace", "") or Path.home() / "hermes-workspace")
    cwd = str(dossier) if dossier.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="jarvis-hermes-") as temporaire:
        usage_fichier = Path(temporaire) / "usage.json"
        proc = subprocess.run(
            [exe, "-z", prompt, "--usage-file", str(usage_fichier)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "erreur inconnue").strip()[-500:]
            raise RuntimeError(f"Hermes CLI a échoué : {detail}")
        texte = (proc.stdout or "").strip()
        try:
            usage = json.loads(usage_fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            usage = {}
    tokens, cout, modele = _usage_tuple(usage)
    return texte or "(reponse vide d'Hermes)", tokens, cout, modele


def _appeler_hermes_http(prompt, session, timeout=None):
    """Ancienne passerelle OpenAI-compatible, gardée pour compatibilité."""
    base = reglage("hermes.api_url", "http://127.0.0.1:8642").rstrip("/")
    cle = _cle_api()
    if not cle:
        raise RuntimeError("cle API Hermes introuvable (hermes.api_key)")
    body = {
        "model": "hermes-agent",
        "input": prompt,
        "conversation": session or reglage("hermes.session", "jarvis-delegation"),
    }
    reponse = requests.post(
        f"{base}/v1/responses", json=body,
        headers={"Authorization": f"Bearer {cle}"},
        timeout=int(timeout or reglage("hermes.timeout", 900)),
    )
    reponse.raise_for_status()
    data = reponse.json()
    morceaux = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for bloc in item.get("content", []):
                if bloc.get("type") == "output_text" and bloc.get("text"):
                    morceaux.append(bloc["text"])
    modele_utilise = str(data.get("model") or reglage("hermes.modele_facturation", "") or "")
    u = data.get("usage") or {}
    tokens, cout, modele_usage = _usage_tuple(u, modele_utilise)
    if cout is None and isinstance(u, dict):
        entree = int(u.get("input_tokens") or 0)
        sortie = int(u.get("output_tokens") or 0)
        try:
            from core.budget import _prix
            pin, pout = _prix(modele_utilise)
            if pin or pout:
                cout = round((entree * pin + sortie * pout) / 1_000_000, 4)
        except Exception:
            pass
    return (("\n".join(morceaux).strip() or "(reponse vide d'Hermes)"),
            tokens, cout, modele_usage or modele_utilise)


def _appeler_hermes(tache: str, session: str = ""):
    """Appelle Hermes. Renvoie texte, tokens, cout estime et modele.

    `auto` conserve l'ancienne API lorsqu'elle est disponible et se replie sur
    `hermes -z` avec les versions recentes, dont `gateway` ne sert plus d'API.
    """
    return appeler_hermes_brut(_prompt_hermes(tache), session)


def appeler_hermes_brut(prompt: str, session: str = "", timeout=None):
    """Appel Hermes synchrone sans consigne vocale, pour les pipelines internes.

    Meme transport que les delegations (API puis repli CLI). Hermes ne recoit
    que le texte du prompt : aucun credential Jarvis ne transite.
    """
    transport = str(reglage("hermes.transport", "auto") or "auto").lower()
    if transport == "cli":
        return _appeler_hermes_cli(prompt, timeout)
    try:
        return _appeler_hermes_http(prompt, session, timeout)
    except Exception:
        if transport == "http":
            raise
        return _appeler_hermes_cli(prompt, timeout)


def _resume_vocal(texte: str) -> str:
    """Extrait la ligne 'RESUME:' (sinon le dernier paragraphe) pour la voix."""
    for ligne in reversed((texte or "").splitlines()):
        l = ligne.strip()
        if l.lower().startswith(("resume:", "resume :", "résumé:", "résumé :")):
            return l.split(":", 1)[1].strip()
    paras = [p.strip() for p in (texte or "").splitlines() if p.strip()]
    return paras[-1] if paras else (texte or "")


def _journaliser(tache: str, resultat: str) -> None:
    """Conserve localement un résultat caviardé, jamais les secrets évidents."""
    if not bool(reglage("hermes.journaliser", True)):
        return
    try:
        dossier = Path(__file__).resolve().parent.parent / "logs" / "hermes"
        dossier.mkdir(parents=True, exist_ok=True)
        retention_jours = max(0, int(reglage("hermes.retention_jours", 30) or 0))
        if retention_jours:
            limite = time.time() - retention_jours * 86400
            for ancien in dossier.glob("delegation-*.md"):
                try:
                    if ancien.stat().st_mtime < limite:
                        ancien.unlink()
                except OSError:
                    pass
        horo = datetime.now().strftime("%Y%m%d-%H%M%S")
        tache_sure = confidentialite.caviarder(tache)
        resultat_sur = confidentialite.caviarder(resultat)
        (dossier / f"delegation-{horo}.md").write_text(
            f"# Delegation {horo}\n\n## Tache\n{tache_sure}\n\n"
            f"## Resultat\n{resultat_sur}\n",
            encoding="utf-8")
    except Exception:
        pass


def deleguer_en_fond(tache: str, intro: str = "Hermes a termine. ",
                     nom_thread: str = "deleguer-hermes", session: str = "") -> str:
    """Delegue une tache a Hermes en tache de fond (session nommee optionnelle),
    la SUIT comme une tache (registre), journalise le resultat complet, et annonce a
    voix haute un resume court (filtre confidentialite). Renvoie tout de suite
    l'accuse pour Jarvis. Reutilise par deleguer_a_hermes et les outils de contenu."""
    t = _ajouter_tache(session, tache)
    session_effective = t["session"]

    def worker():
        try:
            resultat, tokens, cout, modele_utilise = _appeler_hermes(
                tache, session_effective)
            _journaliser(tache, resultat)
            resume = confidentialite.filtrer(
                _resume_vocal(resultat), max_car=int(reglage("hermes.resume_max", 500)))
            a_valider = _MARQUEUR_VALIDATION in (resume or "") or "[A VALIDER]" in (resultat[:400] or "")
            resume = resume.replace(_MARQUEUR_VALIDATION, "").strip()
            _finir_tache(t, "en_attente_validation" if a_valider else "terminee",
                         resume=resume, tokens=tokens, cout=cout,
                         modele=modele_utilise)
            prefixe = intro if not a_valider else "Hermes attend ta validation. "
            voix.parler(prefixe + resume)
            try:                                  # retour Hermes aussi a l'ecran (overlay)
                import overlay
                overlay.afficher(resume, type="reponse")
            except Exception:
                pass
        except Exception as e:
            _finir_tache(t, "echouee", resume=str(e)[:120])
            voix.parler("La delegation a Hermes a echoue. "
                        + confidentialite.filtrer(str(e), 120))
        finally:
            _maj_tokens()                         # conso Hermes mise a jour apres la tache
            _pousser_hud()
    threading.Thread(target=worker, daemon=True,
                     name=f"{nom_thread}-{t['id']}").start()
    return "Je confie ça à Hermes. Je te préviens dès que c'est prêt."


@outil(
    nom="deleguer_a_hermes",
    description=(
        "Confie une tache de REFLEXION, d'ANALYSE ou de RECHERCHE DE FOND a Hermes "
        "(agent delibératif local). A appeler DE TOI-MEME, sans demander, des que la "
        "demande est une tache de fond : analyse, veille, recherche longue, synthese, "
        "reflexion approfondie, ou un travail de creation de contenu (script, hooks, "
        "accroches, idees video, analyse d'inspirations, reecriture) — et bien sur si "
        "l'utilisateur dit 'delegue a Hermes', "
        "'fais une recherche de fond', 'lance Hermes sur...'. Plusieurs delegations "
        "peuvent tourner EN PARALLELE : donne un `session` court et parlant (ex. "
        "'veille-ia', 'analyse-budget') pour les suivre separement. Jarvis annonce "
        "« je confie ca a Hermes » et previent vocalement quand c'est pret. NE PAS "
        "utiliser pour une question simple/reflexe a laquelle tu peux repondre direct."
    ),
    parametres={
        "type": "object",
        "properties": {
            "tache": {"type": "string",
                      "description": "La tache/question a confier a Hermes, formulee clairement."},
            "session": {"type": "string",
                        "description": "Nom court de la session (optionnel) pour paralleliser "
                                       "plusieurs delegations independantes. Ex. 'veille-ia'."},
        },
        "required": ["tache"],
    },
)
def deleguer_a_hermes(tache: str, session: str = "") -> str:
    """Envoie la tache a Hermes en tache de fond ; previent a voix haute a la fin."""
    tache = (tache or "").strip()
    if not tache:
        return "Je n'ai pas compris la tache a deleguer."
    return deleguer_en_fond(tache, session=(session or "").strip())


_ETIQ = {"en_cours": "en cours", "terminee": "terminée",
         "en_attente_validation": "en attente de ta validation", "echouee": "échouée"}


@outil(
    nom="taches_hermes",
    description="Fait le point sur les taches confiees a Hermes : ce qui tourne, ce "
                "qui est termine, ce qui attend ta validation. Pour « ou en sont les "
                "taches ? », « qu'est-ce qu'Hermes fait ? », « les delegations en cours ».",
    parametres={"type": "object", "properties": {}},
)
def taches_hermes() -> str:
    taches = taches_liste()
    if not taches:
        return "Aucune tache confiee a Hermes pour l'instant."
    encours = [t for t in taches if t["statut"] == "en_cours"]
    valider = [t for t in taches if t["statut"] == "en_attente_validation"]
    finies = [t for t in taches if t["statut"] == "terminee"][-3:]
    bouts = []
    if encours:
        noms = ", ".join(f"« {t['tache'][:40]} »" for t in encours[:4])
        bouts.append(f"{len(encours)} en cours : {noms}")
    if valider:
        noms = ", ".join(f"« {t['tache'][:40]} »" for t in valider[:3])
        bouts.append(f"{len(valider)} en attente de ta validation : {noms}")
    if finies and not encours and not valider:
        bouts.append("dernière terminée : " + (finies[-1]["resume"] or finies[-1]["tache"])[:120])
    return ". ".join(bouts) + "." if bouts else "Tout est traité, rien en attente."
