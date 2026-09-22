"""Tracker de gestes de la main — SOUS-PROCESS ISOLE (Python 3.11 + MediaPipe).

Frontiere vie privee : ce process est le SEUL a voir l'image de la webcam. Aucune
image n'est stockee, loggee ni transmise — seuls des *labels de gestes* ("poing",
"mode_fenetres"...) partent vers Jarvis en loopback local (POST /api/gestes, avec
un token). MediaPipe (nouvelle API Tasks) tourne en CPU (XNNPACK).

Lance par core/gestes.py (Jarvis 3.13). Config passee via l'env GESTES_CONF (JSON).
Mode calibration : `--calibrate` (affiche la camera + landmarks + seuils reglables).

Vocabulaire v2 (gestes FIABLES, tenus) :
  main ouverte immobile -> pause ; pouce leve -> lecture ; poing -> couper Jarvis
  2 doigts -> mode fenetres, puis main ouverte + swipe horizontal/vertical
  3 doigts -> mode audio, puis main ouverte + swipe horizontal/vertical
  index seul tenu -> mode souris, puis ce meme index pilote le pointeur
  2 mains ouvertes -> ecarter pour zoomer, rapprocher pour dezoomer
Chaque mode attend une paume ouverte brièvement stable après la pose de sélection
et exige une sortie du cadre entre deux actions.
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
POUCE_MCP, POUCE_IP, POUCE_TIP = 2, 3, 4
INDEX_TIP, MAJEUR_TIP, ANN_TIP, AURIC_TIP = 8, 12, 16, 20
INDEX_PIP, MAJEUR_PIP, ANN_PIP, AURIC_PIP = 6, 10, 14, 18
INDEX_MCP, MAJEUR_MCP, AURIC_MCP = 5, 9, 17


# ============================================================ classifieurs PURS
# (fonctions sans effet de bord, testables avec des landmarks synthetiques)

def _d(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def doigt_leve(lm, tip, pip):
    """Détecte un doigt tendu quelle que soit l'orientation de la main.

    Comparer les coordonnées Y ne fonctionne que doigts vers le haut : pendant
    un swipe horizontal, une vraie paume ouverte devenait donc un « poing ».
    Un doigt tendu a son extrémité sensiblement plus loin du poignet que sa PIP.
    La marge est proportionnelle à la taille apparente de la main.
    """
    echelle = max(0.05, _d(lm[POIGNET], lm[MAJEUR_MCP]))
    return _d(lm[tip], lm[POIGNET]) > _d(lm[pip], lm[POIGNET]) + 0.22 * echelle


def ratio_ouverture_pouce(lm):
    """Écart pouce/index rapporté à la taille apparente de la paume."""
    echelle = max(0.04, _d(lm[POIGNET], lm[MAJEUR_MCP]))
    return _d(lm[POUCE_TIP], lm[INDEX_MCP]) / echelle


def extension_pouce(lm):
    """Allongement du pouce au-delà de son articulation, normalisé par la paume."""
    echelle = max(0.04, _d(lm[POIGNET], lm[MAJEUR_MCP]))
    return (_d(lm[POUCE_TIP], lm[POIGNET])
            - _d(lm[POUCE_IP], lm[POIGNET])) / echelle


def pouce_ouvert(lm):
    """Pouce réellement tendu, même vu de biais par la webcam."""
    return extension_pouce(lm) > 0.12 and ratio_ouverture_pouce(lm) > 0.25


def doigts_tendus(lm):
    """Nombre de doigts tendus (index..auriculaire), hors pouce."""
    paires = ((INDEX_TIP, INDEX_PIP), (MAJEUR_TIP, MAJEUR_PIP),
              (ANN_TIP, ANN_PIP), (AURIC_TIP, AURIC_PIP))
    return sum(1 for tip, pip in paires if doigt_leve(lm, tip, pip))


def doigts_detectes(lm):
    """Nombre total de doigts ouverts, pouce compris, pour la calibration."""
    return doigts_tendus(lm) + int(pouce_ouvert(lm))


def _doigts(lm):
    """État index, majeur, annulaire, auriculaire (True = tendu)."""
    return tuple(doigt_leve(lm, tip, pip) for tip, pip in (
        (INDEX_TIP, INDEX_PIP), (MAJEUR_TIP, MAJEUR_PIP),
        (ANN_TIP, ANN_PIP), (AURIC_TIP, AURIC_PIP)))


def est_main_ouverte(lm):
    """Paume complète : les quatre doigts longs et le pouce sont déployés."""
    return doigts_tendus(lm) == 4 and pouce_ouvert(lm)


def est_quatre_doigts(lm):
    """Les quatre doigts levés avec le pouce replié : sélection Souris."""
    # L'extension distingue un pouce ouvert vu de biais d'un pouce réellement
    # replié. L'écart maximal reste généreux pour reconnaître le chiffre 4.
    pouce_replie = (not pouce_ouvert(lm)
                     and ratio_ouverture_pouce(lm) <= 0.75)
    return _doigts(lm) == (True, True, True, True) and pouce_replie


def est_index_seul(lm):
    """Index tendu, majeur/annulaire/auriculaire repliés : pilotage du pointeur."""
    return _doigts(lm) == (True, False, False, False)


def est_index_pointeur(lm):
    """Index visible en mode souris, avec tolérance sur le majeur mal suivi."""
    index, _majeur, annulaire, auriculaire = _doigts(lm)
    return index and not annulaire and not auriculaire


def ratio_pincement(lm):
    """Distance pouce-index rapportée à la taille apparente de la paume."""
    echelle = max(0.04, _d(lm[POIGNET], lm[MAJEUR_MCP]))
    return _d(lm[POUCE_TIP], lm[INDEX_TIP]) / echelle


def est_main_deployee(lm):
    """Paume assez ouverte pour piloter un mode déjà explicitement armé.

    Trois doigts longs suffisent après l'armement explicite d'un mode, ou lorsque
    deux mains sont visibles. Dans ces contextes, cette tolérance ne peut pas
    armer la souris et absorbe les pertes momentanées pendant un mouvement.
    """
    return doigts_tendus(lm) >= 3


def est_deux_doigts(lm):
    """Index + majeur, les deux autres repliés : sélection Fenêtres."""
    return _doigts(lm) == (True, True, False, False)


def est_trois_doigts(lm):
    """Index + majeur + annulaire, auriculaire replié : sélection Audio."""
    return _doigts(lm) == (True, True, True, False)


def est_pouce_leve(lm):
    """Pouce franchement vertical, les quatre autres doigts repliés."""
    return (doigts_tendus(lm) == 0
            and lm[POUCE_TIP][1] < lm[POUCE_IP][1] - 0.035
            and _d(lm[POUCE_TIP], lm[INDEX_MCP]) > 0.10)


def est_poing(lm):
    return doigts_tendus(lm) == 0 and not est_pouce_leve(lm)


def centre_main(lm):
    """Centre stable de la paume pour mesurer un swipe sans dépendre d'un doigt."""
    points = (POIGNET, INDEX_MCP, MAJEUR_MCP, AURIC_MCP)
    return (sum(lm[i][0] for i in points) / len(points),
            sum(lm[i][1] for i in points) / len(points))


def pose(lm):
    """Nom de la pose statique courante, ou None."""
    if est_main_ouverte(lm):
        return "main_ouverte"
    if est_trois_doigts(lm):
        return "mode_audio"
    if est_deux_doigts(lm):
        return "mode_fenetres"
    if est_index_seul(lm):
        return "mode_souris"
    if est_pouce_leve(lm):
        return "pouce_leve"
    if est_poing(lm):
        return "poing"
    return None


# ==================================================================== FSM

class MachineGestes:
    """Machine à états anti-faux-positifs avec modes explicites temporaires."""

    def __init__(self, conf):
        s = conf.get("seuils", {})
        self.tenue_s = float(s.get("tenue_s", 1.4))
        self.tenue_mode_s = float(s.get("tenue_mode_s", 0.9))
        self.cooldown_s = float(s.get("cooldown_s", 0.8))
        self.swipe_seuil = float(s.get("swipe_seuil", 0.20))
        self.swipe_vertical_seuil = float(s.get("swipe_vertical_seuil", 0.18))
        self.swipe_fenetre_s = float(s.get("swipe_fenetre_s", 1.0))
        self.swipe_dominance = float(s.get("swipe_dominance", 1.20))
        self.swipe_pret_s = float(s.get("swipe_pret_s", 0.35))
        self.swipe_cooldown_s = float(s.get("swipe_cooldown_s", 0.18))
        self.swipe_pause_s = float(s.get("swipe_pause_s", 0.28))
        self.swipe_tourne_seuil = float(s.get("swipe_tourne_seuil", 0.05))
        self.stabilite_seuil = float(s.get("stabilite_seuil", 0.06))
        self.inverser_vertical = bool(s.get("inverser_vertical", False))
        self.mode_duree_s = float(s.get("mode_duree_s", 30.0))
        self.sortie_absence_s = float(s.get("sortie_absence_s", 3.0))
        self.zoom_seuil = float(s.get("zoom_seuil", 0.12))
        self.zoom_reduire_seuil = float(s.get("zoom_reduire_seuil", 0.08))
        self.zoom_tenue_s = float(s.get("zoom_tenue_s", 0.45))
        self.zoom_stabilite_seuil = float(s.get("zoom_stabilite_seuil", 0.035))
        self.souris_marge = float(s.get("souris_marge", 0.10))
        self.souris_lissage = float(s.get("souris_lissage", 0.32))
        self.souris_pincement_seuil = float(s.get("souris_pincement_seuil", 0.55))
        self.souris_tenue_s = float(s.get("souris_tenue_s", 0.45))
        self.souris_clic = bool(s.get("souris_clic", False))

        self._geste_courant = None      # geste tenu en cours d'observation
        self._depuis = 0.0              # depuis quand il est tenu
        self._dernier_envoi = -1e9      # cooldown global (1er geste jamais bloque)
        self.mode = None                # None | fenetres | audio | souris
        self._mode_jusqu = 0.0
        self._attend_relachement = False
        self._absence_depuis = None     # fermeture après une vraie sortie du cadre
        self._hist_xy = []              # (t, x, y) après sélection d'un mode
        self._pret_depuis = 0.0         # début de l'immobilité avant un swipe
        self._pret_position = None      # position de référence pendant l'immobilité
        self._pret_confirme = False     # le trajet de retour n'est jamais un swipe
        self._swipe_verrou_axe = None   # fin du dernier geste : "h" | "v"
        self._swipe_pause_position = None
        self._swipe_pause_depuis = 0.0
        self._zoom_reference = None     # distance des paumes après stabilisation
        self._zoom_depuis = 0.0         # début de la stabilisation à deux mains
        self._zoom_pret = False
        self.zoom_distance = None       # diagnostic local pour la calibration
        self.evenement_pointeur = None  # {x, y, clic}, consommé par la boucle I/O
        self._pointeur_lisse = None
        self._pincement_actif = False
        self._pincement_arme = False
        self._dernier_clic = -1e9
        self.souris_ratio_pincement = None
        self._selection_souris_position = None
        self._selection_souris_depuis = 0.0
        self.debug_evenement = ""       # diagnostic local affiché en calibration

    def _cooldown_ok(self, t):
        return (t - self._dernier_envoi) >= self.cooldown_s

    def _reinitialiser_tenue(self):
        self._geste_courant = None
        self._depuis = 0.0

    def _reinitialiser_pret(self):
        self._hist_xy.clear()
        self._pret_depuis = 0.0
        self._pret_position = None
        self._pret_confirme = False
        self._swipe_verrou_axe = None
        self._swipe_pause_position = None
        self._swipe_pause_depuis = 0.0

    def _suivre_fin_swipe(self, t, x, y):
        """Évite les doublons puis réarme sur pause ou changement d'axe.

        Un swipe est souvent reconnu avant que la main ait fini sa course. La
        fin du mouvement ne doit pas compter comme un second geste, mais un
        virage horizontal/vertical volontaire doit pouvoir partir tout de suite.
        """
        if self._swipe_verrou_axe is None:
            return True

        self._hist_xy.append((t, x, y))
        fenetre = min(self.swipe_fenetre_s,
                      max(0.22, self.swipe_pause_s * 2.0))
        self._hist_xy = [p for p in self._hist_xy if t - p[0] <= fenetre]
        debut = self._hist_xy[0]
        dx = x - debut[1]
        dy = y - debut[2]
        seuil = max(0.025, self.swipe_tourne_seuil)

        tourne = ((self._swipe_verrou_axe == "h"
                   and abs(dy) >= seuil
                   and abs(dy) >= abs(dx) * 1.15)
                  or (self._swipe_verrou_axe == "v"
                      and abs(dx) >= seuil
                      and abs(dx) >= abs(dy) * 1.15))
        if tourne:
            # Élimine de l'historique la queue du geste précédent, mais garde
            # le début utile du nouveau trajet perpendiculaire.
            coord = 1 if self._swipe_verrou_axe == "h" else 2
            tolerance = max(0.018, seuil * 0.55)
            indice = 0
            for i in range(len(self._hist_xy) - 2, -1, -1):
                if abs(self._hist_xy[i][coord] - self._hist_xy[-1][coord]) > tolerance:
                    indice = min(i + 1, len(self._hist_xy) - 1)
                    break
            self._hist_xy = self._hist_xy[indice:]
            self._swipe_verrou_axe = None
            self._swipe_pause_position = (x, y)
            self._swipe_pause_depuis = t
            return True

        position = self._swipe_pause_position
        if position is None:
            self._swipe_pause_position = (x, y)
            self._swipe_pause_depuis = t
            return False
        mouvement = ((x - position[0]) ** 2 + (y - position[1]) ** 2) ** 0.5
        if mouvement > max(0.018, self.stabilite_seuil * 0.40):
            self._swipe_pause_position = (x, y)
            self._swipe_pause_depuis = t
            return False
        if (t - self._swipe_pause_depuis) >= self.swipe_pause_s:
            self._swipe_verrou_axe = None
            self._hist_xy = [(t, x, y)]
            self._swipe_pause_position = (x, y)
            self._swipe_pause_depuis = t
        return False

    def _fermer_mode(self):
        self.mode = None
        self._mode_jusqu = 0.0
        self._attend_relachement = False
        self._absence_depuis = None
        self._reinitialiser_pret()
        self._reinitialiser_pointeur()

    def _reinitialiser_pointeur(self):
        self.evenement_pointeur = None
        self._pointeur_lisse = None
        self._pincement_actif = False
        self._pincement_arme = False
        self.souris_ratio_pincement = None

    def _reinitialiser_selection_souris(self):
        self._selection_souris_position = None
        self._selection_souris_depuis = 0.0

    def _tenir_selection_souris(self, lm, t, duree=None):
        """Arme la souris seulement si l'index reste presque immobile."""
        position = centre_main(lm)
        if self._selection_souris_position is None:
            self._selection_souris_position = position
            self._selection_souris_depuis = t
            return False
        dx = position[0] - self._selection_souris_position[0]
        dy = position[1] - self._selection_souris_position[1]
        if (dx * dx + dy * dy) ** 0.5 > max(0.12, self.stabilite_seuil):
            self._selection_souris_position = position
            self._selection_souris_depuis = t
            return False
        attente = self.souris_tenue_s if duree is None else duree
        if (t - self._selection_souris_depuis) < attente:
            return False
        self._reinitialiser_selection_souris()
        return True

    def _reinitialiser_zoom(self):
        self._zoom_reference = None
        self._zoom_depuis = 0.0
        self._zoom_pret = False
        self.zoom_distance = None

    @property
    def etat_swipe(self):
        """État lisible par l'écran de calibration, sans exposer de landmarks."""
        if not self.mode:
            return "-"
        if self._attend_relachement:
            return "ouvre la main"
        if not self._pret_confirme:
            return "stabilise la main ouverte"
        if self._swipe_verrou_axe is not None:
            return "change d'axe ou marque une pause"
        return "PRET - swipe maintenant"

    @property
    def etat_zoom(self):
        """État lisible du geste à deux mains pour l'écran de calibration."""
        if self.zoom_distance is None:
            return "montre 2 mains ouvertes"
        if not self._zoom_pret:
            return "stabilise les 2 mains"
        return "PRET - ecarte ou rapproche"

    @property
    def etat_souris(self):
        if self.mode != "souris":
            if self._selection_souris_position is not None:
                return "ARMEMENT INDEX - ne bouge plus"
            return "-"
        if self._attend_relachement:
            return "garde seulement l'index"
        if self.evenement_pointeur is None:
            return "pointe avec l'index"
        return "POINTEUR ACTIF"

    def _alimenter_souris(self, lm, t):
        """Produit un événement pointeur normalisé, jamais une image/landmark brut."""
        self.evenement_pointeur = None
        if self._attend_relachement:
            if est_quatre_doigts(lm):
                return None
            self._attend_relachement = False

        ratio = ratio_pincement(lm)
        self.souris_ratio_pincement = ratio
        seuil = max(0.15, min(1.5, self.souris_pincement_seuil))
        relache = seuil * 1.35
        index_visible = est_index_pointeur(lm)
        pincement_visible = self._pincement_arme and ratio <= relache

        # Pendant un vrai pincement, l'index se replie souvent et cesse d'être
        # classé comme « index seul ». On conserve alors la dernière position
        # du pointeur pour que le pincement puisse quand même produire un clic.
        if not index_visible and not pincement_visible:
            return None

        if index_visible:
            marge = max(0.0, min(0.35, self.souris_marge))
            amplitude = max(0.1, 1.0 - 2.0 * marge)
            x = max(0.0, min(1.0, (lm[INDEX_TIP][0] - marge) / amplitude))
            y = max(0.0, min(1.0, (lm[INDEX_TIP][1] - marge) / amplitude))
            alpha = max(0.05, min(1.0, self.souris_lissage))
            if self._pointeur_lisse is None:
                self._pointeur_lisse = (x, y)
            else:
                px, py = self._pointeur_lisse
                self._pointeur_lisse = (px + (x - px) * alpha,
                                        py + (y - py) * alpha)

        if self._pointeur_lisse is None:
            return None

        clic = False
        if ratio >= relache:
            self._pincement_actif = False
            self._pincement_arme = True
        elif ratio <= seuil and not self._pincement_actif:
            if self._pincement_arme and (t - self._dernier_clic) >= self.cooldown_s:
                clic = self.souris_clic
                self._dernier_clic = t
                if clic:
                    self.debug_evenement = "souris_clic"
            self._pincement_actif = True

        self.evenement_pointeur = {
            "x": round(self._pointeur_lisse[0], 5),
            "y": round(self._pointeur_lisse[1], 5),
            "clic": bool(clic),
        }
        self._mode_jusqu = t + self.mode_duree_s
        return None

    def _tenir(self, instant, t, duree=None, marquer_cooldown=True):
        """True une seule fois quand une pose est restée stable assez longtemps."""
        if instant != self._geste_courant:
            self._geste_courant = instant
            self._depuis = t
            return False
        attente = self.tenue_s if duree is None else duree
        if instant is not None and (t - self._depuis) >= attente and self._cooldown_ok(t):
            # Verrouille cette pose jusqu'à un vrai changement/relâchement.
            self._geste_courant = instant
            self._depuis = float("inf")
            if marquer_cooldown:
                self._dernier_envoi = t
            return True
        return False

    def alimenter(self, lm, t):
        """lm = 21 (x,y) normalises, ou None si aucune main. Renvoie un label ou None."""
        self.evenement_pointeur = None
        if lm is None:
            self._reinitialiser_tenue()
            if self.mode:
                # Une ou plusieurs images perdues pendant un mouvement ne
                # doivent ni désarmer le mode ni oublier que le geste précédent
                # est encore verrouillé. On oublie seulement les coordonnées
                # devenues discontinues, puis la première image revenue sert de
                # nouvelle origine sûre.
                self._hist_xy.clear()
                self._pret_position = None
                self._pret_depuis = t
                if self._absence_depuis is None:
                    self._absence_depuis = t
                elif (t - self._absence_depuis) >= self.sortie_absence_s:
                    ancien_mode = self.mode
                    self._fermer_mode()
                    self.debug_evenement = f"mode_{ancien_mode}_sortie"
            else:
                self._reinitialiser_pret()
                if self._attend_relachement:
                    self._attend_relachement = False
            self._reinitialiser_pointeur()
            self._reinitialiser_selection_souris()
            return None

        self._absence_depuis = None
        if self.mode:
            # Tant que la main reste visible, le mode ne peut pas expirer.
            self._mode_jusqu = t + self.mode_duree_s

        instant = pose(lm)
        if instant != "mode_souris":
            self._reinitialiser_selection_souris()

        # Le poing reste un arrêt d'urgence, même lorsqu'un mode est armé.
        if instant == "poing" and self._tenir("poing", t):
            self._fermer_mode()
            return "poing"

        if self.mode:
            if self.mode == "souris":
                return self._alimenter_souris(lm, t)
            # Un index volontaire et immobile permet de passer directement
            # d'Onglets/Audio à Souris. S'il apparaît brièvement pendant un
            # swipe, le mode courant continue sans interruption.
            if (instant == "mode_souris"
                    and self._tenir_selection_souris(lm, t)):
                self._fermer_mode()
                self.mode = "souris"
                self._mode_jusqu = t + self.mode_duree_s
                self._attend_relachement = False
                return "mode_souris"
            # Après 2/3 doigts, une paume ouverte remplace naturellement la pose
            # de sélection. Sortir la main du cadre fonctionne aussi, sans être
            # obligatoire. La stabilisation ci-dessous absorbe la transition.
            if self._attend_relachement:
                if not est_main_deployee(lm):
                    return None
                self._attend_relachement = False
                self._reinitialiser_pret()

            # Une action de mode exige une main entière ouverte en mouvement.
            if not est_main_deployee(lm):
                # Une paume ouverte peut être lue comme partielle pendant un
                # changement de direction. Le mode reste prêt ; seule l'origine
                # du prochain swipe doit être recalée.
                self._hist_xy.clear()
                self._pret_position = None
                self._pret_depuis = t
                self._pret_confirme = True
                # Si un swipe vient d'être reconnu, conserver son verrou même
                # quand MediaPipe perd brièvement des doigts. Sinon le retour
                # naturel vers le centre serait pris pour le geste opposé.
                self._reinitialiser_tenue()
                return None
            x, y = centre_main(lm)

            # Le changement de pose ou le retour dans le champ crée un grand
            # déplacement artificiel. On attend donc une brève immobilité, puis
            # seulement on ouvre une fenêtre de mesure pour le vrai swipe.
            if not self._pret_confirme:
                if self._pret_position is None:
                    self._pret_position = (x, y)
                    self._pret_depuis = t
                    return None
                dx_pret = x - self._pret_position[0]
                dy_pret = y - self._pret_position[1]
                if (dx_pret * dx_pret + dy_pret * dy_pret) ** 0.5 > self.stabilite_seuil:
                    self._pret_position = (x, y)
                    self._pret_depuis = t
                    return None
                # Mesure image par image : une dérive lente et naturelle de la
                # main ne remet pas sans cesse le chronomètre à zéro.
                self._pret_position = (x, y)
                if (t - self._pret_depuis) < self.swipe_pret_s:
                    return None
                self._pret_confirme = True
                self._hist_xy = [(t, x, y)]
                return None

            if self._swipe_verrou_axe is not None:
                if not self._suivre_fin_swipe(t, x, y):
                    return None
            else:
                self._hist_xy.append((t, x, y))
            self._hist_xy = [p for p in self._hist_xy if t - p[0] <= self.swipe_fenetre_s]
            if (len(self._hist_xy) < 3
                    or (t - self._dernier_envoi) < self.swipe_cooldown_s):
                return None
            dx = self._hist_xy[-1][1] - self._hist_xy[0][1]
            dy = self._hist_xy[-1][2] - self._hist_xy[0][2]
            horizontal = abs(dx) >= self.swipe_seuil and abs(dx) >= abs(dy) * self.swipe_dominance
            vertical = (abs(dy) >= self.swipe_vertical_seuil
                        and abs(dy) >= abs(dx) * self.swipe_dominance)
            if not horizontal and not vertical:
                return None

            vers_bas = dy > 0
            if self.inverser_vertical:
                vers_bas = not vers_bas

            if self.mode == "fenetres":
                if horizontal:
                    resultat = "fenetre_droite" if dx > 0 else "fenetre_gauche"
                else:
                    resultat = "defilement_bas" if vers_bas else "defilement_haut"
            else:
                if horizontal:
                    resultat = "piste_suivante" if dx > 0 else "piste_precedente"
                else:
                    resultat = "volume_bas" if vers_bas else "volume_haut"
            self._dernier_envoi = t
            # Verrouille seulement la fin de ce mouvement. Une pause ou un
            # virage franc sur l'autre axe réarme automatiquement le suivant.
            self._hist_xy = [(t, x, y)]
            self._pret_position = (x, y)
            self._pret_depuis = t
            self._pret_confirme = True
            self._swipe_verrou_axe = "h" if horizontal else "v"
            self._swipe_pause_position = (x, y)
            self._swipe_pause_depuis = t
            self._mode_jusqu = t + self.mode_duree_s
            return resultat

        # Hors mode : 2/3 doigts arment les swipes ; l'index seul arme la souris.
        if instant == "mode_souris":
            if self._tenir_selection_souris(lm, t):
                self.mode = "souris"
                self._mode_jusqu = t + self.mode_duree_s
                self._attend_relachement = False
                self._reinitialiser_pret()
                return instant
            return None

        if instant in {"mode_fenetres", "mode_audio"}:
            if self._tenir(instant, t, self.tenue_mode_s, marquer_cooldown=False):
                self.mode = {
                    "mode_fenetres": "fenetres",
                    "mode_audio": "audio",
                }[instant]
                self._mode_jusqu = t + self.mode_duree_s
                self._attend_relachement = True
                self._reinitialiser_pret()
                return instant
            return None

        if instant in {"main_ouverte", "pouce_leve"} and self._tenir(instant, t):
            return instant
        if instant not in {"main_ouverte", "pouce_leve", "poing"}:
            self._reinitialiser_tenue()
        return None

    def alimenter_plusieurs(self, mains, t):
        """Route une ou deux mains et reconnaît le zoom à deux mains.

        Deux paumes ouvertes doivent d'abord rester stables. Leur écartement
        relatif déclenche ensuite des crans de zoom continus : la distance
        courante devient la nouvelle référence après chaque action.
        """
        mains = list(mains or [])
        if len(mains) < 2:
            self._reinitialiser_zoom()
            return self.alimenter(mains[0] if mains else None, t)

        # Le poing reste prioritaire même si une deuxième main est visible.
        poing = next((lm for lm in mains if est_poing(lm)), None)
        if poing is not None:
            self._reinitialiser_zoom()
            return self.alimenter(poing, t)

        # À deux mains, on neutralise les poses/swipes à une main. Le zoom exige
        # deux paumes franchement déployées pour ne pas partir en discutant.
        self._reinitialiser_tenue()
        self._reinitialiser_pret()
        if not all(est_main_deployee(lm) for lm in mains[:2]):
            self._reinitialiser_zoom()
            return None

        if self.mode:
            self._fermer_mode()

        c1, c2 = centre_main(mains[0]), centre_main(mains[1])
        distance = _d(c1, c2)
        self.zoom_distance = distance

        if self._zoom_reference is None:
            self._zoom_reference = distance
            self._zoom_depuis = t
            return None

        if not self._zoom_pret:
            if abs(distance - self._zoom_reference) > self.zoom_stabilite_seuil:
                self._zoom_reference = distance
                self._zoom_depuis = t
                return None
            if (t - self._zoom_depuis) < self.zoom_tenue_s:
                return None
            self._zoom_pret = True
            self._zoom_reference = distance
            self.debug_evenement = "zoom_pret"
            return None

        delta = distance - self._zoom_reference
        seuil = self.zoom_seuil if delta >= 0 else self.zoom_reduire_seuil
        if abs(delta) < seuil or not self._cooldown_ok(t):
            return None

        resultat = "zoom_agrandir" if delta > 0 else "zoom_reduire"
        self._dernier_envoi = t
        self._zoom_reference = distance
        self._zoom_depuis = t
        self._zoom_pret = True
        self.debug_evenement = resultat
        return resultat


# ==================================================================== I/O

def _envoyer(url, token, geste):
    try:
        requests.post(url, json={"geste": geste},
                      headers={"X-Gestes-Token": token}, timeout=1.5)
    except Exception:
        pass  # Jarvis occupe / injoignable : on ignore, jamais de blocage


def _envoyer_pointeur(url, token, evenement):
    """Envoie seulement une position normalisée locale, jamais les landmarks."""
    try:
        requests.post(url, json={"pointeur": evenement},
                      headers={"X-Gestes-Token": token}, timeout=0.25)
    except Exception:
        pass


def _mains_np(res):
    """Extrait jusqu'à deux mains en listes de (x,y) normalisés."""
    return [[(p.x, p.y) for p in main] for main in (res.hand_landmarks or [])]


def boucle(conf, calibrer=False, demo=False):
    device = int(conf.get("device", 0))
    fps = int(conf.get("fps", 24))
    url = conf.get("url", "http://127.0.0.1:8790/api/gestes")
    token = conf.get("token", "")
    modele = conf.get("model_path", "gestes/models/hand_landmarker.task")

    conf_det = float(conf.get("confiance_detection", 0.7))
    conf_track = float(conf.get("confiance_suivi", 0.7))
    base = mp_python.BaseOptions(model_asset_path=modele)
    options = mp_vision.HandLandmarkerOptions(
        base_options=base, num_hands=2,
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
    historique_gestes = []
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
            mains = _mains_np(res)

            geste = fsm.alimenter_plusieurs(mains, t0)
            if fsm.evenement_pointeur and (not calibrer or demo):
                _envoyer_pointeur(url, token, fsm.evenement_pointeur)
            if geste:
                historique_gestes.append(geste)
                historique_gestes[:] = historique_gestes[-4:]
            if calibrer and fsm.debug_evenement:
                historique_gestes.append(fsm.debug_evenement)
                historique_gestes[:] = historique_gestes[-4:]
                fsm.debug_evenement = ""
            if geste and (not calibrer or demo):
                _envoyer(url, token, geste)

            if calibrer:
                _afficher_calibration(
                    frame, mains, fsm, historique_gestes, t0, demo=demo)
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

def _afficher_calibration(frame, mains, fsm, historique_gestes, maintenant,
                          demo=False):
    h, w = frame.shape[:2]
    if mains:
        couleurs = ((0, 255, 0), (255, 180, 0))
        for numero, lm in enumerate(mains[:2]):
            for x, y in lm:
                cv2.circle(frame, (int(x * w), int(y * h)), 4,
                           couleurs[numero], -1)
        poses = " | ".join(
            f"M{i + 1}:{pose(lm) or '-'} ({doigts_detectes(lm)} doigts)"
            for i, lm in enumerate(mains[:2]))
        lm = mains[0]
        ratio_pouce = ratio_ouverture_pouce(lm)
        extension = extension_pouce(lm)
        infos = [f"mains:{len(mains)}  {poses}",
                 f"M1 ouverte:{est_main_ouverte(lm)}  pouce ecart:{ratio_pouce:.2f} "
                 f"ext:{extension:.2f} ouvert:{pouce_ouvert(lm)}  "
                 f"2:{est_deux_doigts(lm)}  3:{est_trois_doigts(lm)}  poing:{est_poing(lm)}",
                 f"main deployee pour swipe:{est_main_deployee(lm)}"]
    else:
        infos = ["aucune main detectee"]
    restant = max(0.0, fsm._mode_jusqu - maintenant) if fsm.mode else 0.0
    distance_zoom = "-" if fsm.zoom_distance is None else f"{fsm.zoom_distance:.3f}"
    ratio_souris = ("-" if fsm.souris_ratio_pincement is None
                     else f"{fsm.souris_ratio_pincement:.2f}")
    infos += [f"mode:{fsm.mode or '-'} ({restant:.1f}s)  etape:{fsm.etat_swipe}",
              f"souris:{fsm.etat_souris}  clic:{'on' if fsm.souris_clic else 'off'} "
              f"pincement:{ratio_souris}",
              f"zoom:{fsm.etat_zoom}  distance:{distance_zoom}",
              f"tenue:{fsm.tenue_s:.2f}  mode tenue:{fsm.tenue_mode_s:.2f} "
              f"pret:{fsm.swipe_pret_s:.2f}",
              f"cooldown:{fsm.cooldown_s:.2f}  swipe H:{fsm.swipe_seuil:.2f} "
              f"V:{fsm.swipe_vertical_seuil:.2f}  axe V:{'inverse' if fsm.inverser_vertical else 'normal'}",
              f"zoom avant:{fsm.zoom_seuil:.2f}  arriere:{fsm.zoom_reduire_seuil:.2f} "
              f"tenue:{fsm.zoom_tenue_s:.2f}",
              "[t/T] tenue -/+  [c/C] cooldown -/+  [w/W] swipe H -/+",
              "[v/V] swipe V -/+  [z/Z] zoom avant -/+  [r/R] zoom arriere -/+",
              "[x/X] tenue zoom -/+  [p] clic pincement on/off  [k/K] pincement -/+",
              "[i] inverser V  [s] sauver  [q] quitter"]
    if demo:
        infos.insert(0, ">>> MODE DEMO : ACTIONS PC ACTIVES")
    if historique_gestes:
        infos.insert(0, ">>> HIST : " + " > ".join(historique_gestes))
    for i, ligne in enumerate(infos):
        cv2.putText(frame, ligne, (10, 24 + i * 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 255, 255), 1, cv2.LINE_AA)
    titre = ("Jarvis — démo gestes (actions PC actives)" if demo
             else "Jarvis — calibration gestes")
    cv2.imshow(titre, frame)
    if demo and not getattr(fsm, "_fenetre_demo_epinglee", False):
        try:
            cv2.setWindowProperty(titre, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass
        fsm._fenetre_demo_epinglee = True


def _touches_calibration(k, fsm):
    if k in (ord("q"), 27):
        return False
    if k == ord("t"):
        fsm.tenue_s = max(0.3, fsm.tenue_s - 0.1)
    elif k == ord("T"):
        fsm.tenue_s = min(3.0, fsm.tenue_s + 0.1)
    elif k == ord("c"):
        fsm.cooldown_s = max(0.5, fsm.cooldown_s - 0.1)
    elif k == ord("C"):
        fsm.cooldown_s = min(5.0, fsm.cooldown_s + 0.1)
    elif k == ord("w"):
        fsm.swipe_seuil = max(0.10, fsm.swipe_seuil - 0.01)
    elif k == ord("W"):
        fsm.swipe_seuil = min(0.60, fsm.swipe_seuil + 0.01)
    elif k == ord("v"):
        fsm.swipe_vertical_seuil = max(0.10, fsm.swipe_vertical_seuil - 0.01)
    elif k == ord("V"):
        fsm.swipe_vertical_seuil = min(0.60, fsm.swipe_vertical_seuil + 0.01)
    elif k == ord("z"):
        fsm.zoom_seuil = max(0.05, fsm.zoom_seuil - 0.01)
    elif k == ord("Z"):
        fsm.zoom_seuil = min(0.40, fsm.zoom_seuil + 0.01)
    elif k == ord("r"):
        fsm.zoom_reduire_seuil = max(0.03, fsm.zoom_reduire_seuil - 0.01)
    elif k == ord("R"):
        fsm.zoom_reduire_seuil = min(0.30, fsm.zoom_reduire_seuil + 0.01)
    elif k == ord("x"):
        fsm.zoom_tenue_s = max(0.20, fsm.zoom_tenue_s - 0.05)
    elif k == ord("X"):
        fsm.zoom_tenue_s = min(2.0, fsm.zoom_tenue_s + 0.05)
    elif k == ord("p"):
        fsm.souris_clic = not fsm.souris_clic
    elif k == ord("k"):
        fsm.souris_pincement_seuil = max(0.15, fsm.souris_pincement_seuil - 0.05)
    elif k == ord("K"):
        fsm.souris_pincement_seuil = min(1.5, fsm.souris_pincement_seuil + 0.05)
    elif k == ord("i"):
        fsm.inverser_vertical = not fsm.inverser_vertical
    elif k == ord("s"):
        seuils = {
            "tenue_s": round(fsm.tenue_s, 2),
            "tenue_mode_s": round(fsm.tenue_mode_s, 2),
            "cooldown_s": round(fsm.cooldown_s, 2),
            "swipe_seuil": round(fsm.swipe_seuil, 3),
            "swipe_vertical_seuil": round(fsm.swipe_vertical_seuil, 3),
            "swipe_fenetre_s": round(fsm.swipe_fenetre_s, 2),
            "swipe_dominance": round(fsm.swipe_dominance, 2),
            "swipe_pret_s": round(fsm.swipe_pret_s, 2),
            "swipe_cooldown_s": round(fsm.swipe_cooldown_s, 2),
            "swipe_pause_s": round(fsm.swipe_pause_s, 2),
            "swipe_tourne_seuil": round(fsm.swipe_tourne_seuil, 3),
            "stabilite_seuil": round(fsm.stabilite_seuil, 3),
            "inverser_vertical": fsm.inverser_vertical,
            "mode_duree_s": round(fsm.mode_duree_s, 2),
            "sortie_absence_s": round(fsm.sortie_absence_s, 2),
            "zoom_seuil": round(fsm.zoom_seuil, 3),
            "zoom_reduire_seuil": round(fsm.zoom_reduire_seuil, 3),
            "zoom_tenue_s": round(fsm.zoom_tenue_s, 2),
            "zoom_stabilite_seuil": round(fsm.zoom_stabilite_seuil, 3),
            "souris_marge": round(fsm.souris_marge, 3),
            "souris_lissage": round(fsm.souris_lissage, 3),
            "souris_pincement_seuil": round(fsm.souris_pincement_seuil, 3),
            "souris_tenue_s": round(fsm.souris_tenue_s, 2),
            "souris_clic": fsm.souris_clic,
        }
        chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump({"seuils": seuils}, f, ensure_ascii=False, indent=2)
        print(f"[gestes] seuils sauvegardes -> {chemin}", file=sys.stderr)
    return True


def main():
    conf = json.loads(os.environ.get("GESTES_CONF", "{}"))
    demo = "--demo" in sys.argv
    calibrer = "--calibrate" in sys.argv or demo
    boucle(conf, calibrer=calibrer, demo=demo)


if __name__ == "__main__":
    main()
