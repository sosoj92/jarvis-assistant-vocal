"""Tracker de gestes de la main — SOUS-PROCESS ISOLE (Python 3.11 + MediaPipe).

Frontiere vie privee : ce process est le SEUL a voir l'image de la webcam. Aucune
image n'est stockee, loggee ni transmise — seuls des *labels de gestes* ("poing",
"pincement_haut"...) partent vers Jarvis en loopback local (POST /api/gestes, avec
un token). MediaPipe (nouvelle API Tasks) tourne en CPU (XNNPACK).

Lance par core/gestes.py (Jarvis 3.13). Config passee via l'env GESTES_CONF (JSON).
Mode calibration : `--calibrate` (affiche la camera + landmarks + seuils reglables).

Vocabulaire v1 (gestes FIABLES, tenus) :
  pincement (pouce-index) + glissement vertical -> pincement_haut / pincement_bas
  main ouverte tenue      -> main_ouverte
  poing ferme tenu        -> poing
  swipe horizontal        -> swipe_gauche / swipe_droite
  (optionnel) main levee 2 s -> armement ("Jarvis regarde")
"""
import json
import os
import sys
import time

import cv2
import numpy as np
import requests
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import mediapipe as mp

def _backend_camera():
    """Backend de capture natif de l'OS.

    DirectShow est propre a Windows : sur macOS il faut AVFoundation, sinon
    VideoCapture s'ouvre a vide et le tracker croit la webcam absente.
    """
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_V4L2


# Indices des 21 landmarks de la main (MediaPipe).
POIGNET = 0
POUCE_TIP, INDEX_TIP, MAJEUR_TIP, ANN_TIP, AURIC_TIP = 4, 8, 12, 16, 20
INDEX_PIP, MAJEUR_PIP, ANN_PIP, AURIC_PIP = 6, 10, 14, 18
INDEX_MCP, AURIC_MCP = 5, 17


# ============================================================ classifieurs PURS
# (fonctions sans effet de bord, testables avec des landmarks synthetiques)

def _d(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def doigt_leve(lm, tip, pip):
    """Un doigt (index/majeur/annulaire/auriculaire) est tendu si le bout est
    NETTEMENT au-dessus (y plus petit) de sa phalange PIP."""
    return lm[tip][1] < lm[pip][1] - 0.02


def pouce_ouvert(lm):
    """Pouce ecarte : bout du pouce loin du bord interne de la main (index MCP)."""
    return _d(lm[POUCE_TIP], lm[INDEX_MCP]) > 0.10


def doigts_tendus(lm):
    """Nombre de doigts tendus (index..auriculaire), hors pouce."""
    paires = ((INDEX_TIP, INDEX_PIP), (MAJEUR_TIP, MAJEUR_PIP),
              (ANN_TIP, ANN_PIP), (AURIC_TIP, AURIC_PIP))
    return sum(1 for tip, pip in paires if doigt_leve(lm, tip, pip))


def est_main_ouverte(lm):
    # 4 doigts tendus (index..auriculaire) suffisent : la detection du pouce ecarte
    # est trop variable selon la main/l'angle pour etre exigee.
    return doigts_tendus(lm) >= 4


def est_poing(lm):
    return doigts_tendus(lm) == 0 and not pouce_ouvert(lm)


def distance_pincement(lm):
    """Distance normalisee pouce-index (petit = pincement)."""
    return _d(lm[POUCE_TIP], lm[INDEX_TIP])


def est_pincement(lm, seuil):
    return distance_pincement(lm) < seuil


def centre_x(lm):
    """Abscisse de reference de la main (poignet) pour le swipe."""
    return lm[POIGNET][0]


# ==================================================================== FSM

class MachineGestes:
    """Machine a etats anti-faux-positifs : gestes TENUS, zone morte, cooldown,
    swipe par vitesse, armement optionnel. Emet un label de geste ou None."""

    def __init__(self, conf):
        s = conf.get("seuils", {})
        self.pincement = float(s.get("pincement", 0.06))
        self.tenue_s = float(s.get("tenue_s", 1.0))
        self.cooldown_s = float(s.get("cooldown_s", 1.5))
        self.deadzone_lum = float(s.get("deadzone_lum", 0.06))
        self.swipe_seuil = float(s.get("swipe_seuil", 0.22))
        self.swipe_fenetre_s = float(s.get("swipe_fenetre_s", 0.4))
        arm = conf.get("armement", {})
        self.arm_actif = bool(arm.get("actif", False))
        self.arm_duree_s = float(arm.get("duree_s", 2.0))
        self.arm_fenetre_s = float(arm.get("fenetre_s", 8.0))

        self._geste_courant = None      # geste tenu en cours d'observation
        self._depuis = 0.0              # depuis quand il est tenu
        self._dernier_envoi = -1e9      # cooldown global (1er geste jamais bloque)
        self._pincement_base_y = None   # y de reference du pincement (glissement)
        self._hist_x = []               # (t, x) pour le swipe
        self._arme_jusqu = 0.0          # fenetre d'armement
        self._arm_depuis = 0.0

    def _cooldown_ok(self, t):
        return (t - self._dernier_envoi) >= self.cooldown_s

    def _arme(self, t):
        return (not self.arm_actif) or (t < self._arme_jusqu)

    def alimenter(self, lm, t):
        """lm = 21 (x,y) normalises, ou None si aucune main. Renvoie un label ou None."""
        if lm is None:
            self._geste_courant = None
            self._pincement_base_y = None
            self._hist_x.clear()
            return None

        # --- Armement (main levee tenue) : ouvre une fenetre "Jarvis regarde" ---
        if self.arm_actif:
            if est_main_ouverte(lm) and lm[POIGNET][1] < 0.5:  # main haute
                if not self._arm_depuis:
                    self._arm_depuis = t
                elif t - self._arm_depuis >= self.arm_duree_s and t >= self._arme_jusqu:
                    self._arme_jusqu = t + self.arm_fenetre_s
                    self._arm_depuis = 0.0
                    return "armement"
            else:
                self._arm_depuis = 0.0

        # --- Pincement + glissement vertical (continu, avec zone morte) ---
        if est_pincement(lm, self.pincement):
            y = lm[INDEX_TIP][1]
            if self._pincement_base_y is None:
                self._pincement_base_y = y
            elif self._arme(t) and self._cooldown_ok(t):
                if y < self._pincement_base_y - self.deadzone_lum:
                    self._pincement_base_y = y
                    self._dernier_envoi = t
                    return "pincement_haut"
                if y > self._pincement_base_y + self.deadzone_lum:
                    self._pincement_base_y = y
                    self._dernier_envoi = t
                    return "pincement_bas"
            self._geste_courant = None      # pincement occupe la main
            self._hist_x.clear()
            return None
        self._pincement_base_y = None

        # --- Swipe (vitesse horizontale, main ouverte) ---
        self._hist_x.append((t, centre_x(lm)))
        self._hist_x = [(tt, xx) for tt, xx in self._hist_x if t - tt <= self.swipe_fenetre_s]
        if est_main_ouverte(lm) and len(self._hist_x) >= 3:
            dx = self._hist_x[-1][1] - self._hist_x[0][1]
            if abs(dx) >= self.swipe_seuil and self._arme(t) and self._cooldown_ok(t):
                self._dernier_envoi = t
                self._hist_x.clear()
                self._geste_courant = None
                # image miroir : dx>0 (main vers la droite de l'image) = swipe droite
                return "swipe_droite" if dx > 0 else "swipe_gauche"

        # --- Gestes TENUS : poing / main ouverte (1 s stable) ---
        instant = "poing" if est_poing(lm) else ("main_ouverte" if est_main_ouverte(lm) else None)
        if instant != self._geste_courant:
            self._geste_courant = instant
            self._depuis = t
            return None
        if instant is not None and (t - self._depuis) >= self.tenue_s \
                and self._arme(t) and self._cooldown_ok(t):
            self._depuis = t + 999  # arme une seule fois jusqu'au relachement
            self._dernier_envoi = t
            return instant
        return None


# ==================================================================== I/O

def _envoyer(url, token, geste):
    try:
        requests.post(url, json={"geste": geste},
                      headers={"X-Gestes-Token": token}, timeout=1.5)
    except Exception:
        pass  # Jarvis occupe / injoignable : on ignore, jamais de blocage


def _landmarks_np(res):
    """Extrait la 1re main en liste de (x,y) normalises, ou None."""
    if not res.hand_landmarks:
        return None
    return [(p.x, p.y) for p in res.hand_landmarks[0]]


def boucle(conf, calibrer=False):
    device = int(conf.get("device", 0))
    fps = int(conf.get("fps", 24))
    url = conf.get("url", "http://127.0.0.1:8790/api/gestes")
    token = conf.get("token", "")
    modele = conf.get("model_path", "gestes/models/hand_landmarker.task")

    conf_det = float(conf.get("confiance_detection", 0.7))
    conf_track = float(conf.get("confiance_suivi", 0.7))
    base = mp_python.BaseOptions(model_asset_path=modele)
    options = mp_vision.HandLandmarkerOptions(
        base_options=base, num_hands=1,
        running_mode=mp_vision.RunningMode.VIDEO,
        min_hand_detection_confidence=conf_det, min_tracking_confidence=conf_track)
    landmarker = mp_vision.HandLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(device, _backend_camera())
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(conf.get("largeur", 640)))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(conf.get("hauteur", 480)))
    if not cap.isOpened():
        print(f"[gestes] webcam device {device} introuvable", file=sys.stderr)
        if sys.platform == "darwin":
            print("[gestes] macOS : autorise la Camera pour ton terminal dans "
                  "Reglages Systeme > Confidentialite et securite, puis relance.",
                  file=sys.stderr)
        return

    fsm = MachineGestes(conf)
    periode = 1.0 / max(5, fps)
    print(f"[gestes] tracker demarre (device {device}, {fps} fps){' — CALIBRATION' if calibrer else ''}",
          file=sys.stderr)

    try:
        while True:
            t0 = time.time()
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            frame = cv2.flip(frame, 1)  # miroir naturel
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            res = landmarker.detect_for_video(image, int(t0 * 1000))
            lm = _landmarks_np(res)

            geste = fsm.alimenter(lm, t0)
            if geste and not calibrer:
                _envoyer(url, token, geste)

            if calibrer:
                _afficher_calibration(frame, lm, fsm, geste)
                k = cv2.waitKey(1) & 0xFF
                if not _touches_calibration(k, fsm):
                    break

            dt = time.time() - t0
            if dt < periode:
                time.sleep(periode - dt)
    finally:
        cap.release()
        if calibrer:
            cv2.destroyAllWindows()
        landmarker.close()


# --------------------------------------------------------- mode calibration

def _afficher_calibration(frame, lm, fsm, geste):
    h, w = frame.shape[:2]
    if lm is not None:
        for x, y in lm:
            cv2.circle(frame, (int(x * w), int(y * h)), 4, (0, 255, 0), -1)
        pinc = distance_pincement(lm)
        infos = [f"doigts tendus : {doigts_tendus(lm)}  pouce : {pouce_ouvert(lm)}",
                 f"pincement dist : {pinc:.3f}  (seuil {fsm.pincement:.3f})",
                 f"main ouverte : {est_main_ouverte(lm)}  poing : {est_poing(lm)}"]
    else:
        infos = ["aucune main detectee"]
    infos += [f"tenue_s {fsm.tenue_s:.2f}  cooldown_s {fsm.cooldown_s:.2f}  swipe {fsm.swipe_seuil:.2f}",
              "[ + - ] seuil pincement   [ t/T ] tenue   [ s ] sauver   [ q ] quitter"]
    if geste:
        infos.insert(0, f">>> GESTE : {geste}")
    for i, ligne in enumerate(infos):
        cv2.putText(frame, ligne, (10, 24 + i * 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imshow("Jarvis — calibration gestes", frame)


def _touches_calibration(k, fsm):
    if k in (ord("q"), 27):
        return False
    if k == ord("+"):
        fsm.pincement = min(0.20, fsm.pincement + 0.005)
    elif k == ord("-"):
        fsm.pincement = max(0.02, fsm.pincement - 0.005)
    elif k == ord("t"):
        fsm.tenue_s = max(0.3, fsm.tenue_s - 0.1)
    elif k == ord("T"):
        fsm.tenue_s = min(3.0, fsm.tenue_s + 0.1)
    elif k == ord("s"):
        seuils = {"pincement": round(fsm.pincement, 3), "tenue_s": round(fsm.tenue_s, 2),
                  "cooldown_s": fsm.cooldown_s, "deadzone_lum": fsm.deadzone_lum,
                  "swipe_seuil": fsm.swipe_seuil, "swipe_fenetre_s": fsm.swipe_fenetre_s}
        chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump({"seuils": seuils}, f, ensure_ascii=False, indent=2)
        print(f"[gestes] seuils sauvegardes -> {chemin}", file=sys.stderr)
    return True


def main():
    conf = json.loads(os.environ.get("GESTES_CONF", "{}"))
    calibrer = "--calibrate" in sys.argv
    boucle(conf, calibrer=calibrer)


if __name__ == "__main__":
    main()
