"""Connexion Alexa assistée par navigateur (à faire UNE fois).

    python scripts/alexa_login.py            # login par navigateur + vérif
    python scripts/alexa_login.py --check     # teste le cookie déjà sauvé (sans re-login)

Amazon a fermé le login « headless » par identifiants. La méthode qui marche
(celle de Home Assistant) : un **proxy local** ouvre une page où tu te connectes
**normalement dans ton navigateur** (email, mot de passe, captcha, 2FA — tout se
fait chez Amazon), et le proxy **capture la session**. Le cookie est sauvegardé
dans logs/alexa/.storage/, réutilisé ensuite par les outils Alexa.

⚠️ Point délicat : le proxy n'injecte les cookies dans la session qu'au moment où
ton navigateur atteint la **page finale Amazon** (« Successfully logged in »). Ce
script attend donc que la **session soit réellement peuplée** avant de sauver —
sinon on écrivait un cookie vide (d'où les « Connexion Alexa requise » passés).

alexapy est une lib communautaire non officielle : ça peut casser si Amazon change
quelque chose. Détail des échecs : relancer avec --debug (logs/alexa/login-debug.log, contient les cookies : ne pas le partager). Voir docs/alexa.md.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from core.config import reglage  # noqa: E402

# Console Windows en cp1252 : les emoji/cadres feraient planter les print(). On
# force UTF-8 en sortie (errors=replace) pour ne jamais casser un diagnostic.
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _dossier():
    d = RACINE / (reglage("alexa.dossier", "logs/alexa"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cookie_path(fichier):
    # alexapy écrit dans un sous-dossier « .storage/… » : créer le parent, sinon
    # la sauvegarde du cookie échoue en silence (OSError catchée par alexapy).
    p = _dossier() / fichier
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _chemin_cookie_reel(email):
    """Le fichier .cookies principal, tel que le nomme alexapy (_cookiefile[0])."""
    return Path(_cookie_path(f".storage/alexa_media.{email}.cookies"))


# --- Tokens OAuth (refresh_token/mac_dms) : la SEULE voie de session durable. ---
# alexapy ne les persiste pas lui-même ; c'est à nous de les sauver et de les
# réinjecter (oauth=...) au démarrage. Fichier sensible → sous logs/ (gitignore).
_OAUTH_CLES = ("access_token", "refresh_token", "mac_dms", "expires_in")


def _oauth_path(email):
    return Path(_cookie_path(f".storage/alexa_media.{email}.oauth.json"))


def _charger_oauth(email):
    p = _oauth_path(email)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _sauver_oauth(login, email):
    data = {k: getattr(login, k, None) for k in _OAUTH_CLES}
    _oauth_path(email).write_text(json.dumps(data), encoding="utf-8")
    return data


def _activer_debug():
    # Ce journal contient les echanges de connexion Amazon (cookies, code
    # d'autorisation) : seulement sur demande (--debug), jamais par defaut.
    if "--debug" not in sys.argv:
        return
    h = logging.FileHandler(_dossier() / "login-debug.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for nom in ("alexapy", "authcaptureproxy"):
        lg = logging.getLogger(nom)
        lg.setLevel(logging.DEBUG)
        lg.addHandler(h)


def _nouveau_login(oauth=None):
    from alexapy import AlexaLogin
    return AlexaLogin(
        url=reglage("alexa.url", "amazon.fr"),
        email=reglage("alexa.email", ""), password=reglage("alexa.password", ""),
        outputpath=_cookie_path, otp_secret=(reglage("alexa.otp_secret", "") or ""),
        oauth=(oauth or {}))


def _proxy_totp_frais(login, base_url):
    """AlexaProxy qui régénère le code TOTP à CHAQUE remplissage de page.

    Bug amont : AlexaProxy fige le code OTP à sa construction
    (`get_totp_token()` appelé une seule fois). Un TOTP expire en 30 s → si la
    page 2FA arrive plus tard, le code injecté est périmé, Amazon le refuse, et le
    flux reboucle sur la connexion (register → maplanding → oauth en rond). On
    régénère donc le code au moment exact du remplissage.
    """
    from alexapy import AlexaProxy

    class _ProxyFrais(AlexaProxy):
        def autofill(self, items, html):
            tok = self._login.get_totp_token()
            if tok:
                items = {**items, "otpCode": tok}
            return super().autofill(items, html)

    return _ProxyFrais(login, base_url)


def _nb_cookies_session(login):
    try:
        return sum(1 for _ in login.session.cookie_jar)
    except Exception:
        return 0


async def _verifier(email):
    """Vérif DURE : rejoue le vrai chemin runtime (nouvelle session depuis l'OAuth
    sauvé) et confirme par un appel réel. C'est ce que fera Jarvis au démarrage."""
    from alexapy import AlexaAPI
    oauth = _charger_oauth(email)
    a_refresh = bool(oauth.get("refresh_token"))
    ok, ndev = False, 0
    l2 = _nouveau_login(oauth)
    try:
        await l2.login()
        ok = await l2.test_loggedin()
        if ok:
            ndev = len(await AlexaAPI.get_devices(l2) or [])
            _sauver_oauth(l2, email)   # persiste un refresh_token éventuellement pivoté
    except Exception as e:
        print("  (rejeu runtime :", str(e)[:100], ")")
    finally:
        try:
            await l2.close()
        except Exception:
            pass
    print("\n── Vérification de la session durable ──────────────────")
    print(f"  Cookie sur disque   : {'oui' if _chemin_cookie_reel(email).exists() else 'NON'}")
    print(f"  refresh_token sauvé : {'oui' if a_refresh else 'NON'}")
    print(f"  Rejeu runtime OK    : {'oui' if ok else 'NON'}"
          + (f"  ({ndev} appareil(s))" if ok else ""))
    print("─────────────────────────────────────────────────────────")
    return a_refresh and ok


async def _check():
    """Teste la session SAUVÉE par un VRAI appel Alexa (sans re-login navigateur)."""
    email = reglage("alexa.email", "")
    if not email:
        print("Renseigne d'abord alexa.email / alexa.password dans config.yaml.")
        return
    _activer_debug()
    oauth = _charger_oauth(email)
    print(f"OAuth attendu : {_oauth_path(email)}")
    if not oauth.get("refresh_token"):
        print("❌ Aucun refresh_token sauvegardé. Lance « python scripts/alexa_login.py ».")
        return
    from alexapy import AlexaAPI
    login = _nouveau_login(oauth)
    try:
        await login.login()   # voie refresh_token (rebuild silencieux)
        if not await login.test_loggedin():
            print("❌ Session refusée par Amazon (token expiré ?). Relance le login.")
            return
        _sauver_oauth(login, email)   # persiste le token rafraîchi
        devices = await AlexaAPI.get_devices(login) or []
        print(f"✅ Connecté. {len(devices)} appareil(s) Alexa :")
        for d in devices:
            print(f"   · {d.get('accountName','?')} "
                  f"({'en ligne' if d.get('online') else 'hors ligne'})")
    finally:
        try:
            await login.close()
        except Exception:
            pass


async def _login_navigateur():
    email = reglage("alexa.email", "")
    if not (email and reglage("alexa.password", "")):
        print("Renseigne d'abord alexa.email / alexa.password dans config.yaml.")
        return
    _activer_debug()
    port = int(reglage("alexa.proxy_port", 3000))
    login = _nouveau_login()
    proxy = _proxy_totp_frais(login, f"http://127.0.0.1:{port}")

    await proxy.start_proxy()
    url_ouvrir = str(proxy.access_url())
    print("\n" + "=" * 64)
    print("  Ouvre CETTE adresse dans ton navigateur (sur ce PC) :")
    print("     ", url_ouvrir)
    print("  Connecte-toi à Amazon normalement (email, mot de passe, 2FA).")
    print("  ⚠️ VA JUSQU'AU BOUT : attends la page « Successfully logged in »")
    print("     (sinon la session n'est pas capturée).")
    print("=" * 64 + "\n  En attente de la connexion... (Ctrl+C pour annuler)")

    connecte = False
    try:
        for i in range(600):  # ~10 min
            # Signal FIABLE : le handler du proxy (test_amazon_url) a peuplé la
            # session ET posé login_successful / access_token quand le navigateur
            # a atteint la page finale Amazon. On exige des cookies en session
            # pour ne JAMAIS sauver un cookie vide.
            statut_ok = bool((login.status or {}).get("login_successful")
                             or login.access_token)
            if statut_ok and _nb_cookies_session(login) > 0:
                connecte = True
                break
            # Filet : validation réelle de la session toutes les ~4 s.
            if i and i % 4 == 0 and _nb_cookies_session(login) > 0:
                try:
                    if await login.test_loggedin(rebuild_session=False):
                        connecte = True
                        break
                except Exception:
                    pass
            await asyncio.sleep(1)

        if not connecte:
            n = _nb_cookies_session(login)
            print("\n⏱ Délai dépassé sans capturer la session "
                  f"(cookies en session : {n}).")
            if n == 0:
                print("   → Ton navigateur n'a pas atteint la page finale Amazon.")
                print("     Reprends et va jusqu'à « Successfully logged in ».")
            print("   Pour un diagnostic détaillé, relance avec --debug "
                  "(journal local logs/alexa/login-debug.log, ne le partage pas : "
                  "il contient tes cookies Amazon).")
            return

        # 1) Échange l'authorization_code (capturé par le proxy) contre des tokens
        #    OAuth durables : refresh_token + mac_dms. SANS ça, le cookie seul ne
        #    réauthentifie jamais l'API Alexa au redémarrage.
        print("\n  Enregistrement de l'appareil (obtention du refresh_token)…")
        try:
            await login.get_tokens()
        except Exception as e:
            print("  (get_tokens a échoué :", str(e)[:100], ")")
        # 2) Persiste le cookie (fallback) ET les tokens OAuth (voie durable).
        await login.finalize_login()
        _sauver_oauth(login, email)

        if await _verifier(email):
            print("\n✅ Connecté à Alexa, session durable vérifiée (refresh_token).")
            print("   Redémarre Jarvis, puis dis « mes appareils Alexa »,")
            print("   ou teste tout de suite : python scripts/alexa_login.py --check")
        else:
            print("\n⚠️ Login capturé mais la session durable n'est pas exploitable.")
            print("   (Souvent : get_tokens a échoué.) Relance avec --debug pour un")
            print("   journal détaillé ; ne le partage pas, il contient tes cookies Amazon.")
    except KeyboardInterrupt:
        print("\nAnnulé.")
    finally:
        try:
            await proxy.stop_proxy()
        except Exception:
            pass
        try:
            await login.close()
        except Exception:
            pass


def _afficher_code():
    """Affiche un code TOTP frais (à taper à la main si l'auto-remplissage rate)."""
    s = (reglage("alexa.otp_secret", "") or "").replace(" ", "")
    if not s:
        print("Aucun alexa.otp_secret dans config.yaml.")
        return
    try:
        import pyotp
        totp = pyotp.TOTP(s)
        reste = 30 - (int(__import__("time").time()) % 30)
        print(f"Code d'authentification : {totp.now()}   (valide encore ~{reste} s)")
    except Exception as e:
        print("Secret TOTP invalide :", e)


async def main():
    if "--check" in sys.argv:
        await _check()
    elif "--code" in sys.argv:
        _afficher_code()
    else:
        await _login_navigateur()


if __name__ == "__main__":
    asyncio.run(main())
