"""Panneau de configuration web LOCAL de Jarvis.

Servi par le serveur unifie (core.serveur), mais ACCESSIBLE UNIQUEMENT EN LOCAL :
un garde rejette toute requete arrivant par le tunnel ngrok (en-tete
X-Forwarded-For, ou Host different de localhost). Le panneau ne passe donc jamais
par Internet, meme si le meme port sert le pont iPhone.

Doctrine : c'est du Jarvis PUR (config locale). Il AFFICHE l'etat d'Hermes mais ne
lui donne aucun droit nouveau. Il ecrit seulement ce qui est sans danger : choix de
modele (config.yaml) et modele d'Hermes (sa config). Jamais de regle de securite.

Trois vues (une seule page a onglets) :
  - Modeles : materiel (GPU/VRAM), LLM Ollama + Whisper (catalogue reco selon VRAM,
    installer/tester/supprimer), et le modele actif par backend (local/cloud/hermes).
  - Etat : la chaine UP/DOWN (Jarvis, MCP, tunnel, gateway Hermes, Docker, connexion
    MCP) + bouton "reconnecter" (remede du parking MCP).
  - Permissions : le perimetre de securite en lecture seule (mcp_expose, confirmation,
    montages Hermes). Les niveaux N1/N2/N3 et les revocations viendront avec la N8.
"""
import json
import logging
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from core.config import FICHIER as CONFIG_FICHIER, definir, reglage

LOG = logging.getLogger("jarvis.panneau")
_RACINE = Path(__file__).resolve().parent.parent
_HTML = _RACINE / "web" / "panneau.html"

_HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1", "[::1]"}

# Progression des "ollama pull" en cours : nom -> {statut, pct, message}.
_PULLS = {}


# ============================================================ catalogue modeles

# VRAM requise = estimation quantifie Q4 (Go). tool_calling / francais = aptitudes.
CATALOGUE_LLM = [
    {"nom": "llama3.2:3b",  "params": "3B",  "vram": 3.5,  "taille_go": 2.0,
     "tool_calling": True,  "francais": True,  "licence": "Llama 3.2"},
    {"nom": "qwen2.5:3b",   "params": "3B",  "vram": 3.5,  "taille_go": 1.9,
     "tool_calling": True,  "francais": True,  "licence": "Qwen (Apache-2.0)"},
    {"nom": "qwen2.5:7b",   "params": "7B",  "vram": 6.0,  "taille_go": 4.7,
     "tool_calling": True,  "francais": True,  "licence": "Qwen (Apache-2.0)"},
    {"nom": "mistral:7b",   "params": "7B",  "vram": 6.0,  "taille_go": 4.1,
     "tool_calling": True,  "francais": True,  "licence": "Apache-2.0"},
    {"nom": "llama3.1:8b",  "params": "8B",  "vram": 6.5,  "taille_go": 4.9,
     "tool_calling": True,  "francais": True,  "licence": "Llama 3.1"},
    {"nom": "qwen2.5:14b",  "params": "14B", "vram": 10.0, "taille_go": 9.0,
     "tool_calling": True,  "francais": True,  "licence": "Qwen (Apache-2.0)"},
]

# Whisper tourne en CPU chez toi (GPU casse) : la VRAM n'est pas le facteur limitant,
# on classe par qualite/vitesse. "francais_fiable" a partir de small.
CATALOGUE_WHISPER = [
    {"nom": "tiny",             "vram": 1.0, "francais_fiable": False, "note": "tres rapide, peu precis"},
    {"nom": "base",             "vram": 1.0, "francais_fiable": False, "note": "rapide, moyen"},
    {"nom": "small",            "vram": 2.0, "francais_fiable": True,  "note": "bon compromis"},
    {"nom": "medium",           "vram": 5.0, "francais_fiable": True,  "note": "precis (defaut conseille)"},
    {"nom": "large-v3",         "vram": 10.0, "francais_fiable": True, "note": "le plus precis, lent en CPU"},
    {"nom": "large-v3-turbo",   "vram": 6.0, "francais_fiable": True,  "note": "precis et plus rapide que large"},
]


# ==================================================================== materiel

def _materiel():
    """GPU/VRAM via pynvml (meme logique que doctor.py). exploitable = total - marge."""
    infos = {"gpu": [], "vram_total_go": 0.0, "vram_exploitable_go": 0.0, "cpu_seulement": True}
    try:
        import pynvml
        pynvml.nvmlInit()
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            nom = pynvml.nvmlDeviceGetName(h)
            nom = nom.decode() if isinstance(nom, bytes) else nom
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            total = mem.total / (1024 ** 3)
            libre = mem.free / (1024 ** 3)
            infos["gpu"].append({"nom": nom, "vram_total_go": round(total, 1),
                                 "vram_libre_go": round(libre, 1)})
            infos["vram_total_go"] += total
        pynvml.nvmlShutdown()
        if infos["gpu"]:
            infos["cpu_seulement"] = False
            # Exploitable pour un LLM : total - ~1.5 Go (OS + Whisper CPU tourne a cote).
            infos["vram_exploitable_go"] = round(max(0.0, infos["vram_total_go"] - 1.5), 1)
            infos["vram_total_go"] = round(infos["vram_total_go"], 1)
    except Exception as e:
        LOG.info("materiel: pas de GPU NVIDIA (%s)", e)
    return infos


# ==================================================================== ollama

def _ollama_hote():
    return reglage("ollama.hote", "http://localhost:11434").rstrip("/")


def _ollama_joignable():
    try:
        import requests
        requests.get(f"{_ollama_hote()}/api/version", timeout=3)
        return True
    except Exception:
        return False


def _ollama_installes():
    """Liste des modeles installes : [{nom, taille_go}]."""
    try:
        import requests
        r = requests.get(f"{_ollama_hote()}/api/tags", timeout=5)
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            out.append({"nom": m.get("name", ""),
                        "taille_go": round((m.get("size", 0) or 0) / (1024 ** 3), 1)})
        return out
    except Exception as e:
        LOG.info("ollama tags: %s", e)
        return []


def _modeles():
    """Etat complet de la page Modeles."""
    mat = _materiel()
    dispo = mat["vram_exploitable_go"] if not mat["cpu_seulement"] else 0.0
    installes = _ollama_installes()
    noms_installes = {m["nom"] for m in installes}

    def badge_llm(c):
        return {**c,
                "installe": c["nom"] in noms_installes or any(
                    n.split(":")[0] == c["nom"].split(":")[0] and n == c["nom"] for n in noms_installes),
                "tient_en_vram": (not mat["cpu_seulement"]) and c["vram"] <= dispo}

    whisper_actif = reglage("whisper.modele", "medium")
    whisper_dl = _whisper_installes()

    return {
        "materiel": mat,
        "backend_actif": (reglage("mode", "cloud") or "cloud").lower(),
        "actifs": {
            "local": reglage("ollama.modele", "qwen2.5:7b"),
            "cloud": reglage("anthropic.modele", "claude-haiku-4-5"),
            "whisper": whisper_actif,
            "hermes": _hermes_modele(),
        },
        "ollama": {
            "joignable": _ollama_joignable(),
            "hote": _ollama_hote(),
            "installes": installes,
            "catalogue": [badge_llm(c) for c in CATALOGUE_LLM],
        },
        "whisper": {
            "installes": whisper_dl,
            "catalogue": [{**c, "installe": c["nom"] in whisper_dl,
                           "tient_en_vram": (not mat["cpu_seulement"]) and c["vram"] <= dispo}
                          for c in CATALOGUE_WHISPER],
        },
    }


def _ollama_pull(nom):
    """Telecharge un modele en tache de fond, avec suivi de progression."""
    _PULLS[nom] = {"statut": "en cours", "pct": 0, "message": "demarrage"}

    def worker():
        try:
            import requests
            with requests.post(f"{_ollama_hote()}/api/pull",
                               json={"model": nom, "stream": True},
                               stream=True, timeout=3600) as r:
                r.raise_for_status()
                for ligne in r.iter_lines():
                    if not ligne:
                        continue
                    try:
                        d = json.loads(ligne.decode("utf-8", "ignore"))
                    except Exception:
                        continue
                    if d.get("error"):
                        _PULLS[nom] = {"statut": "erreur", "pct": 0, "message": d["error"]}
                        return
                    total, fait = d.get("total"), d.get("completed")
                    pct = int(fait * 100 / total) if total and fait else _PULLS[nom]["pct"]
                    _PULLS[nom] = {"statut": "en cours", "pct": pct,
                                   "message": d.get("status", "")}
            _PULLS[nom] = {"statut": "termine", "pct": 100, "message": "installe"}
        except Exception as e:
            LOG.exception("ollama pull %s", nom)
            _PULLS[nom] = {"statut": "erreur", "pct": 0, "message": str(e)[:200]}

    threading.Thread(target=worker, daemon=True, name=f"pull-{nom}").start()
    return {"ok": True, "message": f"Telechargement de {nom} lance."}


def _ollama_supprimer(nom):
    try:
        import requests
        r = requests.delete(f"{_ollama_hote()}/api/delete", json={"model": nom}, timeout=15)
        if r.status_code >= 400:
            return {"ok": False, "message": f"Suppression refusee ({r.status_code})."}
        _PULLS.pop(nom, None)
        return {"ok": True, "message": f"{nom} supprime."}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


def _ollama_tester(nom):
    """Mini-benchmark : latence + un appel d'outil factice + une phrase en francais."""
    import requests
    hote = _ollama_hote()
    outil = [{"type": "function", "function": {
        "name": "allumer_lumiere",
        "description": "Allume ou eteint une lumiere d'une piece.",
        "parameters": {"type": "object", "properties": {
            "piece": {"type": "string"}, "allumer": {"type": "boolean"}},
            "required": ["piece", "allumer"]}}}]
    res = {"nom": nom}
    # 1) phrase en francais + latence
    t0 = time.time()
    try:
        r = requests.post(f"{hote}/api/chat", timeout=120, json={
            "model": nom, "stream": False, "think": False,
            "messages": [{"role": "user",
                          "content": "Reponds en une phrase courte, en francais : presente-toi."}]})
        r.raise_for_status()
        res["latence_ms"] = int((time.time() - t0) * 1000)
        res["phrase_fr"] = (r.json().get("message", {}).get("content") or "").strip()[:200]
    except Exception as e:
        return {"ok": False, "nom": nom, "message": f"Echec du modele : {str(e)[:160]}"}
    # 2) appel d'outil factice
    try:
        r = requests.post(f"{hote}/api/chat", timeout=120, json={
            "model": nom, "stream": False, "think": False, "tools": outil,
            "messages": [{"role": "user", "content": "Allume la lumiere du salon."}]})
        r.raise_for_status()
        tc = r.json().get("message", {}).get("tool_calls") or []
        res["tool_call_ok"] = any(
            (c.get("function", {}) or {}).get("name") == "allumer_lumiere" for c in tc)
    except Exception:
        res["tool_call_ok"] = False
    res["ok"] = True
    return res


# ==================================================================== whisper

def _hf_cache():
    from pathlib import Path as _P
    import os
    base = os.environ.get("HF_HOME") or str(_P.home() / ".cache" / "huggingface")
    return _P(base) / "hub"


def _whisper_installes():
    """Modeles Whisper deja telecharges (repere via le cache HuggingFace)."""
    dl = []
    cache = _hf_cache()
    if not cache.exists():
        return dl
    for c in CATALOGUE_WHISPER:
        # faster-whisper -> repos "Systran/faster-whisper-<nom>"
        motif = f"models--Systran--faster-whisper-{c['nom']}"
        if (cache / motif).exists():
            dl.append(c["nom"])
    return dl


def _whisper_installer(nom):
    _PULLS[f"whisper:{nom}"] = {"statut": "en cours", "pct": 0, "message": "telechargement"}

    def worker():
        try:
            from faster_whisper import WhisperModel
            WhisperModel(nom, device="cpu", compute_type="int8")  # declenche le download
            _PULLS[f"whisper:{nom}"] = {"statut": "termine", "pct": 100, "message": "installe"}
        except Exception as e:
            LOG.exception("whisper install %s", nom)
            _PULLS[f"whisper:{nom}"] = {"statut": "erreur", "pct": 0, "message": str(e)[:200]}

    threading.Thread(target=worker, daemon=True, name=f"whisper-{nom}").start()
    return {"ok": True, "message": f"Telechargement de Whisper {nom} lance."}


def _whisper_supprimer(nom):
    dossier = _hf_cache() / f"models--Systran--faster-whisper-{nom}"
    if not dossier.exists():
        return {"ok": False, "message": "Modele non trouve dans le cache."}
    try:
        shutil.rmtree(dossier)
        return {"ok": True, "message": f"Whisper {nom} supprime."}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


# ==================================================================== hermes

def _hermes_config():
    from pathlib import Path as _P
    import os
    return _P(os.environ["LOCALAPPDATA"]) / "hermes" / "config.yaml"


def _hermes_modele():
    """Lit model.default dans la config Hermes (affichage)."""
    try:
        import yaml
        data = yaml.safe_load(_hermes_config().read_text(encoding="utf-8")) or {}
        return (data.get("model", {}) or {}).get("default", "?")
    except Exception:
        return "?"


def _hermes_definir_modele(modele):
    """Change model.default cote Hermes via son CLI (sans toucher aux droits)."""
    exe = shutil.which("hermes")
    if not exe:
        return {"ok": False, "message": "CLI 'hermes' introuvable dans le PATH du serveur. "
                "Change le modele cote Hermes (hermes config set model.default ...)."}
    try:
        p = subprocess.run([exe, "config", "set", "model.default", modele],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if p.returncode != 0:
            return {"ok": False, "message": (p.stderr or p.stdout or "echec").strip()[:200]}
        return {"ok": True, "message": f"Modele d'Hermes -> {modele}. Redemarre Hermes pour l'appliquer."}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


# ============================================================== modele actif

def _definir_actif(backend, modele):
    backend = (backend or "").lower()
    if not modele:
        return {"ok": False, "message": "Modele manquant."}
    if backend == "local":
        definir("mode", "local")
        definir("ollama.modele", modele)
        return {"ok": True, "message": f"Backend LOCAL actif, modele {modele}. Redemarre Jarvis."}
    if backend == "cloud":
        definir("mode", "cloud")
        definir("anthropic.modele", modele)
        return {"ok": True, "message": f"Backend CLOUD actif, modele {modele}. Redemarre Jarvis."}
    if backend == "whisper":
        definir("whisper.modele", modele)
        return {"ok": True, "message": f"Whisper -> {modele}. Redemarre Jarvis."}
    if backend == "hermes":
        return _hermes_definir_modele(modele)
    return {"ok": False, "message": f"Backend inconnu : {backend}."}


# ==================================================================== reglages

# Clés éditables depuis le panneau (whitelist stricte : jamais de secret/clé).
_CLES_REGLABLES = {
    "mode": "str", "audio.micro": "int", "audio.haut_parleur": "nint",
    "assistant.personnalite": "str", "assistant.duree_suite": "int",
    "assistant.seuil_reveil": "float",
}


def _audio_devices():
    try:
        import sounddevice as sd
        entrees, sorties = [], []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                entrees.append({"index": i, "nom": d.get("name", "")})
            if d.get("max_output_channels", 0) > 0:
                sorties.append({"index": i, "nom": d.get("name", "")})
        return entrees, sorties
    except Exception:
        return [], []


def _reglages():
    entrees, sorties = _audio_devices()
    return {
        "mode": reglage("mode", "cloud"),
        "micro": reglage("audio.micro", 1),
        "haut_parleur": reglage("audio.haut_parleur", None),
        "personnalite": reglage("assistant.personnalite", "jarvis_sarcastique"),
        "duree_suite": reglage("assistant.duree_suite", 10),
        "seuil_reveil": reglage("assistant.seuil_reveil", 0.5),
        "entrees": entrees, "sorties": sorties,
        "personnalites": ["jarvis_sarcastique", "neutre", "concis"],
    }


def _definir_reglage(cle, valeur):
    from core.config import definir
    typ = _CLES_REGLABLES.get(cle)
    if typ is None:
        return {"ok": False, "message": "Réglage non autorisé."}
    try:
        if typ == "nint":
            valeur = None if valeur in (None, "", "defaut", "null") else int(valeur)
        elif typ == "int":
            valeur = int(valeur)
        elif typ == "float":
            valeur = float(valeur)
        else:
            valeur = str(valeur)
        definir(cle, valeur)
        return {"ok": True, "message": "Enregistré. Redémarre Jarvis pour l'appliquer."}
    except Exception as e:
        return {"ok": False, "message": str(e)[:120]}


# ==================================================================== etat

def _port_listen(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.4).close()
        return True
    except OSError:
        return False


def _mcp_repond():
    """Le serveur MCP repond-il ? (GET /mcp -> 400/406 = vivant)."""
    try:
        import requests
        r = requests.get("http://127.0.0.1:8765/mcp", timeout=5)
        return r.status_code in (400, 406, 405)
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return code in (400, 406, 405)


def _docker_up():
    exe = shutil.which("docker")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info"], capture_output=True,
                              timeout=15).returncode == 0
    except Exception:
        return False


def _hermes_mcp_connecte():
    """'hermes mcp list' montre-t-il jarvis connecte (pas parke) ?"""
    exe = shutil.which("hermes")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        sortie = (p.stdout or "") + (p.stderr or "")
        bas = sortie.lower()
        if "jarvis" not in bas:
            return False
        # parke / failed / disconnected -> KO
        return not any(x in bas for x in ("parked", "parke", "failed", "disconnected", "error"))
    except Exception:
        return None


def _etat():
    # Tunnel : on LIT l'existant, on ne le rouvre JAMAIS (sinon ngrok refuse
    # "endpoint already online"). URL manuelle, sinon le tunnel deja ouvert au demarrage.
    tunnel = reglage("serveur.public_url", "") or reglage("twilio.public_url", "")
    if not tunnel:
        try:
            from core import serveur
            tunnel = getattr(serveur, "_URL", None) or ""
        except Exception:
            tunnel = ""
    chaine = [
        {"cle": "jarvis", "nom": "Serveur Jarvis (web unifie)",
         "up": _port_listen(int(reglage("serveur.port", 8790))), "detail": "pont iPhone / Twilio"},
        {"cle": "mcp", "nom": "Serveur MCP Jarvis :8765",
         "up": _port_listen(8765) and _mcp_repond(), "detail": "outils domotique/PC (loopback)"},
        {"cle": "tunnel", "nom": "Tunnel ngrok", "up": bool(tunnel),
         "detail": tunnel or "aucune URL publique"},
        {"cle": "gateway", "nom": "Gateway Hermes :8642",
         "up": _port_listen(8642), "detail": "API deleguer_a_hermes (loopback)"},
        {"cle": "docker", "nom": "Docker (moteur)", "up": _docker_up(),
         "detail": "backend d'execution Hermes"},
    ]
    connecte = _hermes_mcp_connecte()
    chaine.append({"cle": "mcp_connexion", "nom": "Connexion MCP Hermes -> Jarvis",
                   "up": bool(connecte), "inconnu": connecte is None,
                   "detail": "hermes mcp list" if connecte is not None else "hermes CLI indisponible"})
    return {"chaine": chaine}


# ==================================================================== budget (N9)

def _twilio_compteur():
    """Compteur mensuel Twilio (logs/calls/compteur.json), ou None."""
    try:
        dossier = reglage("appels.dossier", "logs/calls")
        p = Path(dossier)
        p = p if p.is_absolute() else (_RACINE / p)
        f = p / "compteur.json"
        if not f.exists():
            return None
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _budget():
    """Budget cote Jarvis (jour/mois) + compteur Twilio. Rapide (fichiers locaux)."""
    try:
        from core import budget
        jarvis = budget.resume()
    except Exception:
        LOG.exception("budget")
        jarvis = {"jour": {}, "mois": {}}
    return {"jarvis": jarvis, "twilio": _twilio_compteur()}


def _hermes_insights(jours):
    """Parse `hermes insights --days N` : sessions, messages, total tokens."""
    exe = shutil.which("hermes")
    if not exe:
        return None
    try:
        import re
        p = subprocess.run([exe, "insights", "--days", str(jours)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        txt = (p.stdout or "") + (p.stderr or "")

        def num(motif):
            m = re.search(motif, txt)
            return int(m.group(1).replace(",", "")) if m else 0
        return {"sessions": num(r"Sessions:\s+([\d,]+)"),
                "messages": num(r"Messages:\s+([\d,]+)"),
                "tokens": num(r"Total tokens:\s+([\d,]+)")}
    except Exception:
        LOG.exception("hermes insights")
        return None


def _hermes_crons():
    """Liste des crons Hermes (nom, planning, prochaine execution)."""
    exe = shutil.which("hermes")
    if not exe:
        return []
    try:
        p = subprocess.run([exe, "cron", "list"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
        crons, cur = [], None
        for ligne in (p.stdout or "").splitlines():
            s = ligne.strip()
            if s.startswith("Name:"):
                cur = {"nom": s.split(":", 1)[1].strip()}
                crons.append(cur)
            elif cur and s.startswith("Schedule:"):
                cur["planning"] = s.split(":", 1)[1].strip()
            elif cur and s.startswith("Next run:"):
                cur["prochain"] = s.split(":", 1)[1].strip()
        return crons
    except Exception:
        return []


def _hermes_texte(args, timeout=25, lignes=12):
    """Sortie brute (tronquee) d'une commande hermes, pour l'affichage."""
    exe = shutil.which("hermes")
    if not exe:
        return ""
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        txt = (p.stdout or "").strip()
        return "\n".join(txt.splitlines()[:lignes])
    except Exception:
        return ""


def _hermes_activite():
    """Crons + derniers runs + taches en cours + tokens (jour/mois). Lent (CLI Hermes)."""
    return {
        "crons": _hermes_crons(),
        "runs_texte": _hermes_texte(["cron", "runs", "--limit", "5"]),
        "taches_texte": _hermes_texte(["kanban", "list"]),
        "insights_jour": _hermes_insights(1),
        "insights_mois": _hermes_insights(30),
    }


def _reconnecter_mcp():
    """Remede du parking : hermes mcp remove/add jarvis (voir status-hermes.ps1)."""
    exe = shutil.which("hermes")
    if not exe:
        return {"ok": False, "message": "CLI 'hermes' introuvable dans le PATH du serveur."}
    url = "http://127.0.0.1:8765/mcp"
    try:
        subprocess.run([exe, "mcp", "remove", "jarvis"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        p = subprocess.run([exe, "mcp", "add", "jarvis", "--url", url],
                           input="n\ny\n", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        ok = p.returncode == 0
        return {"ok": ok, "message": "jarvis reconnecte." if ok
                else (p.stderr or p.stdout or "echec").strip()[:200]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


# ==================================================================== permissions

def _permissions():
    """Perimetre de securite EN LECTURE SEULE (la N8 ajoutera N1/N2/N3 + revocations)."""
    from core import registre
    registre.charger_outils()
    outils = []
    for o in sorted(registre.tous(), key=lambda x: (x.nom)):
        outils.append({
            "nom": o.nom,
            "niveau": registre.niveau(o.nom),
            "mcp_expose": bool(o.mcp_expose),
            "confirmation": bool(o.confirmation),
            "toujours": registre.est_autorise(o.nom),
            "description": (o.description or "")[:120],
        })
    # Montages Hermes (Docker) : lus dans sa config, pour la vue "perimetre fichiers".
    montages = []
    try:
        import yaml
        data = yaml.safe_load(_hermes_config().read_text(encoding="utf-8")) or {}
        args = (((data.get("terminal", {}) or {}).get("docker_extra_args")) or [])
        for a in args:
            if isinstance(a, str) and ":" in a and ("/vault" in a or "/scripts" in a):
                montages.append(a)
    except Exception:
        pass
    return {
        "regle_n3": "N3 (critique) : confirmation TOUJOURS, jamais memorisable en 'toujours', "
                    "jamais a distance. Le pont iPhone ne declenche QUE des N1 (mcp_expose ET "
                    "sans confirmation) ; toute action a confirmation (N2/N3) est refusee a "
                    "distance, et le 'toujours autoriser' n'ouvre RIEN a distance. [verrouille dans le code]",
        "outils": outils,
        "compte": {"total": len(outils),
                   "mcp_expose": sum(1 for o in outils if o["mcp_expose"]),
                   "confirmation": sum(1 for o in outils if o["confirmation"]),
                   "n1": sum(1 for o in outils if o["niveau"] == "N1"),
                   "n2": sum(1 for o in outils if o["niveau"] == "N2"),
                   "n3": sum(1 for o in outils if o["niveau"] == "N3"),
                   "toujours": sum(1 for o in outils if o["toujours"])},
        "hermes_montages": montages,
        "note_n8": "N1 = sur (local + iPhone). N2 = sensible (confirmation ; memorisable "
                   "'toujours autoriser', revocable ici). N3 = critique (confirmation toujours, "
                   "jamais memorisable, jamais a distance).",
    }


# ==================================================================== routes

def _local_seulement(request):
    """True si la requete vient VRAIMENT du poste local (pas du LAN ni du tunnel).

    On se base sur l'IP REELLE de la socket (request.client.host), non falsifiable
    par un en-tete, PLUS l'absence d'en-tetes X-Forwarded-* (que ngrok ajoute
    toujours -> identifie le trafic tunnelise). L'ancien check sur l'en-tete Host
    etait contournable (`curl -H "Host: localhost"`)."""
    if request.headers.get("x-forwarded-for") or request.headers.get("x-forwarded-host"):
        return False
    hote = (getattr(request.client, "host", "") or "").strip().lower()
    return hote in {"127.0.0.1", "::1", "localhost"}


def monter_routes(app):
    """Monte les routes du panneau sur l'app FastAPI unifiee (appelee par core.serveur)."""
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse

    def garde(request: Request):
        if not _local_seulement(request):
            return JSONResponse({"ok": False,
                                 "message": "Panneau accessible en local uniquement."},
                                status_code=403)
        # Anti-CSRF : sur les écritures (POST), exiger application/json. Une page
        # web malveillante ne peut pas envoyer ce Content-Type en « requête simple »
        # (il déclenche un préflight CORS qu'on ne satisfait pas) -> pas de CSRF.
        if request.method not in ("GET", "HEAD"):
            ct = (request.headers.get("content-type", "") or "").lower()
            if "application/json" not in ct:
                return JSONResponse({"ok": False, "message": "Content-Type invalide."},
                                    status_code=415)
        return None

    @app.get("/panneau")
    def panneau(request: Request):
        refus = garde(request)
        if refus:
            return refus
        if not _HTML.exists():
            return HTMLResponse("<h1>Panneau</h1><p>web/panneau.html manquant.</p>", 500)
        return HTMLResponse(_HTML.read_text(encoding="utf-8"))

    # -- lecture --
    @app.get("/api/panneau/modeles")
    def api_modeles(request: Request):
        return garde(request) or _modeles()

    @app.get("/api/panneau/etat")
    def api_etat(request: Request):
        return garde(request) or _etat()

    @app.get("/api/panneau/budget")
    def api_budget(request: Request):
        return garde(request) or _budget()

    @app.get("/api/panneau/hermes-activite")
    def api_hermes_activite(request: Request):
        return garde(request) or _hermes_activite()

    @app.get("/api/panneau/permissions")
    def api_permissions(request: Request):
        return garde(request) or _permissions()

    @app.get("/api/panneau/pull-status")
    def api_pull_status(request: Request, nom: str = ""):
        return garde(request) or _PULLS.get(nom, {"statut": "inconnu", "pct": 0, "message": ""})

    @app.get("/api/panneau/reglages")
    def api_reglages(request: Request):
        return garde(request) or _reglages()

    # -- ecriture (sans danger : modeles + reconnexion) --
    async def _corps(request):
        try:
            return await request.json()
        except Exception:
            return {}

    @app.post("/api/panneau/ollama/pull")
    async def api_pull(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _ollama_pull(str(d.get("nom", "")).strip()) if d.get("nom") \
            else JSONResponse({"ok": False, "message": "nom manquant."}, 400)

    @app.post("/api/panneau/ollama/supprimer")
    async def api_suppr(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _ollama_supprimer(str(d.get("nom", "")).strip())

    @app.post("/api/panneau/ollama/tester")
    async def api_test(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _ollama_tester(str(d.get("nom", "")).strip())

    @app.post("/api/panneau/whisper/pull")
    async def api_wpull(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _whisper_installer(str(d.get("nom", "")).strip())

    @app.post("/api/panneau/whisper/supprimer")
    async def api_wsuppr(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _whisper_supprimer(str(d.get("nom", "")).strip())

    @app.post("/api/panneau/modele-actif")
    async def api_actif(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _definir_actif(d.get("backend"), str(d.get("modele", "")).strip())

    @app.post("/api/panneau/reglage")
    async def api_reglage(request: Request):
        if (r := garde(request)):
            return r
        d = await _corps(request)
        return _definir_reglage(str(d.get("cle", "")).strip(), d.get("valeur"))

    @app.post("/api/panneau/reconnecter-mcp")
    def api_reco(request: Request):
        return garde(request) or _reconnecter_mcp()

    @app.post("/api/panneau/permissions/revoquer")
    async def api_revoquer(request: Request):
        if (r := garde(request)):
            return r
        from core import registre
        nom = str((await _corps(request)).get("nom", "")).strip()
        ok = registre.revoquer(nom)
        return {"ok": ok, "message": f"« {nom} » repasse en confirmation a chaque fois."
                if ok else "Rien a revoquer pour cet outil."}

    LOG.info("panneau monte : /panneau (local uniquement)")
