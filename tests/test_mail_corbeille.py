"""Messagerie : la corbeille vise le mail de la liste entendue, verifie le retour
du serveur, et les connexions ont un delai d'attente. IMAP/SMTP simules."""
import unittest
from unittest.mock import MagicMock, patch

from core import registre

registre.charger_outils()

from tools import finances, mail  # noqa: E402


class FausseBoite:
    """Faux IMAP4_SSL : une boite partagee {uid: (expediteur, objet)}."""
    boite = {}
    store_reponse = "OK"
    stores = []
    instances = []

    def __init__(self, serveur, port=993, timeout=None, **_):
        self.timeout = timeout
        self.deconnecte = False
        FausseBoite.instances.append(self)

    def login(self, *_):
        return "OK", [b""]

    def select(self, *_):
        return "OK", [b""]

    def uid(self, commande, *args):
        if commande == "search":
            return "OK", [b" ".join(sorted(self.boite))]
        if commande == "fetch":
            uid = args[0]
            if uid not in self.boite:
                return "OK", [None]
            exp, sujet = self.boite[uid]
            entete = f"From: {exp}\r\nSubject: {sujet}\r\n\r\n".encode()
            return "OK", [(b"1 (UID " + uid + b")", entete), b")"]
        if commande == "store":
            FausseBoite.stores.append(args[0])
            return self.store_reponse, [b""]
        raise AssertionError(commande)

    def logout(self):
        self.deconnecte = True


class _Base(unittest.TestCase):
    def setUp(self):
        FausseBoite.boite = {b"101": ("Promo <p@x.example>", "Soldes"),
                             b"102": ("Paul <paul@x.example>", "Diner"),
                             b"103": ("Banque <b@x.example>", "Releve")}
        FausseBoite.store_reponse = "OK"
        FausseBoite.stores = []
        FausseBoite.instances = []
        self._patches = [
            patch.object(mail, "MAIL_ADRESSE", "moi@x.example"),
            patch.object(mail, "MAIL_MOT_DE_PASSE_APP", "factice"),
            patch.object(mail.imaplib, "IMAP4_SSL", FausseBoite),
            patch.object(mail, "_DERNIERS_MAILS", []),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()


class ListeMemoriseeTest(_Base):
    def test_lecture_de_fond_ne_change_pas_la_cible(self):
        self.assertIn("3. De Promo", mail.lire_mails(5))
        FausseBoite.boite[b"104"] = ("Nouveau <n@x.example>", "Bonjour")
        fond = mail.lire_mails(3, memoriser=False)
        self.assertIn("1. De Nouveau", fond)
        self.assertEqual(mail.mettre_a_la_corbeille(3),
                         "Mail mis a la corbeille, recuperable pendant trente jours.")
        self.assertEqual(FausseBoite.stores, [b"101"])

    def test_liste_memorisee_avec_expediteur_et_objet(self):
        mail.lire_mails(5)
        self.assertEqual(mail._liste_memorisee()[0], (b"103", "Banque", "Releve"))

    def test_mail_disparu_pas_de_store(self):
        mail.lire_mails(5)
        del FausseBoite.boite[b"101"]
        resultat = mail.mettre_a_la_corbeille(3)
        self.assertIn("n'est plus", resultat)
        self.assertEqual(FausseBoite.stores, [])

    def test_objet_different_pas_de_store(self):
        mail.lire_mails(5)
        FausseBoite.boite[b"101"] = ("Autre <a@x.example>", "Autre chose")
        self.assertIn("ne correspond plus", mail.mettre_a_la_corbeille(3))
        self.assertEqual(FausseBoite.stores, [])

    def test_store_refuse_annonce_un_echec(self):
        mail.lire_mails(5)
        FausseBoite.store_reponse = "NO"
        resultat = mail.mettre_a_la_corbeille(1)
        self.assertTrue(resultat.startswith("Impossible de mettre a la corbeille"))


class DelaiTest(_Base):
    def test_imap_avec_delai_et_deconnexion_sur_erreur(self):
        mail.lire_mails(5)
        self.assertTrue(FausseBoite.instances)
        for imap in FausseBoite.instances:
            self.assertEqual(imap.timeout, mail.DELAI_MAIL_S)
        FausseBoite.instances = []
        with patch.object(FausseBoite, "uid", side_effect=OSError("coupure")):
            self.assertIn("Impossible", mail.lire_mails(5))
        self.assertTrue(FausseBoite.instances[0].deconnecte)

    def test_smtp_avec_delai(self):
        smtp = MagicMock()
        with patch.object(mail.smtplib, "SMTP_SSL", return_value=smtp) as ouvrir, \
                patch.dict(mail._BROUILLON, {"destinataire": "a@x.example", "sujet": "S",
                                             "corps": "C"}, clear=True):
            self.assertIn("Mail envoye", mail.envoyer_mail())
        self.assertEqual(ouvrir.call_args.kwargs.get("timeout"), mail.DELAI_MAIL_S)

    def test_finances_avec_delai(self):
        with patch.object(finances.imaplib, "IMAP4_SSL", side_effect=OSError("stop")) as ouvrir:
            with self.assertRaises(OSError):
                finances._scanner(1)
        self.assertEqual(ouvrir.call_args.kwargs.get("timeout"), mail.DELAI_MAIL_S)


if __name__ == "__main__":
    unittest.main()
