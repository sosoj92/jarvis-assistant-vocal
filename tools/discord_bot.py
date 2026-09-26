"""Bot Discord : resume tes mentions (24h) et les messages du jour par salon.

LIMITES (importantes) : un bot ne voit que les serveurs ou TU l'as invite et les
salons ou il a la permission de lire. Il ne peut PAS lire tes MP prives (DMs avec
d'autres personnes), ni les serveurs ou il n'est pas, ni savoir ce que tu as lu
(l'etat "non lu" est propre a ton compte). On n'utilise jamais ton token de compte
perso (interdit par Discord).

Prerequis : dans le portail developpeur Discord, activer le "Message Content
Intent" du bot, l'inviter sur ton serveur, et mettre token + user_id dans
config.yaml (section discord).
"""
import asyncio
import datetime
import threading
import time

from core.config import reglage
from core.journal import obtenir
from core.registre import outil

LOG = obtenir()

# Reference vers le bot lance en tache de fond (boucle asyncio dans un thread).
_BOT = {"loop": None, "client": None, "lance": False}

_CAP_SALON = 150     # messages max lus par salon
_CAP_TOTAL = 600     # messages max au total (garde-fou anti-lenteur)
_DELAI = 45          # secondes avant d'abandonner le scan


def _configure():
    return bool(reglage("discord.token", "") and reglage("discord.user_id", ""))


def demarrer_discord():
    """Connecte le bot en tache de fond (si configure)."""
    if not _configure() or _BOT["lance"]:
        return
    _BOT["lance"] = True
    threading.Thread(target=_lancer, daemon=True).start()
    print("Bot Discord : connexion en cours...")


def _lancer():
    import discord

    token = reglage("discord.token", "")
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    _BOT["client"] = client

    @client.event
    async def on_ready():
        LOG.info("discord: connecte comme %s", client.user)
        print(f"Bot Discord connecte ({client.user}).")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _BOT["loop"] = loop
    try:
        loop.run_until_complete(client.start(token))
    except Exception as e:
        LOG.exception("discord: bot arrete")
        print(f"Bot Discord arrete : {e}")


async def _collecter(client, apres):
    """Collecte les messages lisibles depuis 'apres'. Renvoie une liste de dicts."""
    out = []
    for guild in client.guilds:
        for salon in guild.text_channels:
            if len(out) >= _CAP_TOTAL:
                return out
            try:
                if not salon.permissions_for(guild.me).read_message_history:
                    continue
                async for msg in salon.history(after=apres, limit=_CAP_SALON):
                    out.append({
                        "auteur": msg.author.display_name,
                        "bot": msg.author.bot,
                        "serveur": guild.name,
                        "salon": salon.name,
                        "texte": (msg.content or "").replace("\n", " ").strip()[:200],
                        "mentions": [u.id for u in msg.mentions],
                        "quand": msg.created_at,
                    })
            except Exception:
                continue
    return out


def _lancer_scan(coro_factory):
    """Execute une coroutine de scan sur la boucle du bot, avec messages clairs."""
    if not _configure():
        return None, ("Discord n'est pas configure : ajoute le token du bot et ton "
                      "user_id dans config.yaml.")
    client, loop = _BOT["client"], _BOT["loop"]
    if not (loop and client and client.is_ready()):
        return None, "Le bot Discord n'est pas encore connecte, reessaie dans un instant."
    futur = asyncio.run_coroutine_threadsafe(coro_factory(client), loop)
    try:
        return futur.result(timeout=_DELAI), None
    except asyncio.TimeoutError:
        return None, ("Le scan Discord prend trop de temps (beaucoup de salons). "
                      "Reessaie, ou reduis le nombre de salons ou le bot peut lire.")
    except Exception as e:
        return None, f"Impossible de lire Discord : {e or type(e).__name__}"


# ------------------------------------------------------------------- mentions

@outil(
    nom="get_mentions_summary",
    description="Resume tes mentions Discord des dernieres 24h (dans les serveurs ou "
                "le bot est present). A utiliser pour 'mes mentions Discord', 'on m'a "
                "tague sur Discord'.",
    lent=True,
    phrase_attente="Je regarde tes mentions Discord.",
)
def get_mentions_summary() -> str:
    apres = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    messages, erreur = _lancer_scan(lambda c: _collecter(c, apres))
    if erreur:
        return erreur
    user_id = int(reglage("discord.user_id"))
    mentions = [m for m in messages if user_id in m["mentions"]]
    if not mentions:
        return "Aucune mention Discord dans les dernieres 24 heures."
    apercu = " ; ".join(f"{m['auteur']} dans {m['serveur']}/{m['salon']} : {m['texte']}"
                        for m in mentions[-6:])
    return f"{len(mentions)} mention(s) sur Discord ces 24h. {apercu}"


# ----------------------------------------------------- resume des salons (jour)

def _debut_periode(heures):
    if heures and heures > 0:
        return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=heures)
    minuit = datetime.datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0)
    return minuit.astimezone(datetime.timezone.utc)


def digest_journal(heures: int = 24, attente_s: float = 18.0):
    """Statistiques Discord sobres pour Signal Matin, sans contenu de message.

    Le journal ne conserve ni citation, ni auteur, ni message brut. Il imprime
    seulement les volumes, le nombre de mentions et les salons les plus actifs.
    """
    if not _configure():
        return None, "Discord n'est pas configure."
    demarrer_discord()
    deadline = time.monotonic() + max(1.0, attente_s)
    while time.monotonic() < deadline:
        client, loop = _BOT["client"], _BOT["loop"]
        if loop and client and client.is_ready():
            break
        time.sleep(.25)
    apres = _debut_periode(heures)
    messages, erreur = _lancer_scan(lambda c: _collecter(c, apres))
    if erreur:
        return None, erreur
    user_id = int(reglage("discord.user_id"))
    utiles = [m for m in messages if not m["bot"] and m["texte"]]
    mentions = sum(user_id in m["mentions"] for m in utiles)
    par_salon = {}
    for message in utiles:
        key = (message["serveur"], message["salon"])
        par_salon[key] = par_salon.get(key, 0) + 1
    actifs = [
        {"serveur": serveur, "salon": salon, "messages": total}
        for (serveur, salon), total in sorted(
            par_salon.items(), key=lambda row: (-row[1], row[0]))[:4]
    ]
    return {
        "messages": len(utiles),
        "salons": len(par_salon),
        "mentions": mentions,
        "actifs": actifs,
    }, None


@outil(
    nom="get_channel_summary",
    description="Resume les nouveaux messages du jour sur tes salons Discord (tous les "
                "salons lisibles, pas seulement les mentions). Pour 'resume-moi ce qui "
                "s'est dit sur Discord aujourd'hui', 'quoi de neuf sur mes salons', 'le "
                "recap Discord de la journee'.",
    parametres={
        "type": "object",
        "properties": {
            "heures": {"type": "integer",
                       "description": "Fenetre en heures (0 ou absent = depuis ce matin)."}
        },
    },
    lent=True,
    phrase_attente="Je parcours tes salons Discord.",
)
def get_channel_summary(heures: int = 0) -> str:
    apres = _debut_periode(heures)
    messages, erreur = _lancer_scan(lambda c: _collecter(c, apres))
    if erreur:
        return erreur
    # Ecarte les messages du bot lui-meme ; garde le reste.
    messages = [m for m in messages if not m["bot"] and m["texte"]]
    if not messages:
        quand = "aujourd'hui" if not heures else f"ces {heures}h"
        return f"Aucun nouveau message sur tes salons Discord {quand}."

    # Regroupe par serveur/salon pour un digest que l'assistant resume ensuite.
    par_salon = {}
    for m in messages:
        par_salon.setdefault((m["serveur"], m["salon"]), []).append(m)

    lignes = []
    for (serveur, salon), msgs in sorted(par_salon.items(), key=lambda x: -len(x[1])):
        extrait = " | ".join(f"{x['auteur']}: {x['texte']}" for x in msgs[-12:])
        lignes.append(f"[{serveur} / #{salon}] ({len(msgs)} msg) {extrait}")

    quand = "aujourd'hui" if not heures else f"ces {heures}h"
    entete = (f"{len(messages)} message(s) sur {len(par_salon)} salon(s) {quand}. "
              "Fais-en un resume vocal clair, par salon, en allant a l'essentiel :\n")
    return entete + "\n".join(lignes[:15])
