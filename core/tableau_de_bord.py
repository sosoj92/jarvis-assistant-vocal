"""Tableau de bord du HUD : tuiles en lecture seule, rafraichies en fond.

Au repos, la fenetre Jarvis (hud.html) reduit le reacteur et affiche ces tuiles
facon Echo Show. Ce module les assemble a partir des outils existants (agenda,
factures, Loopstr, Instagram, Discord, colis, meteo, Spotify) et les publie au HUD
via hud.tableau().

Regles :
  - lecture seule (N1) : aucune action, aucun @outil, donc rien d'expose au MCP ;
  - chaque source a son propre delai de rafraichissement (les factures, lues par
    navigateur, une fois par heure par defaut) : afficher le tableau ne declenche
    jamais de lecture ;
  - une source en echec donne une tuile « indisponible » sans toucher les autres ;
  - les tuiles ne contiennent que des resumes (compteurs, titres courts), jamais
    de secret ; les erreurs ne sont journalisees que par leur type.

Les sources lisent la configuration du processus qui les fait tourner : en local
(jarvis14.py), config.yaml ; dans l'agent du bureau, desktop_agent/config.yaml.
Voir docs/tableau_de_bord.md.
"""
import datetime as dt
import json
import logging
import re
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent

# Etats d'une tuile, interpretes tels quels par hud.html.
OK = "ok"
VIDE = "vide"
INDISPONIBLE = "indisponible"
NON_CONFIGURE = "non_configure"

_MAX_LIGNES = 5
_PAS_BOUCLE = 20.0          # secondes entre deux tours de la boucle de fond
_REESSAI_ECHEC = 300.0      # une source en echec est retentee apres 5 min au plus


class NonConfigure(Exception):
    """La source n'est pas configuree dans ce processus (message affichable)."""


@dataclass
class Source:
    id: str
    titre: str
    lire: Callable[[], dict]    # renvoie les champs d'une tuile ; leve en cas d'echec
    ttl: float                  # secondes entre deux lectures reussies


def _texte(valeur, longueur=70):
    return " ".join(str(valeur or "").split())[:longueur]


# Emoji et pictogrammes : « 🚀 Marque — Publication », « 💬・général ». Ils
# ornent les noms chez Loopstr ou Discord mais ne sont pas des elements d'interface.
_DECOR = {"‍", "︎", "️", "⃣"}
_SEPARATEURS_TETE = "・·•|｜-–—:_~ "


def _propre(valeur, longueur=70):
    """Texte sans emoji ni separateur decoratif en tete (« 💬・général » -> « général »)."""
    sans = "".join(c for c in str(valeur or "")
                   if c not in _DECOR and not 0x1F3FB <= ord(c) <= 0x1F3FF
                   and unicodedata.category(c) not in ("So", "Cs", "Co", "Cn"))
    return _texte(sans.strip().lstrip(_SEPARATEURS_TETE).strip(), longueur)


def _marque_tache(titre):
    """« 🚀 Marque — Publication » -> ("Marque", "Publication")."""
    propre = _propre(titre, 90)
    morceaux = re.split(r"\s+[—–-]\s+", propre, maxsplit=1)
    return (morceaux[0], morceaux[1]) if len(morceaux) == 2 else (propre, "")


def _ligne(texte, detail="", alerte=False):
    return {"texte": _texte(texte), "detail": _texte(detail, 50), "alerte": bool(alerte)}


def _heure(maintenant):
    return maintenant.strftime("%H:%M")


class Assembleur:
    """Cache de tuiles : chaque source est relue seulement quand son delai est passe.

    horloge (monotone) et maintenant (date locale) sont injectables pour les tests.
    """

    def __init__(self, sources, horloge=time.monotonic,
                 maintenant=lambda: dt.datetime.now().astimezone()):
        self.sources = list(sources)
        self._horloge = horloge
        self._maintenant = maintenant
        self._tuiles = {}
        self._prochaine = {}
        self._derniere_reussite = {}
        self._verrou = threading.Lock()

    def _lire(self, source):
        maintenant = self._maintenant()
        base = {"id": source.id, "titre": source.titre, "maj": _heure(maintenant)}
        try:
            champs = dict(source.lire() or {})
        except NonConfigure as e:
            return {**base, "etat": NON_CONFIGURE, "message": _texte(e, 120)}, source.ttl
        except Exception as e:
            # Le type seul : un message d'erreur peut contenir une URL a jeton.
            LOG.info("tableau: source %s indisponible (%s)", source.id, type(e).__name__)
            message = "Indisponible pour le moment."
            if source.id in self._derniere_reussite:
                message += f" Dernière lecture à {self._derniere_reussite[source.id]}."
            return ({**base, "etat": INDISPONIBLE, "message": message},
                    min(source.ttl, _REESSAI_ECHEC))
        lignes = [l for l in champs.get("lignes", []) if isinstance(l, dict)][:_MAX_LIGNES]
        tuile = {
            **base,
            "etat": champs.get("etat") or (OK if lignes or champs.get("valeur") else VIDE),
            "valeur": _texte(champs.get("valeur"), 12),
            "legende": _texte(champs.get("legende"), 40),
            "lignes": lignes,
            "message": _texte(champs.get("message"), 120),
        }
        # Donnees structurees pour l'affichage (facultatives) : lignes/valeur restent
        # le resume lisible par toute fenetre, meme ancienne.
        if isinstance(champs.get("donnees"), dict):
            tuile["donnees"] = champs["donnees"]
        if tuile["etat"] in (OK, VIDE):          # « Chrome fermé » n'est pas une lecture
            self._derniere_reussite[source.id] = base["maj"]
        return tuile, source.ttl

    def rafraichir(self, force=False, publier=None):
        """Relit les sources dont le delai est passe. Renvoie True si une tuile a change.

        publier(tuiles), s'il est donne, est appele apres chaque tuile changee : une
        source lente (factures) ne retarde pas l'affichage des autres."""
        change = False
        for source in self.sources:
            if not force and self._horloge() < self._prochaine.get(source.id, 0.0):
                continue
            tuile, delai = self._lire(source)
            self._prochaine[source.id] = self._horloge() + delai
            with self._verrou:
                avant = self._tuiles.get(source.id)
                self._tuiles[source.id] = tuile
            if avant != tuile:
                change = True
                if publier is not None:
                    publier(self.tuiles())
        return change

    def tuiles(self):
        """Tuiles connues, dans l'ordre des sources."""
        with self._verrou:
            return [dict(self._tuiles[s.id]) for s in self.sources if s.id in self._tuiles]


# ------------------------------------------------------------------ sources


def _reglage(chemin, defaut=None):
    from core.config import reglage
    return reglage(chemin, defaut)


def _jour(d, maintenant):
    """aujourd'hui / demain / mer. 22, pour une date locale."""
    ecart = (d.date() - maintenant.date()).days
    if ecart == 0:
        return "aujourd'hui"
    if ecart == 1:
        return "demain"
    jours = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
    return f"{jours[d.weekday()]} {d.day}"


def _service_agenda():
    """Service Google Agenda sans jamais lancer le flux OAuth interactif.

    tools.agenda._service() ouvre un navigateur si le jeton manque : depuis un
    thread de fond, ce serait une fenetre surprise et un thread bloque."""
    from tools import agenda
    if agenda._SERVICE is not None:
        return agenda._SERVICE
    fichier = agenda._chemin("agenda.token", "google_token.json")
    if not fichier.exists():
        raise NonConfigure("Agenda Google non relié sur ce poste.")
    from google.oauth2.credentials import Credentials
    jeton = Credentials.from_authorized_user_file(str(fichier), agenda.SCOPES)
    if not jeton.valid and not (jeton.expired and jeton.refresh_token):
        if agenda._serveur_sans_peripheriques():
            # Personne ne peut consentir sur ce poste sans ecran.
            raise NonConfigure("Agenda Google à reconnecter depuis un poste avec écran "
                               "(uv run python -m tools.agenda), puis copier "
                               "google_token.json sur le serveur.")
        raise NonConfigure("Agenda Google à reconnecter : demande-moi ton agenda à la voix.")
    return agenda._service(interactif=False)


def source_agenda(maintenant=None):
    from tools import agenda
    service = _service_agenda()
    maintenant = maintenant or dt.datetime.now().astimezone()
    fin = maintenant + dt.timedelta(days=7)
    evenements = []
    for cid, info in agenda._calendriers(service).items():
        if agenda._est_loopstr(info.get("nom", "")):
            continue                          # deja dans la tuile Loopstr
        try:
            res = service.events().list(
                calendarId=cid, timeMin=maintenant.isoformat(), timeMax=fin.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=10).execute()
        except Exception:
            continue
        for e in res.get("items", []):
            d, tout_jour = agenda._debut_ev(e)
            if d is not None:
                evenements.append((d, tout_jour, e.get("summary", "(sans titre)")))
    evenements.sort(key=lambda x: x[0])
    if not evenements:
        return {"etat": VIDE, "message": "Rien de prévu ces 7 prochains jours.",
                "donnees": {"evenements": []}}
    du_jour = sum(1 for d, _, _ in evenements if d.date() == maintenant.date())
    lignes = []
    for d, tout_jour, titre in evenements[:_MAX_LIGNES]:
        quand = _jour(d, maintenant) + ("" if tout_jour else " · " + agenda._heure_fr(d))
        lignes.append(_ligne(_propre(titre), quand, alerte=d.date() == maintenant.date()))
    donnees = {"evenements": [{"debut": d.isoformat(), "tout_jour": bool(tout_jour),
                               "titre": _propre(titre)} for d, tout_jour, titre in evenements[:12]]}
    return {"valeur": str(du_jour), "legende": "aujourd'hui", "lignes": lignes,
            "donnees": donnees}


def lire_factures_isole(url, port, timeout=90):
    """Lance core.tableau_factures dans un processus a part et renvoie son resume."""
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    fini = subprocess.run(
        [sys.executable, "-m", "core.tableau_factures"],
        input=json.dumps({"url": url, "port": port}), capture_output=True,
        text=True, encoding="utf-8", timeout=timeout, cwd=str(_RACINE), **options)
    sortie = [l for l in (fini.stdout or "").splitlines() if l.strip()]
    if not sortie:
        raise RuntimeError("lecteur de factures sans reponse")
    return json.loads(sortie[-1])


def _euros(montant):
    entier = f"{montant:,.0f}".replace(",", " ") if montant >= 100 else \
        f"{montant:.2f}".replace(".", ",").replace(",00", "")
    return entier + " €"


def source_factures(lecteur=lire_factures_isole):
    url = str(_reglage("factures.url", "") or "").strip()
    if not url:
        raise NonConfigure("Adresse facture.net absente (factures.url).")
    port = int(_reglage("navigateur.cdp_port", 9222) or 9222)
    resume = lecteur(url, port)
    etat = resume.get("etat")
    if etat == "chrome_ferme":
        return {"etat": INDISPONIBLE,
                "message": "Ouvre « Chrome + Jarvis » pour que je lise facture.net."}
    if etat == "session_expiree":
        return {"etat": INDISPONIBLE,
                "message": "Session facture.net expirée : reconnecte-toi dans ChromeJarvis."}
    if etat != "ok":
        raise RuntimeError(f"factures: {etat}")
    donnees = {cle: {"nombre": (resume.get(cle) or {}).get("nombre"),
                     "montant": (resume.get(cle) or {}).get("montant")} if resume.get(cle) else None
               for cle in ("impayees", "retard")}
    donnees["aucun"] = bool(resume.get("aucun"))
    libelles = {"retard": ("en retard", "en retard"), "impayees": ("impayée", "impayées")}
    lignes, montants = [], {}
    for cle in ("retard", "impayees"):
        indicateur = resume.get(cle)
        if not indicateur:
            continue
        nombre, montant = indicateur.get("nombre"), indicateur.get("montant")
        singulier, pluriel = libelles[cle]
        if nombre is None:
            texte = pluriel.capitalize()
        else:
            texte = f"{nombre} facture{'s' if nombre > 1 else ''} " \
                    f"{pluriel if nombre > 1 else singulier}"
        lignes.append(_ligne(texte, _euros(montant) if montant is not None else "",
                             alerte=cle == "retard"))
        if montant is not None:
            montants[cle] = montant
    if not lignes:
        if resume.get("aucun"):
            return {"etat": OK, "valeur": "0", "legende": "impayée",
                    "message": "Aucune facture impayée.", "donnees": donnees}
        return {"etat": VIDE, "message": "Aucun impayé repéré sur le tableau de bord. "
                                         "Demande-moi « où en sont mes factures »."}
    if "impayees" in montants:
        valeur, legende = _euros(montants["impayees"]), "à encaisser"
    elif "retard" in montants:
        valeur, legende = _euros(montants["retard"]), "en retard"
    else:
        valeur, legende = "", ""
    return {"valeur": valeur, "legende": legende, "lignes": lignes, "donnees": donnees}


def source_loopstr(maintenant=None):
    from tools import loopstr
    if not _reglage("loopstr.url", ""):
        raise NonConfigure("Flux Loopstr non configuré (loopstr.url).")
    evenements = loopstr._charger() or []
    maintenant = maintenant or dt.datetime.now().astimezone()
    minuit = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = minuit + dt.timedelta(days=14)
    echeances = [(d, t) for d, typ, t in evenements
                 if typ == "deadline" and minuit <= d < fin]
    if not echeances:
        return {"etat": VIDE, "message": "Aucune échéance de partenariat sur 14 jours.",
                "donnees": {"echeances": []}}
    semaine = sum(1 for d, _ in echeances if d < minuit + dt.timedelta(days=7))
    lignes = [_ligne(_propre(t), _jour(d, maintenant),
                     alerte=(d.date() - maintenant.date()).days <= 1)
              for d, t in echeances[:_MAX_LIGNES]]
    donnees = {"echeances": []}
    for d, t in echeances[:12]:
        marque, tache = _marque_tache(t)
        donnees["echeances"].append({"debut": d.isoformat(), "marque": marque, "tache": tache})
    return {"valeur": str(semaine), "legende": "sur 7 jours", "lignes": lignes,
            "donnees": donnees}


def source_instagram(aujourd_hui=None):
    """Abonnes de chaque compte et variation depuis le dernier releve.

    Un seul appel par compte (pas les insights des videos) ; l'historique de
    instagram_resume est lu, jamais ecrit."""
    from tools import instagram
    comptes = instagram._comptes()
    if not comptes:
        raise NonConfigure("Instagram non configuré.")
    aujourd_hui = aujourd_hui or dt.date.today()
    historique = instagram._charger_historique()
    lignes, total, connu, echecs, fiches = [], 0, False, 0, []
    for compte in comptes:
        try:
            infos = instagram._get(compte["user_id"], compte["token"],
                                   fields="username,followers_count,media_count")
        except Exception:
            echecs += 1
            lignes.append(_ligne(compte["nom"], "lecture impossible", alerte=True))
            fiches.append({"compte": _texte(compte["nom"], 40), "abonnes": None,
                           "delta": None, "depuis": None, "serie": [], "erreur": True})
            continue
        abonnes = infos.get("followers_count")
        qui = f"@{infos['username']}" if infos.get("username") else compte["nom"]
        detail = f"{abonnes} abonnés" if abonnes is not None else "abonnés inconnus"
        par_jour = historique.get(compte["nom"], {}) or {}
        passes = [j for j in sorted(par_jour) if j < aujourd_hui.isoformat()]
        avant = (par_jour[passes[-1]] or {}).get("abonnes") if passes else None
        ecart, quand = None, None
        if abonnes is not None and avant is not None:
            ecart = int(abonnes) - int(avant)
            hier = (aujourd_hui - dt.timedelta(days=1)).isoformat()
            quand = "hier" if passes[-1] == hier else \
                "le " + dt.date.fromisoformat(passes[-1]).strftime("%d/%m")
            detail += f" · {ecart:+d} depuis {quand}"
            total += ecart
            connu = True
        lignes.append(_ligne(qui, detail))
        # Courbe : releves quotidiens de instagram_resume (30 derniers) + valeur du jour.
        serie = [int(v["abonnes"]) for v in (par_jour[j] or {} for j in passes[-29:])
                 if isinstance(v.get("abonnes"), int)]
        if abonnes is not None:
            serie.append(int(abonnes))
        fiches.append({"compte": _texte(infos.get("username") or compte["nom"], 40),
                       "abonnes": abonnes, "delta": ecart, "depuis": quand,
                       "serie": serie if len(serie) >= 2 else []})
    if echecs == len(comptes):
        raise RuntimeError("instagram: aucun compte lisible")
    donnees = {"comptes": fiches}
    if connu:
        return {"valeur": f"{total:+d}", "legende": "abonnés", "lignes": lignes,
                "donnees": donnees}
    return {"lignes": lignes, "donnees": donnees}


def source_discord():
    """Volumes et mentions des dernieres 24 h, sans aucun contenu de message."""
    from tools import discord_bot
    if not discord_bot._configure():
        raise NonConfigure("Bot Discord non configuré.")
    stats, erreur = discord_bot.digest_journal(heures=24, attente_s=10.0)
    if erreur or not stats:
        raise RuntimeError("discord: scan impossible")
    mentions = int(stats.get("mentions", 0))
    lignes = [_ligne(f"{stats.get('messages', 0)} messages",
                     f"{stats.get('salons', 0)} salon(s) actifs")]
    serveurs = {}
    for actif in stats.get("actifs", []):
        salon, serveur = _propre(actif.get("salon", ""), 40), _propre(actif.get("serveur", ""), 40)
        if len(lignes) < _MAX_LIGNES:
            lignes.append(_ligne(f"#{salon}", f"{actif.get('messages', 0)} msg · {serveur}"))
        serveurs.setdefault(serveur, []).append(
            {"nom": salon, "messages": int(actif.get("messages", 0))})
    donnees = {"mentions": mentions, "messages": int(stats.get("messages", 0)),
               "salons": int(stats.get("salons", 0)),
               "serveurs": [{"nom": nom, "salons": salons} for nom, salons in serveurs.items()]}
    return {"valeur": str(mentions), "legende": "mention(s) 24 h", "lignes": lignes,
            "donnees": donnees}


def source_colis():
    from tools import colis, mail
    if not mail._mail_configure():
        raise NonConfigure("Messagerie non configurée.")
    en_cours = colis.colis_en_cours()
    if not en_cours:
        return {"etat": VIDE, "message": "Aucun colis en route."}
    libelles = {cle: texte for cle, texte, _ in colis._ETAPES}
    lignes = [_ligne(c["marchand"], libelles.get(c["etape"], ""),
                     alerte=c["etape"] in ("livraison", "relais"))
              for c in en_cours[:_MAX_LIGNES]]
    donnees = {"colis": [{"marchand": _propre(c["marchand"], 40), "etape": c["etape"],
                          "libelle": libelles.get(c["etape"], "")} for c in en_cours[:8]]}
    return {"valeur": str(len(en_cours)), "legende": "en cours", "lignes": lignes,
            "donnees": donnees}


def source_meteo():
    from tools import meteo
    d = meteo._open_meteo("current=temperature_2m,weather_code"
                          "&daily=temperature_2m_min,temperature_2m_max,"
                          "precipitation_probability_max&forecast_days=1")
    actuel, jour = d["current"], d.get("daily", {})
    ciel = meteo._CODES_METEO.get(actuel.get("weather_code"), "temps variable")
    lignes = []
    donnees = {"temperature": round(actuel["temperature_2m"]), "ciel": ciel,
               "code": actuel.get("weather_code"), "lieu": _texte(meteo._LIEU.get("ville"), 40),
               "min": None, "max": None, "pluie": None}
    try:
        donnees["min"] = round(jour["temperature_2m_min"][0])
        donnees["max"] = round(jour["temperature_2m_max"][0])
        lignes.append(_ligne(meteo._LIEU.get("ville") or "Aujourd'hui",
                             f"{donnees['min']}° / {donnees['max']}°"))
        pluie = jour.get("precipitation_probability_max", [None])[0]
        if pluie is not None:
            donnees["pluie"] = pluie
            lignes.append(_ligne("Pluie", f"{pluie} %", alerte=pluie >= 60))
    except (KeyError, IndexError, TypeError):
        pass
    return {"valeur": f"{round(actuel['temperature_2m'])}°", "legende": ciel,
            "lignes": lignes, "donnees": donnees}


def source_spotify():
    from tools import spotify
    if not spotify._configure():
        raise NonConfigure("Spotify non connecté.")
    etat = spotify._etat_lecture()
    morceau = (etat or {}).get("item") or {}
    if not morceau:
        return {"etat": VIDE, "message": "Rien en lecture."}
    artistes = ", ".join(a.get("name", "") for a in morceau.get("artists", [])[:2])
    appareil = ((etat.get("device") or {}).get("name")) or ""
    statut = "en lecture" if etat.get("is_playing") else "en pause"
    donnees = {"titre": _texte(morceau.get("name"), 80), "artistes": _texte(artistes, 80),
               "appareil": _texte(appareil, 40), "lecture": bool(etat.get("is_playing"))}
    return {"etat": OK, "lignes": [_ligne(morceau.get("name", ""), artistes),
                                   _ligne(statut.capitalize(), appareil)],
            "donnees": donnees}


# Ordre d'affichage par defaut ; hud.tableau_de_bord.sources choisit et ordonne.
_CATALOGUE = {
    "agenda": ("Agenda", source_agenda, 600),
    "factures": ("Factures", source_factures, 3600),
    "loopstr": ("Loopstr", source_loopstr, 900),
    "instagram": ("Instagram", source_instagram, 3600),
    "discord": ("Discord", source_discord, 1800),
    "colis": ("Colis", source_colis, 1800),
    "meteo": ("Météo", source_meteo, 1800),
    "spotify": ("Spotify", source_spotify, 60),
}
SOURCES_PAR_DEFAUT = ("agenda", "factures", "loopstr", "instagram", "discord")


def sources_configurees(reglages):
    """Sources demandees par la config (hud.tableau_de_bord), dans son ordre."""
    noms = reglages.get("sources") or SOURCES_PAR_DEFAUT
    minutes_factures = reglages.get("factures_minutes", 60)
    sources = []
    for nom in noms:
        nom = str(nom).strip().lower()
        if nom not in _CATALOGUE or any(s.id == nom for s in sources):
            continue
        titre, lire, ttl = _CATALOGUE[nom]
        if nom == "factures":
            try:
                ttl = max(15.0, float(minutes_factures)) * 60
            except (TypeError, ValueError):
                pass
        sources.append(Source(nom, titre, lire, ttl))
    return sources


# ------------------------------------------------------------------ fond

_EN_COURS = {"thread": None, "assembleur": None}
# Destinataires des tuiles : la fenetre locale (hud.tableau) et, cote serveur, les
# postes distants connectes (core/satellite.py). Une seule boucle les sert tous.
_ABONNES = []
_VERROU_ABONNES = threading.Lock()


def abonner(publier):
    """Ajoute un destinataire publier(tuiles), appele a chaque changement."""
    with _VERROU_ABONNES:
        if publier not in _ABONNES:
            _ABONNES.append(publier)


def desabonner(publier):
    with _VERROU_ABONNES:
        if publier in _ABONNES:
            _ABONNES.remove(publier)


def _publier_tous(tuiles):
    with _VERROU_ABONNES:
        destinataires = list(_ABONNES)
    for publier in destinataires:
        try:
            publier(tuiles)
        except Exception as e:     # un poste deconnecte ne prive pas les autres
            LOG.info("tableau: destinataire en echec (%s)", type(e).__name__)


def tuiles():
    """Tuiles courantes de la boucle de fond ([] si elle ne tourne pas)."""
    assembleur = _EN_COURS["assembleur"]
    return assembleur.tuiles() if assembleur is not None else []


def filtrer(liste, choix):
    """Tuiles retenues pour un destinataire : choix True = toutes, sinon une liste d'ids."""
    if choix is True:
        return list(liste)
    voulus = {str(c).strip().lower() for c in (choix or [])}
    return [t for t in liste if str(t.get("id", "")).lower() in voulus]


_VERROU_DEMARRAGE = threading.Lock()


def demarrer(publier=None, reglages=None):
    """Lance la boucle de fond qui publie les tuiles (une seule fois par processus).

    publier(tuiles), s'il est donne, est abonne : appele a chaque changement. Renvoie
    True si la boucle tourne. Sans effet si hud.tableau_de_bord.actif est faux."""
    with _VERROU_DEMARRAGE:
        return _demarrer(publier, reglages)


def _demarrer(publier, reglages):
    if _EN_COURS["thread"] is not None:
        if publier is not None:
            abonner(publier)
        return True
    if reglages is None:
        reglages = _reglage("hud.tableau_de_bord", {})
    if reglages is True:                     # raccourci « tableau_de_bord: true »
        reglages = {"actif": True}
    if not isinstance(reglages, dict) or not bool(reglages.get("actif", False)):
        return False
    sources = sources_configurees(reglages)
    if not sources:
        return False
    if publier is not None:
        abonner(publier)                     # avant le premier tour de la boucle
    assembleur = Assembleur(sources)

    def boucle():
        while True:
            try:
                assembleur.rafraichir(publier=_publier_tous)
            except Exception as e:
                LOG.info("tableau: tour en echec (%s)", type(e).__name__)
            time.sleep(_PAS_BOUCLE)

    fil = threading.Thread(target=boucle, name="hud-tableau", daemon=True)
    _EN_COURS.update(thread=fil, assembleur=assembleur)
    fil.start()
    return True
