"""Tests hors réseau du routage média direct, sans Astra."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import registre
from tools import media, spotify, systeme  # charge aussi l'outil controler_media


class MediaRoutingTests(unittest.TestCase):
    def test_commandes_transport_utilisent_les_touches_media(self):
        cas = {
            "Hey Jarvis, change de musique": "suivant",
            "musique précédente": "precedent",
            "mets en pause": "pause",
            "reprends la musique": "pause",
        }
        for phrase, action in cas.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    media.router_commande_media(phrase),
                    ("controler_media", {"action": action}),
                )

    def test_playlist_et_titre_spotify_sont_routes_sans_astra(self):
        self.assertEqual(
            media.router_commande_media("Lance ma playlist Chill sur Spotify"),
            ("lire_spotify", {"recherche": "chill", "type_media": "playlist"}),
        )
        self.assertEqual(
            media.router_commande_media("Joue Blinding Lights sur Spotify"),
            ("lire_spotify", {
                "recherche": "blinding lights", "type_media": "titre"}),
        )
        self.assertEqual(
            media.router_commande_media(
                "Lance ma playlist Chill sur Spotify", piece="cuisine"),
            ("lire_spotify", {
                "recherche": "chill", "type_media": "playlist",
                "piece": "cuisine",
            }),
        )

    def test_commandes_transport_du_satellite_ciblent_spotify_connect(self):
        self.assertEqual(
            media.router_commande_media("musique suivante", piece="cuisine"),
            ("controler_spotify", {"action": "suivant", "piece": "cuisine"}),
        )
        self.assertEqual(
            media.router_commande_media("reprends la musique", piece="cuisine"),
            ("controler_spotify", {"action": "reprendre", "piece": "cuisine"}),
        )

    def test_variantes_suivant_et_precedent(self):
        suivants = (
            "suivant", "next", "skip", "mets la suivante",
            "saute ce morceau", "change de chanson", "prochaine chanson",
        )
        precedents = (
            "précédent", "mets la précédente", "remets celle d'avant",
            "chanson d'avant", "reviens d'un morceau",
        )
        for phrase in suivants:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    media.router_commande_media(phrase, piece="cuisine"),
                    ("controler_spotify", {
                        "action": "suivant", "piece": "cuisine"}),
                )
        for phrase in precedents:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    media.router_commande_media(phrase, piece="cuisine"),
                    ("controler_spotify", {
                        "action": "precedent", "piece": "cuisine"}),
                )

    def test_variantes_pause_restent_deterministes_sur_satellite(self):
        for phrase in (
                "mets pause", "mets Spotify en pause",
                "mets la musique en pause", "arrête Spotify", "stop",
                "stoppe la musique", "coupe le son", "suspends la lecture",
                "interromps ce morceau", "éteins la musique",
                "fais une pause", "appuie sur pause", "ne joue plus",
                "je ne veux plus de musique", "mets ça sur pause",
                "pause-moi la musique", "fais arrêter la musique",
                "arrête ce que j'écoute", "coupe ce qui joue"):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    media.router_commande_media(phrase, piece="cuisine"),
                    ("controler_spotify", {
                        "action": "pause", "piece": "cuisine"}),
                )

    def test_variantes_play_restent_deterministes_sur_satellite(self):
        for phrase in (
                "play", "mets play", "appuie sur play",
                "reprends", "continue la musique", "mets en lecture",
                "remets la musique", "relance Spotify", "redémarre la lecture",
                "fais repartir la musique", "enlève la pause",
                "reprends là où tu t'es arrêté", "continue là où tu en étais",
                "remets ce qui jouait", "peux-tu me remettre la musique",
                "est-ce que tu pourrais relancer Spotify",
                "vas-y remets la musique", "rallume la musique",
                "réactive Spotify", "fais reprendre la musique",
                "reprends ce que j'écoutais", "lance la musique maintenant",
                "mets-moi la musique Jarvis",
                "je veux que tu relances la musique"):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    media.router_commande_media(phrase, piece="cuisine"),
                    ("controler_spotify", {
                        "action": "reprendre", "piece": "cuisine"}),
                )

    def test_negation_ne_declenche_pas_une_commande_media(self):
        for phrase in (
                "ne mets pas la musique en pause",
                "n'arrête pas Spotify",
                "ne relance pas la musique"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    media.router_commande_media(phrase, piece="cuisine"))

    def test_serie_netflix_est_routee_sans_astra(self):
        self.assertEqual(
            media.router_commande_media("Lance la série Arcane sur Netflix"),
            ("lire_netflix", {"titre": "arcane"}),
        )

    def test_alexa_et_les_phrases_discursives_ne_sont_pas_detournees(self):
        for phrase in (
                "Mets la musique sur Alexa",
                "Est-ce que tu connais ma playlist Chill ?",
                "J'aimerais parler de la série Arcane sur Netflix"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(media.router_commande_media(phrase))

    def test_outils_media_ne_demandent_pas_confirmation(self):
        for nom in ("controler_media", "controler_spotify", "lancer_spotify",
                    "lire_spotify", "lire_netflix"):
            with self.subTest(nom=nom):
                outil = registre.get(nom)
                self.assertIsNotNone(outil)
                self.assertFalse(outil.confirmation)
                self.assertEqual(registre.niveau(nom), "N1")

    def test_lancer_spotify_ouvre_et_reprend_la_lecture(self):
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._etat_lecture", return_value={
                    "is_playing": False, "device": {"id": "bureau"}}), \
                patch("tools.spotify._reprendre_lecture",
                      return_value=SimpleNamespace(status_code=204)) as reprendre, \
                patch("tools.spotify._ouvrir_application_spotify") as ouvrir, \
                patch("tools.spotify.time.sleep") as dormir:
            resultat = spotify.lancer_spotify()

        self.assertEqual(resultat, "Spotify est lancé et la lecture a repris.")
        ouvrir.assert_called_once_with()
        reprendre.assert_called_once_with()
        dormir.assert_not_called()

    def test_lancer_spotify_ne_met_pas_en_pause_si_ca_joue_deja(self):
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._etat_lecture", return_value={
                    "is_playing": True, "device": {"id": "bureau"}}), \
                patch("tools.spotify._reprendre_lecture") as reprendre, \
                patch("tools.spotify._ouvrir_application_spotify") as ouvrir:
            resultat = spotify.lancer_spotify()

        self.assertEqual(resultat, "Spotify est ouvert et déjà en lecture.")
        ouvrir.assert_called_once_with()
        reprendre.assert_not_called()

    def test_lancer_spotify_depuis_cuisine_transfere_vers_enceinte(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as transferer, \
                patch("tools.spotify._ouvrir_application_spotify") as ouvrir:
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Je lance Spotify sur Jarvis Cuisine.")
        transferer.assert_called_once_with("device-cuisine", lecture=True)
        ouvrir.assert_not_called()

    def test_reprendre_sur_enceinte_inactive_transfere_d_abord(self):
        appareil = {
            "id": "device-cuisine", "name": "Jarvis Cuisine",
            "is_active": False,
        }
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as transferer, \
                patch("tools.spotify._reprendre_lecture") as reprendre:
            resultat = spotify.controler_spotify("reprendre", "cuisine")

        self.assertEqual(resultat, "Je reprends la musique.")
        transferer.assert_called_once_with("device-cuisine", lecture=True)
        reprendre.assert_not_called()

    def test_suivant_sur_enceinte_inactive_transfere_puis_commande(self):
        appareil = {
            "id": "device-cuisine", "name": "Jarvis Cuisine",
            "is_active": False,
        }
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as transferer, \
                patch("tools.spotify._commande_lecture",
                      return_value=SimpleNamespace(status_code=204)) as commander, \
                patch("tools.spotify.time.sleep") as dormir:
            resultat = spotify.controler_spotify("suivant", "cuisine")

        self.assertEqual(resultat, "Je passe au morceau suivant.")
        transferer.assert_called_once_with("device-cuisine", lecture=True)
        dormir.assert_called_once_with(0.2)
        commander.assert_called_once_with("device-cuisine", "suivant")

    def test_spotify_accepte_tous_les_statuts_http_2xx(self):
        appareil = {
            "id": "device-cuisine", "name": "Jarvis Cuisine",
            "is_active": True,
        }
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._commande_lecture",
                      return_value=SimpleNamespace(status_code=202)):
            resultat = spotify.controler_spotify("pause", "cuisine")

        self.assertEqual(resultat, "Musique en pause.")

    def test_pause_est_envoyee_meme_si_raspotify_se_dit_inactif(self):
        appareil = {
            "id": "device-cuisine", "name": "Jarvis Cuisine",
            "is_active": False,
        }
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._commande_lecture",
                      return_value=SimpleNamespace(status_code=204)) as commander, \
                patch("tools.spotify._transferer_lecture") as transferer:
            resultat = spotify.controler_spotify("pause", "cuisine")

        self.assertEqual(resultat, "Musique en pause.")
        commander.assert_called_once_with("device-cuisine", "pause")
        transferer.assert_not_called()

    def test_pause_appliquee_ne_rapporte_pas_un_faux_echec(self):
        appareil = {
            "id": "device-cuisine", "name": "Jarvis Cuisine",
            "is_active": True,
        }
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._commande_lecture",
                      return_value=SimpleNamespace(status_code=404)), \
                patch("tools.spotify._etat_lecture", return_value={
                    "is_playing": False,
                    "device": {"name": "Jarvis Cuisine"},
                }), \
                patch("tools.spotify.time.sleep"):
            resultat = spotify.controler_spotify("pause", "cuisine")

        self.assertEqual(resultat, "Musique en pause.")

    def test_titre_spotify_depuis_cuisine_cible_l_appareil(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._chercher_media", return_value={
                    "uri": "spotify:track:abc", "name": "Blinding Lights"}), \
                patch("tools.spotify._demarrer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as demarrer:
            resultat = spotify.lire_spotify("Blinding Lights", piece="cuisine")

        self.assertEqual(
            resultat, "Je lance « Blinding Lights » sur Jarvis Cuisine.")
        demarrer.assert_called_once_with(
            "spotify:track:abc", "titre", device_id="device-cuisine")

    def test_playlist_personnelle_exacte_passe_avant_la_recherche_publique(self):
        with patch("tools.spotify._playlist_id",
                   return_value="playlist-trajet") as personnelle, \
                patch.object(spotify, "requests") as requetes:
            resultat = spotify._chercher_media("trajet", "playlist")

        self.assertEqual(resultat, {
            "uri": "spotify:playlist:playlist-trajet",
            "name": "trajet",
        })
        personnelle.assert_called_once_with("trajet", creer=False)
        requetes.get.assert_not_called()

    def test_spotify_connect_lance_le_resultat_exact(self):
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._chercher_media", return_value={
                    "uri": "spotify:track:abc", "name": "Blinding Lights"}), \
                patch("tools.spotify._demarrer_lecture",
                      return_value=SimpleNamespace(status_code=204)), \
                patch("core.plateforme.ouvrir") as lancer:
            resultat = spotify.lire_spotify("Blinding Lights")

        self.assertEqual(resultat, "Je lance « Blinding Lights » sur Spotify.")
        lancer.assert_not_called()

    def test_spotify_sans_oauth_ouvre_une_recherche_locale(self):
        with patch("tools.spotify._configure", return_value=False), \
                patch("core.plateforme.ouvrir") as lancer:
            resultat = spotify.lire_spotify("Daft Punk")

        self.assertIn("recherche Spotify", resultat)
        lancer.assert_called_once_with("spotify:search:Daft%20Punk")

    @patch("tools.media.time.sleep")
    @patch("tools.navigateur.browser_interact", return_value="C'est clique.")
    @patch("tools.navigateur.browser_open", return_value="Netflix ouvert.")
    def test_netflix_ouvre_et_tente_une_action_bornee(
            self, ouvrir, interagir, _sleep):
        resultat = media.lire_netflix("Arcane")

        self.assertEqual(resultat, "Je lance « Arcane » sur Netflix.")
        ouvrir.assert_called_once_with(
            url="https://www.netflix.com/search?q=Arcane")
        self.assertIn("Netflix uniquement", interagir.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
