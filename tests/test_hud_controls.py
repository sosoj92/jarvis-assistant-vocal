"""Tests sans reseau du tiroir de configuration rapide du HUD."""
import json
import unittest
from unittest.mock import patch

import hud


class HudControlsTests(unittest.TestCase):
    def test_bascule_mode_reutilise_la_whitelist_du_panneau(self):
        attendu = {"ok": True, "message": "Mode hybride actif."}
        with patch("core.panneau._definir_reglage", return_value=attendu) as regler, \
                patch.object(hud, "_synchroniser_controles") as synchroniser:
            resultat = hud._appliquer_controle({"action": "mode", "valeur": "hybride"})

        self.assertEqual(resultat, attendu)
        regler.assert_called_once_with("mode", "hybride")
        synchroniser.assert_called_once_with()

    def test_modele_cloud_transmet_fournisseur_et_profil(self):
        with patch("core.panneau._definir_actif",
                   return_value={"ok": True, "message": "ok"}) as definir, \
                patch.object(hud, "_synchroniser_controles"):
            resultat = hud._appliquer_controle({
                "action": "modele_cloud",
                "fournisseur": "openai",
                "modele": "gpt-test",
                "profil": "qualite",
            })

        self.assertTrue(resultat["ok"])
        definir.assert_called_once_with(
            "cloud", "gpt-test", profil="qualite", fournisseur="openai")

    def test_moteur_voix_reinitialise_par_le_panneau(self):
        with patch("core.panneau._definir_reglage",
                   return_value={"ok": True, "message": "ok"}) as regler, \
                patch.object(hud, "_synchroniser_controles"):
            resultat = hud._appliquer_controle({
                "action": "moteur_voix", "valeur": "elevenlabs"})

        self.assertTrue(resultat["ok"])
        regler.assert_called_once_with("tts.moteur", "elevenlabs")

    def test_etat_public_ne_renvoie_aucun_secret(self):
        valeurs = {
            "mode": "hybride",
            "openai.cle": "secret-openai-a-ne-jamais-renvoyer",
            "anthropic.cle": "secret-anthropic-a-ne-jamais-renvoyer",
            "elevenlabs.cle": "secret-eleven-a-ne-jamais-renvoyer",
            "openai.modele": "gpt-test",
            "openai.modele_qualite": "gpt-test-pro",
            "anthropic.modele": "claude-test",
            "anthropic.modele_qualite": "claude-test-pro",
            "ollama.modele": "qwen-test",
            "tts.moteur": "elevenlabs",
            "elevenlabs.voix": "voice-id-public",
            "elevenlabs.modele": "eleven_flash_v2_5",
            "serveur.port": 8790,
        }

        def lire(cle, default=None):
            return valeurs.get(cle, default)

        with patch("core.config.reglage", side_effect=lire), \
                patch("core.cloud.fournisseur", return_value="openai"), \
                patch("core.cloud.modele", return_value="gpt-test"), \
                patch("core.panneau._openai_etat", return_value={
                    "configure": True, "joignable": True,
                    "catalogue": [{"nom": "gpt-test", "role": "Test",
                                   "accessible": True}],
                }), \
                patch("core.panneau._elevenlabs_voix", return_value={
                    "configure": True, "joignable": True,
                    "voix": [{"id": "voice-id-public", "nom": "Jarvis"}],
                    "erreur": "",
                }), \
                patch("core.panneau._ollama_installes",
                      return_value=[{"nom": "qwen-test", "taille_go": 1.0}]), \
                patch("core.panneau._ollama_joignable", return_value=True):
            donnees = hud._etat_controles()

        brut = json.dumps(donnees)
        self.assertTrue(donnees["ok"])
        self.assertNotIn("secret-openai", brut)
        self.assertNotIn("secret-anthropic", brut)
        self.assertNotIn("secret-eleven", brut)

    def test_tester_voix_sans_parleur_ne_promet_rien(self):
        from core import voix
        with patch.object(voix, "_parleur", None), \
                patch.object(hud.threading, "Thread") as fil:
            resultat = hud._appliquer_controle({"action": "tester_voix"})
        self.assertFalse(resultat["ok"])
        self.assertIn("Aucune voix", resultat["message"])
        # Pas de renvoi vers un test qui jouerait sur une autre machine.
        self.assertNotIn("panneau", resultat["message"])
        self.assertIn("dis bonjour", resultat["message"])
        fil.assert_not_called()

    def test_tester_voix_avec_parleur_joue_une_seule_fois(self):
        from core import voix
        import threading
        lance, libere = threading.Event(), threading.Event()
        textes = []

        def parleur(texte):
            textes.append(texte)
            lance.set()
            libere.wait(2)

        with patch.object(voix, "_parleur", parleur):
            premier = hud._appliquer_controle({"action": "tester_voix"})
            self.assertTrue(lance.wait(2))
            second = hud._appliquer_controle({"action": "tester_voix"})
            libere.set()
            for _ in range(100):                 # le verrou se libere en fin de test
                if not hud._TEST_VOIX.locked():
                    break
                threading.Event().wait(0.01)
        self.assertTrue(premier["ok"])
        self.assertFalse(second["ok"])             # un seul test a la fois
        self.assertEqual(len(textes), 1)
        self.assertFalse(hud._TEST_VOIX.locked())


if __name__ == "__main__":
    unittest.main()
