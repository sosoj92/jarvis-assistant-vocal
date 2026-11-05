"""Memoire long terme : remember (memoriser), recall (chercher), forget (oublier).

La memoire est structuree en preferences / people (proches) / projects / facts.
Jarvis appelle remember automatiquement quand l'utilisateur exprime une
preference, mentionne un proche ou parle d'un projet.
"""
from core import memoire
from core.registre import outil
from core.util import sans_accents

_CATEGORIES = {
    "preference": "preferences", "preferences": "preferences", "pref": "preferences",
    "personne": "people", "personnes": "people", "people": "people",
    "proche": "people", "proches": "people", "contact": "people",
    "projet": "projects", "projets": "projects", "project": "projects",
    "fait": "facts", "faits": "facts", "fact": "facts", "info": "facts",
}


@outil(
    nom="remember",
    description="Memorise durablement une information sur l'utilisateur. A appeler "
                "AUTOMATIQUEMENT (sans commenter) quand il exprime une preference "
                "('je prefere les lumieres chaudes le soir'), mentionne un proche, "
                "ou parle d'un projet en cours. Choisis la bonne categorie.",
    parametres={
        "type": "object",
        "properties": {
            "categorie": {
                "type": "string",
                "enum": ["preference", "personne", "projet", "fait"],
                "description": "Type d'information a memoriser.",
            },
            "contenu": {
                "type": "string",
                "description": "L'information, formulee clairement. "
                               "Ex : 'aime les lumieres chaudes le soir'.",
            },
            "cle": {
                "type": "string",
                "description": "Etiquette courte (nom du proche, du projet, ou "
                               "sujet de la preference). Facultatif pour un fait.",
            },
        },
        "required": ["categorie", "contenu"],
    },
)
def remember(categorie: str, contenu: str, cle: str = "") -> str:
    """Memorise une information dans la bonne categorie."""
    contenu = (contenu or "").strip()
    if not contenu:
        return "Rien a retenir."
    cat = _CATEGORIES.get(sans_accents(categorie).strip(), "facts")
    cle = (cle or "").strip()

    with memoire.VERROU:        # pas de remember/forget concurrent entre lecture et ecriture
        m = memoire.charger()
        if cat == "facts":
            if contenu not in m["facts"]:
                m["facts"].append(contenu)
        else:
            etiquette = cle or contenu[:40]
            m[cat][etiquette] = contenu
        memoire.sauver(m)
    return "C'est note."


@outil(
    nom="recall",
    description="Cherche une information dans la memoire long terme (preferences, "
                "proches, projets, faits). A utiliser quand l'utilisateur demande "
                "'qu'est-ce que tu sais sur...', 'tu te souviens de...'.",
    parametres={
        "type": "object",
        "properties": {
            "requete": {"type": "string",
                        "description": "Sujet recherche (vide = tout resumer)."}
        },
    },
)
def recall(requete: str = "") -> str:
    """Cherche dans la memoire ; sans requete, resume tout ce qui est connu."""
    m = memoire.charger()
    besoin = sans_accents(requete).strip()

    trouves = []
    for cat in ("preferences", "people", "projects"):
        for cle, val in m[cat].items():
            if not besoin or besoin in sans_accents(f"{cle} {val}"):
                trouves.append(f"{cle} : {val}")
    for fait in m["facts"]:
        if not besoin or besoin in sans_accents(fait):
            trouves.append(fait)

    if not trouves:
        return "Je n'ai rien la-dessus." if besoin else "Je ne retiens rien pour l'instant."
    return "Je retiens : " + " ; ".join(trouves)


@outil(
    nom="forget",
    description="Oublie les informations memorisees contenant un sujet donne. A "
                "utiliser quand l'utilisateur dit 'oublie...', 'efface ce que tu sais sur...'.",
    parametres={
        "type": "object",
        "properties": {
            "sujet": {"type": "string", "description": "Mot-cle a oublier."}
        },
        "required": ["sujet"],
    },
)
def forget(sujet: str) -> str:
    """Oublie tout ce qui contient ce sujet, dans toutes les categories."""
    besoin = sans_accents(sujet).strip()
    if not besoin:
        return "Quoi oublier ?"

    with memoire.VERROU:
        m = memoire.charger()
        retires = 0
        for cat in ("preferences", "people", "projects"):
            for cle in list(m[cat]):
                if besoin in sans_accents(f"{cle} {m[cat][cle]}"):
                    del m[cat][cle]
                    retires += 1
        avant = len(m["facts"])
        m["facts"] = [f for f in m["facts"] if besoin not in sans_accents(f)]
        retires += avant - len(m["facts"])

        if retires == 0:
            return "Je n'ai rien la-dessus."
        # Copie dans logs/memory.json.bak : un sujet trop court ou mal entendu
        # peut effacer bien plus que prevu, l'ancienne memoire reste recuperable.
        memoire.sauvegarder()
        memoire.sauver(m)
    return f"Oublie : {retires} element(s)."
