"""Tests purs du vocabulaire v2 et de la machine de gestes.

MediaPipe/OpenCV vivent dans le venv Python 3.11 du tracker. Ces stubs permettent
de tester la logique géométrique depuis le venv principal sans charger la caméra.
"""
import sys
import types
import unittest
import math


def _module(nom):
    module = types.ModuleType(nom)
    sys.modules[nom] = module
    return module


_module("cv2")
_module("requests")
mp = _module("mediapipe")
tasks = _module("mediapipe.tasks")
mp_python = _module("mediapipe.tasks.python")
vision = _module("mediapipe.tasks.python.vision")
mp.tasks = tasks
tasks.python = mp_python
mp_python.vision = vision

from gestes.tracker import (  # noqa: E402
    MachineGestes,
    extension_pouce,
    est_deux_doigts,
    est_index_pointeur,
    est_index_seul,
    est_main_deployee,
    est_main_ouverte,
    est_poing,
    est_pouce_leve,
    est_quatre_doigts,
    est_trois_doigts,
    pose,
    ratio_ouverture_pouce,
)


def _main(doigts=0, pouce=False, x=0.5, y=0.5):
    """Landmarks synthétiques : `doigts` premiers doigts tendus."""
    lm = [(x, y) for _ in range(21)]
    lm[0] = (x, y + 0.15)
    paires = ((5, 6, 8, -0.09), (9, 10, 12, -0.03),
              (13, 14, 16, 0.03), (17, 18, 20, 0.09))
    for i, (mcp, pip, tip, dx) in enumerate(paires):
        lm[mcp] = (x + dx, y + 0.03)
        lm[pip] = (x + dx, y - 0.04)
        lm[tip] = (x + dx, y - 0.24 if i < doigts else y + 0.08)
    lm[3] = (x - 0.12, y - 0.02)
    lm[4] = (x - 0.12, y - 0.22) if pouce else (x - 0.07, y + 0.02)
    return lm


def _paume(x=0.5, y=0.5):
    """Main entièrement ouverte : quatre doigts longs et pouce déployé."""
    return _main(4, pouce=True, x=x, y=y)


def _tourner(lm, angle):
    """Tourne les landmarks autour du poignet, comme une main inclinée."""
    ox, oy = lm[0]
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return [(ox + (x - ox) * cos_a - (y - oy) * sin_a,
             oy + (x - ox) * sin_a + (y - oy) * cos_a) for x, y in lm]


def _fsm():
    return MachineGestes({"seuils": {
        "tenue_s": 1.0,
        "tenue_mode_s": 0.5,
        "cooldown_s": 0.1,
        "swipe_pas_horizontal": 0.08,
        "swipe_pas_vertical": 0.07,
        "swipe_fenetre_s": 1.0,
        "swipe_dominance": 1.1,
        "swipe_pret_s": 0.3,
        "stabilite_seuil": 0.06,
        "mode_duree_s": 5.0,
        "zoom_seuil": 0.12,
        "zoom_reduire_seuil": 0.08,
        "zoom_tenue_s": 0.4,
        "zoom_stabilite_seuil": 0.03,
        "souris_marge": 0.10,
        "souris_lissage": 0.32,
        "souris_pincement_seuil": 0.55,
        "souris_clic": True,
    }})


class ClassifieursTests(unittest.TestCase):
    def test_cinq_poses_sont_distinctes(self):
        self.assertFalse(est_main_ouverte(_main(4)))
        self.assertTrue(est_main_ouverte(_paume()))
        self.assertTrue(est_quatre_doigts(_main(4)))
        self.assertFalse(est_quatre_doigts(_paume()))
        self.assertTrue(est_index_seul(_main(1)))
        self.assertTrue(est_index_pointeur(_main(2)))
        self.assertTrue(est_deux_doigts(_main(2)))
        self.assertTrue(est_trois_doigts(_main(3)))
        self.assertTrue(est_pouce_leve(_main(0, pouce=True)))
        self.assertTrue(est_poing(_main(0)))
        self.assertTrue(est_main_deployee(_main(3)))
        self.assertTrue(est_main_deployee(_paume()))
        self.assertIsNone(pose(_main(4)))
        self.assertEqual(pose(_main(1)), "mode_souris")
        self.assertEqual(pose(_paume()), "main_ouverte")
        self.assertLessEqual(ratio_ouverture_pouce(_main(4)), 0.30)
        self.assertGreater(ratio_ouverture_pouce(_paume()), 0.45)
        self.assertLess(extension_pouce(_main(4)), 0.12)
        self.assertGreater(extension_pouce(_paume()), 0.12)

    def test_main_ouverte_reste_ouverte_a_l_horizontale(self):
        horizontale = _tourner(_paume(), math.pi / 2)
        self.assertTrue(est_main_ouverte(horizontale))
        self.assertFalse(est_poing(horizontale))


class ModesTests(unittest.TestCase):
    def test_ancienne_calibration_est_migree_vers_des_petits_pas(self):
        fsm = MachineGestes({
            "seuils": {
                "swipe_seuil": 0.14,
                "swipe_vertical_seuil": 0.12,
            }
        })
        self.assertAlmostEqual(fsm.swipe_seuil, 0.09)
        self.assertAlmostEqual(fsm.swipe_vertical_seuil, 0.075)

    def test_index_seul_arme_la_souris_et_deplace_le_pointeur(self):
        fsm = _fsm()
        index = _main(1, x=0.45, y=0.55)
        self.assertIsNone(fsm.alimenter(index, 0.0))
        self.assertEqual(fsm.etat_souris, "ARMEMENT INDEX - ne bouge plus")
        self.assertEqual(fsm.alimenter(index, 0.6), "mode_souris")
        self.assertEqual(fsm.mode, "souris")

        self.assertIsNone(fsm.alimenter(index, 0.7))
        self.assertIsNotNone(fsm.evenement_pointeur)
        self.assertFalse(fsm.evenement_pointeur["clic"])
        self.assertEqual(fsm.etat_souris, "POINTEUR ACTIF")

        # Après une position pouce écarté, le pincement produit un seul clic.
        # Un vrai pincement replie souvent l'index : le clic doit rester reconnu
        # même si la pose n'est alors plus classée comme « index seul ».
        pince = _main(0, x=0.45, y=0.55)
        pince[4] = (pince[8][0] + 0.005, pince[8][1] + 0.005)
        self.assertIsNone(fsm.alimenter(pince, 0.9))
        self.assertTrue(fsm.evenement_pointeur["clic"])
        self.assertIsNone(fsm.alimenter(pince, 1.0))
        self.assertFalse(fsm.evenement_pointeur["clic"])

    def test_main_ouverte_avec_pouce_ne_declenche_pas_mode_souris(self):
        fsm = _fsm()
        ouverte = _main(4, pouce=True)
        self.assertIsNone(fsm.alimenter(ouverte, 0.0))
        self.assertEqual(fsm.alimenter(ouverte, 1.1), "main_ouverte")
        self.assertIsNone(fsm.mode)

    def test_index_immobile_bascule_un_autre_mode_vers_souris(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_main(1), 0.7))
        self.assertEqual(fsm.alimenter(_main(1), 1.3), "mode_souris")
        self.assertEqual(fsm.mode, "souris")

    def test_mode_arme_tolere_trois_doigts_visibles_pendant_le_swipe(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_main(3, x=0.2), 0.7))
        self.assertIsNone(fsm.alimenter(_main(3, x=0.2), 1.05))
        self.assertEqual(fsm.alimenter(_main(3, x=0.3), 1.15), "fenetre_droite")
        self.assertIsNone(fsm.alimenter(_main(3, x=0.3), 1.25))

    def test_deux_mains_ouvertes_ecartees_zoom_avant(self):
        fsm = _fsm()
        mains = [_paume(x=0.30), _paume(x=0.60)]
        self.assertIsNone(fsm.alimenter_plusieurs(mains, 0.0))
        self.assertIsNone(fsm.alimenter_plusieurs(mains, 0.45))
        self.assertEqual(fsm.etat_zoom, "PRET - ecarte ou rapproche")
        self.assertIsNone(fsm.alimenter_plusieurs(
            [_paume(x=0.26), _paume(x=0.64)], 0.55))
        self.assertEqual(fsm.alimenter_plusieurs(
            [_paume(x=0.20), _paume(x=0.75)], 0.65), "zoom_agrandir")
        self.assertEqual(fsm.etat_zoom, "PRET - ecarte ou rapproche")

    def test_zoom_peut_inverser_sans_sortir_les_mains(self):
        fsm = _fsm()
        mains = [_paume(x=0.20), _paume(x=0.80)]
        fsm.alimenter_plusieurs(mains, 0.0)
        fsm.alimenter_plusieurs(mains, 0.45)
        self.assertEqual(fsm.alimenter_plusieurs(
            [_paume(x=0.32), _paume(x=0.68)], 0.60), "zoom_reduire")
        self.assertIsNone(fsm.alimenter_plusieurs(
            [_paume(x=0.28), _paume(x=0.72)], 1.20))
        self.assertEqual(fsm.alimenter_plusieurs(
            [_paume(x=0.20), _paume(x=0.80)], 1.45), "zoom_agrandir")
        self.assertEqual(fsm.etat_zoom, "PRET - ecarte ou rapproche")

    def test_zoom_arriere_est_plus_sensible_que_zoom_avant(self):
        fsm = _fsm()
        mains = [_paume(x=0.25), _paume(x=0.75)]
        fsm.alimenter_plusieurs(mains, 0.0)
        fsm.alimenter_plusieurs(mains, 0.45)
        # Un rapprochement de 0,09 dépasse le seuil arrière (0,08).
        self.assertEqual(fsm.alimenter_plusieurs(
            [_paume(x=0.295), _paume(x=0.705)], 0.55), "zoom_reduire")

        # Le même écartement reste sous le seuil avant (0,12), même après le
        # cooldown, sans obliger les mains à quitter le cadre.
        self.assertIsNone(fsm.alimenter_plusieurs(
            [_paume(x=0.25), _paume(x=0.75)], 1.40))

    def test_zoom_continue_plusieurs_crans_dans_le_meme_sens(self):
        fsm = _fsm()
        mains = [_paume(x=0.30), _paume(x=0.60)]
        fsm.alimenter_plusieurs(mains, 0.0)
        fsm.alimenter_plusieurs(mains, 0.45)
        self.assertEqual(fsm.alimenter_plusieurs(
            [_paume(x=0.20), _paume(x=0.75)], 0.60), "zoom_agrandir")
        self.assertEqual(fsm.alimenter_plusieurs(
            [_paume(x=0.12), _paume(x=0.87)], 1.45), "zoom_agrandir")

    def test_deux_mains_non_ouvertes_ne_declenchent_pas_le_zoom(self):
        fsm = _fsm()
        for t in (0.0, 0.5, 1.0):
            self.assertIsNone(fsm.alimenter_plusieurs(
                [_main(2, x=0.2), _main(4, x=0.8)], t))
        self.assertEqual(fsm.etat_zoom, "montre 2 mains ouvertes")

    def test_poing_reste_prioritaire_avec_deux_mains_visibles(self):
        fsm = _fsm()
        mains = [_main(0, x=0.3), _paume(x=0.7)]
        self.assertIsNone(fsm.alimenter_plusieurs(mains, 0.0))
        self.assertEqual(fsm.alimenter_plusieurs(mains, 1.1), "poing")

    def test_main_ouverte_et_pouce_sont_tenus_une_seule_fois(self):
        fsm = _fsm()
        ouverte = _main(4, pouce=True)
        self.assertIsNone(fsm.alimenter(ouverte, 0.0))
        self.assertEqual(fsm.alimenter(ouverte, 1.1), "main_ouverte")
        self.assertIsNone(fsm.alimenter(ouverte, 2.5))
        fsm.alimenter(None, 2.6)
        self.assertIsNone(fsm.alimenter(_main(0, pouce=True), 3.0))
        self.assertEqual(fsm.alimenter(_main(0, pouce=True), 4.1), "pouce_leve")

    def test_mode_fenetres_accepte_des_petits_pas_continus(self):
        fsm = _fsm()
        self.assertIsNone(fsm.alimenter(_main(2), 0.0))
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        # On peut passer directement de 2 doigts à la paume ouverte.
        self.assertIsNone(fsm.alimenter(_paume(x=0.2), 0.7))
        self.assertIsNone(fsm.alimenter(_paume(x=0.2), 1.05))
        self.assertEqual(fsm.alimenter(_paume(x=0.30), 1.15), "fenetre_droite")
        self.assertEqual(fsm.mode, "fenetres")
        self.assertEqual(fsm.etat_swipe, "PAUME ACTIVE - bouge par petits pas")

        # Continuer doucement dans le même sens produit un deuxième cran.
        self.assertEqual(fsm.alimenter(_paume(x=0.39), 1.35), "fenetre_droite")

        # Une pause, même longue, ne produit rien et ne ferme pas le mode.
        self.assertIsNone(fsm.alimenter(_paume(x=0.39), 1.70))
        self.assertIsNone(fsm.alimenter(_paume(x=0.39), 2.10))
        self.assertEqual(fsm.mode, "fenetres")

        # Le même mode change d'axe sans refaire les deux doigts.
        self.assertEqual(fsm.alimenter(_paume(x=0.39, y=0.40), 2.30),
                         "defilement_haut")
        self.assertEqual(fsm.alimenter(_paume(x=0.39, y=0.31), 2.50),
                         "defilement_haut")

    def test_mode_audio_vertical_regle_le_volume(self):
        fsm = _fsm()
        fsm.alimenter(_main(3), 0.0)
        self.assertEqual(fsm.alimenter(_main(3), 0.6), "mode_audio")
        self.assertIsNone(fsm.alimenter(_paume(y=0.65), 0.7))
        self.assertIsNone(fsm.alimenter(_paume(y=0.65), 1.05))
        self.assertEqual(fsm.alimenter(_paume(y=0.55), 1.15), "volume_haut")
        self.assertEqual(fsm.alimenter(_paume(y=0.47), 1.35), "volume_haut")

    def test_poing_repositionne_sans_action_opposee(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_paume(x=0.55), 0.7))
        self.assertIsNone(fsm.alimenter(_paume(x=0.55), 1.05))
        self.assertEqual(fsm.alimenter(_paume(x=0.45), 1.15),
                         "fenetre_gauche")

        # Le poing ramène la main à droite sans action et sans couper le mode.
        self.assertIsNone(fsm.alimenter(_main(0, x=0.50), 1.25))
        self.assertIsNone(fsm.alimenter(_main(0, x=0.65), 1.45))
        self.assertEqual(fsm.mode, "fenetres")
        self.assertEqual(fsm.etat_swipe, "POING - repositionne sans action")
        self.assertIsNone(fsm.alimenter(_paume(x=0.65), 1.55))
        self.assertEqual(fsm.etat_swipe, "PAUME ACTIVE - bouge par petits pas")

        # Après réouverture, un nouveau petit pas agit depuis la nouvelle origine.
        self.assertEqual(fsm.alimenter(_paume(x=0.55), 1.80),
                         "fenetre_gauche")

    def test_perte_camera_courte_ne_desarme_pas_le_mode(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_paume(x=0.20), 0.7))
        self.assertIsNone(fsm.alimenter(_paume(x=0.20), 1.05))
        self.assertEqual(fsm.alimenter(_paume(x=0.30), 1.15),
                         "fenetre_droite")

        self.assertIsNone(fsm.alimenter(None, 1.30))
        self.assertIsNone(fsm.alimenter(None, 2.00))
        self.assertEqual(fsm.mode, "fenetres")
        self.assertIsNone(fsm.alimenter(_paume(x=0.55, y=0.50), 2.10))
        self.assertEqual(fsm.alimenter(_paume(x=0.55, y=0.40), 2.20),
                         "defilement_haut")

    def test_axe_vertical_peut_etre_inverse_par_calibration(self):
        fsm = _fsm()
        fsm.inverser_vertical = True
        fsm.alimenter(_main(3), 0.0)
        self.assertEqual(fsm.alimenter(_main(3), 0.6), "mode_audio")
        self.assertIsNone(fsm.alimenter(_paume(y=0.65), 0.7))
        self.assertIsNone(fsm.alimenter(_paume(y=0.65), 1.05))
        self.assertEqual(fsm.alimenter(_paume(y=0.55), 1.15), "volume_bas")

    def test_mode_arme_tolere_un_pouce_mal_vu_sans_armer_la_souris(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_main(4, x=0.2), 0.7))
        self.assertIsNone(fsm.alimenter(_main(4, x=0.2), 1.05))
        self.assertEqual(fsm.alimenter(_main(4, x=0.3), 1.12), "fenetre_droite")
        self.assertEqual(fsm.mode, "fenetres")

    def test_zoom_tolere_un_pouce_mal_vu_sur_chaque_main(self):
        fsm = _fsm()
        mains = [_main(4, x=0.30), _main(4, x=0.60)]
        self.assertIsNone(fsm.alimenter_plusieurs(mains, 0.0))
        self.assertIsNone(fsm.alimenter_plusieurs(mains, 0.45))
        self.assertEqual(fsm.alimenter_plusieurs(
            [_main(4, x=0.20), _main(4, x=0.75)], 0.60), "zoom_agrandir")

    def test_retour_dans_le_cadre_ne_compte_pas_comme_swipe(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        fsm.alimenter(None, 0.7)
        self.assertIsNone(fsm.alimenter(_paume(x=0.1), 0.8))
        # Grand mouvement pendant la phase de stabilisation : aucun geste.
        self.assertIsNone(fsm.alimenter(_paume(x=0.6), 0.9))
        self.assertIsNone(fsm.alimenter(_paume(x=0.6), 1.25))
        self.assertEqual(fsm.etat_swipe, "PAUME ACTIVE - bouge par petits pas")
        self.assertEqual(fsm.alimenter(_paume(x=0.5), 1.35), "fenetre_gauche")

    def test_derive_lente_n_empeche_pas_l_etat_pret(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_paume(x=0.20), 0.70))
        self.assertIsNone(fsm.alimenter(_paume(x=0.24), 0.82))
        self.assertIsNone(fsm.alimenter(_paume(x=0.28), 0.94))
        self.assertIsNone(fsm.alimenter(_paume(x=0.32), 1.06))
        self.assertEqual(fsm.etat_swipe, "PAUME ACTIVE - bouge par petits pas")

    def test_swipe_sans_mode_ne_declenche_rien(self):
        fsm = _fsm()
        self.assertIsNone(fsm.alimenter(_paume(x=0.2), 0.0))
        self.assertIsNone(fsm.alimenter(_paume(x=0.5), 0.2))

    def test_mode_reste_actif_main_visible_et_sort_apres_absence(self):
        fsm = _fsm()
        fsm.alimenter(_main(2), 0.0)
        self.assertEqual(fsm.alimenter(_main(2), 0.6), "mode_fenetres")
        self.assertIsNone(fsm.alimenter(_paume(), 50.0))
        self.assertEqual(fsm.mode, "fenetres")
        self.assertIsNone(fsm.alimenter(None, 50.1))
        self.assertEqual(fsm.mode, "fenetres")
        self.assertIsNone(fsm.alimenter(None, 53.2))
        self.assertIsNone(fsm.mode)
        self.assertEqual(fsm.debug_evenement, "mode_fenetres_sortie")


if __name__ == "__main__":
    unittest.main()
