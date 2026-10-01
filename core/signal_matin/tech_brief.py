"""Brief Tech & IA analytique de Signal Matin.

Chaine : flux publics -> tri sur les titres (modele economique) -> lecture
integrale par Jarvis -> pistes de contexte web par Hermes (URL seulement, que
Jarvis relit lui-meme) -> redaction -> relecture factuelle -> verification
mecanique de chaque citation dans le texte de sa source.

Toute etape en echec renvoie ``None`` : le cahier tech classique reste imprime.
Hermes ne recoit que des sujets publics, jamais un credential ni une donnee
personnelle ; l'appel au modele passe par ``core.cloud`` et entre dans le budget.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from core import cloud
from core.config import reglage

from .models import BriefAnalysis, BriefFact, BriefSource, BriefThread, NewsItem, TechBrief
from .news_enrichment import _article_text

LOG = logging.getLogger("jarvis.signal_matin")
ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = ROOT / "notes" / "signal_matin_brief_history.json"
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre")
TEXTE_MIN = 900
TEXTE_MAX = 7_000
CITATION_MOTS_MAX = 25
REF = re.compile(r"\[(\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\]")
CITATION_DANS_TEXTE = re.compile(r"[«“\"]\s*([^«»“”\"]{12,400}?)\s*[»”\"]")

# Prompt editorial fourni par l'utilisatrice. Seules les adaptations validees
# ont ete faites (articles fournis au lieu de la recherche web, numeros de
# source au lieu des liens, traduction des citations anglaises, sujets deja
# traites, fenetre 24 h prioritaire / 72 h maximum). Le format de sortie JSON
# est ajoute a la fin pour la mise en page du journal.
BRIEF = """Tu prépares mon brief matinal quotidien sur la tech et l'intelligence artificielle. Je veux comprendre l'actualité, pas seulement la connaître : ton rôle est de décortiquer les informations, d'en expliquer les enjeux et de les relier entre elles pour m'aider à me forger un esprit critique. Rédige en français et livre le brief directement dans ta réponse, sans me poser de question.

PÉRIMÈTRE
- Tech et IA en général : nouveaux modèles, produits et sorties, annonces d'entreprises, recherche, levées de fonds, acquisitions, semi-conducteurs, cloud, infrastructures.
- Politique et régulation autour de la tech et de l'IA, partout dans le monde : États-Unis, Union européenne et France, Chine, reste de l'Asie, Moyen-Orient, Afrique, Amérique latine. Lois, décisions de justice, contrôles à l'export, souveraineté numérique, rivalités entre puissances.

MÉTHODE
1. La date du jour est le {date}. Les articles fournis plus bas ont été collectés dans des flux d'actualité puis lus en entier : ils sont ta seule matière. Privilégie les dernières 24 heures ; un article plus ancien (72 heures au maximum) ne sert que pour un sujet important pas encore traité. Les textes marqués « contexte » viennent d'une recherche web complémentaire et ont eux aussi été lus en entier. Privilégie les sources primaires (communiqués, textes officiels, publications des entreprises, études) et les médias reconnus. Appuie-toi sur le texte complet, sans te fier au seul titre.
2. Avant de rédiger, extrais textuellement (mot pour mot, entre guillemets) la citation pertinente de chaque texte retenu : un extrait court par source (moins de 15 mots), copié exactement depuis le texte fourni, avec le numéro de la source. Si le texte est en anglais, garde la citation en anglais et donne sa traduction française à part.
3. Choisis les 5 à 8 informations les plus importantes, puis les 2 ou 3 qui méritent une analyse approfondie.
4. Pour ces analyses, appuie-toi sur les textes de contexte fournis afin de retrouver le contexte : événements antérieurs, décisions liées, chiffres, réactions des acteurs concernés. Tu n'as aucune mémoire des briefs précédents en dehors de la liste des sujets déjà traités fournie plus bas : tout lien avec une information passée doit s'appuyer sur un texte fourni et cité. Ne reprends un sujet déjà traité que s'il y a un fait nouveau, et dis ce qui est nouveau.

RÈGLES DE FIABILITÉ
- Si tu ne connais pas la réponse ou si tu n'as pas assez d'informations pour répondre avec certitude, dis-le explicitement plutôt que de spéculer.
- Associe chaque affirmation factuelle à une citation ou à une source précise (avec son numéro [n]). Si un fait ne peut pas être prouvé par le texte d'une source, supprime-le.
- Sépare toujours les faits de l'analyse. L'analyse est une interprétation : signale-la comme telle, montre le raisonnement qui part des faits sourcés, et indique ton niveau de confiance (élevé, moyen, faible). Ne présente jamais une hypothèse comme un fait.
- N'ajoute aucun fait tiré de tes connaissances générales sans l'avoir vérifié dans un des textes fournis.
- Si deux sources se contredisent, signale-le et cite les deux.
- Distingue ce qui est annoncé de ce qui est réellement disponible ou démontré (une annonce d'entreprise n'est pas une preuve).
- Sur les sujets politiques, expose les positions en présence de façon équilibrée, sans prendre parti.
- S'il y a peu d'actualité, fais un brief plus court plutôt que de combler avec des informations anciennes ou incertaines.

FORMAT DU BRIEF
Titre : « Brief Tech & IA – [date du jour] »

1. L'essentiel en 5 lignes
Ce qu'il faut retenir si je n'ai que deux minutes.

2. Les informations du jour (5 à 8)
Pour chacune : le fait en une ou deux phrases, la citation courte entre guillemets, la source (son numéro : le média et la date sont ajoutés à la mise en page), et une phrase « Pourquoi c'est important ».

3. Analyses approfondies (2 ou 3 sujets)
Pour chaque sujet :
- Les faits : ce qui s'est passé, sourcé.
- Le contexte : ce qui a précédé, et les autres informations récentes auxquelles ce sujet se rattache (sourcées).
- Enjeux géopolitiques : rapports de force entre États, souveraineté, alliances, dépendances.
- Enjeux économiques : marchés, modèles économiques, concurrence, emploi, investissements, chiffres.
- Qui y gagne, qui y perd, et quel intérêt chaque acteur a à présenter les choses comme il le fait.
- Lectures divergentes : au moins deux interprétations différentes de l'événement, avec leurs meilleurs arguments.
- Ce qui reste incertain ou invérifiable à ce stade.

4. Fil rouge
Les liens entre les informations du jour : tendances communes, causes partagées, effets en chaîne. Précise pour chaque lien s'il est établi par une source ou s'il s'agit de ton interprétation.

5. Pour exercer mon esprit critique
- 2 ou 3 questions ouvertes que ces actualités devraient me faire me poser.
- Les biais ou angles morts possibles de la couverture médiatique du jour (qui parle, qui ne parle pas, ce qui manque).
- À surveiller : les prochaines échéances ou signaux qui confirmeront ou infirmeront les analyses ci-dessus.

6. Ce que je n'ai pas pu établir
Les questions restées sans réponse fiable.

Vise un brief lisible en dix minutes environ : dense, sans remplissage, avec des phrases claires et les termes techniques expliqués en quelques mots."""

FORMAT_SORTIE = """FORMAT DE SORTIE (technique, pour la mise en page du journal imprimé)
Réponds uniquement par cet objet JSON, sans texte autour. Dans tous les champs de texte, place le numéro de la source juste après chaque fait, sous la forme [3] ou [3, 7].
{
  "essentiel": ["5 lignes au maximum"],
  "informations": [{"fait": "...", "citation": "copie exacte du texte de la source", "traduction": "traduction française si la citation est en anglais, sinon vide", "source": 3, "pourquoi": "Pourquoi c'est important"}],
  "analyses": [{"sujet": "...", "faits": "...", "contexte": "...", "geopolitique": "...", "economie": "...", "gagnants_perdants": "...", "lectures_divergentes": "...", "incertain": "...", "confiance": "élevé | moyen | faible"}],
  "fil_rouge": [{"lien": "...", "nature": "établi | interprétation"}],
  "questions": ["..."],
  "angles_morts": ["..."],
  "a_surveiller": ["..."],
  "non_etabli": ["..."]
}
Sépare les paragraphes d'un même champ par \\n. Dans les analyses, une citation anglaise est suivie de sa traduction entre parenthèses.
Les « informations » ne citent que des textes de type « actualite » ; les textes de type « contexte » servent uniquement aux analyses, au fil rouge et à l'esprit critique."""

RELECTURE = """Tu relis un brief avant impression. Voici le brief (JSON) puis les textes sources numérotés.
Pour chaque affirmation factuelle, dans tous les champs, vérifie qu'elle est soutenue par le texte de la source citée [n].
- Supprime, ou corrige à la baisse, toute affirmation non soutenue par sa source, tout fait tiré de connaissances générales et tout numéro de source erroné.
- Une citation doit être une copie exacte d'un passage de sa source : sinon, remplace-la par un passage exact de la même source qui appuie le fait, ou supprime l'information.
- Ne touche pas aux passages clairement présentés comme une interprétation, sauf s'ils présentent une hypothèse comme un fait.
- Ne rajoute aucune information.
Réponds uniquement par le même objet JSON, avec la même structure, plus un champ "retraits" : liste courte de ce que tu as supprimé ou corrigé."""


# ------------------------------------------------------------------ utilitaires

def _mots(texte: str) -> str:
    """Suite de mots comparable, insensible a la typographie et aux balises."""
    texte = unicodedata.normalize("NFKC", html.unescape(texte or "")).casefold()
    return " ".join(re.findall(r"\w+", texte))


def citation_verifiee(citation: str, texte_source: str) -> bool:
    """Vrai si la citation apparait mot pour mot, dans le meme ordre, dans la source."""
    mots = _mots(citation)
    nombre = len(mots.split())
    return 3 <= nombre <= CITATION_MOTS_MAX and f" {mots} " in f" {_mots(texte_source)} "


def _json_objet(texte: str) -> dict:
    debut, fin = (texte or "").find("{"), (texte or "").rfind("}")
    if debut < 0 or fin <= debut:
        return {}
    try:
        valeur = json.loads(texte[debut:fin + 1])
    except ValueError:
        return {}
    return valeur if isinstance(valeur, dict) else {}


def _json_liste(texte: str) -> list[dict]:
    debut, fin = (texte or "").find("["), (texte or "").rfind("]")
    if debut < 0 or fin <= debut:
        return []
    try:
        valeur = json.loads(texte[debut:fin + 1])
    except ValueError:
        return []
    return [ligne for ligne in valeur if isinstance(ligne, dict)] if isinstance(valeur, list) else []


def _txt(valeur, limite: int) -> str:
    valeur = str(valeur or "").strip()
    if len(valeur) <= limite:
        return valeur
    return valeur[:limite].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _liste(valeur, nombre: int, limite: int = 400) -> list[str]:
    if not isinstance(valeur, list):
        return []
    return [_txt(v, limite) for v in valeur if str(v or "").strip()][:nombre]


def _confiance(valeur) -> str:
    texte = _mots(str(valeur or ""))
    for indice, nom in (("lev", "élevé"), ("moyen", "moyen"), ("faibl", "faible")):
        if indice in texte:
            return nom
    return ""


def date_fr(jour: dt.date) -> str:
    return f"{'1er' if jour.day == 1 else jour.day} {MOIS[jour.month - 1]} {jour.year}"


def _cloud(systeme: str, contenu: str, max_tokens: int, cle_modele: str) -> str:
    return cloud.repondre_texte(
        systeme, [{"role": "user", "content": contenu}],
        max_tokens=max_tokens,
        nom_modele=str(reglage(cle_modele, "") or ""),
    )


# ------------------------------------------------------------------ historique

def _lire_historique(chemin: Path) -> dict:
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        return donnees if isinstance(donnees.get("jours"), dict) else {"jours": {}}
    except (OSError, ValueError, AttributeError):
        return {"jours": {}}


def deja_traites(historique: dict, jour: dt.date, jours: int) -> tuple[set[str], list[str]]:
    """URL et sujets des jours precedents ; le jour meme est ignore (relance)."""
    limite = jour - dt.timedelta(days=jours)
    urls: set[str] = set()
    sujets: list[str] = []
    for cle, lignes in sorted(historique.get("jours", {}).items()):
        try:
            date = dt.date.fromisoformat(cle)
        except ValueError:
            continue
        if not limite <= date < jour:
            continue
        for ligne in lignes if isinstance(lignes, list) else []:
            if not isinstance(ligne, dict):
                continue
            if ligne.get("url"):
                urls.add(str(ligne["url"]))
            if ligne.get("sujet"):
                sujets.append(f"{cle} : {ligne['sujet']}")
    return urls, sujets[-60:]


def _enregistrer_historique(chemin: Path, historique: dict, jour: dt.date,
                            brief: TechBrief, jours: int) -> None:
    urls = {source.id: str(source.url) for source in brief.sources
            if source.url and source.role == "actualite"}
    lignes = [{"sujet": _txt(fait.fact, 180), "url": urls.get(fait.source_id, "")}
              for fait in brief.facts]
    lignes += [{"sujet": _txt(analyse.subject, 180), "url": ""} for analyse in brief.analyses]
    historique.setdefault("jours", {})[jour.isoformat()] = lignes
    garde = jour - dt.timedelta(days=max(jours * 2, 14))
    historique["jours"] = {
        cle: valeur for cle, valeur in historique["jours"].items()
        if cle >= garde.isoformat()
    }
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(historique, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ etapes

def _selectionner(candidats: list[NewsItem], now: dt.datetime, sujets_passes: list[str],
                  nombre: int) -> tuple[list[int], list[dict]]:
    lignes = []
    for index, item in enumerate(candidats):
        publie = item.source.published_at
        heures = round((now - publie).total_seconds() / 3600) if publie else None
        lignes.append({"i": index, "media": item.source.name, "il_y_a_heures": heures,
                       "titre": item.title, "resume": _txt(item.summary, 260)})
    consigne = f"""Date : {date_fr(now.date())}.
Périmètre : tech et IA (modèles, produits, entreprises, recherche, levées de fonds, acquisitions, semi-conducteurs, cloud, infrastructures) et politique ou régulation de la tech dans le monde entier.
Parmi les candidats, choisis au plus {nombre} articles à lire en entier pour écrire un brief analytique :
- privilégie les dernières 24 heures ; au-delà, seulement un sujet important pas encore traité ;
- privilégie les sources primaires, la diversité des médias et des régions, et un seul article par événement sauf angle vraiment différent ;
- écarte les sujets déjà traités les jours précédents, sauf fait nouveau important ;
- écarte le divertissement, les tests de produits grand public et ce qui sort du périmètre.
Désigne aussi 2 ou 3 sujets qui méritent une analyse approfondie, avec pour chacun une question de contexte à rechercher sur le web.
Sujets déjà traités : {json.dumps(sujets_passes, ensure_ascii=False)}
Candidats : {json.dumps(lignes, ensure_ascii=False)}
Réponds uniquement par : {{"articles": [0, 4], "approfondir": [{{"sujet": "...", "recherche": "...", "articles": [0]}}]}}"""
    reponse = _cloud(
        "Tu es chef d'édition d'un brief quotidien Tech & IA. Tu choisis, tu ne rédiges pas. "
        "Réponds uniquement par l'objet JSON demandé.",
        consigne, 2000, "signal_matin.modele_selection_brief",
    )
    donnees = _json_objet(reponse)
    choix = []
    for valeur in donnees.get("articles", []) if isinstance(donnees.get("articles"), list) else []:
        valeur = int(valeur) if str(valeur).isdigit() else -1
        if 0 <= valeur < len(candidats) and valeur not in choix:
            choix.append(valeur)
    sujets = [s for s in donnees.get("approfondir", []) if isinstance(s, dict) and s.get("sujet")]
    return choix[:nombre], sujets[:3]


def _lire_textes(urls: list[str], allow_proxy: bool) -> list[str]:
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(
            lambda url: _article_text(url, allow_public_proxy=allow_proxy)[:TEXTE_MAX], urls,
        ))


def _pistes_hermes(sujets: list[dict], urls_connues: set[str], jour: dt.date,
                   rapport: dict, timeout: int = 420) -> list[dict]:
    """Hermes propose des pages de contexte ; Jarvis les lira et verifiera lui-meme."""
    if not sujets:
        return []
    liste = "\n".join(
        f"{numero}. {s.get('sujet')} — recherche : {s.get('recherche') or s.get('sujet')}"
        for numero, s in enumerate(sujets, start=1)
    )
    prompt = f"""Nous sommes le {date_fr(jour)}. Pour chacun des sujets ci-dessous, trouve avec ta recherche web 2 ou 3 pages de CONTEXTE utiles pour l'analyser : événements antérieurs, décisions liées, chiffres, réactions des acteurs concernés. Privilégie les sources primaires (textes officiels, communiqués, études) et les médias reconnus, en français ou en anglais.
Fais au plus 2 recherches par sujet. N'ouvre pas les pages : choisis à partir des résultats de recherche, les pages seront lues et vérifiées ensuite.
N'utilise aucune de ces URL déjà connues : {json.dumps(sorted(urls_connues)[:40])}
Sujets :
{liste}
Réponds uniquement par un tableau JSON : [{{"sujet": 1, "url": "https://...", "titre": "...", "media": "..."}}]"""
    try:
        from tools.deleguer_a_hermes import appeler_hermes_brut
        texte, tokens, cout, modele = appeler_hermes_brut(
            prompt, session="signal-matin-brief",
            timeout=min(timeout, int(reglage("signal_matin.brief_hermes_timeout", 420) or 420)),
        )
    except Exception as erreur:
        LOG.warning("Signal Matin : contexte Hermes indisponible : %s", erreur)
        rapport["hermes"] = f"indisponible ({type(erreur).__name__})"
        return []
    rapport["hermes"] = {"modele": modele, "tokens": tokens, "cout_estime": cout}
    pistes, vues = [], set(urls_connues)
    par_sujet: dict[int, int] = {}
    for ligne in _json_liste(texte):
        url = str(ligne.get("url") or "").strip()
        sujet = ligne.get("sujet") if isinstance(ligne.get("sujet"), int) else 0
        if not url.startswith(("http://", "https://")) or url in vues:
            continue
        if par_sujet.get(sujet, 0) >= 3:
            continue
        vues.add(url)
        par_sujet[sujet] = par_sujet.get(sujet, 0) + 1
        pistes.append({"url": url, "titre": _txt(ligne.get("titre"), 240),
                       "media": _txt(ligne.get("media") or "Source web", 120)})
    return pistes[:8]


def _pistes_web(sujets: list[dict], urls_connues: set[str], rapport: dict) -> list[dict]:
    """Jarvis cherche lui-meme les pages de contexte (DuckDuckGo, sans cle d'API).

    Aucun credential n'est en jeu et rien ne transite par Hermes. Les pages
    proposees sont ensuite lues en entier et verifiees comme les articles.
    """
    if not sujets:
        return []
    try:
        from ddgs import DDGS
    except ImportError:
        rapport["contexte"] = "recherche web non installee"
        return []
    candidats: list[dict] = []
    vues = set(urls_connues)
    try:
        with DDGS() as ddgs:
            for numero, sujet in enumerate(sujets, start=1):
                requetes = dict.fromkeys(
                    r for r in (str(sujet.get("recherche") or "").strip(),
                                str(sujet.get("sujet") or "").strip()) if r
                )
                for requete in requetes:
                    for resultat in ddgs.text(requete, region="wt-wt", max_results=6) or []:
                        url = str(resultat.get("href") or "").strip()
                        if not url.startswith(("http://", "https://")) or url in vues:
                            continue
                        vues.add(url)
                        hote = (urlparse(url).hostname or "Source web").removeprefix("www.")
                        candidats.append({
                            "sujet": numero, "url": url, "titre": _txt(resultat.get("title"), 240),
                            "media": _txt(hote, 120), "extrait": _txt(resultat.get("body"), 200),
                        })
    except Exception as erreur:
        LOG.warning("Signal Matin : recherche de contexte indisponible : %s", erreur)
        rapport["contexte"] = f"recherche web indisponible ({type(erreur).__name__})"
    pistes = _trier_sources(candidats, sujets, rapport)
    if not isinstance(rapport.get("contexte"), str):
        rapport["contexte"] = {"source": "web", "candidats": len(candidats), "pistes": len(pistes)}
    return pistes


def _trier_sources(candidats: list[dict], sujets: list[dict], rapport: dict) -> list[dict]:
    """Garde au plus 3 sources fiables par sujet ; repli sur l'ordre du moteur si le tri echoue."""
    def premiers(liste: list[dict]) -> list[dict]:
        gardes, par_sujet = [], {}
        for candidat in liste:
            if par_sujet.get(candidat["sujet"], 0) < 3:
                par_sujet[candidat["sujet"]] = par_sujet.get(candidat["sujet"], 0) + 1
                gardes.append(candidat)
        return gardes[:8]

    if len(candidats) <= 3:
        return premiers(candidats)
    lignes = [{"i": i, "sujet": c["sujet"], "media": c["media"], "titre": c["titre"],
               "extrait": c["extrait"]} for i, c in enumerate(candidats)]
    liste_sujets = [{"sujet": n, "intitule": s.get("sujet")} for n, s in enumerate(sujets, start=1)]
    try:
        reponse = _cloud(
            "Tu selectionnes des sources pour un brief d'actualite exigeant. Reponds uniquement "
            "par l'objet JSON demande.",
            "Pour chaque sujet, choisis au plus 3 pages de contexte, par ordre de preference : "
            "sources primaires (textes officiels, communiques, etudes), institutions, puis medias "
            "reconnus pour leur fiabilite. Ecarte les agregateurs, blogs de referencement, contenus "
            "sponsorises, sites partisans et pages sans rapport avec le sujet. Mieux vaut moins de "
            "sources que des sources douteuses.\n"
            f"Sujets : {json.dumps(liste_sujets, ensure_ascii=False)}\n"
            f"Candidats : {json.dumps(lignes, ensure_ascii=False)}\n"
            'Format : {"choix": [0, 3, 5]}',
            800, "signal_matin.modele_selection_brief",
        )
        indices = _json_objet(reponse).get("choix")
        if not isinstance(indices, list):
            raise ValueError("selection illisible")
        choisis = [candidats[int(i)] for i in dict.fromkeys(indices)
                   if str(i).isdigit() and int(i) < len(candidats)]
    except Exception as erreur:
        LOG.info("Signal Matin : tri des sources de contexte indisponible : %s", erreur)
        rapport["tri_contexte"] = "repli sur l'ordre du moteur"
        return premiers(candidats)
    rapport["tri_contexte"] = f"{len(choisis)} source(s) retenue(s) sur {len(candidats)}"
    return premiers(choisis)


def _verifier_texte(texte: str, sources: dict[int, dict], retraits: list[str]) -> str:
    """Retire les phrases dont une citation n'existe pas mot pour mot, et les refs inconnues."""
    def refs_valides(match: re.Match) -> str:
        ids = [int(n) for n in re.split(r"\s*[,;]\s*", match.group(1)) if int(n) in sources]
        return f"[{', '.join(map(str, ids))}]" if ids else ""

    paragraphes = []
    for paragraphe in str(texte or "").split("\n"):
        phrases = re.split(r"(?<=[.!?])\s+", paragraphe.strip())
        gardees = []
        for phrase in phrases:
            ids = [int(n) for groupe in REF.findall(phrase)
                   for n in re.split(r"\s*[,;]\s*", groupe) if int(n) in sources]
            textes = [sources[i]["texte"] for i in ids] or [s["texte"] for s in sources.values()]
            fausse = next((
                m.group(1) for m in CITATION_DANS_TEXTE.finditer(phrase)
                # Une traduction suit sa citation entre parentheses : elle n'est
                # pas dans la source anglaise et n'a pas a l'etre.
                if "(" not in phrase[max(0, m.start() - 2):m.start()]
                and len(m.group(1).split()) >= 4
                and not any(citation_verifiee(m.group(1), t) for t in textes)
            ), None)
            if fausse:
                retraits.append(f"phrase retirée (citation introuvable) : « {_txt(fausse, 90)} »")
                continue
            gardees.append(REF.sub(refs_valides, phrase))
        if any(gardees):
            paragraphes.append(" ".join(p for p in gardees if p))
    return "\n".join(paragraphes).strip()


def _assembler(donnees: dict, sources: dict[int, dict], jour: dt.date,
               retraits: list[str]) -> tuple[TechBrief | None, int]:
    faits: list[BriefFact] = []
    verifiees = 0
    for ligne in donnees.get("informations", []) if isinstance(donnees.get("informations"), list) else []:
        if not isinstance(ligne, dict):
            continue
        source_id = ligne.get("source")
        citation = str(ligne.get("citation") or "").strip().strip("«»\"“” ")
        if not isinstance(source_id, int) or source_id not in sources:
            retraits.append(f"information retirée (source inconnue) : {_txt(ligne.get('fait'), 90)}")
            continue
        # Une page de contexte n'est pas datee : elle nourrit les analyses, jamais
        # « les informations du jour ».
        if sources[source_id]["role"] != "actualite":
            retraits.append(f"information retirée (page de contexte non datée [{source_id}]) : "
                            f"{_txt(ligne.get('fait'), 90)}")
            continue
        if not citation_verifiee(citation, sources[source_id]["texte"]):
            retraits.append(
                f"information retirée (citation introuvable dans [{source_id}]) : « {_txt(citation, 90)} »")
            continue
        fait = _txt(_verifier_texte(ligne.get("fait"), sources, retraits), 900)
        if not fait:
            retraits.append(f"information retirée (texte non vérifiable) : « {_txt(citation, 90)} »")
            continue
        verifiees += 1
        faits.append(BriefFact(
            fact=fait,
            quote=_txt(citation, 300),
            translation=_txt(ligne.get("traduction"), 400),
            source_id=source_id,
            why=_txt(_verifier_texte(ligne.get("pourquoi"), sources, retraits), 600),
        ))
    if len(faits) < 2:
        return None, verifiees

    analyses = []
    for ligne in donnees.get("analyses", []) if isinstance(donnees.get("analyses"), list) else []:
        if not isinstance(ligne, dict) or not ligne.get("sujet"):
            continue
        def champ(nom: str, limite: int = 2400) -> str:
            return _txt(_verifier_texte(ligne.get(nom), sources, retraits), limite)

        analyses.append(BriefAnalysis(
            subject=_txt(ligne.get("sujet"), 200),
            facts=champ("faits"), context=champ("contexte"),
            geopolitics=champ("geopolitique"), economics=champ("economie"),
            stakes=champ("gagnants_perdants"), readings=champ("lectures_divergentes"),
            uncertain=champ("incertain", 1600),
            confidence=_confiance(ligne.get("confiance")),
        ))

    fils = []
    for ligne in donnees.get("fil_rouge", []) if isinstance(donnees.get("fil_rouge"), list) else []:
        if isinstance(ligne, dict):
            texte = _txt(_verifier_texte(ligne.get("lien"), sources, retraits), 900)
            if texte:
                fils.append(BriefThread(text=texte, established="tabli" in str(ligne.get("nature", "")).casefold()))

    essentiels = [e for e in (_txt(_verifier_texte(v, sources, retraits), 400)
                              for v in _liste(donnees.get("essentiel"), 5, 600)) if e]
    textes = [*essentiels, *(f.fact for f in faits), *(f.why for f in faits),
              *(t.text for t in fils)]
    for analyse in analyses:
        textes.extend(str(v) for v in analyse.model_dump().values())
    utilisees = {f.source_id for f in faits}
    for groupe in REF.findall(" ".join(textes)):
        utilisees.update(int(n) for n in re.split(r"\s*[,;]\s*", groupe))
    brief = TechBrief(
        title=f"Brief Tech & IA – {date_fr(jour)}",
        essentials=essentiels,
        facts=faits[:8],
        analyses=analyses[:3],
        threads=fils[:6],
        questions=_liste(donnees.get("questions"), 3),
        blind_spots=_liste(donnees.get("angles_morts"), 4),
        watch=_liste(donnees.get("a_surveiller"), 5),
        unknowns=_liste(donnees.get("non_etabli"), 6),
        sources=[
            BriefSource(id=i, name=s["media"], title=s["titre"], url=s["url"] or None,
                        published_at=s["date"], role=s["role"])
            for i, s in sorted(sources.items()) if i in utilisees
        ],
    )
    return brief, verifiees


# ------------------------------------------------------------------ point d'entree

def construire_brief(
    candidats: list[NewsItem],
    now: dt.datetime,
    *,
    allow_proxy: bool,
    enregistrer_historique: bool = True,
    historique_path: Path = HISTORY_PATH,
    rapport: dict | None = None,
) -> TechBrief | None:
    """Construit le brief ou renvoie None (le cahier tech classique prend le relais)."""
    rapport = rapport if rapport is not None else {}
    if not bool(reglage("signal_matin.brief_tech", False)) or not cloud.disponible():
        rapport["etat"] = "desactive"
        return None
    debut = time.monotonic()
    budget_s = int(reglage("signal_matin.brief_budget_secondes", 780) or 780)
    jours = int(reglage("signal_matin.brief_historique_jours", 14) or 14)
    historique = _lire_historique(historique_path)
    urls_passees, sujets_passes = deja_traites(historique, now.date(), jours)
    candidats = [c for c in candidats if str(c.source.url or "") not in urls_passees][:80]
    rapport["candidats"] = len(candidats)
    if len(candidats) < 3:
        rapport["etat"] = "trop peu de candidats"
        return None

    nombre = max(4, min(int(reglage("signal_matin.brief_articles_max", 14) or 14), 20))
    choix, sujets = _selectionner(candidats, now, sujets_passes, nombre)
    retenus = [candidats[i] for i in choix]
    textes = _lire_textes([str(item.source.url or "") for item in retenus], allow_proxy)
    sources: dict[int, dict] = {}
    for item, texte in zip(retenus, textes):
        if len(texte) >= TEXTE_MIN:
            sources[len(sources) + 1] = {
                "media": item.source.name, "titre": item.title, "url": str(item.source.url or ""),
                "date": item.source.published_at, "role": "actualite", "texte": texte,
            }
    rapport["articles_lus"] = f"{len(sources)}/{len(retenus)}"
    if len(sources) < 3:
        rapport["etat"] = "trop peu d'articles lisibles"
        return None

    # Hermes recoit le temps restant, en gardant une reserve pour la redaction
    # et la relecture : un Hermes lent ne fait jamais perdre tout le brief.
    reserve_redaction = 360
    restant = budget_s - (time.monotonic() - debut) - reserve_redaction
    # web : Jarvis cherche lui-meme (DuckDuckGo, sans cle) ; hermes : agent avec
    # recherche web ; aucun : analyses fondees sur les seuls articles du jour.
    mode_contexte = str(reglage("signal_matin.brief_contexte", "web") or "web").lower()
    connues = {s["url"] for s in sources.values()} | urls_passees
    if mode_contexte == "aucun":
        rapport["contexte"] = "desactive"
    elif restant >= 90:
        if mode_contexte == "hermes":
            pistes = _pistes_hermes(sujets, connues, now.date(), rapport, timeout=int(restant))
        else:
            pistes = _pistes_web(sujets, connues, rapport)
        for piste, texte in zip(pistes, _lire_textes([p["url"] for p in pistes], True)):
            if len(texte) >= TEXTE_MIN and len(sources) < 30:
                sources[len(sources) + 1] = {
                    "media": piste["media"], "titre": piste["titre"], "url": piste["url"],
                    "date": None, "role": "contexte", "texte": texte,
                }
        rapport["contexte_lu"] = sum(1 for s in sources.values() if s["role"] == "contexte")
    else:
        rapport["contexte"] = "saute (plus assez de temps)"

    matiere = [{
        "source": i, "type": s["role"], "media": s["media"], "titre": s["titre"],
        "date": s["date"].strftime("%Y-%m-%d %H:%M") if s["date"] else "",
        "texte": s["texte"],
    } for i, s in sources.items()]
    approfondir = [{"sujet": s.get("sujet"), "question": s.get("recherche")} for s in sujets]
    contenu = (
        BRIEF.replace("{date}", date_fr(now.date())) + "\n\n" + FORMAT_SORTIE
        + "\n\nSUJETS DÉJÀ TRAITÉS LES JOURS PRÉCÉDENTS\n" + json.dumps(sujets_passes, ensure_ascii=False)
        + "\n\nSUJETS PROPOSÉS POUR LES ANALYSES APPROFONDIES\n" + json.dumps(approfondir, ensure_ascii=False)
        + "\n\nTEXTES FOURNIS\n" + json.dumps(matiere, ensure_ascii=False)
    )
    max_tokens = int(reglage("signal_matin.brief_max_tokens", 16000) or 16000)
    brouillon = _json_objet(_cloud(
        "Tu rédiges le brief décrit par l'utilisatrice, uniquement à partir des textes fournis. "
        "Réponds uniquement par l'objet JSON demandé.",
        contenu, max_tokens, "signal_matin.modele_brief",
    ))
    if not brouillon:
        rapport["etat"] = "reponse de redaction illisible"
        return None

    relu = brouillon
    if bool(reglage("signal_matin.brief_relecture", True)):
        textes_sources = [{"source": i, "texte": s["texte"]} for i, s in sources.items()]
        corrige = _json_objet(_cloud(
            "Tu es relecteur-vérificateur. Tu ne rajoutes rien. Réponds uniquement par l'objet JSON demandé.",
            RELECTURE + "\n\nBRIEF\n" + json.dumps(brouillon, ensure_ascii=False)
            + "\n\nTEXTES SOURCES\n" + json.dumps(textes_sources, ensure_ascii=False),
            max_tokens, "signal_matin.modele_brief",
        ))
        if corrige.get("informations"):
            relu = corrige
            rapport["relecture"] = _liste(corrige.get("retraits"), 20, 300)

    retraits: list[str] = []
    brief, verifiees = _assembler(relu, sources, now.date(), retraits)
    rapport["retraits_mecaniques"] = retraits
    rapport["duree_s"] = round(time.monotonic() - debut)
    if brief is None:
        rapport["etat"] = "moins de 2 informations verifiees"
        return None
    corrections = len(rapport.get("relecture", []))
    brief = brief.model_copy(update={"verification": _txt(
        f"{verifiees} citations retrouvées mot pour mot dans leur source ; "
        f"{len(retraits)} passage(s) retiré(s) à la vérification ; "
        f"{corrections} correction(s) à la relecture ; {len(sources)} textes lus en entier.", 600)})
    rapport["etat"] = "ok"
    if enregistrer_historique:
        try:
            _enregistrer_historique(historique_path, historique, now.date(), brief, jours)
        except OSError as erreur:
            LOG.warning("Signal Matin : historique du brief non ecrit : %s", erreur)
    return brief
