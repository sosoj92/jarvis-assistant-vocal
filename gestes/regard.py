"""Prototype local de controle du pointeur par le regard.

La webcam reste strictement dans ce processus. Aucune image, aucun landmark et
aucune calibration ne sont enregistres ni transmis. Le clic par haussement
volontaire des deux sourcils est
desactive au demarrage et doit etre active explicitement avec la touche ``c``.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import argparse

from core import plateforme
import math
from pathlib import Path
import time

import numpy as np


# Topologie MediaPipe Face Landmarker (478 points avec les iris).
OEIL_DROIT = {
    "coins": (33, 133),
    "haut": (159, 158),
    "bas": (145, 153),
    "iris": (468, 469, 470, 471, 472),
}
OEIL_GAUCHE = {
    "coins": (362, 263),
    "haut": (386, 385),
    "bas": (374, 380),
    "iris": (473, 474, 475, 476, 477),
}
SOURCIL_DROIT_BAS = (46, 53, 52, 65, 55)
SOURCIL_DROIT_HAUT = (70, 63, 105, 66, 107)
SOURCIL_GAUCHE_BAS = (276, 283, 282, 295, 285)
SOURCIL_GAUCHE_HAUT = (300, 293, 334, 296, 336)
SOURCIL_DROIT = SOURCIL_DROIT_BAS + SOURCIL_DROIT_HAUT
SOURCIL_GAUCHE = SOURCIL_GAUCHE_BAS + SOURCIL_GAUCHE_HAUT
BOUCHE_CONTOUR = (61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
                  308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78, 13)
NB_CARACTERISTIQUES_REGARD = 13


def _distance(a, b):
    return float(np.hypot(float(a[0]) - float(b[0]),
                          float(a[1]) - float(b[1])))


def _moyenne(points, indices):
    return np.mean(points[list(indices), :2], axis=0)


def _projection(point, debut, fin):
    """Position de *point* sur le segment oriente debut -> fin."""
    axe = np.asarray(fin, dtype=float) - np.asarray(debut, dtype=float)
    denom = float(np.dot(axe, axe))
    if denom < 1e-9:
        return 0.5
    return float(np.dot(np.asarray(point, dtype=float) - debut, axe) / denom)


def _caracteristiques_oeil(points, spec):
    iris = _moyenne(points, spec["iris"])
    coin_a, coin_b = (points[i, :2] for i in spec["coins"])
    haut = _moyenne(points, spec["haut"])
    bas = _moyenne(points, spec["bas"])
    axe = np.asarray(coin_b) - np.asarray(coin_a)
    largeur = max(1e-6, float(np.linalg.norm(axe)))
    perpendiculaire = np.asarray((-axe[1], axe[0])) / largeur
    milieu = (np.asarray(coin_a) + np.asarray(coin_b)) / 2.0
    vertical_local = float(np.dot(iris - milieu, perpendiculaire) / largeur)
    return (_projection(iris, coin_a, coin_b), vertical_local,
            _projection(iris, haut, bas))


def caracteristiques_regard(points):
    """Vecteur regard + position de tete appris par la calibration.

    La verticale est mesuree de deux manieres complementaires : dans le repere
    geometrique de l'oeil (robuste aux mouvements de tete) et entre les paupieres
    (signal plus ample). La regression choisit leur poids pour chaque personne.
    """
    points = np.asarray(points, dtype=float)
    if points.shape[0] < 478:
        raise ValueError("Face Landmarker doit fournir les 478 points avec iris")
    dh, dv, dp = _caracteristiques_oeil(points, OEIL_DROIT)
    gh, gv, gp = _caracteristiques_oeil(points, OEIL_GAUCHE)
    oeil_droit = points[33, :2]
    oeil_gauche = points[263, :2]
    centre_yeux = (oeil_droit + oeil_gauche) / 2.0
    nez = points[1, :2]
    front = points[10, :2]
    menton = points[152, :2]
    largeur = max(1e-6, _distance(oeil_droit, oeil_gauche))
    hauteur = max(1e-6, _distance(front, menton))
    roulis = math.atan2(float(oeil_gauche[1] - oeil_droit[1]),
                        float(oeil_gauche[0] - oeil_droit[0]))
    nez_x = float((nez[0] - centre_yeux[0]) / largeur)
    nez_y = float((nez[1] - centre_yeux[1]) / hauteur)
    return np.asarray(
        [dh, dv, dp, gh, gv, gp,
         centre_yeux[0], centre_yeux[1], largeur,
         nez_x, nez_y, roulis, hauteur],
        dtype=float,
    )


@dataclass
class CalibrationRegard:
    moyenne: np.ndarray
    echelle: np.ndarray
    coefficients_x: np.ndarray
    coefficients_y: np.ndarray
    centres_rbf: np.ndarray | None = None
    poids_rbf: np.ndarray | None = None
    largeur_rbf: float = 0.18
    erreur_moyenne: float = 0.0

    @staticmethod
    def _developper(observations_normalisees, axe):
        """Base courte et regularisee, specialisee par axe de l'ecran."""
        z = np.atleast_2d(np.asarray(observations_normalisees, dtype=float))
        if z.shape[1] != NB_CARACTERISTIQUES_REGARD:
            raise ValueError("observation du regard invalide")
        if axe == "x":
            # Iris horizontaux + translation, lacet et roulis de la tete.
            base = z[:, [0, 3, 6, 8, 9, 11]]
            extras = np.column_stack((
                z[:, 0] ** 2, z[:, 3] ** 2, z[:, 0] * z[:, 3],
                z[:, 0] * z[:, 9], z[:, 3] * z[:, 9],
            ))
        else:
            # Deux lectures verticales par oeil + tangage et hauteur de tete.
            base = z[:, [1, 2, 4, 5, 7, 10, 12]]
            extras = np.column_stack((
                z[:, 1] ** 2, z[:, 4] ** 2, z[:, 1] * z[:, 4],
                z[:, 1] * z[:, 10], z[:, 4] * z[:, 10],
            ))
        return np.column_stack((np.ones(len(z)), base, extras))

    @staticmethod
    def _ridge(matrice, cible, regularisation=0.04):
        penalite = np.eye(matrice.shape[1]) * float(regularisation)
        penalite[0, 0] = 0.0
        return np.linalg.solve(
            matrice.T @ matrice + penalite,
            matrice.T @ np.asarray(cible, dtype=float),
        )

    @classmethod
    def ajuster(cls, observations, cibles, ancres_observations=None,
                ancres_cibles=None):
        x = np.asarray(observations, dtype=float)
        y = np.asarray(cibles, dtype=float)
        if (x.ndim != 2 or x.shape[1] != NB_CARACTERISTIQUES_REGARD
                or len(x) < 14):
            raise ValueError("pas assez de points de calibration")
        moyenne = np.mean(x, axis=0)
        echelle = np.std(x, axis=0)
        echelle[echelle < 1e-6] = 1.0
        z = (x - moyenne) / echelle
        matrice_x = cls._developper(z, "x")
        matrice_y = cls._developper(z, "y")
        coefficients_x = cls._ridge(matrice_x, y[:, 0])
        coefficients_y = cls._ridge(matrice_y, y[:, 1])
        calibration = cls(moyenne, echelle, coefficients_x, coefficients_y)
        if ancres_observations is not None and ancres_cibles is not None:
            ancres_observations = np.asarray(ancres_observations, dtype=float)
            ancres_cibles = np.asarray(ancres_cibles, dtype=float)
            globales = np.asarray([
                calibration._predire_globale(obs) for obs in ancres_observations
            ])
            residus = ancres_cibles - globales
            distances = np.linalg.norm(
                globales[:, None, :] - globales[None, :, :], axis=2)
            hors_diagonale = distances + np.eye(len(globales)) * 10.0
            voisinages = np.min(hors_diagonale, axis=1)
            largeur_rbf = float(np.clip(np.median(voisinages) * 1.8,
                                        0.07, 0.28))
            noyau = np.exp(-(distances ** 2) / (2.0 * largeur_rbf ** 2))
            regularisation = np.eye(len(globales)) * 0.025
            calibration.centres_rbf = globales
            calibration.poids_rbf = np.linalg.solve(
                noyau + regularisation, residus)
            calibration.largeur_rbf = largeur_rbf
        predictions = np.asarray([calibration.predire(obs) for obs in x])
        calibration.erreur_moyenne = float(
            np.mean(np.linalg.norm(predictions - y, axis=1)))
        return calibration

    def _predire_globale(self, observation):
        observation = np.asarray(observation, dtype=float)
        z = (observation - self.moyenne) / self.echelle
        px = float(self._developper(z, "x")[0] @ self.coefficients_x)
        py = float(self._developper(z, "y")[0] @ self.coefficients_y)
        return np.asarray((px, py), dtype=float)

    def predire(self, observation):
        globale = self._predire_globale(observation)
        if self.centres_rbf is None or self.poids_rbf is None:
            return np.clip(globale, 0.0, 1.0)
        distances = np.linalg.norm(self.centres_rbf - globale, axis=1)
        noyau = np.exp(-(distances ** 2) / (2.0 * self.largeur_rbf ** 2))
        correction = noyau @ self.poids_rbf
        return np.clip(globale + correction, 0.0, 1.0)


def lisser_pointeur(precedent, brut, diagonale):
    """Filtre adaptatif : precis a l'arret, reactif lors d'un grand deplacement."""
    brut = np.asarray(brut, dtype=float)
    if precedent is None:
        return brut
    precedent = np.asarray(precedent, dtype=float)
    distance = float(np.linalg.norm(brut - precedent))
    if distance <= max(2.0, diagonale * 0.0012):
        return precedent
    proportion = min(1.0, distance / max(1.0, diagonale * 0.15))
    alpha = 0.18 + 0.55 * proportion
    return alpha * brut + (1.0 - alpha) * precedent


@dataclass
class DetecteurSourcils:
    tenue_s: float = 0.34
    cooldown_s: float = 0.70
    _jusqu: float = 0.0
    _candidat_depuis: float | None = None
    _attend_neutre: bool = False

    def alimenter(self, score, profil, maintenant):
        """Retourne ``clic_gauche`` pour deux sourcils leves puis relaches."""
        score = float(score)
        if score <= float(profil["retour"]):
            self._candidat_depuis = None
            self._attend_neutre = False
            return None
        if self._attend_neutre or maintenant < self._jusqu:
            return None
        if score < float(profil["seuil"]):
            self._candidat_depuis = None
            return None
        if self._candidat_depuis is None:
            self._candidat_depuis = maintenant
            return None
        if maintenant - self._candidat_depuis < self.tenue_s:
            return None
        self._attend_neutre = True
        self._jusqu = maintenant + self.cooldown_s
        self._candidat_depuis = None
        return "clic_gauche"


class SourisLocale:
    """Controle souris via core/plateforme (Win32 sur Windows, Quartz sur macOS)."""

    def __init__(self):
        import mss
        with mss.mss() as sct:
            self.largeur = int(sct.monitors[1]["width"])
            self.hauteur = int(sct.monitors[1]["height"])

    def deplacer(self, x, y):
        plateforme.souris_deplacer(int(x), int(y))

    def cliquer(self, bouton):
        plateforme.souris_cliquer("droite" if bouton == "clic_droit" else "gauche")


def _landmarks_np(resultat):
    if not resultat.face_landmarks:
        return None
    return np.asarray([(p.x, p.y, p.z)
                       for p in resultat.face_landmarks[0]], dtype=float)


def _blendshapes_dict(resultat):
    if not resultat.face_blendshapes:
        return {}
    return {
        str(categorie.category_name): float(categorie.score)
        for categorie in resultat.face_blendshapes[0]
    }


def score_clignement(blendshapes):
    """Retourne le niveau du plus ferme des deux yeux."""
    normalisees = {
        str(nom).replace("_", "").lower(): float(score)
        for nom, score in (blendshapes or {}).items()
    }
    return max(normalisees.get("eyeblinkleft", 0.0),
               normalisees.get("eyeblinkright", 0.0))


def score_sourcils(blendshapes):
    """Score de haussement symetrique, tolerant aux variantes de nommage."""
    normalisees = {
        str(nom).replace("_", "").lower(): float(score)
        for nom, score in (blendshapes or {}).items()
    }
    interieur = normalisees.get("browinnerup", 0.0)
    gauche = normalisees.get("browouterupleft", 0.0)
    droite = normalisees.get("browouterupright", 0.0)
    return (interieur + gauche + droite) / 3.0


def caracteristiques_sourcils(points, blendshapes):
    """Indices complementaires : modele et distance sourcils-paupieres."""
    modele = score_sourcils(blendshapes)
    if points is None:
        return np.asarray((modele, 0.0), dtype=float)
    points = np.asarray(points, dtype=float)
    largeur_visage = max(1e-6, _distance(points[234], points[454]))
    sourcil_droit_y = float(np.mean(points[list(SOURCIL_DROIT_HAUT), 1]))
    sourcil_gauche_y = float(np.mean(points[list(SOURCIL_GAUCHE_HAUT), 1]))
    paupiere_droite_y = float(np.mean(points[list(OEIL_DROIT["haut"]), 1]))
    paupiere_gauche_y = float(np.mean(points[list(OEIL_GAUCHE["haut"]), 1]))
    ecart = ((paupiere_droite_y - sourcil_droit_y)
             + (paupiere_gauche_y - sourcil_gauche_y)) / (2.0 * largeur_visage)
    return np.asarray((modele, ecart), dtype=float)


def construire_profil_sourcils(neutre, sourcils_leves):
    """Conserve seulement les indices ayant vraiment change chez la personne."""
    neutre = np.asarray(neutre, dtype=float)
    sourcils_leves = np.asarray(sourcils_leves, dtype=float)
    delta = sourcils_leves - neutre
    minimums = np.asarray((0.015, 0.003), dtype=float)
    fiables = delta >= minimums
    if not np.any(fiables):
        # Dernier recours : utilise l'indice le plus distinctif, mais garde un
        # delta atteignable puisque mesure sur le vrai geste de calibration.
        meilleur = int(np.argmax(delta / minimums))
        fiables[meilleur] = True
    delta = np.where(fiables, np.maximum(delta, minimums * 0.55), delta)
    return {
        "neutre": neutre,
        "delta": delta,
        "fiables": fiables,
        "garde": 0.20,
        "seuil": 0.46,
        "retour": 0.13,
    }


def niveau_sourcils(caracteristiques, profil):
    caracteristiques = np.asarray(caracteristiques, dtype=float)
    fiables = np.asarray(profil["fiables"], dtype=bool)
    progression = ((caracteristiques - profil["neutre"])
                   / np.maximum(1e-6, profil["delta"]))
    return float(np.clip(np.median(progression[fiables]), -0.5, 2.5))


def _dessiner_texte(cv2, image, lignes, couleur=(0, 255, 255)):
    for i, ligne in enumerate(lignes):
        cv2.putText(image, ligne, (18, 30 + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, couleur, 2, cv2.LINE_AA)


def _detecter(landmarker, mp, cv2, frame, timestamp_ms):
    miroir = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(miroir, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    resultat = landmarker.detect_for_video(image, timestamp_ms)
    return miroir, _landmarks_np(resultat), _blendshapes_dict(resultat)


def filtrer_mesures(mesures):
    """Retire les frames perturbees par un clignement ou un mouvement brusque."""
    valeurs = np.asarray(mesures, dtype=float)
    if len(valeurs) < 5:
        return valeurs
    mediane = np.median(valeurs, axis=0)
    mad = np.median(np.abs(valeurs - mediane), axis=0)
    echelle = np.maximum(1e-6, 1.4826 * mad)
    scores = np.median(np.abs(valeurs - mediane) / echelle, axis=1)
    conservees = valeurs[scores <= 3.5]
    return conservees if len(conservees) >= 5 else valeurs


def _calibrer(cv2, cap, landmarker, mp, souris):
    largeur, hauteur = souris.largeur, souris.hauteur
    nom = "Jarvis - calibration du regard"
    cv2.namedWindow(nom, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(nom, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    ecran = np.zeros((hauteur, largeur, 3), dtype=np.uint8)
    _dessiner_texte(cv2, ecran, [
        "CALIBRATION PRECISE DU REGARD",
        "Reste dans ta posture naturelle et fixe chaque point bleu.",
        "Ne te crispe pas : les petits mouvements normaux sont appris.",
        "Evite de cligner pendant la barre verte ; tu peux cligner entre deux points.",
        "Appuie sur ESPACE pour commencer - Echap pour quitter.",
    ])
    cv2.imshow(nom, ecran)
    while True:
        touche = cv2.waitKey(30) & 0xFF
        if touche == 32:
            break
        if touche in (27, ord("q")):
            raise KeyboardInterrupt

    # Deux passages courts sur les neuf zones importantes sont plus robustes
    # qu'une longue grille unique : ils mesurent la derive et reduisent la fatigue.
    grille = [
        (0.08, 0.08), (0.50, 0.08), (0.92, 0.08),
        (0.92, 0.50), (0.50, 0.50), (0.08, 0.50),
        (0.08, 0.92), (0.50, 0.92), (0.92, 0.92),
    ]
    cibles = [(0.50, 0.50), *grille, *reversed(grille), (0.50, 0.50)]
    observations, sorties = [], []
    ancres_observations, ancres_cibles = [], []
    dernier_ts = 0

    for numero, cible in enumerate(cibles, 1):
        valide_depuis = None
        mesures = []
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            maintenant = time.monotonic()
            ts = max(dernier_ts + 1, int(maintenant * 1000))
            dernier_ts = ts
            _, points, _ = _detecter(landmarker, mp, cv2, frame, ts)
            if points is None:
                valide_depuis = None
                statut = "Visage non detecte"
                progression = 0.0
            else:
                if valide_depuis is None:
                    valide_depuis = maintenant
                ecoule = maintenant - valide_depuis
                progression = min(1.0, ecoule / 1.05)
                statut = "Fixe le point" if ecoule < 0.42 else "Mesure..."
                if ecoule >= 0.42:
                    mesures.append(caracteristiques_regard(points))
                if ecoule >= 1.05 and len(mesures) >= 10:
                    break

            ecran[:] = 0
            x, y = int(cible[0] * largeur), int(cible[1] * hauteur)
            cv2.circle(ecran, (x, y), 24, (255, 210, 0), 3)
            cv2.circle(ecran, (x, y), 7, (255, 210, 0), -1)
            cv2.rectangle(ecran, (x - 45, y + 42),
                          (x - 45 + int(90 * progression), y + 50),
                          (0, 220, 120), -1)
            _dessiner_texte(cv2, ecran,
                            [f"Point {numero}/{len(cibles)} - {statut}",
                             "Garde ta posture naturelle et fixe le point",
                             "Echap : quitter"])
            cv2.imshow(nom, ecran)
            touche = cv2.waitKey(1) & 0xFF
            if touche in (27, ord("q")):
                raise KeyboardInterrupt

        mesures_nettoyees = filtrer_mesures(mesures)
        ancre = np.median(mesures_nettoyees, axis=0)
        ancres_observations.append(ancre)
        ancres_cibles.append(cible)
        observations.extend(mesures_nettoyees)
        sorties.extend([cible] * len(mesures_nettoyees))

    def capturer_expression(titre, instruction):
        """Capture les sourcils apres validation par Espace."""
        nonlocal dernier_ts
        debut = None
        valeurs = []
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            maintenant = time.monotonic()
            ts = max(dernier_ts + 1, int(maintenant * 1000))
            dernier_ts = ts
            _, points, blendshapes = _detecter(
                landmarker, mp, cv2, frame, ts)
            ecran[:] = 0
            cv2.circle(ecran, (largeur // 2, hauteur // 2),
                       12, (255, 210, 0), -1)
            if debut is None:
                lignes = [titre, instruction,
                          "Quand tu es prete, appuie sur ESPACE et tiens la pose.",
                          "Echap : quitter"]
                progression = 0.0
            else:
                ecoule = maintenant - debut
                progression = min(1.0, ecoule / 0.95)
                lignes = [titre, "Tiens encore...", "Echap : quitter"]
                if points is not None and ecoule >= 0.12:
                    valeurs.append(
                        caracteristiques_sourcils(points, blendshapes))
                if ecoule >= 0.95 and len(valeurs) >= 6:
                    return np.median(np.asarray(valeurs), axis=0)
            cv2.rectangle(ecran, (largeur // 2 - 70, hauteur // 2 + 45),
                          (largeur // 2 - 70 + int(140 * progression),
                           hauteur // 2 + 54), (0, 220, 120), -1)
            _dessiner_texte(cv2, ecran, lignes)
            cv2.imshow(nom, ecran)
            touche = cv2.waitKey(1) & 0xFF
            if touche in (27, ord("q")):
                raise KeyboardInterrupt
            if touche == 32 and points is not None:
                debut = maintenant
                valeurs.clear()

    neutre = capturer_expression(
        "APPRENTISSAGE DES SOURCILS - 1/2",
        "Regarde le centre avec les sourcils relaches.")

    sourcils_leves = None
    for tentative in range(3):
        sourcils_leves = capturer_expression(
            "APPRENTISSAGE DES SOURCILS - 2/2",
            "Leve clairement les DEUX sourcils." if tentative == 0 else
            "Geste peu visible : leve davantage les deux sourcils.")
        ecarts = np.asarray(sourcils_leves) - np.asarray(neutre)
        if np.any(ecarts >= np.asarray((0.015, 0.003))):
            break

    profil_sourcils = construire_profil_sourcils(neutre, sourcils_leves)
    calibration = CalibrationRegard.ajuster(
        observations, sorties, ancres_observations, ancres_cibles)

    ecran[:] = 0
    _dessiner_texte(cv2, ecran, [
        "CALIBRATION TERMINEE",
        "Tes sourcils ont maintenant leur propre seuil.",
        "Dans le test, la touche C active ou coupe les clics.",
    ], couleur=(0, 255, 80))
    cv2.imshow(nom, ecran)
    cv2.waitKey(900)
    cv2.destroyWindow(nom)
    return calibration, profil_sourcils


def executer(device=0, modele=None, clics_actifs=False):
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    modele = Path(modele or Path(__file__).parent / "models" / "face_landmarker.task")
    if not modele.exists():
        raise FileNotFoundError(
            f"Modele absent: {modele}. Lance d'abord scripts/setup_regard.py")

    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(modele)),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
        min_face_detection_confidence=0.55,
        min_face_presence_confidence=0.55,
        min_tracking_confidence=0.55,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(options)
    cap = cv2.VideoCapture(int(device), cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)
    if not cap.isOpened():
        landmarker.close()
        raise RuntimeError("Webcam indisponible (ferme d'abord la calibration des gestes)")

    souris = SourisLocale()
    try:
        calibration, profil_sourcils = _calibrer(
            cv2, cap, landmarker, mp, souris)
        nom = "Jarvis - test regard (local)"
        cv2.namedWindow(nom, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(nom, 720, 480)
        cv2.setWindowProperty(nom, cv2.WND_PROP_TOPMOST, 1)

        mouvement_actif = True
        clic_actif = bool(clics_actifs)
        lisse = None
        predictions_brutes = deque(maxlen=3)
        diagonale = math.hypot(souris.largeur, souris.hauteur)
        correction_centre = np.zeros(2, dtype=float)
        derniere_prediction = None
        detecteur_sourcils = DetecteurSourcils()
        dernier_ts = 0
        reprise_pointeur_apres = 0.0
        message = ("Calibration OK - clic ACTIF" if clic_actif
                   else "Calibration OK - clic DESACTIVE")
        message_jusqu = time.monotonic() + 4.0

        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            maintenant = time.monotonic()
            ts = max(dernier_ts + 1, int(maintenant * 1000))
            dernier_ts = ts
            miroir, points, blendshapes = _detecter(
                landmarker, mp, cv2, frame, ts)
            indices_sourcils = caracteristiques_sourcils(points, blendshapes)
            sourcils = niveau_sourcils(indices_sourcils, profil_sourcils)
            clignement = score_clignement(blendshapes)
            verrouiller_pointeur = (
                sourcils >= profil_sourcils["garde"] or clignement >= 0.75)

            if points is not None:
                if verrouiller_pointeur:
                    # Lever les sourcils peut deplacer legerement les paupieres.
                    # On garde la derniere position jusqu'au retour au neutre.
                    reprise_pointeur_apres = maintenant + 0.18
                    predictions_brutes.clear()

                action = detecteur_sourcils.alimenter(
                    sourcils, profil_sourcils, maintenant)
                if action:
                    if clic_actif:
                        souris.cliquer(action)
                        message = "CLIC GAUCHE"
                    else:
                        message = "SOURCILS DETECTES - appuie sur C pour cliquer"
                    message_jusqu = maintenant + 1.2

                if not verrouiller_pointeur and maintenant >= reprise_pointeur_apres:
                    observation = caracteristiques_regard(points)
                    derniere_prediction = np.clip(
                        calibration.predire(observation) + correction_centre,
                        0.0, 1.0)
                    nx, ny = derniere_prediction
                    brut = np.asarray([nx * (souris.largeur - 1),
                                       ny * (souris.hauteur - 1)])
                    predictions_brutes.append(brut)
                    brut_robuste = np.median(
                        np.asarray(predictions_brutes), axis=0)
                    lisse = lisser_pointeur(lisse, brut_robuste, diagonale)
                    if mouvement_actif:
                        souris.deplacer(*lisse)

                h, w = miroir.shape[:2]
                for spec, couleur in ((OEIL_DROIT, (0, 255, 0)),
                                      (OEIL_GAUCHE, (255, 180, 0))):
                    for indice in spec["coins"] + spec["haut"] + spec["bas"] + spec["iris"]:
                        p = points[indice]
                        cv2.circle(miroir, (int(p[0] * w), int(p[1] * h)),
                                   2, couleur, -1)
                for indices in (SOURCIL_DROIT, SOURCIL_GAUCHE):
                    for indice in indices:
                        p = points[indice]
                        cv2.circle(miroir, (int(p[0] * w), int(p[1] * h)),
                                   3, (255, 0, 255), -1)
                # La bouche est suivie par le modele mais ne commande aucun clic.
                # Ces petits points rendent simplement ce suivi visible.
                for indice in BOUCHE_CONTOUR:
                    p = points[indice]
                    cv2.circle(miroir, (int(p[0] * w), int(p[1] * h)),
                               1, (120, 120, 120), -1)

            lignes = [
                f"SOURIS: {'ON' if mouvement_actif else 'OFF'}   "
                f"CLICS: {'ON' if clic_actif else 'OFF'}",
                f"SOURCILS: {sourcils:.3f} / seuil {profil_sourcils['seuil']:.3f}",
                "[M] souris  [C] clics  [F] recentrer  [R] recalibrer",
                "Deux sourcils leves et tenus = clic gauche",
            ]
            if maintenant < message_jusqu:
                lignes.insert(0, message)
            _dessiner_texte(cv2, miroir, lignes,
                            (0, 255, 80) if clic_actif else (0, 255, 255))
            cv2.imshow(nom, miroir)
            touche = cv2.waitKey(1) & 0xFF
            if touche in (27, ord("q")):
                break
            if touche == ord("m"):
                mouvement_actif = not mouvement_actif
            elif touche == ord("c"):
                clic_actif = not clic_actif
                message = "CLICS ACTIVES" if clic_actif else "CLICS DESACTIVES"
                message_jusqu = maintenant + 2.0
            elif touche == ord("f") and derniere_prediction is not None:
                correction_centre += np.asarray((0.5, 0.5)) - derniere_prediction
                predictions_brutes.clear()
                lisse = None
                message = "CENTRE RECALÉ"
                message_jusqu = maintenant + 2.0
            elif touche == ord("r"):
                cv2.destroyWindow(nom)
                calibration, profil_sourcils = _calibrer(
                    cv2, cap, landmarker, mp, souris)
                cv2.namedWindow(nom, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(nom, 720, 480)
                cv2.setWindowProperty(nom, cv2.WND_PROP_TOPMOST, 1)
                lisse = None
                predictions_brutes.clear()
                correction_centre[:] = 0.0
                derniere_prediction = None
                reprise_pointeur_apres = 0.0
                detecteur_sourcils = DetecteurSourcils()
                clic_actif = bool(clics_actifs)
                message = ("Recalibration OK - clic ACTIF" if clic_actif
                           else "Recalibration OK - clic DESACTIVE")
                message_jusqu = time.monotonic() + 3.0
    finally:
        cap.release()
        cv2.destroyAllWindows()
        landmarker.close()


def main():
    parser = argparse.ArgumentParser(description="Test local du pointeur par le regard")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--model")
    parser.add_argument(
        "--clics-actifs", action="store_true",
        help="active le clic par sourcils dès la fin de la calibration")
    args = parser.parse_args()
    try:
        executer(args.device, args.model, args.clics_actifs)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
