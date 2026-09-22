"""Google Sheets (classeurs) : lire, chercher, ecrire dans tes feuilles.

CRM et facturation pour beaucoup d'utilisateurs, ce sont des feuilles Google
Sheets (listes de clients/partenaires, factures, plannings). Cet outil donne
a Jarvis l'acces direct en lecture ET ecriture, via l'API officielle Sheets,
en OAuth2 — meme fichier d'identifiants que l'agenda et Gmail.

Autorisation (une fois) :
    uv run python scripts/google_login.py sheets

Securite :
  - classeurs_ecrire_cellule / classeurs_ajouter_ligne demandent la
    confirmation vocale avant d'agir (regle 95/5 : Jarvis prepare, tu valides).
  - Les donnees ne sont jamais logguees.

Config (facultatif, pour des noms courts) :
    classeurs:
      alias:
        partenaires: "1AbC...id_du_classeur_US_Partner_List"
        factures: "1XyZ...id_du_classeur_Invoice_2026"
"""

import logging

from core.config import reglage
from core.registre import outil

LOG = logging.getLogger("jarvis")

_SERVICE = None


# ------------------------------------------------------------------ connexion

def _service():
    """Service Sheets OAuth2, construit une fois puis reutilise."""
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    from core import google_oauth
    creds = google_oauth.identifiants(
        google_oauth.SCOPES_SHEETS,
        google_oauth.chemin("classeurs.token", "google_token_sheets.json"),
        interactif=False)
    from googleapiclient.discovery import build
    _SERVICE = build("sheets", "v4", credentials=creds)
    return _SERVICE


def _resoudre(classeur):
    """Classeur par id, URL copiee, ou alias defini dans config.yaml."""
    classeur = (classeur or "").strip()
    if not classeur:
        return ""
    alias = reglage("classeurs.alias", {}) or {}
    if classeur in alias:
        return str(alias[classeur])
    # URL complete : l'id est entre /d/ et /edit
    if classeur.startswith("http"):
        reste = classeur.split("/d/", 1)
        if len(reste) == 2:
            return reste[1].split("/", 1)[0]
    return classeur


# --------------------------------------------------------------- mise en forme

def _aplatir(valeurs, max_lignes=12):
    """Lignes lues -> phrases courtes ; limite le flot pour la voix."""
    if not valeurs:
        return "La plage est vide."
    lignes = []
    for i, ligne in enumerate(valeurs[:max_lignes], 1):
        cellules = [str(c).strip() for c in ligne if str(c).strip()]
        if cellules:
            lignes.append(f"{i}. " + " ; ".join(cellules))
    if len(valeurs) > max_lignes:
        lignes.append(f"... et {len(valeurs) - max_lignes} lignes de plus.")
    return " ".join(lignes) if lignes else "La plage est vide."


# -------------------------------------------------------------------- outils

@outil(
    nom="classeurs_lire",
    description="Lit une plage de cellules d'un classeur Google Sheets. "
                "Pour tes listes de clients/partenaires, factures, plannings. "
                "Exemples : « lis la colonne A des partenaires », "
                "« qu'est-ce qu'il y a dans factures A2 a F20 ».",
    parametres={
        "type": "object",
        "properties": {
            "classeur": {"type": "string",
                         "description": "Nom d'alias, id, ou URL du classeur."},
            "plage": {"type": "string",
                      "description": "Plage A1, ex. 'A1:F20', 'Feuille1!A:A'. "
                                     "Vide = A1:F50."},
        },
        "required": ["classeur"],
    },
    lent=True,
    phrase_attente="Je regarde ta feuille, un instant.",
    mcp_expose=False,
)
def classeurs_lire(classeur: str = "", plage: str = "") -> str:
    """Lit une plage d'un classeur Sheets et la resume a voix haute."""
    ident = _resoudre(classeur)
    if not ident:
        return ("Donne-moi le nom du classeur (ou son id/URL), ou definis des "
                "alias dans config.yaml sous classeurs.alias.")
    plage = (plage or "A1:F50").strip()
    try:
        reponse = (_service().spreadsheets()
                   .values().get(spreadsheetId=ident, range=plage).execute())
        return _aplatir(reponse.get("values", []))
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Impossible de lire le classeur ({str(e)[:120]})."


@outil(
    nom="classeurs_chercher",
    description="Cherche une valeur dans les premieres colonnes d'un classeur "
                "Google Sheets et renvoie la ligne entiere. Pour « est-ce que "
                "PhoneBox est dans la liste des partenaires », « retrouve la "
                "facture INV-2026-041 ».",
    parametres={
        "type": "object",
        "properties": {
            "classeur": {"type": "string",
                         "description": "Nom d'alias, id, ou URL du classeur."},
            "valeur": {"type": "string",
                       "description": "Texte a retrouver (nom, numero, email...)."},
            "feuille": {"type": "string",
                        "description": "Nom d'onglet ; vide = onglet principal."},
        },
        "required": ["classeur", "valeur"],
    },
    lent=True,
    phrase_attente="Je cherche dans ta feuille.",
    mcp_expose=False,
)
def classeurs_chercher(classeur: str = "", valeur: str = "",
                      feuille: str = "") -> str:
    """Cherche une valeur dans un classeur et renvoie la ligne trouvee."""
    ident = _resoudre(classeur)
    if not ident:
        return ("Donne-moi le nom du classeur (ou son id/URL), ou definis des "
                "alias dans config.yaml sous classeurs.alias.")
    cible = (valeur or "").strip().lower()
    if not cible:
        return "Qu'est-ce que je dois chercher ?"
    try:
        feuilles = (_service().spreadsheets()
                    .get(spreadsheetId=ident, fields="sheets(properties(name))"
                    ).execute().get("sheets", []))
        noms = [f["properties"]["name"] for f in feuilles]
        onglet = (feuille or "").strip() or noms[0] if noms else ""
        if not onglet:
            return "Je ne trouve pas les onglets de ce classeur."
        reponse = (_service().spreadsheets().values()
                   .get(spreadsheetId=ident, range=f"{onglet}!A:Z").execute())
        for i, ligne in enumerate(reponse.get("values", []), 1):
            if any(cible in str(c).lower() for c in ligne):
                cellules = [str(c).strip() for c in ligne if str(c).strip()]
                return (f"Trouve ligne {i} : " + " ; ".join(cellules)
                        + ".")
        return f"« {valeur} » n'apparait nulle part dans ce classeur."
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Impossible de chercher dans ce classeur ({str(e)[:120]})."


def _annonce_ecriture(args):
    classeur = args.get("classeur") or "le classeur"
    plage = args.get("plage") or "la ligne"
    return f"Je vais ecrire {plage} dans {classeur}."


@outil(
    nom="classeurs_ecrire_cellule",
    description="Ecrit une valeur dans UNE cellule precise d'un classeur "
                "Google Sheets. Demande confirmation avant d'agir.",
    parametres={
        "type": "object",
        "properties": {
            "classeur": {"type": "string",
                         "description": "Nom d'alias, id, ou URL du classeur."},
            "plage": {"type": "string",
                      "description": "Cellule ou plage A1, ex. 'B14'."},
            "valeur": {"type": "string",
                       "description": "Texte a ecrire dans la cellule."},
        },
        "required": ["classeur", "plage", "valeur"],
    },
    confirmation=True,
    annonce=_annonce_ecriture,
    lent=True,
    phrase_attente="J'ouvre la feuille.",
    mcp_expose=False,
)
def classeurs_ecrire_cellule(classeur: str = "", plage: str = "",
                             valeur: str = "") -> str:
    """Ecrit une valeur dans une cellule, apres confirmation vocale."""
    ident = _resoudre(classeur)
    if not ident:
        return "Je ne sais pas dans quel classeur ecrire."
    plage = (plage or "").strip()
    if not plage:
        return "Dans quelle cellule dois-je ecrire ?"
    try:
        (_service().spreadsheets().values()
         .update(spreadsheetId=ident, range=plage, valueInputOption="RAW",
                 body={"values": [[valeur]]}).execute())
        return f"C'est ecrit : {plage} vaut « {valeur} »."
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Impossible d'ecrire dans le classeur ({str(e)[:120]})."


@outil(
    nom="classeurs_ajouter_ligne",
    description="Ajoute une ligne a la fin d'une feuille Google Sheets. Pour "
                "enregistrer un nouveau client, une nouvelle facture, un "
                "nouveau partenaire. Demande confirmation avant d'agir.",
    parametres={
        "type": "object",
        "properties": {
            "classeur": {"type": "string",
                         "description": "Nom d'alias, id, ou URL du classeur."},
            "feuille": {"type": "string",
                        "description": "Nom d'onglet ; vide = onglet principal."},
            "ligne": {"type": "array", "items": {"type": "string"},
                      "description": "Cellules de la ligne, dans l'ordre des "
                                     "colonnes."},
        },
        "required": ["classeur", "ligne"],
    },
    confirmation=True,
    annonce=_annonce_ecriture,
    lent=True,
    phrase_attente="J'ouvre la feuille.",
    mcp_expose=False,
)
def classeurs_ajouter_ligne(classeur: str = "", feuille: str = "",
                           ligne: list = None) -> str:
    """Ajoute une ligne a la fin d'une feuille, apres confirmation vocale."""
    if ligne is None:
        ligne = []
    ident = _resoudre(classeur)
    if not ident:
        return "Je ne sais pas dans quel classeur ecrire."
    valeurs = [str(c) for c in ligne if str(c).strip()]
    if not valeurs:
        return "Il n'y a rien a ecrire dans cette ligne."
    try:
        (_service().spreadsheets().values()
         .append(spreadsheetId=ident,
                 range=(feuille or "").strip() or "A1",
                 valueInputOption="RAW",
                 insertDataOption="INSERT_ROWS",
                 body={"values": [valeurs]}).execute())
        return ("Ligne ajoutee : " + " ; ".join(valeurs) + ".")
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Impossible d'ajouter la ligne ({str(e)[:120]})."
