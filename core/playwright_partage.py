"""Instance Playwright partagee (une seule pour tout le process).

Les outils reservation (navigateur pilote) et navigateur (connexion a Chrome)
partagent une seule instance pour eviter tout conflit de boucle interne.

ATTENTION : l'API sync de Playwright est liee au thread qui l'a demarree
(greenlets). Depuis un autre thread, elle leve « cannot switch to a different
thread » ; depuis une boucle asyncio en cours, elle refuse de demarrer. Or chaque
tour vocal, chaque satellite (asyncio.to_thread) et chaque confirmation peuvent
tourner sur un thread different. Tout le travail Playwright doit donc passer par
executer(), qui le fait tourner sur UN thread dedie, toujours le meme.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

_PW = None
_THREAD_PW = None           # thread qui a demarre _PW (seul a pouvoir s'en servir)
_LOCAL = threading.local()


def _marquer_thread_dedie():
    _LOCAL.dedie = True


# Un seul worker : tout le travail Playwright est serialise sur ce thread.
_EXECUTEUR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright",
                                initializer=_marquer_thread_dedie)


def sur_thread_dedie():
    """Vrai si l'appelant tourne deja sur le thread Playwright dedie."""
    return getattr(_LOCAL, "dedie", False)


def executer(fn, *args, **kwargs):
    """Execute fn(*args, **kwargs) sur le thread Playwright dedie et renvoie son
    resultat (ses exceptions remontent telles quelles). Appel reentrant (deja sur
    ce thread) : execution directe, sans interblocage."""
    if sur_thread_dedie():
        return fn(*args, **kwargs)
    return _EXECUTEUR.submit(fn, *args, **kwargs).result()


def obtenir():
    """Instance Playwright partagee. Utilisable UNIQUEMENT dans le thread qui l'a
    creee : appeler obtenir() (et tout ce qui touche Playwright) via executer()."""
    global _PW, _THREAD_PW
    if _PW is None:
        from playwright.sync_api import sync_playwright
        _PW = sync_playwright().start()
        _THREAD_PW = threading.current_thread()
    elif _THREAD_PW is not threading.current_thread():
        # Sans ce garde, l'echec arrivait plus tard en erreur de greenlet obscure.
        raise RuntimeError(
            "Playwright est lie au thread qui l'a demarre : passer par "
            "core.playwright_partage.executer() pour l'utiliser depuis un autre thread.")
    return _PW
