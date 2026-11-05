"""Détection d'abonnements par mail (Gmail IMAP déjà configuré) — alimente le
cockpit Finances SANS credential bancaire ni API d'agrégation (doctrine).

Flux : on scanne les REÇUS des derniers mois, on en déduit service + montant +
périodicité (règles + annuaire de services connus), on écrit une proposition dans
finances/abonnements_detectes.yaml (REVUE, jamais écrasement direct), puis on
intègre dans abonnements.yaml UNIQUEMENT sur confirmation. Tout reste local.

N1 pour la détection (lecture + fichier de revue) ; N2 (confirmation) pour
l'intégration. Non exposé au MCP. Voir docs/cockpit.md.
"""
import csv
import datetime as dt
import html as _html
import imaplib
import io
import re
from pathlib import Path

import yaml

from core import transactions as tx
from core.config import reglage
from core.registre import outil

# Réutilise la config Gmail du module mail.
from tools.mail import (DELAI_MAIL_S, IMAP_SERVEUR, MAIL_ADRESSE, _corps_texte,
                        _decoder_entete, _mail_configure, _mail_mdp)

_RACINE = Path(__file__).resolve().parent.parent
_DOSSIER = _RACINE / "finances"
_ABONNEMENTS = _DOSSIER / "abonnements.yaml"
_DETECTES = _DOSSIER / "abonnements_detectes.yaml"

# Annuaire : sous-chaîne du domaine expéditeur -> (service, catégorie).
_SERVICES = {
    "apple.com": ("Apple", "Abonnements"), "itunes.com": ("Apple", "Abonnements"),
    "netflix.com": ("Netflix", "Streaming"), "spotify.com": ("Spotify", "Musique"),
    "adobe.com": ("Adobe", "Logiciels"), "disney": ("Disney+", "Streaming"),
    "youtube.com": ("YouTube Premium", "Streaming"), "deezer.com": ("Deezer", "Musique"),
    "canal": ("Canal+", "Streaming"), "microsoft.com": ("Microsoft 365", "Logiciels"),
    "openai.com": ("ChatGPT", "Logiciels"), "anthropic.com": ("Claude", "Logiciels"),
    "notion.so": ("Notion", "Logiciels"), "dropbox.com": ("Dropbox", "Cloud"),
    "amazon": ("Amazon Prime", "Abonnements"), "paramount": ("Paramount+", "Streaming"),
    "twitch.tv": ("Twitch", "Streaming"), "patreon.com": ("Patreon", "Abonnements"),
    "molotov": ("Molotov", "Streaming"), "audible": ("Audible", "Abonnements"),
    "linkedin.com": ("LinkedIn Premium", "Logiciels"), "github.com": ("GitHub", "Logiciels"),
    "figma.com": ("Figma", "Logiciels"), "google.com": ("Google One", "Cloud"),
}

_MOTS_ANNUEL = ("par an", "/an", "annuel", "yearly", "per year", "année", "annual")
_MONTANT = re.compile(
    r"(?P<d1>[€$]|eur|usd)\s*(?P<a1>\d{1,4}[.,]\d{2})"
    r"|(?P<a2>\d{1,4}[.,]\d{2})\s*(?P<d2>[€$]|eur|usd)", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_PROCESSEURS = ("stripe.com", "paypal.com", "paddle.com", "chargebee", "braintree")

# Ne PAS compter : échecs de paiement, alertes, codes, sign-in, etc.
_EXCLURE = ("unsuccessful", "failed", "declined", "echoue", "refus", "security alert",
            "sign-in", "sign in", "signin", "new sign", "verification", "verify code",
            "verification code", "trusted device", "new device", "action needed",
            "password", "reset", "welcome", "bienvenue", "confirme ton", "confirm your")
# Doit RESSEMBLER à un reçu / prélèvement.
_RECU = ("receipt", "recu", "invoice", "facture", "payment to", "subscription",
         "abonnement", "renew", "renouvel", "billed", "charged", "your bill",
         "prelevement", "paiement", "order confirmation", "payment received",
         "thanks for your payment", "merci pour ton paiement")


def _texte_message(msg):
    """Texte brut du mail ; à défaut, texte extrait du HTML (reçus souvent en HTML)."""
    plain = _corps_texte(msg)
    if plain and plain.strip():
        return plain
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_type() == "text/html":
            charge = p.get_payload(decode=True) or b""
            h = charge.decode(p.get_content_charset() or "utf-8", "replace")
            return _html.unescape(_TAGS.sub(" ", h))
    return ""


def _est_exclu(txt):
    t = txt.lower()
    return any(x in t for x in _EXCLURE)


def _est_recu(txt):
    t = txt.lower()
    return any(x in t for x in _RECU)


_GENERIQUES = {"info", "e", "noreply", "no-reply", "no reply", "support", "team",
               "contact", "billing", "hello", "mail", "news", "account", "service",
               "notifications", "notification", "receipts", "invoice", "no_reply"}


def _service_depuis(nom_exp, exp_adresse, sujet):
    # Seul le domaine (après le @) identifie le service : la partie locale et le nom
    # affiché sont écrits librement par l'expéditeur (« netflix.com@pirate.example »).
    adresse = (exp_adresse or "").lower()
    dom = adresse.rsplit("@", 1)[1] if "@" in adresse else ""
    for cle, (nom, cat) in _SERVICES.items():
        if cle in dom:
            return nom, cat
    # Nom affiché borné : il repart vers le modèle et dans le cockpit.
    nom = (nom_exp or "").strip().strip('"')[:40].strip()
    bon_nom = nom and len(nom) > 2 and nom.lower() not in _GENERIQUES
    # Stripe/PayPal/GoCardless : le vrai marchand est le NOM affiché de l'expéditeur.
    if any(p in dom for p in _PROCESSEURS) and bon_nom:
        return nom, "Autres"
    m = re.match(r"([\w-]+)\.", dom)
    if m and m.group(1).lower() not in _GENERIQUES:
        return m.group(1).capitalize(), "Autres"
    return (nom if bon_nom else "Abonnement"), "Autres"


_MOTS_RECURRENT = ("subscription", "abonnement", "recurring", "monthly", "mensuel",
                   "/mois", "par mois", "per month", "/an", "par an", "annuel",
                   "yearly", "renew", "renouvel")


def _montant(texte):
    """(montant_en_euros, devise_origine) le plus plausible. $ converti en € via
    finances.taux_usd_eur. None si rien de crédible."""
    taux = float(reglage("finances.taux_usd_eur", 0.92))
    cands = []
    for m in _MONTANT.finditer(texte):
        val = (m.group("a1") or m.group("a2") or "").replace(",", ".")
        dev = (m.group("d1") or m.group("d2") or "€").lower()
        usd = dev in ("$", "usd")
        try:
            v = float(val)
        except ValueError:
            continue
        if not (0.5 <= v <= 2000):
            continue
        eur = round(v * taux, 2) if usd else v
        avant = texte[max(0, m.start() - 40):m.start()].lower()
        prio = 2 if ("total" in avant or "montant" in avant or "debite" in avant
                     or "charged" in avant) else 1
        cands.append((prio, eur, "$" if usd else "€"))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cands[0][1], cands[0][2]


def _dossier_tous(imap):
    """Nom du dossier « Tous les messages » (Gmail \\All, localisé) ; sinon INBOX."""
    try:
        typ, boites = imap.list()
        for b in boites or []:
            ligne = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
            if "\\All" in ligne:
                m = re.search(r'"([^"]+)"\s*$', ligne) or re.search(r'([^ ]+)\s*$', ligne)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "INBOX"


def _scanner(mois):
    """Détecte les abonnements RÉCURRENTS (≥2 reçus, OU un mot-clé d'abonnement).
    Renvoie {service: {service, montant, periodicite, jour, categorie, date, devise}}."""
    par_service = {}                                 # service -> liste d'occurrences
    imap = imaplib.IMAP4_SSL(IMAP_SERVEUR, timeout=DELAI_MAIL_S)
    imap.login(MAIL_ADRESSE, _mail_mdp())
    try:
        imap.select(f'"{_dossier_tous(imap)}"')      # Tous les messages (reçus archivés inclus)
        # Requête ASCII (imaplib encode en ASCII ; Gmail est insensible aux accents).
        # Mots-clés de reçu OU expéditeurs de services connus.
        expediteurs = " OR ".join(sorted({d.split(".")[0] for d in _SERVICES}))
        requete = (f'(subject:(recu OR receipt OR abonnement OR subscription OR '
                   f'renouvellement OR renewal OR facture OR invoice OR bill OR '
                   f'prelevement OR paiement OR payment) OR from:({expediteurs})) '
                   f'newer_than:{int(mois)}m')
        # X-GM-RAW attend la requête comme UNE chaîne IMAP -> entre guillemets.
        typ, donnees = imap.uid("search", None, "X-GM-RAW", f'"{requete}"')
        ids = donnees[0].split() if donnees and donnees[0] else []
        import email as emod
        for num in ids[-200:]:                       # borne de sécurité
            _, d = imap.uid("fetch", num, "(BODY.PEEK[])")
            if not d or not d[0]:
                continue
            msg = emod.message_from_bytes(d[0][1])
            exp = _decoder_entete(msg.get("From", ""))
            adresse = re.search(r"[\w.+-]+@[\w.-]+", exp)
            adresse = adresse.group(0) if adresse else exp
            nom_exp = re.sub(r"<[^>]*>", "", exp).strip().strip('"')
            sujet = _decoder_entete(msg.get("Subject", ""))
            corps = _texte_message(msg) or ""
            blob = sujet + "\n" + corps
            if _est_exclu(sujet) or not _est_recu(blob):   # ni échec/alerte, et un vrai reçu
                continue
            res = _montant(blob)
            if res is None:
                continue
            montant, devise = res                          # montant déjà en €
            service, cat = _service_depuis(nom_exp, adresse, sujet)
            bl = (sujet + corps).lower()
            per = "annuel" if any(x in bl for x in _MOTS_ANNUEL) else "mensuel"
            kw = any(x in bl for x in _MOTS_RECURRENT)     # dit-il « abonnement » ?
            try:
                da = emod.utils.parsedate_to_datetime(msg.get("Date"))
                jour, iso = da.day, da.date().isoformat()
            except Exception:
                jour, iso = 1, ""
            par_service.setdefault(service, []).append(
                {"montant": montant, "devise": devise, "per": per, "jour": jour,
                 "date": iso, "cat": cat, "kw": kw})

        # Décision : abonnement si ≥2 reçus (récurrence) OU un mail au mot-clé explicite.
        trouves = {}
        for service, occ in par_service.items():
            recurrent = len(occ) >= 2 or any(o["kw"] for o in occ)
            if not recurrent:
                continue
            dernier = max(occ, key=lambda o: o["date"])
            per = "annuel" if any(o["per"] == "annuel" for o in occ) else "mensuel"
            trouves[service] = {"service": service, "montant": dernier["montant"],
                                "periodicite": per, "jour": dernier["jour"],
                                "categorie": dernier["cat"], "date": dernier["date"],
                                "devise": dernier["devise"], "occurrences": len(occ)}
        return trouves
    finally:
        try:
            imap.logout()
        except Exception:
            pass


# ============================================================ import CSV bancaire

def _colonne(entetes, *cands):
    for i, e in enumerate(entetes):
        en = re.sub(r"[^a-z]", "", e.lower())
        for c in cands:
            if c in en:
                return i
    return None


def _nombre(s):
    """Montant d'un export bancaire : « -45,10 », « 1 234,56 », « 1.234,56 »,
    « 1,234.56 », « 12,99- » (signe final). None si illisible."""
    s = str(s or "").strip().replace(" ", "").replace(" ", "")
    for blanc in (" ", " "):
        s = s.replace(blanc, "")                    # espaces U+00A0 et U+2009
    if s.endswith("-") and not s.startswith("-"):
        s = "-" + s[:-1]                                # signe final -> devant
    if "," in s and "." in s:
        # Le dernier separateur rencontre est la decimale, l'autre les milliers.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _date_iso(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parser_csv(texte):
    """Détecte le séparateur + les colonnes (date, libellé, montant OU débit/crédit).
    Renvoie (transactions, nombre de lignes de données illisibles ignorées)."""
    sep = ";" if texte[:2000].count(";") >= texte[:2000].count(",") else ","
    lignes = list(csv.reader(io.StringIO(texte), delimiter=sep))
    # trouve la ligne d'en-tête (celle qui contient 'date')
    idx = next((i for i, l in enumerate(lignes[:15])
                if any("date" in c.lower() for c in l)), 0)
    entetes = lignes[idx]
    ic = _colonne(entetes, "date")
    il = _colonne(entetes, "libelle", "label", "description", "nature", "detail")
    im = _colonne(entetes, "montant", "amount")
    idb = _colonne(entetes, "debit")
    icr = _colonne(entetes, "credit")
    trans = []
    ignorees = 0
    for l in lignes[idx + 1:]:
        if not any(str(c).strip() for c in l):
            continue                                       # ligne vide
        if ic is not None and ic >= len(l):
            ignorees += 1
            continue
        date = _date_iso(l[ic]) if ic is not None else None
        lib = l[il].strip() if (il is not None and il < len(l)) else ""
        if im is not None and im < len(l):
            montant = _nombre(l[im])
        else:
            deb = _nombre(l[idb]) if (idb is not None and idb < len(l)) else None
            cred = _nombre(l[icr]) if (icr is not None and icr < len(l)) else None
            # Certaines banques ecrivent le debit en negatif dans la colonne Debit :
            # le sens vient de la colonne, pas du signe.
            montant = (abs(cred or 0) - abs(deb or 0)
                       if (deb is not None or cred is not None) else None)
        if date and lib and montant is not None:
            trans.append({"date": date, "libelle": lib, "montant": round(montant, 2),
                          "source": "csv"})
        else:
            ignorees += 1
    return trans, ignorees


@outil(
    nom="importer_releve",
    description="Importe un relevé bancaire CSV (export de ta banque) dans le cockpit : "
                "dépenses/rentrées catégorisées, localement. Pour « importe mon relevé », "
                "« ajoute mes transactions ». Sans chemin, prend le dernier CSV du dossier "
                "surveillé (finances.dossier_csv).",
    parametres={
        "type": "object",
        "properties": {
            "chemin": {"type": "string", "description": "Chemin du fichier CSV "
                       "(optionnel ; vide = le plus récent du dossier surveillé)."}
        },
    },
    lent=True,
    phrase_attente="J'importe ton relevé.",
    mcp_expose=False,
    affichage="toujours",
)
def importer_releve(chemin: str = "") -> str:
    p = None
    if chemin and chemin.strip():
        p = Path(chemin.strip()).expanduser()
    else:
        dossier = _RACINE / reglage("finances.dossier_csv", "finances/releves")
        csvs = sorted(dossier.glob("*.csv"), key=lambda x: x.stat().st_mtime) \
            if dossier.exists() else []
        p = csvs[-1] if csvs else None
    if not p or not p.exists():
        return ("Je n'ai pas trouvé de CSV. Dépose ton export bancaire dans "
                "finances/releves/, ou précise le chemin.")
    try:
        texte = p.read_text(encoding="utf-8-sig", errors="replace")
        trans, ignorees = _parser_csv(texte)
    except Exception as e:
        return f"Lecture du CSV impossible ({str(e)[:100]})."
    if not trans:
        return "Aucune transaction lisible dans ce fichier (colonnes date/libellé/montant ?)."
    n = tx.ajouter(trans)
    v = tx.vue_mois()
    illisibles = (f" {ignorees} ligne(s) illisible(s) ignorée(s)." if ignorees else "")
    return (f"Importé : {n} nouvelles transactions sur {len(trans)} lues.{illisibles} Ce mois : "
            f"{v['sorties']:.0f} € de sorties, {v['entrees']:.0f} € de rentrées "
            f"(solde {v['solde']:+.0f} €).")


@outil(
    nom="corriger_categorie",
    description="Corrige/mémorise la catégorie d'un type de transaction (retenu pour la "
                "suite). Pour « range X en Y », « les paiements Truc c'est la catégorie "
                "Machin ».",
    parametres={
        "type": "object",
        "properties": {
            "motif": {"type": "string", "description": "Mot-clé du libellé (ex. 'uber')."},
            "categorie": {"type": "string", "description": "La catégorie à appliquer."},
        },
        "required": ["motif", "categorie"],
    },
    mcp_expose=False,
)
def corriger_categorie(motif: str, categorie: str) -> str:
    try:
        tx.memoriser_regle(motif, categorie)
    except ValueError:
        return "Précise le libellé à reconnaître."
    return f"C'est noté : « {motif} » ira dans « {categorie} » (rétroactif)."


@outil(
    nom="detecter_abonnements",
    description="Cherche mes abonnements dans mes mails (reçus Apple, Netflix, Spotify, "
                "Adobe…) et propose de mettre à jour le cockpit. Pour « détecte mes "
                "abonnements », « cherche mes abonnements dans mes mails », « scanne "
                "mes reçus ». N'écrit rien dans mes abonnements sans confirmation.",
    parametres={
        "type": "object",
        "properties": {
            "mois": {"type": "integer",
                     "description": "Profondeur de recherche en mois (défaut 6)."}
        },
    },
    lent=True,
    phrase_attente="Je fouille tes reçus dans tes mails.",
    mcp_expose=False,
    affichage="toujours",
)
def detecter_abonnements(mois: int = 6) -> str:
    if not _mail_configure():
        return "La messagerie n'est pas configurée (mail.adresse / mot de passe d'app)."
    try:
        trouves = _scanner(max(1, min(int(mois or 6), 24)))
    except Exception as e:
        return f"Le scan des mails a échoué ({str(e)[:120]})."
    if not trouves:
        return "Je n'ai trouvé aucun reçu d'abonnement dans tes mails récents."
    _DOSSIER.mkdir(parents=True, exist_ok=True)
    liste = sorted(trouves.values(), key=lambda x: -x["montant"])
    _DETECTES.write_text(yaml.safe_dump(liste, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
    apercu = ", ".join(f"{a['service']} {a['montant']:.2f}€" for a in liste[:6])
    suite = "" if len(liste) <= 6 else f" et {len(liste) - 6} autres"
    return (f"J'ai trouvé {len(liste)} abonnements : {apercu}{suite}. Ils sont dans "
            "abonnements_detectes.yaml. Dis « intègre-les » pour les ajouter au cockpit.")


@outil(
    nom="integrer_abonnements_detectes",
    description="Ajoute au cockpit les abonnements détectés dans les mails (fichier de "
                "revue abonnements_detectes.yaml). Pour « intègre-les », « ajoute les "
                "abonnements détectés », « valide mes abonnements ».",
    confirmation=True,
    annonce=lambda a: "Je vais ajouter les abonnements détectés à ton cockpit.",
    mcp_expose=False,
)
def integrer_abonnements_detectes() -> str:
    if not _DETECTES.exists():
        return "Aucune détection en attente. Lance d'abord « détecte mes abonnements »."
    detectes = yaml.safe_load(_DETECTES.read_text(encoding="utf-8")) or []
    existants = []
    if _ABONNEMENTS.exists():
        existants = yaml.safe_load(_ABONNEMENTS.read_text(encoding="utf-8")) or []
    noms = {str(a.get("service", "")).lower() for a in existants if isinstance(a, dict)}
    ajoutes = 0
    for a in detectes:
        if str(a.get("service", "")).lower() in noms:
            continue                                 # ne remplace pas un existant manuel
        existants.append({k: a[k] for k in ("service", "montant", "periodicite",
                                            "jour", "categorie") if k in a})
        ajoutes += 1
    _ABONNEMENTS.write_text(yaml.safe_dump(existants, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
    if not ajoutes:
        return "Tous les abonnements détectés étaient déjà dans ton cockpit."
    return f"C'est fait, j'ai ajouté {ajoutes} abonnement(s) au cockpit."
