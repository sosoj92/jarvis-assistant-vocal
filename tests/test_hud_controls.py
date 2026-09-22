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
                "action": "moteur_voix", "valeur": "piper"})

        self.assertTrue(resultat["ok"])
        regler.assert_called_once_with("tts.moteur", "piper")

    def test_etat_public_ne_renvoie_aucun_secret(self):
        valeurs = {
            "mode": "hybride",
            "openai.cle": "secret-openai-a-ne-jamais-renvoyer",
            "anthropic.cle": "secret-anthropic-a-ne-jamais-renvoyer",
            "openai.modele": "gpt-test",
            "openai.modele_qualite": "gpt-test-pro",
            "anthropic.modele": "claude-test",
            "anthropic.modele_qualite": "claude-test-pro",
            "ollama.modele": "qwen-test",
            "tts.moteur": "piper",
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
                patch("core.panneau._ollama_installes",
                      return_value=[{"nom": "qwen-test", "taille_go": 1.0}]), \
                patch("core.panneau._ollama_joignable", return_value=True):
            donnees = hud._etat_controles()

        brut = json.dumps(donnees)
        self.assertTrue(donnees["ok"])
        self.assertNotIn("secret-openai", brut)
        self.assertNotIn("secret-anthropic", brut)
        self.assertNotIn("secret-eleven", brut)


if __name__ == "__main__":
    unittest.main()
