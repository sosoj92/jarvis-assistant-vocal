"""Test manuel des outils systeme, composant par composant.

    uv run python scripts/test_mac.py            # tout, sans rien modifier
    uv run python scripts/test_mac.py --volume   # inclut les tests qui AGISSENT

Complementaire de doctor.py (qui verifie la configuration) et de la suite
pytest (qui verifie le code) : ici on touche vraiment au materiel, et on
affiche ce que macOS repond. C'est ce qui permet de distinguer un bug d'une
autorisation manquante.

Par defaut, rien n'est modifie : les tests qui changent le volume ou envoient
des touches demandent --volume / --touches. Aucun test n'eteint la machine.
"""
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from core import plateforme  # noqa: E402

OK, KO, WARN, INFO = "  [OK]", "  [X] ", "  [!] ", "  [i] "
_scores = {"ok": 0, "ko": 0, "warn": 0}


def titre(t):
    print(f"\n=== {t} ===")


def ok(msg):
    print(f"{OK} {msg}"); _scores["ok"] += 1


def ko(msg, fix=""):
    print(f"{KO} {msg}")
    if fix:
        print(f"       -> {fix}")
    _scores["ko"] += 1


def warn(msg, fix=""):
    print(f"{WARN} {msg}")
    if fix:
        print(f"       -> {fix}")
    _scores["warn"] += 1


def info(msg):
    print(f"{INFO} {msg}")


# ------------------------------------------------------------------ tests

def t_systeme():
    titre("Systeme")
    ok(plateforme.nom_machine())
    info(f"identifiant interne : {plateforme.SYSTEME}")
    if plateforme.EST_MAC:
        info("Apple Silicon" if plateforme.est_apple_silicon() else "Mac Intel")
    else:
        warn(f"ce script cible macOS ; ici c'est {plateforme.SYSTEME}",
             "les tests non pertinents seront sautes.")


def t_pyobjc():
    titre("PyObjC (acces bas niveau macOS)")
    if not plateforme.EST_MAC:
        info("hors macOS : sans objet.")
        return
    for module, role in (("AppKit", "app au premier plan, touches media"),
                         ("Quartz", "titres de fenetres, ecrans")):
        try:
            __import__(module)
            ok(f"{module} disponible ({role})")
        except Exception as e:
            warn(f"{module} absent ({role}) : {e}",
                 "uv sync — sinon Jarvis retombe sur osascript, plus lent.")


def t_chemins():
    titre("Chemins")
    racine = plateforme.racine_disque()
    (ok if Path(racine).exists() else ko)(f"racine disque : {racine}")
    info(f"donnees applicatives : {plateforme.dossier_donnees('ChromeJarvis')}")
    info(f"bash : {plateforme.bash_exe()}")
    info(f"python systeme : {plateforme.python_systeme()}")
    chrome = plateforme.chrome_exe()
    if chrome:
        ok(f"Chrome : {chrome}")
    else:
        warn("Chrome introuvable",
             "installe Google Chrome, ou renseigne navigateur.chrome_exe.")


def t_fenetre():
    titre("Fenetre au premier plan")
    titre_fen, proc = plateforme.fenetre_active()
    if proc:
        ok(f"application : {proc}")
    else:
        warn("application au premier plan inconnue",
             "sur macOS : autorise l'Accessibilite pour ton terminal.")
    if titre_fen:
        ok(f"titre : {titre_fen}")
    elif plateforme.EST_MAC:
        warn("titre de fenetre vide",
             "autorisation « Enregistrement de l'ecran » manquante. Le nom de "
             "l'app suffit a la plupart des gestes.")


def t_ecrans():
    titre("Ecrans")
    rects = plateforme.moniteurs()
    if not rects:
        warn("aucun ecran enumere",
             "l'overlay et le cockpit retomberont sur l'ecran principal.")
        return
    for i, (g, h, d, b) in enumerate(rects):
        ok(f"ecran {i} : {d - g}x{b - h} en ({g},{h})")


def t_volume(agir):
    titre("Volume")
    actuel = plateforme.volume_actuel()
    if actuel is None:
        warn("volume non mesurable sur ce systeme",
             "normal sur Windows ; sur macOS, verifie osascript.")
    else:
        ok(f"volume actuel : {actuel} %")
    if not agir:
        info("test actif non lance (ajoute --volume pour l'essayer).")
        return
    if actuel is None:
        return
    info("baisse de 2 crans, puis retour a la valeur d'origine...")
    plateforme.volume_ajuster("baisser", 2)
    time.sleep(0.6)
    apres = plateforme.volume_actuel()
    plateforme.volume_definir(actuel)
    if apres is not None and apres < actuel:
        ok(f"le volume a bien bouge ({actuel} % -> {apres} %), puis restaure.")
    else:
        ko("le volume n'a pas bouge", "verifie osascript / les autorisations.")


def t_media(agir):
    titre("Touches media")
    if not agir:
        info("test actif non lance (ajoute --touches pour envoyer un play/pause).")
        return
    info("envoi d'un play/pause...")
    if plateforme.media("pause"):
        ok("commande acceptee (regarde si ta lecture a bascule).")
    else:
        warn("aucune commande n'a abouti",
             "macOS : autorise l'Accessibilite, ou ouvre Spotify/Musique.")


def t_voix(agir):
    titre("Voix de secours")
    if not plateforme.voix_systeme_disponible():
        ko(f"aucune voix systeme ({plateforme.SYSTEME})",
           "macOS : `say` fait partie du systeme, verifie ton PATH.")
        return
    ok(f"disponible : {plateforme.nom_voix_systeme()}")
    if plateforme.EST_MAC and "·" not in plateforme.nom_voix_systeme():
        warn("aucune voix francaise installee",
             "Reglages Systeme > Accessibilite > Contenu enonce > Gerer les voix "
             "-> ajoute Thomas ou Amelie.")
    if not agir:
        info("test actif non lance (ajoute --voix pour entendre une phrase).")
        return
    p = plateforme.parler_systeme("Bonjour, je suis Jarvis.")
    if p is None:
        ko("le moteur de voix n'a pas demarre")
        return
    p.communicate(input="Bonjour, je suis Jarvis.".encode("utf-8"))
    (ok if p.returncode == 0 else ko)(f"lecture terminee (code {p.returncode})")


def t_micro():
    titre("Micro")
    try:
        import sounddevice as sd
    except OSError as e:
        ko(f"PortAudio indisponible ({e})",
           "brew install portaudio, puis uv sync --reinstall-package sounddevice")
        return
    except Exception as e:
        ko(f"sounddevice absent ({e})", "uv sync")
        return
    entrees = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
               if d["max_input_channels"] > 0]
    if not entrees:
        ko("aucune entree audio",
           "macOS : Reglages Systeme > Confidentialite > Microphone, puis "
           "relance le terminal.")
        return
    ok(f"{len(entrees)} entree(s) audio")
    for i, nom in entrees:
        info(f"index {i} : {nom}")
    try:
        defaut = sd.query_devices(sd.default.device[0])["name"]
        ok(f"entree par defaut : {defaut}")
    except Exception:
        warn("pas d'entree par defaut")


def t_stats():
    titre("Statistiques systeme")
    try:
        from tools.stats import get_system_stats
        ok(get_system_stats())
    except Exception as e:
        ko(f"get_system_stats a echoue : {e}")


def t_reseau():
    titre("Reseau")
    if plateforme.ping("127.0.0.1", timeout_ms=1500):
        ok("ping 127.0.0.1 : la detection de presence fonctionnera.")
    else:
        warn("ping 127.0.0.1 sans reponse",
             "la detection de presence (presence.ip) ne marchera pas.")


# -------------------------------------------------------------------- flux

def main():
    args = set(sys.argv[1:])
    tout = "--tout" in args
    print("=" * 52)
    print("  Test des outils systeme de Jarvis")
    print("=" * 52)
    if not any(a.startswith("--") for a in args):
        print("\nTests passifs uniquement. Options : --volume  --touches  --voix  --tout")

    t_systeme()
    t_pyobjc()
    t_chemins()
    t_fenetre()
    t_ecrans()
    t_volume(tout or "--volume" in args)
    t_media(tout or "--touches" in args)
    t_voix(tout or "--voix" in args)
    t_micro()
    t_stats()
    t_reseau()

    print("\n" + "=" * 52)
    print(f"  Bilan : {_scores['ok']} OK, {_scores['warn']} avertissement(s), "
          f"{_scores['ko']} probleme(s).")
    if _scores["ko"]:
        print("  Voir TROUBLESHOOTING_MAC.md pour les [X] ci-dessus.")
    print("=" * 52)
    return 1 if _scores["ko"] else 0


if __name__ == "__main__":
    sys.exit(main())
