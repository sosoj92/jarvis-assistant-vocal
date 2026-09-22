"""Budget & routage à la voix : « mon budget ? » (ventilé par fournisseur, avec la
part d'Hermes) et « passe en local / hybride / qualité ».

JARVIS PUR : lecture de sa propre compta + choix du backend. N1 (lecture / réglage
local). mon_budget exposé au MCP (lecture inoffensive) ; changer de mode ne l'est
pas (ça touche au corps de Jarvis).
"""
import re
import shutil
import subprocess

from core import budget, routage
from core.registre import outil


def _hermes_tokens(jours):
    """Tokens Hermes sur N jours (best-effort, via `hermes insights`)."""
    exe = shutil.which("hermes")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "insights", "--days", str(jours)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        m = re.search(r"Total tokens:\s+([\d,]+)", (p.stdout or "") + (p.stderr or ""))
        return int(m.group(1).replace(",", "")) if m else None
    except Exception:
        return None


def _eur(x):
    return f"{x:.2f}"


@outil(
    nom="mon_budget",
    description="Donne ma consommation et mon budget : coût du jour et du mois, "
                "ventilé par fournisseur (LLM cloud, voix locale, Twilio) + la part "
                "d'Hermes, et le pourcentage du plafond. Pour « mon budget ? », "
                "« combien j'ai dépensé ? », « ma conso ? ».",
    lent=True,
    phrase_attente="Je fais les comptes.",
    mcp_expose=True,
    affichage="toujours",
)
def mon_budget() -> str:
    e = budget.etat()
    r = budget.resume()
    phrases = [f"Aujourd'hui : {_eur(e['total_jour'])} dollars ; ce mois : "
               f"{_eur(e['total_mois'])} dollars."]

    if e["plafond_jour"]:
        phrases.append(f"Soit {int(e['pct_jour']*100)} pour cent du plafond du jour "
                       f"({_eur(e['plafond_jour'])}), il reste {_eur(e['reste_jour'])}.")
    elif e["plafond_mois"]:
        phrases.append(f"Soit {int(e['pct_mois']*100)} pour cent du plafond mensuel.")

    detail = [f"{f} {_eur(v['cout'])}" for f, v in
              sorted(r["mois"].items(), key=lambda kv: -kv[1]["cout"]) if v["cout"] > 0]
    twilio = budget._twilio_mois()
    if twilio > 0:
        detail.append(f"Twilio {_eur(twilio)}")
    if detail:
        phrases.append("Ce mois par poste : " + ", ".join(detail) + " dollars.")

    tok = _hermes_tokens(30)
    if tok:
        phrases.append(f"Hermes a consommé {tok:,}".replace(",", " ")
                       + " tokens sur 30 jours (compté à part).")
    return " ".join(phrases)


@outil(
    nom="mode_routage",
    description="Change le mode de routage de Jarvis : 'local' (tout local, gratuit, "
                "rien ne sort), 'hybride' (défaut : réflexes + vision en cloud éco, "
                "tâches de fond à Hermes), ou 'qualite' (cloud, modèle le plus fort). "
                "Pour « passe en local », « repasse en cloud / hybride », « mode "
                "qualité ».",
    parametres={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["local", "hybride", "qualite"]},
        },
        "required": ["mode"],
    },
    mcp_expose=False,
)
def mode_routage(mode: str) -> str:
    if not routage.definir_mode(mode):
        return "Mode inconnu. Choisis local, hybride ou qualité."
    # un changement manuel désarme la bascule auto (l'utilisateur décide)
    try:
        budget.effacer_bascule_auto()
    except Exception:
        pass
    libelles = {"local": "local, tout reste chez toi et c'est gratuit",
                "hybride": "hybride : réflexes et vision en cloud, réflexion de fond à Hermes",
                "qualite": "qualité, cloud avec le meilleur modèle"}
    m = routage.mode_actuel()
    return f"C'est fait, je passe en {libelles.get(m, m)}. (Effet au prochain échange.)"
