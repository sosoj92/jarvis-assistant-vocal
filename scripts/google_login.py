"""Autorisation Google (OAuth) pour Jarvis : Gmail et/ou Agenda.

    uv run python scripts/google_login.py mail        # Gmail (IMAP + SMTP)
    uv run python scripts/google_login.py agenda      # Google Agenda
    uv run python scripts/google_login.py mail agenda # les deux

A lancer UNE FOIS. Un navigateur s'ouvre, tu choisis ton compte, tu acceptes ;
le jeton est ecrit a cote du projet et se rafraichit ensuite tout seul.

A quoi ca sert : sur Google Workspace, l'administrateur peut interdire les mots
de passe d'application (et Google les retire progressivement). OAuth est le
chemin officiel, et le seul qui marche dans ce cas.

Prealable : un fichier google_credentials.json (identifiants « Application de
bureau » de la console Google Cloud). Voir docs/mail.md, section 1.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from core import google_oauth  # noqa: E402

USAGES = {
    "mail": (google_oauth.SCOPES_MAIL, "mail.token", "google_token_mail.json",
             "Gmail (lire, envoyer, corbeille)"),
    "agenda": (google_oauth.SCOPES_AGENDA, "agenda.token", "google_token.json",
               "Google Agenda (evenements)"),
}


def autoriser(usage):
    scopes, clef_config, defaut, libelle = USAGES[usage]
    jeton = google_oauth.chemin(clef_config, defaut)
    print(f"\n=== {libelle} ===")
    print(f"  jeton : {jeton}")
    if jeton.exists():
        reponse = input("  Un jeton existe deja. Le remplacer ? (o/N) : ").strip().lower()
        if reponse not in ("o", "oui", "y", "yes"):
            print("  On garde l'autorisation existante.")
            return True

    print("  Ouverture du navigateur — choisis ton compte et accepte...")
    try:
        google_oauth.identifiants(scopes, jeton, interactif=True)
    except FileNotFoundError as e:
        print(f"  [X] {e}")
        return False
    except Exception as e:
        print(f"  [X] Autorisation refusee ou interrompue : {str(e)[:200]}")
        return False
    print("  [OK] Autorise.")
    return True


def main():
    demandes = [a.lower() for a in sys.argv[1:] if a.lower() in USAGES]
    if not demandes:
        print(__doc__)
        print("Usages possibles :", ", ".join(USAGES))
        return 1

    print("=" * 56)
    print("  Autorisation Google pour Jarvis")
    print("=" * 56)

    ident = google_oauth.chemin("google.credentials", "google_credentials.json")
    if not ident.exists():
        print(f"\n[X] {ident.name} introuvable ({ident}).")
        print("    Console Google Cloud > API et services > Identifiants >")
        print("    Creer des identifiants > ID client OAuth > Application de bureau,")
        print("    puis telecharge le JSON sous ce nom. Details : docs/mail.md")
        return 1

    ok = all(autoriser(u) for u in demandes)

    if ok and "mail" in demandes:
        print("\nActive OAuth dans config.yaml :")
        print("    mail:")
        print('      adresse: "ton.adresse@ton-domaine.fr"')
        print("      oauth: true")
        print("\nPuis relance Jarvis et dis : « j'ai des nouveaux mails ? »")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
