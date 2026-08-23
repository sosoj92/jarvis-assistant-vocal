"""Overlay de réponses : mini-fenêtre flottante qui affiche à l'écrit ce que Jarvis
dit, en complément (ou à la place) de la voix. JARVIS PUR : affichage local, temps
réel, zéro réseau.

Techno : fenêtre **native tkinter** (stdlib, aucun paquet) + appels **Win32 (ctypes)**
sur Windows, **Cocoa via tkinter** sur macOS.

Sur Windows (RÈGLE D'OR — jamais de vol de focus) :
  - WS_EX_NOACTIVATE  : la fenêtre n'attrape jamais le focus clavier (pas d'alt-tab
                        de ton jeu/appli).
  - WS_EX_TRANSPARENT : clic-transparent par défaut (les clics passent au travers) ;
                        retiré dynamiquement quand la souris SURVOLE l'overlay, pour
                        pouvoir épingler/copier.
  - WS_EX_LAYERED     : opacité réglable.
  - -topmost          : toujours au-dessus.
  - SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) : visible pour toi, INVISIBLE
                        pour OBS/game-capture (tes réponses n'apparaissent pas en live).
Sur macOS, tkinter expose deux des quatre garanties : `-topmost` (toujours au-dessus)
et `-alpha` (opacité). On ajoute `-type utility` quand Tk le supporte, pour ne pas
apparaître dans le Dock ni voler le focus au premier plan. En revanche il n'existe
pas d'équivalent tkinter à WS_EX_TRANSPARENT (clic-transparent) ni à
WDA_EXCLUDEFROMCAPTURE : sur Mac, l'overlay est cliquable, et il EST visible pour
OBS — si tu streames, place-le sur un écran non capturé (overlay.ecran) ou coupe-le
(overlay.actif: false). C'est dit honnêtement plutôt que promis à moitié.

Limite honnête : un jeu en plein écran EXCLUSIF (pas borderless) peut masquer tout
overlay — la plupart des jeux tournent en borderless, donc OK.

Coût nul au repos : la fenêtre est withdraw() tant qu'aucune réponse n'est affichée.
Tout tourne dans un thread daemon ; les erreurs sont avalées (l'assistant prime).

API : demarrer(cfg) · afficher(texte, type=, extra=, duree=) · masquer() ·
      set_actif(bool) · configurer(**kw). Voir docs/overlay.md.
"""
import queue
import sys
import threading
import time

_WIN = sys.platform == "win32"
_MAC = sys.platform == "darwin"

# Réglages par défaut (surchargés par config.yaml -> overlay.*).
_CFG = {
    "actif": True,
    "ecran": 1,               # index moniteur (0 = principal, 1 = 2e écran…)
    "coin": "bas-droite",     # haut-gauche / haut-droite / bas-gauche / bas-droite
    "opacite": 0.92,          # 0.3 – 1.0
    "largeur": 420,           # px
    "duree_min": 4.0,         # s (réponse courte)
    "duree_max": 14.0,        # s (réponse longue)
    "marge": 24,              # px depuis le bord de l'écran
    "exclure_obs": True,      # invisible pour la capture (stream)
}

_Q = queue.Queue()
_THREAD = None
_ETAT = {"root": None, "hwnd": None, "labels": {}, "cache_hide": None,
         "epingle": False, "survol": False, "texte": "", "transparent": True}


# ============================================================ API publique

def demarrer(cfg=None):
    """Démarre l'overlay dans un thread daemon. Sans effet s'il tourne déjà."""
    global _THREAD
    if cfg:
        _CFG.update({k: v for k, v in cfg.items() if v is not None})
    if _THREAD is not None:
        return
    _THREAD = threading.Thread(target=_boucle, daemon=True, name="overlay")
    _THREAD.start()


def afficher(texte, type="reponse", extra=None, duree=None):
    """Affiche une réponse (ou une carte typée) sans jamais voler le focus."""
    if not _CFG.get("actif", True) or not texte:
        return
    _Q.put(("afficher", {"texte": str(texte), "type": type,
                         "extra": extra or {}, "duree": duree}))


def masquer():
    _Q.put(("masquer", None))


_DERNIERE = {"texte": "", "type": "reponse", "extra": {}}


def memoriser(texte, type="reponse", extra=None):
    """Mémorise la dernière réponse SANS l'afficher (pour la surcharge « affiche-le »)."""
    _DERNIERE.update({"texte": str(texte or ""), "type": type, "extra": extra or {}})


def reafficher():
    """Réaffiche la dernière réponse mémorisée (surcharge vocale « affiche-le »)."""
    if not _DERNIERE.get("texte"):
        return False
    _CFG["actif"] = True
    _Q.put(("afficher", {"texte": _DERNIERE["texte"], "type": _DERNIERE["type"],
                         "extra": _DERNIERE["extra"], "duree": None}))
    return True


def set_actif(actif):
    _CFG["actif"] = bool(actif)
    if not actif:
        masquer()


def est_actif():
    return bool(_CFG.get("actif", True))


def set_muet(actif):
    """Mode silencieux visuel : la réponse s'affiche mais Jarvis ne parle pas."""
    _CFG["muet"] = bool(actif)


def est_muet():
    return bool(_CFG.get("muet", False))


def configurer(**kw):
    _CFG.update({k: v for k, v in kw.items() if v is not None})
    _Q.put(("config", None))


def _polices():
    """(police semi-grasse, police normale) disponibles sur ce système."""
    if _MAC:
        return "SF Pro Display Semibold", "SF Pro Display"
    if _WIN:
        return "Segoe UI Semibold", "Segoe UI"
    return "DejaVu Sans Bold", "DejaVu Sans"


# ============================================================ thread tkinter

def _boucle():
    try:
        import tkinter as tk
    except Exception:
        return
    try:
        root = tk.Tk()
    except Exception:
        return
    root.withdraw()
    root.overrideredirect(True)
    try:
        root.wm_attributes("-topmost", True)
    except Exception:
        pass
    try:
        root.wm_attributes("-alpha", float(_CFG["opacite"]))
    except Exception:
        pass

    fond, accent, txtcol, dim = "#0d1017", "#5b8cff", "#e6e8ec", "#9aa2b1"
    cadre = tk.Frame(root, bg=fond, highlightthickness=1, highlightbackground="#2a2f3a")
    cadre.pack(fill="both", expand=True)
    bord = tk.Frame(cadre, bg=accent, width=4)
    bord.pack(side="left", fill="y")
    corps = tk.Frame(cadre, bg=fond)
    corps.pack(side="left", fill="both", expand=True, padx=14, pady=12)

    # Segoe UI n'existe que sur Windows : chaque OS a sa police système.
    demi, normale = _polices()

    lbl_tag = tk.Label(corps, text="JARVIS", bg=fond, fg=accent,
                       font=(demi, 9), anchor="w")
    lbl_tag.pack(fill="x")
    lbl_titre = tk.Label(corps, text="", bg=fond, fg=txtcol, justify="left",
                         anchor="w", font=(demi, 15),
                         wraplength=_CFG["largeur"] - 40)
    lbl_corps = tk.Label(corps, text="", bg=fond, fg=txtcol, justify="left",
                         anchor="w", font=(normale, 12),
                         wraplength=_CFG["largeur"] - 40)
    lbl_pied = tk.Label(corps, text="", bg=fond, fg=dim, anchor="w",
                        font=(normale, 9))

    _ETAT.update({"root": root, "labels": {
        "tag": lbl_tag, "titre": lbl_titre, "corps": lbl_corps, "pied": lbl_pied,
        "bord": bord, "cadre": cadre, "corps_frame": corps}})

    # clic n'importe où sur l'overlay -> épingle + copie le texte
    for w in (cadre, corps, lbl_tag, lbl_titre, lbl_corps, lbl_pied):
        w.bind("<Button-1>", lambda e: _epingler_copier())

    root.after(60, lambda: _init_styles(root))
    root.after(80, lambda: _pomper(root))
    root.after(150, lambda: _surveiller_survol(root))
    try:
        root.mainloop()
    except Exception:
        pass


def _init_styles(root):
    """Applique les styles natifs (une fois la fenêtre créée)."""
    if _MAC:
        _init_styles_mac(root)
        return
    if not _WIN:
        return
    try:
        h = _hwnd(root)
        _ETAT["hwnd"] = h
        _ajouter_exstyle(h, _WS_EX_LAYERED | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
                         | _WS_EX_TOPMOST)
        _set_transparent(h, True)
        _exclure_capture(h, bool(_CFG.get("exclure_obs", True)))
    except Exception:
        pass


def _init_styles_mac(root):
    """macOS : fenêtre flottante utilitaire, au-dessus, sans entrée dans le Dock."""
    for attribut, valeur in (("-topmost", True), ("-type", "utility")):
        try:
            root.wm_attributes(attribut, valeur)
        except Exception:
            pass          # -type n'existe pas sur toutes les versions de Tk
    try:
        # Empêche l'overlay de devenir la fenêtre active au moment de l'affichage.
        root.wm_attributes("-alpha", float(_CFG["opacite"]))
    except Exception:
        pass


# ============================================================ pompe de commandes

def _pomper(root):
    try:
        while True:
            action, data = _Q.get_nowait()
            if action == "afficher":
                _rendre(root, data)
            elif action == "masquer":
                _cacher(root)
            elif action == "config":
                _appliquer_config(root)
    except queue.Empty:
        pass
    except Exception:
        pass
    root.after(80, lambda: _pomper(root))


def _appliquer_config(root):
    try:
        root.wm_attributes("-alpha", float(_CFG["opacite"]))
    except Exception:
        pass
    if _WIN and _ETAT.get("hwnd"):
        _exclure_capture(_ETAT["hwnd"], bool(_CFG.get("exclure_obs", True)))


def _rendre(root, data):
    lab = _ETAT["labels"]
    typ, extra = data["type"], data["extra"]
    texte = data["texte"]
    _ETAT["texte"] = texte
    _ETAT["epingle"] = False

    for w in (lab["titre"], lab["corps"], lab["pied"]):
        w.pack_forget()

    rendu = _CARTES.get(typ, _carte_reponse)
    rendu(lab, texte, extra)

    _placer(root)
    try:
        root.deiconify()
        root.lift()
        root.wm_attributes("-topmost", True)
    except Exception:
        pass
    # anti focus-steal : ne JAMAIS appeler focus_force ; WS_EX_NOACTIVATE fait le reste.

    if _ETAT.get("cache_hide"):
        try:
            root.after_cancel(_ETAT["cache_hide"])
        except Exception:
            pass
    duree = data.get("duree") or _duree_auto(texte)
    _ETAT["cache_hide"] = root.after(int(duree * 1000),
                                     lambda: _cacher(root, auto=True))


def _cacher(root, auto=False):
    if auto and _ETAT.get("epingle"):
        return          # épinglé : on ne masque pas automatiquement
    try:
        root.withdraw()
    except Exception:
        pass


def _duree_auto(texte):
    mots = max(1, len(texte.split()))
    d = _CFG["duree_min"] + mots * 0.35
    return max(_CFG["duree_min"], min(_CFG["duree_max"], d))


# ============================================================ cartes (extensible)

def _carte_reponse(lab, texte, extra):
    lab["tag"].config(text="JARVIS")
    lab["corps"].config(text=texte)
    lab["corps"].pack(fill="x", pady=(4, 0))


def _carte_musique(lab, texte, extra):
    lab["tag"].config(text="♪  MUSIQUE")
    titre = extra.get("titre") or texte
    artiste = extra.get("artiste") or ""
    lab["titre"].config(text=titre)
    lab["titre"].pack(fill="x", pady=(4, 0))
    if artiste:
        lab["corps"].config(text=artiste)
        lab["corps"].pack(fill="x")
    pied = " · ".join(x for x in (extra.get("album"), str(extra.get("annee") or ""))
                      if x)
    if pied:
        lab["pied"].config(text=pied)
        lab["pied"].pack(fill="x", pady=(4, 0))


def _carte_meteo(lab, texte, extra):
    icone = extra.get("icone", "☁")
    lab["tag"].config(text="MÉTÉO")
    lab["titre"].config(text=f"{icone}  {extra.get('temp', '')}".strip())
    lab["titre"].pack(fill="x", pady=(4, 0))
    lab["corps"].config(text=texte)
    lab["corps"].pack(fill="x")


def _carte_minuteur(lab, texte, extra):
    lab["tag"].config(text="⏱  MINUTEUR")
    lab["titre"].config(text=extra.get("restant", texte))
    lab["titre"].pack(fill="x", pady=(4, 0))


# type de réponse -> fonction de rendu (ajoute une entrée pour étendre)
_CARTES = {
    "reponse": _carte_reponse,
    "musique": _carte_musique,
    "meteo": _carte_meteo,
    "minuteur": _carte_minuteur,
}


# ============================================================ placement multi-écran

def _placer(root):
    try:
        root.update_idletasks()
        larg = _CFG["largeur"]
        haut = max(80, root.winfo_reqheight())
        rect = _rect_moniteur(_CFG.get("ecran", 0))
        gauche, top, droite, bas = rect
        marge = _CFG["marge"]
        coin = str(_CFG.get("coin", "bas-droite"))
        x = (droite - larg - marge) if "droite" in coin else (gauche + marge)
        y = (bas - haut - marge) if "bas" in coin else (top + marge)
        root.geometry(f"{larg}x{haut}+{int(x)}+{int(y)}")
    except Exception:
        pass


def _rect_moniteur(index):
    """(gauche, haut, droite, bas) du moniteur voulu ; repli = écran principal."""
    monitors = _enum_moniteurs()
    if monitors and 0 <= index < len(monitors):
        return monitors[index]
    if monitors:
        return monitors[0]
    # repli sans ctypes : écran principal via tkinter
    r = _ETAT["root"]
    return (0, 0, r.winfo_screenwidth(), r.winfo_screenheight())


def _enum_moniteurs():
    """Rectangles des écrans, principal en premier. Liste vide si indisponible."""
    if _MAC:
        try:
            from core import plateforme
            return plateforme.moniteurs()
        except Exception:
            return []
    if not _WIN:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        rects = []

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(wintypes.RECT), ctypes.c_double)

        def _cb(hmon, hdc, lprc, data):
            r = lprc.contents
            rects.append((r.left, r.top, r.right, r.bottom))
            return 1

        u.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
        # moniteur principal (contenant 0,0) en premier pour un index stable
        rects.sort(key=lambda rc: (rc[0] != 0 or rc[1] != 0, rc[0], rc[1]))
        return rects
    except Exception:
        return []


# ============================================================ survol / épingle

def _surveiller_survol(root):
    """Rend l'overlay interactif UNIQUEMENT quand la souris est dessus (sinon
    clic-transparent), pour pouvoir épingler/copier sans jamais gêner.

    macOS n'offre pas de clic-transparent via tkinter : l'overlay y reste
    cliquable en permanence (le pied de carte le signale une fois affiché).
    """
    if _WIN and _ETAT.get("hwnd"):
        try:
            dedans = _souris_dans(root)
            if dedans and _ETAT["transparent"]:
                _set_transparent(_ETAT["hwnd"], False)
                _ETAT["transparent"] = False
                _ETAT["labels"]["pied"].config(text="clic = épingler / copier")
                _ETAT["labels"]["pied"].pack(fill="x", pady=(4, 0))
            elif not dedans and not _ETAT["transparent"]:
                _set_transparent(_ETAT["hwnd"], True)
                _ETAT["transparent"] = True
        except Exception:
            pass
    root.after(150, lambda: _surveiller_survol(root))


def _souris_dans(root):
    try:
        if root.state() == "withdrawn":
            return False
    except Exception:
        return False
    try:
        import ctypes

        class _PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = _PT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        return x <= pt.x <= x + w and y <= pt.y <= y + h
    except Exception:
        return False


def _epingler_copier():
    _ETAT["epingle"] = True
    root = _ETAT.get("root")
    try:
        root.clipboard_clear()
        root.clipboard_append(_ETAT.get("texte", ""))
        _ETAT["labels"]["pied"].config(text="épinglé · copié ✓")
        _ETAT["labels"]["pied"].pack(fill="x", pady=(4, 0))
    except Exception:
        pass


# ============================================================ Win32 (ctypes)

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TOPMOST = 0x00000008
_WDA_NONE = 0x00000000
_WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _u32():
    import ctypes
    return ctypes.windll.user32


def _hwnd(root):
    u = _u32()
    root.update_idletasks()
    h = u.GetParent(root.winfo_id())
    return h or root.winfo_id()


def _get_set_exstyle():
    u = _u32()
    getf = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
    setf = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
    return getf, setf


def _ajouter_exstyle(h, bits):
    getf, setf = _get_set_exstyle()
    ex = getf(h, _GWL_EXSTYLE)
    setf(h, _GWL_EXSTYLE, ex | bits)


def _set_transparent(h, on):
    getf, setf = _get_set_exstyle()
    ex = getf(h, _GWL_EXSTYLE)
    ex = (ex | _WS_EX_TRANSPARENT) if on else (ex & ~_WS_EX_TRANSPARENT)
    setf(h, _GWL_EXSTYLE, ex)


def _exclure_capture(h, on):
    try:
        _u32().SetWindowDisplayAffinity(
            h, _WDA_EXCLUDEFROMCAPTURE if on else _WDA_NONE)
    except Exception:
        pass


# ============================================================ démonstration

if __name__ == "__main__":
    demarrer({"actif": True})
    time.sleep(0.6)
    afficher("C'est Where Is The Love? de The Black Eyed Peas.", type="musique",
             extra={"titre": "Where Is The Love?", "artiste": "The Black Eyed Peas",
                    "album": "Elephunk", "annee": 2003})
    time.sleep(6)
    afficher("Il fait 22 degrés et ensoleillé à Paris cet après-midi.",
             type="meteo", extra={"icone": "☀", "temp": "22°"})
    time.sleep(6)
    afficher("C'est fait, la chambre est allumée.")
    time.sleep(8)
    print("fin démo")
