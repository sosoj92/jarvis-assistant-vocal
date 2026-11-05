"""Gardes HTTP réelles du HUD (_Poignee), sans réseau : faux socket en mémoire.

Chaque requête traverse le vrai cycle de BaseHTTPRequestHandler (lecture de la ligne
de requête, des en-têtes, do_GET/do_POST, réponse). _appliquer_controle est remplacé
par un mock : aucun test ne touche config.yaml ni la voix.
"""
import io
import json
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import hud

LOCAL = ("127.0.0.1", 50123)


class _Lecture(io.BytesIO):
    """Requête entrante ; retient jusqu'où le serveur l'a lue avant de la fermer."""
    position_finale = None

    def close(self):
        if not self.closed:
            self.position_finale = self.tell()
        super().close()


class _FauxSocket:
    def __init__(self, brut, echec_apres=None):
        self.lecture = _Lecture(brut)
        self.recu = bytearray()
        self.envois = 0
        self.echec_apres = echec_apres       # nb d'envois réussis avant « onglet fermé »

    def makefile(self, mode, *args, **kwargs):
        return self.lecture

    def sendall(self, donnees):
        self.envois += 1
        if self.echec_apres is not None and self.envois > self.echec_apres:
            raise BrokenPipeError("onglet ferme")
        self.recu += donnees

    def settimeout(self, _):
        pass


def _requete(methode, chemin, entetes, corps=b""):
    lignes = [f"{methode} {chemin} HTTP/1.1"] + [f"{k}: {v}" for k, v in entetes.items()]
    entete = ("\r\n".join(lignes) + "\r\n\r\n").encode("latin-1")
    return entete, entete + corps


def _envoyer(methode, chemin, entetes, corps=b"", client=LOCAL, echec_apres=None):
    """-> (statut, corps JSON ou None, octets de la requête lus, longueur des en-têtes)."""
    entete, brut = _requete(methode, chemin, entetes, corps)
    sock = _FauxSocket(brut, echec_apres)
    hud._Poignee(sock, client, None)
    reponse = bytes(sock.recu)
    statut = int(reponse.split(b" ", 2)[1]) if reponse else None
    tete, _, contenu = reponse.partition(b"\r\n\r\n")
    donnees = None
    if b"application/json" in tete and contenu:
        donnees = json.loads(contenu.decode("utf-8"))
    return statut, donnees, sock.lecture.position_finale, len(entete)


def _entetes_post(corps, **remplacements):
    entetes = {"Host": f"127.0.0.1:{hud.PORT}", "X-Jarvis-HUD": "1",
               "Content-Type": "application/json", "Content-Length": str(len(corps))}
    for cle, valeur in remplacements.items():
        cle = cle.replace("_", "-")
        if valeur is None:
            entetes.pop(cle, None)
        else:
            entetes[cle] = valeur
    return entetes


CORPS = json.dumps({"action": "mode", "valeur": "hybride"}).encode("utf-8")


class HudPostTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(hud, "_appliquer_controle",
                         MagicMock(return_value={"ok": True, "message": "ok"}))
        self.controle = p.start()
        self.addCleanup(p.stop)

    def post(self, entetes, corps=CORPS, client=LOCAL):
        return _envoyer("POST", "/api/controle", entetes, corps, client)

    def test_requete_legitime_appliquee_une_fois(self):
        statut, donnees, lus, entete = self.post(_entetes_post(CORPS))
        self.assertEqual(statut, 200)
        self.assertTrue(donnees["ok"])
        self.controle.assert_called_once_with({"action": "mode", "valeur": "hybride"})
        self.assertEqual(lus, entete + len(CORPS))

    def test_refus_de_l_action_renvoie_400(self):
        self.controle.return_value = {"ok": False, "message": "Valeur refusee."}
        statut, donnees, _, _ = self.post(_entetes_post(CORPS))
        self.assertEqual(statut, 400)
        self.assertFalse(donnees["ok"])

    def test_requetes_refusees_sans_appliquer_ni_lire_le_corps(self):
        cas = {
            "sans X-Jarvis-HUD": (_entetes_post(CORPS, X_Jarvis_HUD=None), LOCAL, 403),
            "X-Jarvis-HUD faux": (_entetes_post(CORPS, X_Jarvis_HUD="0"), LOCAL, 403),
            "Host externe": (_entetes_post(CORPS, Host="evil.example:8770"), LOCAL, 403),
            "sans Host": (_entetes_post(CORPS, Host=None), LOCAL, 403),
            "X-Forwarded-For": (_entetes_post(CORPS, X_Forwarded_For="203.0.113.7"),
                                LOCAL, 403),
            "X-Forwarded-Host": (_entetes_post(CORPS, X_Forwarded_Host="evil.example"),
                                 LOCAL, 403),
            "client du LAN": (_entetes_post(CORPS), ("192.168.1.20", 50123), 403),
            "text/plain": (_entetes_post(CORPS, Content_Type="text/plain"), LOCAL, 415),
            "text/plain; application/json": (
                _entetes_post(CORPS, Content_Type="text/plain; application/json"), LOCAL, 415),
            "sans Content-Type": (_entetes_post(CORPS, Content_Type=None), LOCAL, 415),
            "taille nulle": (_entetes_post(CORPS, Content_Length="0"), LOCAL, 400),
            "taille negative": (_entetes_post(CORPS, Content_Length="-5"), LOCAL, 400),
            "taille 8193": (_entetes_post(CORPS, Content_Length="8193"), LOCAL, 400),
            "taille non numerique": (_entetes_post(CORPS, Content_Length="abc"), LOCAL, 400),
            "sans Content-Length": (_entetes_post(CORPS, Content_Length=None), LOCAL, 400),
        }
        for nom, (entetes, client, attendu) in cas.items():
            with self.subTest(nom):
                statut, donnees, lus, entete = self.post(entetes, client=client)
                self.assertEqual(statut, attendu)
                self.assertFalse(donnees["ok"])
                self.assertEqual(lus, entete, "le corps ne doit pas etre lu")
        self.controle.assert_not_called()

    def test_taille_maximale_acceptee(self):
        corps = json.dumps({"action": "mode", "valeur": "hybride",
                            "remplissage": "x" * 8000}).encode("utf-8")
        corps += b" " * (8192 - len(corps))
        statut, _, _, _ = self.post(_entetes_post(corps), corps=corps)
        self.assertEqual(statut, 200)
        self.controle.assert_called_once()

    def test_json_invalide_jamais_applique(self):
        corps = b"{pas du json"
        statut, donnees, _, _ = self.post(_entetes_post(corps), corps=corps)
        self.assertGreaterEqual(statut, 400)
        self.assertFalse(donnees["ok"])
        self.controle.assert_not_called()

    def test_autre_chemin_404(self):
        statut, _, _, _ = _envoyer("POST", "/api/autre", _entetes_post(CORPS), CORPS)
        self.assertEqual(statut, 404)
        self.controle.assert_not_called()


class HudGetTests(unittest.TestCase):
    def get(self, chemin, client=LOCAL, **entetes):
        base = {"Host": f"127.0.0.1:{hud.PORT}"}
        base.update({k.replace("_", "-"): v for k, v in entetes.items()})
        return _envoyer("GET", chemin, base, client=client)

    def test_flux_et_controle_refuses_hors_local(self):
        with patch.object(hud, "_etat_controles") as etat:
            for chemin in ("/flux", "/api/controle", "/"):
                for nom, client, entetes in (
                        ("Host externe", LOCAL, {"Host": "evil.example:8770"}),
                        ("X-Forwarded-For", LOCAL, {"X_Forwarded_For": "203.0.113.7"}),
                        ("client du LAN", ("192.168.1.20", 50123), {})):
                    with self.subTest(chemin=chemin, cas=nom):
                        avant = len(hud._CLIENTS)
                        statut, donnees, _, _ = self.get(chemin, client=client, **entetes)
                        self.assertEqual(statut, 403)
                        self.assertFalse(donnees["ok"])
                        self.assertEqual(len(hud._CLIENTS), avant)
        etat.assert_not_called()

    def test_etat_controles_local(self):
        with patch.object(hud, "_etat_controles", return_value={"ok": True}) as etat:
            statut, donnees, _, _ = self.get("/api/controle")
        self.assertEqual((statut, donnees), (200, {"ok": True}))
        etat.assert_called_once_with()

    def test_flux_libere_le_client_quand_l_onglet_se_ferme(self):
        avant = set(hud._CLIENTS)
        with patch.object(hud, "_BATTEMENT", 0.05):
            # en-têtes envoyés, puis la première écriture d'événement échoue
            statut, _, _, _ = _envoyer("GET", "/flux", {"Host": f"127.0.0.1:{hud.PORT}"},
                                       echec_apres=1)
        self.assertEqual(statut, 200)
        self.assertEqual(set(hud._CLIENTS), avant)

    def test_chemin_inconnu_404(self):
        statut, _, _, _ = self.get("/inconnu")
        self.assertEqual(statut, 404)

    def test_sortie_du_flux_apres_eviction(self):
        # _diffuser evince une file pleine : le flux doit se fermer (EventSource se
        # reconnecte) au lieu de rester ouvert sur des battements.
        avant = set(hud._CLIENTS)
        fil_flux = threading.Thread(
            target=_envoyer, args=("GET", "/flux", {"Host": f"127.0.0.1:{hud.PORT}"}),
            daemon=True)
        with patch.object(hud, "_BATTEMENT", 0.05):
            fil_flux.start()
            limite = time.monotonic() + 2
            nouveaux = set()
            while not nouveaux and time.monotonic() < limite:
                time.sleep(0.01)
                nouveaux = set(hud._CLIENTS) - avant
            self.assertEqual(len(nouveaux), 1)
            with hud._VERROU:
                hud._CLIENTS.discard(nouveaux.pop())     # comme _diffuser sur queue.Full
            fil_flux.join(timeout=2)
        self.assertFalse(fil_flux.is_alive())
        self.assertEqual(set(hud._CLIENTS), avant)


class HudServeurTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(socket, "SO_EXCLUSIVEADDRUSE"), "Windows seulement")
    def test_second_serveur_sur_le_meme_port_refuse(self):
        premier = hud._Serveur(("127.0.0.1", 0), hud._Poignee)
        try:
            port = premier.server_address[1]
            with self.assertRaises(OSError):
                hud._Serveur(("127.0.0.1", port), hud._Poignee)
        finally:
            premier.server_close()

    def test_demarrer_signale_le_port_occupe(self):
        with patch.object(hud, "_SERVEUR", None), \
                patch.object(hud, "_Serveur", side_effect=OSError("occupe")), \
                patch("builtins.print") as afficher:
            with self.assertRaises(OSError):
                hud.demarrer(ouvrir=False, tableau_local=False)
        self.assertIn("port", afficher.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
