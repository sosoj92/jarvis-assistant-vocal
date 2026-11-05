"""Transactions bancaires — stockage LOCAL + catégorisation + vue mois. Fondation
provider-agnostique : alimentée par un import CSV (dès aujourd'hui) et, plus tard,
par un fournisseur PSD2 (Enable Banking) qui appendra ici. Rien ne sort.

DOCTRINE : transactions 100% locales (finances/, gitignoré), jamais exposées au MCP ;
Hermes ne reçoit que des AGRÉGATS (bilan mensuel). Aucun mot de passe bancaire ici.

Format d'une transaction (une par ligne dans finances/transactions.jsonl) :
  {"date":"AAAA-MM-JJ", "libelle": "...", "montant": -12.99, "categorie":"...",
   "source":"csv"|"enablebanking", "id":"<hash>"}
montant : négatif = dépense, positif = rentrée.
"""
import collections
import datetime as dt
import hashlib
import json
import logging
import re
from pathlib import Path

import yaml

from core.util import sans_accents

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent
_DOSSIER = _RACINE / "finances"
_FICHIER = _DOSSIER / "transactions.jsonl"
_REGLES = _DOSSIER / "regles_categorisation.yaml"   # corrections mémorisées (perso)

# Règles par défaut : sous-chaîne (sans accents, minuscule) du libellé -> catégorie.
_REGLES_DEFAUT = {
    "carrefour": "Courses", "leclerc": "Courses", "lidl": "Courses", "auchan": "Courses",
    "monoprix": "Courses", "franprix": "Courses", "intermarche": "Courses",
    "uber eats": "Restauration", "deliveroo": "Restauration", "mcdonald": "Restauration",
    "restaurant": "Restauration", "boulangerie": "Restauration",
    "sncf": "Transport", "uber": "Transport", "ratp": "Transport", "total": "Carburant",
    "essence": "Carburant", "amazon": "Shopping", "fnac": "Shopping", "zalando": "Shopping",
    "netflix": "Abonnements", "spotify": "Abonnements", "apple.com": "Abonnements",
    "google": "Abonnements", "canal": "Abonnements", "adobe": "Abonnements",
    "edf": "Énergie", "engie": "Énergie", "octopus": "Énergie", "veolia": "Énergie",
    "free": "Téléphonie", "orange": "Téléphonie", "sfr": "Téléphonie", "bouygues": "Téléphonie",
    "loyer": "Logement", "assurance": "Assurances", "mutuelle": "Santé", "pharmacie": "Santé",
    "salaire": "Revenus", "virement recu": "Revenus", "remboursement": "Revenus",
}


def _norm(s):
    return sans_accents(str(s or "").lower())


# ------------------------------------------------------------ catégorisation

def _regles():
    r = dict(_REGLES_DEFAUT)
    if _REGLES.exists():
        try:
            r.update(yaml.safe_load(_REGLES.read_text(encoding="utf-8")) or {})
        except Exception:
            pass
    return r


def _correspond(cle, lib):
    """Sous-chaîne pour les clés de 3 caractères ou plus ; mot entier pour les
    plus courtes (« bp » touche « CB BP 1234 », « ca » ne touche pas CASTORAMA)."""
    k = _norm(cle).strip()
    if not k:
        return False
    if len(k) >= 3:
        return k in lib
    return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", lib) is not None


def categoriser(libelle, montant=0.0):
    """Catégorie d'une transaction via les règles (perso prioritaires)."""
    lib = _norm(libelle)
    # les règles perso les plus longues (spécifiques) d'abord
    for cle in sorted(_regles(), key=len, reverse=True):
        if _correspond(cle, lib):
            return _regles()[cle]
    return "Revenus" if float(montant or 0) > 0 else "Non catégorisé"


def memoriser_regle(motif, categorie):
    """Mémorise une correction : « ce libellé (motif) => cette catégorie ».
    ValueError si le motif est vide (il toucherait toutes les transactions)."""
    motif = str(motif or "").strip()
    if not _norm(motif).strip():
        raise ValueError("motif vide")
    perso = {}
    if _REGLES.exists():
        try:
            perso = yaml.safe_load(_REGLES.read_text(encoding="utf-8")) or {}
        except Exception:
            perso = {}
    perso[str(motif)] = str(categorie)
    _DOSSIER.mkdir(parents=True, exist_ok=True)
    _REGLES.write_text(yaml.safe_dump(perso, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")


# ------------------------------------------------------------ stockage

def _id(t, rang=0):
    """Identifiant de déduplication. rang = k-ième occurrence identique (même date,
    libellé, montant) dans le relevé importé : deux cafés le même jour restent deux
    transactions. Le rang 0 garde l'ancienne formule (ids déjà stockés)."""
    brut = f"{t.get('date')}|{_norm(t.get('libelle'))}|{t.get('montant')}"
    if rang:
        brut += f"|{rang}"
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:16]


def charger():
    if not _FICHIER.exists():
        return []
    out = []
    for ligne in _FICHIER.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne:
            try:
                out.append(json.loads(ligne))
            except Exception:
                pass
    return out


def ajouter(transactions):
    """Ajoute des transactions (déduplique par id, catégorise si besoin). Renvoie le
    nombre de nouvelles."""
    existantes = charger()
    vus = {t.get("id") for t in existantes}
    rangs = collections.Counter()      # occurrences identiques dans ce lot
    nouvelles = []
    for t in transactions:
        t = dict(t)
        if not t.get("categorie"):
            t["categorie"] = categoriser(t.get("libelle"), t.get("montant"))
        cle = (t.get("date"), _norm(t.get("libelle")), t.get("montant"))
        t["id"] = _id(t, rangs[cle])
        rangs[cle] += 1
        if t["id"] in vus:
            continue
        vus.add(t["id"])
        nouvelles.append(t)
    if nouvelles:
        _DOSSIER.mkdir(parents=True, exist_ok=True)
        with open(_FICHIER, "a", encoding="utf-8") as f:
            for t in nouvelles:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return len(nouvelles)


# ------------------------------------------------------------ agrégats (cockpit)

def _mois(iso):
    return str(iso or "")[:7]


def vue_mois(mois=None):
    """Entrées / sorties du mois + ventilation par catégorie."""
    mois = mois or dt.date.today().strftime("%Y-%m")
    entrees = sorties = 0.0
    par_cat = {}
    for t in charger():
        if _mois(t.get("date")) != mois:
            continue
        m = float(t.get("montant") or 0)
        cat = categoriser(t.get("libelle"), m)      # dynamique : corrections rétroactives
        c = par_cat.setdefault(cat, {"entrees": 0.0, "sorties": 0.0})
        if m >= 0:
            entrees += m
            c["entrees"] = round(c["entrees"] + m, 2)
        else:
            sorties += -m
            c["sorties"] = round(c["sorties"] + -m, 2)
    return {
        "mois": mois, "entrees": round(entrees, 2), "sorties": round(sorties, 2),
        "solde": round(entrees - sorties, 2),
        "par_categorie": dict(sorted(par_cat.items(),
                                     key=lambda kv: -(kv[1]["sorties"]))),
    }


def abonnements_recurrents(min_mois=2):
    """Détecte les prélèvements RÉCURRENTS (même marchand, montant proche, ≥ min_mois
    mois distincts) -> vrais abonnements, montant et jour EXACTS. Meilleur que les mails."""
    import re
    groupes = {}
    for t in charger():
        m = float(t.get("montant") or 0)
        if m >= 0:
            continue                                   # seulement les dépenses
        cle = _norm(t.get("libelle"))
        cle = re.sub(r"\d+", "", cle).strip()          # enlève dates/numéros de la clé
        cle = re.sub(r"\s+", " ", cle)[:40]
        if len(cle) < 3:
            continue
        groupes.setdefault(cle, []).append(
            {"montant": round(-m, 2), "date": t.get("date"),
             "libelle": t.get("libelle"), "cat": t.get("categorie")})
    recurrents = []
    for cle, occ in groupes.items():
        mois_distincts = {_mois(o["date"]) for o in occ}
        if len(mois_distincts) < min_mois:
            continue
        montants = sorted(o["montant"] for o in occ)
        median = montants[len(montants) // 2]
        # montant stable (variation < 15%) => abonnement à prix fixe
        stable = all(abs(o["montant"] - median) <= max(1.0, median * 0.15) for o in occ)
        dernier = max(occ, key=lambda o: o["date"])
        recurrents.append({
            "service": dernier["libelle"], "montant": median,
            "categorie": categoriser(dernier["libelle"], -median), "occurrences": len(occ),
            "mois": len(mois_distincts), "stable": stable,
            "jour": int(str(dernier["date"])[8:10] or 1),
        })
    return sorted(recurrents, key=lambda x: -x["montant"])
