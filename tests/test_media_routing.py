"""Tests hors réseau du routage média direct, sans Astra."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import registre
from tools import media, spotify, systeme  # charge aussi l'outil controler_media


class MediaRoutingTests(unittest.TestCase):
    def setUp(self):
        # Par défaut aucune playlist de lancement : le config.yaml local ne doit
        # pas influencer les tests. Les tests de la playlist la patchent eux-mêmes.
        for cible, valeur in (("tools.spotify._playlist_lancement", (None, "")),
                              ("tools.spotify._lancement_aleatoire", False)):
            patcher = patch(cible, return_value=valeur)
            patcher.start()
            self.addCleanup(patcher.stop)

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

    # État Spotify typique avant « lance Spotify » en cuisine : un titre en pause
    # sur un autre appareil, écouté hors playlist (contexte absent).
    ETAT_EN_PAUSE_AILLEURS = {
        "is_playing": False, "device": {"id": "device-bureau"},
        "context": None, "progress_ms": 61000,
        "item": {"uri": "spotify:track:T1", "type": "track",
                 "album": {"uri": "spotify:album:A1"}},
    }
    ETAT_JOUE_EN_CUISINE = {"is_playing": True, "device": {"id": "device-cuisine"}}

    def test_lancer_spotify_depuis_cuisine_transfere_vers_enceinte(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._etat_lecture", side_effect=[
                    self.ETAT_EN_PAUSE_AILLEURS, self.ETAT_JOUE_EN_CUISINE]), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as transferer, \
                patch("tools.spotify._jouer_corps") as jouer, \
                patch("tools.spotify.time.sleep"), \
                patch("tools.spotify._ouvrir_application_spotify") as ouvrir:
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Je lance Spotify sur Jarvis Cuisine.")
        transferer.assert_called_once_with("device-cuisine", lecture=True)
        jouer.assert_not_called()
        ouvrir.assert_not_called()

    def test_lancer_spotify_relance_le_titre_si_l_enceinte_reste_muette(self):
        # Raspotify accepte le transfert (204) mais ne joue rien : « context is
        # not available ». Jarvis relance alors le titre dans son album.
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._etat_lecture",
                      return_value=self.ETAT_EN_PAUSE_AILLEURS), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)), \
                patch("tools.spotify._joue_sur", side_effect=[False, True]), \
                patch("tools.spotify._jouer_corps",
                      return_value=SimpleNamespace(status_code=204)) as jouer:
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Je lance Spotify sur Jarvis Cuisine.")
        jouer.assert_called_once_with("device-cuisine", {
            "context_uri": "spotify:album:A1",
            "offset": {"uri": "spotify:track:T1"},
            "position_ms": 61000,
        })

    def test_lancer_spotify_n_annonce_pas_un_succes_sans_musique(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._etat_lecture",
                      return_value=self.ETAT_EN_PAUSE_AILLEURS), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)), \
                patch("tools.spotify._joue_sur", return_value=False), \
                patch("tools.spotify._jouer_corps",
                      return_value=SimpleNamespace(status_code=204)):
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertTrue(resultat.startswith("Spotify n'a pas démarré sur Jarvis Cuisine"))
        self.assertNotIn("Je lance", resultat)

    def test_lancer_spotify_ne_touche_a_rien_si_la_cuisine_joue_deja(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._etat_lecture",
                      return_value=self.ETAT_JOUE_EN_CUISINE), \
                patch("tools.spotify._transferer_lecture") as transferer, \
                patch("tools.spotify._jouer_corps") as jouer:
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Spotify joue déjà sur Jarvis Cuisine.")
        transferer.assert_not_called()
        jouer.assert_not_called()

    def test_lancer_spotify_joue_la_playlist_par_defaut_de_la_piece(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._playlist_lancement",
                      return_value=("spotify:playlist:P9", "Chill")), \
                patch("tools.spotify._etat_lecture",
                      return_value=self.ETAT_EN_PAUSE_AILLEURS), \
                patch("tools.spotify._transferer_lecture") as transferer, \
                patch("tools.spotify._jouer_corps",
                      return_value=SimpleNamespace(status_code=204)) as jouer, \
                patch("tools.spotify._joue_sur", return_value=True) as verifier:
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Je lance ta playlist Chill sur Jarvis Cuisine.")
        jouer.assert_called_once_with("device-cuisine",
                                      {"context_uri": "spotify:playlist:P9"})
        verifier.assert_called_once_with("device-cuisine", attente=6.0)
        transferer.assert_not_called()

    def _lancer_playlist_aleatoire(self, total, activation):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._playlist_lancement",
                      return_value=("spotify:playlist:P9", "Chill")), \
                patch("tools.spotify._lancement_aleatoire", return_value=True), \
                patch("tools.spotify._etat_lecture", return_value={}), \
                patch("tools.spotify._nombre_titres", return_value=total), \
                patch("tools.spotify.random.randrange", return_value=42) as tirage, \
                patch("tools.spotify._jouer_corps",
                      return_value=SimpleNamespace(status_code=204)) as jouer, \
                patch("tools.spotify._joue_sur", return_value=True), \
                patch("tools.spotify._activer_aleatoire",
                      return_value=activation) as melanger:
            resultat = spotify.lancer_spotify(piece="cuisine")
        return resultat, jouer, melanger, tirage

    def test_playlist_par_defaut_demarre_au_hasard_en_aleatoire(self):
        resultat, jouer, melanger, tirage = self._lancer_playlist_aleatoire(
            1294, SimpleNamespace(status_code=204))

        self.assertEqual(resultat,
                         "Je lance ta playlist Chill en aléatoire sur Jarvis Cuisine.")
        tirage.assert_called_once_with(1294)
        jouer.assert_called_once_with("device-cuisine", {
            "context_uri": "spotify:playlist:P9", "offset": {"position": 42}})
        melanger.assert_called_once_with("device-cuisine")

    def test_aleatoire_refuse_n_empeche_pas_la_musique(self):
        resultat, _, melanger, _ = self._lancer_playlist_aleatoire(
            1294, SimpleNamespace(status_code=404))

        self.assertEqual(resultat, "Je lance ta playlist Chill sur Jarvis Cuisine.")
        melanger.assert_called_once_with("device-cuisine")

    def test_taille_inconnue_demarre_sans_position(self):
        _, jouer, _, tirage = self._lancer_playlist_aleatoire(
            None, SimpleNamespace(status_code=204))

        tirage.assert_not_called()
        jouer.assert_called_once_with("device-cuisine",
                                      {"context_uri": "spotify:playlist:P9"})

    def test_playlist_par_defaut_ne_coupe_pas_la_musique_en_cours(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._playlist_lancement",
                      return_value=("spotify:playlist:P9", "Chill")), \
                patch("tools.spotify._etat_lecture",
                      return_value=self.ETAT_JOUE_EN_CUISINE), \
                patch("tools.spotify._jouer_corps") as jouer:
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Spotify joue déjà sur Jarvis Cuisine.")
        jouer.assert_not_called()

    def test_playlist_par_defaut_muette_le_dit(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._playlist_lancement",
                      return_value=("spotify:playlist:P9", "Chill")), \
                patch("tools.spotify._etat_lecture", return_value={}), \
                patch("tools.spotify._jouer_corps",
                      return_value=SimpleNamespace(status_code=204)), \
                patch("tools.spotify._joue_sur", return_value=False):
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Ta playlist Chill n'a pas démarré sur Jarvis Cuisine.")

    def test_playlist_par_defaut_introuvable_reprend_la_derniere_musique(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine"}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._playlist_lancement", return_value=(None, "Chill")), \
                patch("tools.spotify._etat_lecture",
                      return_value=self.ETAT_EN_PAUSE_AILLEURS), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as transferer, \
                patch("tools.spotify._joue_sur", return_value=True):
            resultat = spotify.lancer_spotify(piece="cuisine")

        self.assertEqual(resultat, "Je n'ai pas trouvé ta playlist Chill, alors je "
                                   "reprends ta dernière musique sur Jarvis Cuisine.")
        transferer.assert_called_once_with("device-cuisine", lecture=True)


    def test_corps_de_reprise_garde_la_playlist_d_origine(self):
        etat = dict(self.ETAT_EN_PAUSE_AILLEURS,
                    context={"uri": "spotify:playlist:P1"})
        self.assertEqual(spotify._corps_reprise(etat), {
            "context_uri": "spotify:playlist:P1",
            "offset": {"uri": "spotify:track:T1"},
            "position_ms": 61000,
        })
        episode = {"item": {"uri": "spotify:episode:E1", "type": "episode"}}
        self.assertEqual(spotify._corps_reprise(episode),
                         {"uris": ["spotify:episode:E1"], "position_ms": 0})
        self.assertIsNone(spotify._corps_reprise({}))

    def test_joue_sur_attend_la_lecture_puis_abandonne(self):
        with patch("tools.spotify._etat_lecture", side_effect=[
                    {}, self.ETAT_JOUE_EN_CUISINE]), \
                patch("tools.spotify.time.sleep"):
            self.assertTrue(spotify._joue_sur("device-cuisine"))
        with patch("tools.spotify._etat_lecture",
                   return_value=self.ETAT_JOUE_EN_CUISINE), \
                patch("tools.spotify.time.monotonic", side_effect=[0.0, 5.0]), \
                patch("tools.spotify.time.sleep"):
            # Ça joue, mais sur un autre appareil que celui demandé.
            self.assertFalse(spotify._joue_sur("device-bureau"))

    def test_reprendre_sur_enceinte_inactive_transfere_d_abord(self):
        appareil = {
            "id": "device-cuisine", "name": "Jarvis Cuisine",
            "is_active": False,
        }
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._etat_lecture", side_effect=[
                    self.ETAT_EN_PAUSE_AILLEURS, self.ETAT_JOUE_EN_CUISINE]), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)) as transferer, \
                patch("tools.spotify.time.sleep"), \
                patch("tools.spotify._jouer_corps") as jouer:
            resultat = spotify.controler_spotify("reprendre", "cuisine")

        self.assertEqual(resultat, "Je reprends la musique.")
        transferer.assert_called_once_with("device-cuisine", lecture=True)
        jouer.assert_not_called()

    def test_reprendre_sans_musique_le_dit(self):
        appareil = {"id": "device-cuisine", "name": "Jarvis Cuisine", "is_active": True}
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._appareil_piece",
                      return_value=(appareil, "Jarvis Cuisine")), \
                patch("tools.spotify._etat_lecture", return_value={}), \
                patch("tools.spotify._transferer_lecture",
                      return_value=SimpleNamespace(status_code=204)), \
                patch("tools.spotify._joue_sur", return_value=False):
            resultat = spotify.controler_spotify("reprendre", "cuisine")

        self.assertTrue(resultat.startswith("La musique n'a pas repris sur Jarvis Cuisine"))

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
                   return_value="playlist-chill") as personnelle, \
                patch.object(spotify, "requests") as requetes:
            resultat = spotify._chercher_media("chill", "playlist")

        self.assertEqual(resultat, {
            "uri": "spotify:playlist:playlist-chill",
            "name": "chill",
        })
        personnelle.assert_called_once_with("chill", creer=False)
        requetes.get.assert_not_called()

    def test_spotify_connect_lance_le_resultat_exact(self):
        with patch("tools.spotify._configure", return_value=True), \
                patch("tools.spotify._chercher_media", return_value={
                    "uri": "spotify:track:abc", "name": "Blinding Lights"}), \
                patch("tools.spotify._demarrer_lecture",
                      return_value=SimpleNamespace(status_code=204)), \
                patch.object(spotify.os, "startfile") as startfile:
            resultat = spotify.lire_spotify("Blinding Lights")

        self.assertEqual(resultat, "Je lance « Blinding Lights » sur Spotify.")
        startfile.assert_not_called()

    def test_spotify_sans_oauth_ouvre_une_recherche_locale(self):
        with patch("tools.spotify._configure", return_value=False), \
                patch("core.poste_distant.executer_principal", return_value=None), \
                patch.object(spotify.os, "startfile") as startfile:
            resultat = spotify.lire_spotify("Daft Punk")

        self.assertIn("recherche Spotify", resultat)
        startfile.assert_called_once_with("spotify:search:Daft%20Punk")

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


class PlaylistLancementTests(unittest.TestCase):
    """La vraie lecture du réglage, sans le patch par défaut de MediaRoutingTests."""

    def test_playlist_de_lancement_lue_dans_la_configuration(self):
        with patch("tools.spotify.reglage", return_value=" Chill "), \
                patch("tools.spotify._playlist_id", return_value="P9") as chercher:
            self.assertEqual(spotify._playlist_lancement(),
                             ("spotify:playlist:P9", "Chill"))
        chercher.assert_called_once_with("Chill", creer=False)
        with patch("tools.spotify.reglage", return_value=""), \
                patch("tools.spotify._playlist_id") as chercher:
            self.assertEqual(spotify._playlist_lancement(), (None, ""))
        chercher.assert_not_called()

    def test_nombre_de_titres_lu_sur_l_endpoint_items(self):
        # /playlists/{id}/tracks répond 403 depuis 2026 ; seul /items fonctionne.
        reponse = SimpleNamespace(status_code=200, json=lambda: {"total": 1294})
        with patch("tools.spotify._h", return_value={}), \
                patch("tools.spotify.requests") as api:
            api.get.return_value = reponse
            self.assertEqual(spotify._nombre_titres("spotify:playlist:P9"), 1294)
        self.assertTrue(api.get.call_args.args[0].endswith("/playlists/P9/items"))
        with patch("tools.spotify._h", return_value={}), \
                patch("tools.spotify.requests") as api:
            api.get.return_value = SimpleNamespace(status_code=403, json=lambda: {})
            self.assertIsNone(spotify._nombre_titres("spotify:playlist:P9"))


class AjoutPlaylistTests(unittest.TestCase):
    """Ajout à une playlist : uniquement l'endpoint /items, jamais d'appel réel."""

    URI = "spotify:track:T1"

    @staticmethod
    def _page(items, suivante=None):
        return SimpleNamespace(status_code=200,
                               json=lambda: {"items": items, "next": suivante})

    def _deja_present(self, *pages):
        with patch("tools.spotify._h", return_value={}), \
                patch("tools.spotify.requests") as api:
            api.get.side_effect = list(pages)
            present = spotify._deja_present("P9", self.URI)
        return present, api

    def test_doublon_cherche_sur_l_endpoint_items(self):
        present, api = self._deja_present(
            self._page([{"item": {"uri": "spotify:track:autre"}},
                        {"item": {"uri": self.URI}}]))
        self.assertTrue(present)
        url = api.get.call_args.args[0]
        self.assertIn("/playlists/P9/items?", url)
        self.assertNotIn("/tracks", url)
        # /items plafonne à 50 éléments par page (400 au-delà).
        self.assertIn("limit=50", url)

    def test_doublon_lu_aussi_sous_l_ancien_champ_track(self):
        present, _ = self._deja_present(self._page([{"track": {"uri": self.URI}}]))
        self.assertTrue(present)

    def test_doublon_trouve_sur_une_page_suivante(self):
        suivante = "https://api.spotify.com/v1/playlists/P9/items?offset=50&limit=50"
        present, api = self._deja_present(
            self._page([{"item": {"uri": "spotify:track:autre"}}], suivante),
            self._page([{"item": {"uri": self.URI}}]))
        self.assertTrue(present)
        self.assertEqual(api.get.call_count, 2)
        self.assertEqual(api.get.call_args.args[0], suivante)

    def test_titre_absent_ou_element_vide_n_est_pas_un_doublon(self):
        present, _ = self._deja_present(
            self._page([{"item": None}, {"item": {"uri": "spotify:track:autre"}}]))
        self.assertFalse(present)

    def test_erreur_reseau_n_empeche_pas_l_ajout(self):
        with patch("tools.spotify._h", return_value={}), \
                patch("tools.spotify.requests") as api:
            api.get.side_effect = OSError("réseau coupé")
            self.assertFalse(spotify._deja_present("P9", self.URI))

    def _ajouter(self, deja_present):
        with patch("tools.spotify._chercher_uri", return_value=self.URI), \
                patch("tools.spotify._playlist_id", return_value="P9"), \
                patch("tools.spotify._deja_present", return_value=deja_present), \
                patch("tools.spotify.reglage", return_value="Jarvis Finds"), \
                patch("tools.spotify._h", return_value={}), \
                patch("tools.spotify.requests") as api:
            api.post.return_value = SimpleNamespace(
                status_code=201, raise_for_status=lambda: None,
                json=lambda: {"snapshot_id": "abc"})
            message = spotify._ajouter_titre("Titre", "Artiste")
        return message, api

    def test_ajout_poste_sur_l_endpoint_items(self):
        message, api = self._ajouter(deja_present=False)
        self.assertEqual(message, "Ajoutée à Jarvis Finds : Titre de Artiste.")
        api.post.assert_called_once()
        self.assertTrue(api.post.call_args.args[0].endswith("/playlists/P9/items"))
        self.assertEqual(json.loads(api.post.call_args.kwargs["data"]),
                         {"uris": [self.URI]})

    def test_doublon_n_est_pas_ajoute(self):
        message, api = self._ajouter(deja_present=True)
        self.assertEqual(message, "« Titre » est déjà dans la playlist.")
        api.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
