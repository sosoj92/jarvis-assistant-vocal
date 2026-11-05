"""Scripts PowerShell d'exploitation, verifies sans rien lancer de reel.

- synchroniser_serveur_h24.ps1 : redemarrer_jarvis lit la tache modele AVANT
  d'arreter quoi que ce soit ; activer_brief garde les fins de ligne CRLF ;
- start_hermes_server_tunnel.ps1 : le tunnel n'est declare actif qu'une fois le
  port 8642 ouvert par ssh (plus de « vivant a 2 s ») ;
- autostart_install.ps1 : le .cmd de repli garde un chemin accentue.

Aucun ssh, aucune tache planifiee : le Python d'activer_brief tourne dans un
dossier temporaire, et seul le bloc d'ecriture du .cmd est execute (dans tmp).
"""
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SYNCHRO = (SCRIPTS / "synchroniser_serveur_h24.ps1").read_text(encoding="utf-8")
TUNNEL = (SCRIPTS / "start_hermes_server_tunnel.ps1").read_text(encoding="utf-8")
AUTOSTART = (SCRIPTS / "autostart_install.ps1").read_text(encoding="utf-8")
POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None


def _action(nom):
    """Bloc PowerShell d'une action, jusqu'a l'action suivante."""
    debut = SYNCHRO.index(f"if ($Action -eq '{nom}')")
    fin = SYNCHRO.find("\nif ($Action -eq", debut + 1)
    return SYNCHRO[debut:fin if fin != -1 else None]


def _code_distant(bloc):
    """Code envoye au serveur : contenu du here-string @"..."@, une fois developpe."""
    code = re.search(r'Invoke-ServeurH24 @"\n(.*?)\n"@', bloc, re.S).group(1)
    return code.replace("`$", "$").replace("$projetLitteral", "'C:\\depot'")


def _dossier_temporaire(test):
    dossier = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, dossier, True)
    return dossier


def _erreurs_syntaxe(test, chemin):
    """Erreurs du parseur PowerShell (analyse seule, rien n'est execute)."""
    commande = ("$t = $null; $e = $null; "
                "[void][System.Management.Automation.Language.Parser]::ParseFile("
                "$env:FICHIER_A_ANALYSER, [ref]$t, [ref]$e); "
                "$e | ForEach-Object { $_.Message }")
    r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", commande],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "FICHIER_A_ANALYSER": str(chemin)})
    test.assertEqual(r.returncode, 0, r.stderr)
    return r.stdout.strip()


class RedemarrerJarvisTest(unittest.TestCase):
    def test_tache_modele_lue_avant_tout_arret(self):
        code = _code_distant(_action("redemarrer_jarvis"))
        lecture = code.index("Get-ScheduledTask -TaskName 'Jarvis - Signal Matin'")
        self.assertLess(lecture, code.index("Stop-Process"))
        ligne = code[lecture:code.index("\n", lecture)]
        self.assertIn("-ErrorAction SilentlyContinue", ligne)
        garde = code[lecture:code.index("Stop-Process")]
        self.assertIn("if (-not $modele) { throw", garde)
        self.assertEqual(code.count("Get-ScheduledTask -TaskName 'Jarvis - Signal Matin'"), 1)
        self.assertIn("-Principal $modele.Principal", code)


class ActiverBriefTest(unittest.TestCase):
    """Le Python d'activer_brief, execute sur un faux config.yaml dans tmp."""

    def setUp(self):
        bloc = _action("activer_brief")
        py = re.search(r"\$py = @'\n(.*?)\n'@", bloc, re.S).group(1)
        # La fin importe core.cloud, qui lirait le vrai config.yaml : on la retire.
        self.py = py[:py.index("from core import cloud")]
        racine = _dossier_temporaire(self)
        self.depot = racine / "depot"
        self.depot.mkdir()
        self.racine = racine
        (racine / "activer_brief.py").write_text(self.py, encoding="utf-8")

    def _lancer(self, contenu):
        (self.depot / "config.yaml").write_bytes(contenu)
        r = subprocess.run([sys.executable, str(self.racine / "activer_brief.py")],
                           cwd=self.depot, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return (self.depot / "config.yaml").read_bytes()

    def test_crlf_conserve_dans_la_section(self):
        avant = (b"mode: local\r\n# commentaire garde\r\nsignal_matin:\r\n"
                 b"  actif: true\r\n  brief_tech: false\r\naudio:\r\n  micro: null\r\n")
        apres = self._lancer(avant)
        self.assertEqual(apres.count(b"\n"), apres.count(b"\r\n"))   # aucun LF seul
        self.assertIn(b"# commentaire garde\r\n", apres)
        conf = yaml.safe_load(apres)
        self.assertEqual(conf["signal_matin"], {"actif": True, "brief_tech": True,
                                                "modele_brief": "gpt-5.6-terra"})
        self.assertEqual(conf["audio"], {"micro": None})
        copies = list(self.racine.glob("jarvis-sauvegarde-config-*/config.yaml"))
        self.assertEqual([c.read_bytes() for c in copies], [avant])

    def test_crlf_conserve_quand_la_section_est_ajoutee(self):
        apres = self._lancer(b"mode: local\r\naudio:\r\n  micro: null\r\n")
        self.assertEqual(apres.count(b"\n"), apres.count(b"\r\n"))
        self.assertTrue(yaml.safe_load(apres)["signal_matin"]["brief_tech"])

    def test_lf_reste_lf(self):
        apres = self._lancer(b"mode: local\nsignal_matin:\n  actif: true\n")
        self.assertNotIn(b"\r", apres)
        self.assertEqual(yaml.safe_load(apres)["signal_matin"]["modele_brief"],
                         "gpt-5.6-terra")


class TunnelHermesTest(unittest.TestCase):
    def test_delai_de_connexion_borne(self):
        self.assertIn('"-o", "ConnectTimeout=10"', TUNNEL)
        self.assertIn('"-o", "ExitOnForwardFailure=yes"', TUNNEL)

    def test_actif_seulement_quand_ssh_ecoute_sur_8642(self):
        lancement = TUNNEL.index("Start-Process -FilePath")
        suite = TUNNEL[lancement:]
        attente = suite.index("Get-NetTCPConnection -State Listen -LocalPort 8642")
        self.assertIn("$_.OwningProcess -eq $process.Id", suite)
        self.assertLess(attente, suite.index("Tunnel Hermes actif"))
        # Echec : ssh arrete puis erreur levee, pour que la boucle de demarrage reessaie.
        echec = suite[suite.index("if (-not $ecoute -or $process.HasExited)"):]
        self.assertLess(echec.index("Stop-Process -Id $process.Id"), echec.index("throw"))
        self.assertNotIn("Start-Sleep -Seconds 2\nif ($process.HasExited)", TUNNEL)


class AutostartTest(unittest.TestCase):
    def test_plus_d_ecriture_ascii(self):
        self.assertNotIn("-Encoding ascii $cmd", AUTOSTART)
        self.assertIn("Set-Content -Encoding Oem $cmd", AUTOSTART)

    def _ecrire_cmd(self, nom_profil):
        """Execute UNIQUEMENT le bloc d'ecriture du .cmd, dossier Demarrage = tmp."""
        dossier = _dossier_temporaire(self)
        script = dossier / nom_profil / "jarvis-vocal" / "scripts" / "demarrer_jarvis_complet.ps1"
        bloc = AUTOSTART[AUTOSTART.index('$cmd = Join-Path $startup "JarvisAutostart.cmd"'):]
        harnais = dossier / "harnais.ps1"
        entete = (f"$startup = '{dossier}'\n"
                  f"$script = '{script}'\n")
        harnais.write_text(entete + bloc, encoding="utf-8-sig")   # BOM : PS 5.1 lit l'UTF-8
        r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                            "Bypass", "-File", str(harnais)],
                           capture_output=True, timeout=60)
        return r.returncode, dossier / "JarvisAutostart.cmd", str(script)

    @unittest.skipUnless(POWERSHELL, "PowerShell Windows absent")
    def test_chemin_accentue_conserve(self):
        code, cmd, script = self._ecrire_cmd("Hélène")
        self.assertEqual(code, 0)
        page_oem = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        self.assertIn(script, cmd.read_bytes().decode(page_oem))

    @unittest.skipUnless(POWERSHELL, "PowerShell Windows absent")
    def test_caractere_illisible_par_cmd_refuse(self):
        if ctypes.windll.kernel32.GetOEMCP() == 65001:
            self.skipTest("page OEM UTF-8 : tout caractere est representable")
        code, cmd, _ = self._ecrire_cmd("漢字")
        self.assertEqual(code, 1)
        self.assertFalse(cmd.exists())


@unittest.skipUnless(POWERSHELL, "PowerShell Windows absent")
class SyntaxePowerShellTest(unittest.TestCase):
    def test_scripts_sans_erreur_de_syntaxe(self):
        for nom in ("synchroniser_serveur_h24.ps1", "start_hermes_server_tunnel.ps1",
                    "autostart_install.ps1"):
            with self.subTest(script=nom):
                self.assertEqual(_erreurs_syntaxe(self, SCRIPTS / nom), "")

    def test_code_distant_sans_erreur_de_syntaxe(self):
        for action in ("redemarrer_jarvis", "activer_brief"):
            with self.subTest(action=action):
                chemin = _dossier_temporaire(self) / f"{action}.ps1"
                chemin.write_text(_code_distant(_action(action)), encoding="utf-8-sig")
                self.assertEqual(_erreurs_syntaxe(self, chemin), "")


if __name__ == "__main__":
    unittest.main()
