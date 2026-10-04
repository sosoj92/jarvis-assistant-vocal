[CmdletBinding()]
param(
    [ValidateSet('etat', 'mettre_a_jour', 'sauvegarder_et_mettre_a_jour', 'tester_signal_matin', 'verifier_rendu', 'definir_heure', 'etat_hermes', 'modele_hermes_vm', 'tester_hermes_contexte', 'modifications', 'lignes_uniques', 'etat_liseuse', 'mettre_a_jour_liseuse', 'activer_brief', 'tester_brief', 'derniere_edition', 'processus', 'lancement_jarvis', 'etat_agent_bureau', 'redemarrer_jarvis', 'journal_postes', 'routes_lan')]
    [string]$Action = 'etat',

    [string]$Configuration = '',

    # Utilise uniquement par definir_heure : nouvelle heure quotidienne HH:mm.
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = '',

    # Facultatif avec definir_heure : duree maximale d'execution de la tache.
    [ValidateRange(0, 120)]
    [int]$DureeMinutes = 0
)

$ErrorActionPreference = 'Stop'

if (-not $Configuration) {
    $Configuration = Join-Path $PSScriptRoot '..\notes\_serveur_h24.json'
}
$cheminConfiguration = [IO.Path]::GetFullPath($Configuration)
if (-not (Test-Path -LiteralPath $cheminConfiguration)) {
    throw "Configuration privee absente : $cheminConfiguration"
}

$conf = Get-Content -LiteralPath $cheminConfiguration -Raw |
    ConvertFrom-Json
foreach ($champ in @('host', 'user', 'identity_file', 'project', 'printer')) {
    $propriete = $conf.PSObject.Properties[$champ]
    if (-not $propriete -or -not $propriete.Value) {
        throw "Champ manquant dans la configuration privee : $champ"
    }
}

$hote = [string]$conf.host
$utilisateur = [string]$conf.user
$identite = [Environment]::ExpandEnvironmentVariables(
    [string]$conf.identity_file
)
$projet = [string]$conf.project
$imprimante = [string]$conf.printer

if ($hote -notmatch '^[A-Za-z0-9.:-]+$') {
    throw 'Hote SSH invalide.'
}
if ($utilisateur -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'Utilisateur SSH invalide.'
}
if (-not (Test-Path -LiteralPath $identite)) {
    throw "Cle SSH absente : $identite"
}

function Convertir-CommandeDistante([string]$Code) {
    [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Code))
}

function Invoke-ServeurH24([string]$Code) {
    $Code = "`$ProgressPreference = 'SilentlyContinue'`r`n" + $Code
    $encode = Convertir-CommandeDistante $Code
    $cible = "${utilisateur}@${hote}"
    & ssh.exe `
        -o BatchMode=yes `
        -o ConnectTimeout=10 `
        -i $identite `
        $cible `
        powershell.exe -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand $encode
    if ($LASTEXITCODE -ne 0) {
        throw "Commande distante echouee (code $LASTEXITCODE)."
    }
}

function Convertir-LitteralPowerShell([string]$Valeur) {
    "'" + $Valeur.Replace("'", "''") + "'"
}

$projetLitteral = Convertir-LitteralPowerShell $projet
$imprimanteLitteral = Convertir-LitteralPowerShell $imprimante

if ($Action -eq 'etat') {
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
Write-Output ('machine=' + `$env:COMPUTERNAME)
Write-Output ('jarvis=' + (Test-Path -LiteralPath `$repo))
if (Test-Path -LiteralPath `$repo) {
    Write-Output ('branche=' + (git -C `$repo branch --show-current))
    Write-Output ('commit=' + (git -C `$repo rev-parse --short HEAD))
    `$modifications = @(git -C `$repo status --short --untracked-files=no)
    Write-Output ('modifications=' + `$modifications.Count)
}
`$tache = Get-ScheduledTask -TaskName 'Jarvis - Signal Matin' -ErrorAction SilentlyContinue
Write-Output ('tache_signal_matin=' + [bool]`$tache)
if (`$tache) {
    `$info = Get-ScheduledTaskInfo -TaskName 'Jarvis - Signal Matin'
    Write-Output ('dernier_resultat=' + `$info.LastTaskResult)
    Write-Output ('prochaine_execution=' + `$info.NextRunTime.ToString('s'))
}
`$file = Get-Printer -Name $imprimanteLitteral -ErrorAction SilentlyContinue
Write-Output ('imprimante=' + [bool]`$file)
"@
    exit 0
}

if ($Action -eq 'mettre_a_jour') {
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
if (-not (Test-Path -LiteralPath `$repo)) {
    throw 'Depot Jarvis introuvable sur le serveur.'
}
`$modifications = @(git -C `$repo status --porcelain --untracked-files=no)
if (`$modifications.Count -gt 0) {
    Write-Output 'Mise a jour refusee : changements locaux presents sur le serveur.'
    `$modifications
    exit 3
}
git -C `$repo fetch origin
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
git -C `$repo checkout main
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
git -C `$repo pull --ff-only origin main
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
Write-Output ('Serveur synchronise sur ' + (git -C `$repo rev-parse --short HEAD))
"@
    exit 0
}

if ($Action -eq 'modifications') {
    # Lecture seule : noms des fichiers modifies sur le serveur et comparaison avec
    # la version publiee (origin/main). Aucun contenu n'est affiche, rien n'est ecrase.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
git -C `$repo fetch -q origin
`$lignes = @(git -C `$repo status --porcelain --untracked-files=no)
Write-Output ('commit_local=' + (git -C `$repo rev-parse --short HEAD) + ' origin_main=' + (git -C `$repo rev-parse --short origin/main))
foreach (`$ligne in `$lignes) {
    `$fichier = `$ligne.Substring(3)
    git -C `$repo diff --quiet origin/main -- `$fichier
    `$verdict = if (`$LASTEXITCODE -eq 0) { 'IDENTIQUE a origin/main' } else { 'DIFFERE de origin/main' }
    `$taille = (git -C `$repo diff --shortstat HEAD -- `$fichier)
    Write-Output (`$ligne.Substring(0, 2) + ' ' + `$fichier + ' | ' + `$verdict + ' |' + `$taille)
}
"@
    exit 0
}

if ($Action -eq 'sauvegarder_et_mettre_a_jour') {
    # Les modifications locales du serveur sont mises de cote dans un stash Git
    # (recuperables avec git stash list / git stash pop), jamais supprimees, puis
    # le depot avance en fast-forward sur origin/main.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$modifications = @(git -C `$repo status --porcelain --untracked-files=no)
if (`$modifications.Count -gt 0) {
    `$message = 'sauvegarde avant synchronisation ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')
    git -C `$repo stash push -m `$message
    if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
    Write-Output ('Modifications locales mises de cote : ' + (git -C `$repo stash list -1))
}
git -C `$repo fetch -q origin
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
# Fichiers non suivis qui portent le nom d'un fichier publie : deplaces dans un
# dossier de sauvegarde a cote du depot (jamais supprimes) pour laisser passer la mise a jour.
`$publies = @(git -C `$repo ls-tree -r --name-only origin/main)
`$conflits = @(git -C `$repo ls-files --others --exclude-standard | Where-Object { `$publies -contains `$_ })
if (`$conflits.Count -gt 0) {
    `$sauvegarde = Join-Path (Split-Path -Parent `$repo) ('jarvis-sauvegarde-' + (Get-Date -Format 'yyyyMMdd-HHmm'))
    foreach (`$fichier in `$conflits) {
        `$cible = Join-Path `$sauvegarde `$fichier
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent `$cible) | Out-Null
        Move-Item -LiteralPath (Join-Path `$repo `$fichier) -Destination `$cible
    }
    Write-Output ('Fichiers non suivis sauvegardes dans ' + `$sauvegarde + ' : ' + (`$conflits -join ', '))
}
git -C `$repo checkout -q main
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
git -C `$repo pull -q --ff-only origin main
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
Write-Output ('Serveur synchronise sur ' + (git -C `$repo rev-parse --short HEAD))
"@
    exit 0
}

if ($Action -eq 'routes_lan') {
    # Lecture seule : quelles routes WebSocket repondent sur le port LAN, en local,
    # et quel processus ecoute ce port.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Continue'
`$repo = $projetLitteral
Get-NetTCPConnection -State Listen -LocalPort 8791 -ErrorAction SilentlyContinue | ForEach-Object {
    `$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + `$_.OwningProcess)
    Write-Output ('ecoute 8791 : PID ' + `$_.OwningProcess + ' ' + `$p.Name + ' lance=' + `$p.CreationDate.ToString('s') + ' adresse=' + `$_.LocalAddress)
}
`$py = @'
import asyncio, websockets
async def essai(chemin):
    try:
        async with websockets.connect("ws://127.0.0.1:8791" + chemin, open_timeout=8):
            print(chemin.ljust(18), "-> ACCEPTEE")
    except Exception as e:
        print(chemin.ljust(18), "->", str(e)[:70])
async def main():
    for c in ("/satellite", "/desktop-agent", "/chemin-bidon"):
        await essai(c)
asyncio.run(main())
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_routes_lan.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
Remove-Item -LiteralPath `$fichier -Force
"@
    exit 0
}

if ($Action -eq 'journal_postes') {
    # Lecture seule : dernieres lignes du journal Jarvis sur les satellites et l'agent Windows.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Continue'
`$repo = $projetLitteral
`$journal = Join-Path `$repo 'logs\jarvis.log'
if (-not (Test-Path -LiteralPath `$journal)) { Write-Output 'journal absent'; exit 0 }
Get-Content -LiteralPath `$journal -Tail 4000 -Encoding UTF8 |
    Where-Object { `$_ -match '(?i)poste distant|desktop-agent|satellite|LAN' } |
    Select-Object -Last 25
"@
    exit 0
}

if ($Action -eq 'redemarrer_jarvis') {
    # Arrete Jarvis vocal et le serveur MCP (ancien code en memoire), puis relance le
    # wrapper habituel DANS la session Windows de l'utilisatrice via une tache ponctuelle
    # (meme compte que la tache Signal Matin), supprimee aussitot apres.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$wrapper = Join-Path `$repo 'scripts\demarrer_jarvis_complet.ps1'
if (-not (Test-Path -LiteralPath `$wrapper)) { throw 'Wrapper de demarrage introuvable.' }
`$anciens = @(Get-CimInstance Win32_Process -Filter "Name like 'python%' or Name like 'uv%'" |
    Where-Object { [string]`$_.CommandLine -match 'jarvis14\.py|jarvis\.mcp_server' })
foreach (`$p in `$anciens) { Stop-Process -Id `$p.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Output ('processus arretes=' + `$anciens.Count)
# Le ngrok lance par pyngrok survit a Jarvis et garde l'adresse publique : le
# nouveau Jarvis ne pourrait plus ouvrir son tunnel (ERR_NGROK_334).
`$tunnels = @(Get-CimInstance Win32_Process -Filter "Name='ngrok.exe'" |
    Where-Object { [string]`$_.ExecutablePath -match '(?i)pyngrok|\\ngrok\\' })
foreach (`$p in `$tunnels) { Stop-Process -Id `$p.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Output ('tunnels ngrok de Jarvis arretes=' + `$tunnels.Count)
Start-Sleep -Seconds 3

`$modele = Get-ScheduledTask -TaskName 'Jarvis - Signal Matin'
`$nom = 'Jarvis - redemarrage ponctuel'
`$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + `$wrapper + '"') -WorkingDirectory `$repo
`$reglages = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName `$nom -Action `$action -Settings `$reglages -Principal `$modele.Principal -Force | Out-Null
Start-ScheduledTask -TaskName `$nom
`$lance = `$false
for (`$i = 0; `$i -lt 90 -and -not `$lance; `$i++) {
    Start-Sleep -Seconds 2
    `$lance = [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { [string]`$_.CommandLine -match 'jarvis14\.py' })
}
Start-Sleep -Seconds 20
Unregister-ScheduledTask -TaskName `$nom -Confirm:`$false
Write-Output ('jarvis_relance=' + `$lance)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { [string]`$_.CommandLine -match 'jarvis14\.py' } |
    ForEach-Object { Write-Output ('processus=' + `$_.ProcessId + ' lance=' + `$_.CreationDate.ToString('s') + ' session=' + `$_.SessionId) }
foreach (`$port in 8765, 8790, 8791) {
    Write-Output ('port_' + `$port + '=' + [bool](Get-NetTCPConnection -State Listen -LocalPort `$port -ErrorAction SilentlyContinue))
}
"@
    exit 0
}

if ($Action -eq 'etat_agent_bureau') {
    # Lecture seule : ce que le serveur prevoit pour un poste « bureau ». Seuls des
    # identifiants et des oui/non sont affiches, jamais un jeton.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Continue'
`$repo = $projetLitteral
`$py = @'
import yaml
conf = yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}
poste = conf.get("poste_principal") or {}
agents = conf.get("desktop_agents") or []
sats = conf.get("satellites") or []
lan = conf.get("satellite_lan") or {}
def ids(liste):
    return [str(e.get("id")) + ("(jeton)" if e.get("token") else "(SANS jeton)") for e in liste if isinstance(e, dict)]
print("poste_principal.actif=" + str(poste.get("actif")) + " agent=" + str(poste.get("agent")))
print("desktop_agents=" + str(ids(agents)))
print("satellites=" + str(ids(sats)))
print("satellite_lan=" + str({k: v for k, v in lan.items() if "token" not in str(k).lower()}))
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_etat_agent.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
Remove-Item -LiteralPath `$fichier -Force
foreach (`$port in 8790, 8791) {
    Write-Output ('port_' + `$port + '_ecoute=' + [bool](Get-NetTCPConnection -State Listen -LocalPort `$port -ErrorAction SilentlyContinue))
}
Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { `$_.DisplayName -match '(?i)jarvis|satellite|8791' -and `$_.Enabled -eq 'True' } |
    ForEach-Object { Write-Output ('pare_feu=' + `$_.DisplayName) }
"@
    exit 0
}

if ($Action -eq 'lancement_jarvis') {
    # Lecture seule : comment Jarvis demarre sur le serveur (taches, dossier Demarrage,
    # arbre des processus), pour le relancer exactement de la meme facon.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Continue'
Get-ScheduledTask | Where-Object { `$_.TaskName -match '(?i)jarvis|hermes' } | ForEach-Object {
    `$a = @(`$_.Actions)[0]
    Write-Output ('tache=' + `$_.TaskName + ' | etat=' + `$_.State + ' | declencheurs=' +
        ((@(`$_.Triggers) | ForEach-Object { `$_.CimClass.CimClassName -replace 'MSFT_Task', '' }) -join ',') +
        ' | execute=' + [IO.Path]::GetFileName([string]`$a.Execute) + ' ' + ([string]`$a.Arguments -replace '[A-Za-z]:\\[^\s\"]*\\', '...\'))
}
`$demarrage = [Environment]::GetFolderPath('Startup')
Get-ChildItem -LiteralPath `$demarrage -ErrorAction SilentlyContinue | Where-Object { `$_.Name -match '(?i)jarvis|hermes' } | ForEach-Object {
    Write-Output ('demarrage=' + `$_.Name)
}
Get-CimInstance Win32_Process -Filter "Name like 'python%' or Name like 'uv%' or Name like 'pythonw%'" |
    Where-Object { [string]`$_.CommandLine -like '*jarvis14.py*' } | ForEach-Object {
    `$parent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + `$_.ParentProcessId) -ErrorAction SilentlyContinue
    Write-Output ('processus=' + `$_.ProcessId + ' ' + `$_.Name + ' parent=' + `$_.ParentProcessId + ' ' + `$(if (`$parent) { `$parent.Name } else { '(termine)' }) + ' session=' + `$_.SessionId)
}
"@
    exit 0
}

if ($Action -eq 'processus') {
    # Lecture seule : quels programmes Jarvis tournent, depuis quand, dans quel mode.
    # Seuls deux reglages booleens/courts sont lus dans config.yaml, jamais affiche en entier.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Continue'
`$repo = $projetLitteral
`$trouve = `$false
Get-CimInstance Win32_Process -Filter "Name like 'python%' or Name like 'pythonw%' or Name like 'uv%'" | ForEach-Object {
    `$ligne = [string]`$_.CommandLine
    foreach (`$motif in 'jarvis14.py', 'jarvis_desktop_agent.py', 'main.py\" serve', 'generate-morning-paper') {
        if (`$ligne -like ('*' + `$motif.Replace('\"', '') + '*')) {
            `$trouve = `$true
            Write-Output ('processus=' + `$_.ProcessId + ' ' + `$motif.Replace('\"', '') + ' lance=' + `$_.CreationDate.ToString('s'))
            break
        }
    }
}
if (-not `$trouve) { Write-Output 'processus=aucun' }
Get-CimInstance Win32_Process -Filter "Name='ngrok.exe'" | ForEach-Object {
    `$parent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + `$_.ParentProcessId) -ErrorAction SilentlyContinue
    Write-Output ('ngrok=' + `$_.ProcessId + ' lance=' + `$_.CreationDate.ToString('s') + ' parent=' + `$(if (`$parent) { `$parent.Name + ' ' + `$parent.ProcessId } else { '(termine)' }) + ' pyngrok=' + ([string]`$_.ExecutablePath -match '(?i)pyngrok|\\ngrok\\'))
}
Write-Output ('port_hud_8770=' + [bool](Get-NetTCPConnection -State Listen -LocalPort 8770 -ErrorAction SilentlyContinue))
Write-Output ('port_serveur_8790=' + [bool](Get-NetTCPConnection -State Listen -LocalPort 8790 -ErrorAction SilentlyContinue))
Write-Output ('session_utilisateur_active=' + [bool](Get-Process explorer -ErrorAction SilentlyContinue))
`$py = @'
import yaml
conf = yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}
poste = conf.get("poste_principal") or {}
print("serveur_sans_peripheriques=" + str(bool(poste.get("serveur_sans_peripheriques", False))))
print("hud_premier_plan=" + str((conf.get("hud") or {}).get("premier_plan_au_reveil", "defaut")))
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_processus.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
Remove-Item -LiteralPath `$fichier -Force
"@
    exit 0
}

if ($Action -eq 'derniere_edition') {
    # Lecture seule : ce que contient la derniere edition (brief ou cahier classique)
    # et les dernieres lignes utiles du journal d'execution de la tache.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
Set-Location `$repo
`$py = @'
import json
from pathlib import Path
chemin = sorted(Path("output/data").glob("????-??-??-signal-matin.json"))[-1]
donnees = json.loads(chemin.read_text(encoding="utf-8"))
brief = donnees.get("tech_brief")
statut = next((s for s in donnees.get("sources", []) if s.get("name") == "Brief Tech & IA"), {})
print("edition=" + chemin.name[:10] + " generee=" + str(donnees.get("generated_at", ""))[:19])
print("brief_present=" + str(bool(brief)) + " infos=" + str(len(brief["facts"]) if brief else 0)
      + " analyses=" + str(len(brief["analyses"]) if brief else 0))
print("statut_brief=" + str(statut.get("state")) + " | " + str(statut.get("detail")))
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_derniere_edition.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
Remove-Item -LiteralPath `$fichier -Force
`$log = Get-ChildItem (Join-Path `$repo 'output\logs') -Filter 'signal-matin-*.log' | Sort-Object LastWriteTime | Select-Object -Last 1
if (`$log) {
    Write-Output ('journal=' + `$log.Name)
    Get-Content -LiteralPath `$log.FullName | Where-Object { `$_ -match '(?i)debut|fin signal|imprim|erreur|error|pdf' } | Select-Object -Last 8
}
"@
    exit 0
}

if ($Action -eq 'tester_brief') {
    # Repetition generale SANS impression ni historique : brief reel, PDF temporaire,
    # puis lecture du JSON par la liseuse installee. Fichiers temporaires supprimes.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$json = Join-Path `$env:TEMP 'jarvis_test_brief_edition.json'
`$py = @'
import datetime as dt, json, sys, tempfile, time
from pathlib import Path
from pypdf import PdfReader
from core.signal_matin import sources, tech_brief
from core.signal_matin.normalizer import charger_edition
from core.signal_matin.pdf import generer_pdf

maintenant = dt.datetime.now().astimezone()
debut = time.time()
candidats, statut = sources.TechRssSource().collect(maintenant, limit=72, max_age=72)
rapport = {}
brief = tech_brief.construire_brief(candidats, maintenant, allow_proxy=True,
                                    enregistrer_historique=False, rapport=rapport)
print("duree_brief_s=" + str(round(time.time() - debut)) + " candidats=" + str(len(candidats)))
resume = {k: v for k, v in rapport.items() if k not in ("relecture", "retraits_mecaniques")}
print("rapport=" + json.dumps(resume, ensure_ascii=False, default=str)[:900])
print("corrections_relecture=" + str(len(rapport.get("relecture", []))) +
      " retraits_verification=" + str(len(rapport.get("retraits_mecaniques", []))))
if brief is None:
    sys.exit(3)
print("verification=" + brief.verification)
derniere = sorted(Path("output/data").glob("????-??-??-signal-matin.json"))[-1]
edition = charger_edition(derniere, mode="auto").model_copy(update={"tech_brief": brief})
with tempfile.TemporaryDirectory() as dossier:
    pdf = generer_pdf(edition, Path(dossier) / "test.pdf")
    print("pdf_pages=" + str(len(PdfReader(str(pdf)).pages)))
Path(sys.argv[1]).write_text(edition.model_dump_json(exclude_none=True), encoding="utf-8")
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_tester_brief.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
`$env:PYTHONPATH = `$repo
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier `$json
`$code = `$LASTEXITCODE
Remove-Item -LiteralPath `$fichier -Force
if (`$code -ne 0) { exit `$code }

`$liseuse = [string]@((Get-ScheduledTask -TaskName 'Signal Matin - liseuse').Actions)[0].WorkingDirectory
`$pyLiseuse = Join-Path `$liseuse '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath `$pyLiseuse)) { `$pyLiseuse = (Get-Command python).Source }
Set-Location `$liseuse
& `$pyLiseuse -c "import sys; sys.path.insert(0, 'src'); from pathlib import Path; from signal_matin.normalizer import charger_edition; e = charger_edition(Path(sys.argv[1])); print('liseuse_accepte=True brief_infos=' + str(len(e.tech_brief.facts)))" `$json
`$code = `$LASTEXITCODE
Remove-Item -LiteralPath `$json -Force
exit `$code
"@
    exit 0
}

if ($Action -eq 'activer_brief') {
    # Modification chirurgicale de config.yaml (jamais affiche) : seules les cles
    # signal_matin.brief_tech et signal_matin.modele_brief changent ; le resultat est
    # relu et compare a l'ancienne configuration avant ecriture ; copie de sauvegarde
    # hors du depot.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$py = @'
import copy, datetime, shutil, sys
from pathlib import Path
import yaml

VALEURS = {"brief_tech": True, "modele_brief": "gpt-5.6-terra"}
chemin = Path("config.yaml")
texte = chemin.read_text(encoding="utf-8")
nl = "\r\n" if "\r\n" in texte else "\n"
avant = yaml.safe_load(texte) or {}
lignes = texte.splitlines(keepends=True)

def haut_niveau(ligne):
    return ligne.strip() and not ligne[:1].isspace() and not ligne.lstrip().startswith("#")

debut = next((i for i, l in enumerate(lignes)
              if haut_niveau(l) and l.lstrip("﻿").split("#")[0].strip() == "signal_matin:"), None)
if debut is None:
    if "signal_matin" in avant:
        sys.exit("section signal_matin dans un format inattendu : rien n'a ete modifie")
    # Aucune section : Signal Matin tournait avec ses valeurs par defaut. On l'ajoute a la fin.
    if lignes and not lignes[-1].endswith(("\n", "\r")):
        lignes[-1] += nl
    lignes += [nl, "signal_matin:" + nl]
    debut = len(lignes) - 1
fin = next((i for i in range(debut + 1, len(lignes)) if haut_niveau(lignes[i])), len(lignes))
enfants = [l for l in lignes[debut + 1:fin] if l.strip() and not l.lstrip().startswith("#")]
retrait = enfants[0][:len(enfants[0]) - len(enfants[0].lstrip())] if enfants else "  "
for cle, valeur in VALEURS.items():
    rendu = retrait + cle + ": " + ("true" if valeur is True else '"' + str(valeur) + '"') + nl
    trouve = next((i for i in range(debut + 1, fin) if lignes[i].startswith(retrait + cle + ":")), None)
    if trouve is None:
        lignes.insert(debut + 1, rendu)
        fin += 1
    else:
        lignes[trouve] = rendu
nouveau = "".join(lignes)
attendu = copy.deepcopy(avant)
attendu.setdefault("signal_matin", {}).update(VALEURS)
if yaml.safe_load(nouveau) != attendu:
    sys.exit("verification echouee : rien n'a ete modifie")
sauvegarde = Path("..") / ("jarvis-sauvegarde-config-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")) / "config.yaml"
sauvegarde.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(chemin, sauvegarde)
chemin.write_text(nouveau, encoding="utf-8", newline="")
print("config.yaml mis a jour (brief_tech=true, modele_brief=gpt-5.6-terra), reste identique ; copie de sauvegarde hors du depot")
from core import cloud
print("fournisseur=" + cloud.fournisseur() + " cle_disponible=" + str(cloud.disponible()))
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_activer_brief.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
`$env:PYTHONPATH = `$repo
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
`$code = `$LASTEXITCODE
Remove-Item -LiteralPath `$fichier -Force
exit `$code
"@
    exit 0
}

if ($Action -eq 'etat_liseuse' -or $Action -eq 'mettre_a_jour_liseuse') {
    # Le serveur liseuse est une installation separee du depot autonome Signal Matin,
    # retrouvee via sa tache planifiee. etat_liseuse est en lecture seule.
    $mettreAJour = if ($Action -eq 'mettre_a_jour_liseuse') { '$true' } else { '$false' }
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$mettreAJour = $mettreAJour
`$tache = Get-ScheduledTask -TaskName 'Signal Matin - liseuse' -ErrorAction SilentlyContinue
if (-not `$tache) { throw 'Tache Signal Matin - liseuse absente.' }
`$racine = [string]@(`$tache.Actions)[0].WorkingDirectory
Write-Output ('tache=' + `$tache.State + ' depot_git=' + (Test-Path -LiteralPath (Join-Path `$racine '.git')))
Write-Output ('commit=' + (git -C `$racine rev-parse --short HEAD) + ' branche=' + (git -C `$racine branch --show-current))
git -C `$racine fetch -q origin
Write-Output ('origin_main=' + (git -C `$racine rev-parse --short origin/main))
`$modifs = @(git -C `$racine status --porcelain --untracked-files=no)
Write-Output ('modifications=' + `$modifs.Count)
`$modifs
if (-not `$mettreAJour) { exit 0 }

if (`$modifs.Count -gt 0) {
    git -C `$racine stash push -m ('sauvegarde avant synchronisation ' + (Get-Date -Format 'yyyy-MM-dd HH:mm'))
    if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
}
`$publies = @(git -C `$racine ls-tree -r --name-only origin/main)
`$conflits = @(git -C `$racine ls-files --others --exclude-standard | Where-Object { `$publies -contains `$_ })
if (`$conflits.Count -gt 0) {
    `$sauvegarde = Join-Path (Split-Path -Parent `$racine) ('signal-matin-sauvegarde-' + (Get-Date -Format 'yyyyMMdd-HHmm'))
    foreach (`$fichier in `$conflits) {
        `$cible = Join-Path `$sauvegarde `$fichier
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent `$cible) | Out-Null
        Move-Item -LiteralPath (Join-Path `$racine `$fichier) -Destination `$cible
    }
    Write-Output ('Fichiers non suivis sauvegardes : ' + (`$conflits -join ', '))
}
git -C `$racine checkout -q main
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
git -C `$racine pull -q --ff-only origin main
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
Write-Output ('Liseuse synchronisee sur ' + (git -C `$racine rev-parse --short HEAD))
Stop-ScheduledTask -TaskName 'Signal Matin - liseuse' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName 'Signal Matin - liseuse'
Start-Sleep -Seconds 6
Write-Output ('tache_apres_redemarrage=' + (Get-ScheduledTask -TaskName 'Signal Matin - liseuse').State)
"@
    exit 0
}

if ($Action -eq 'verifier_rendu') {
    # Sans reseau ni impression : remet en page la derniere edition du serveur
    # dans un PDF temporaire, puis le supprime. Valide Python, Chromium et la pagination.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$py = @'
import sys, tempfile
from pathlib import Path
from pypdf import PdfReader
from core.signal_matin.normalizer import charger_edition
from core.signal_matin.pdf import generer_pdf
derniere = sorted(Path("output/data").glob("????-??-??-signal-matin.json"))[-1]
edition = charger_edition(derniere, mode="auto")
with tempfile.TemporaryDirectory() as dossier:
    pdf = generer_pdf(edition, Path(dossier) / "verification.pdf")
    print("edition=" + derniere.name[:10] + " densite=" + edition.edition.density.value
          + " pages=" + str(len(PdfReader(str(pdf)).pages)))
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_verifier_rendu.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
`$env:PYTHONPATH = `$repo
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
`$code = `$LASTEXITCODE
Remove-Item -LiteralPath `$fichier -Force
exit `$code
"@
    exit 0
}

if ($Action -eq 'lignes_uniques') {
    # Lecture seule : lignes presentes sur le serveur mais absentes de origin/main,
    # pour verifier qu'aucun travail propre au serveur ne serait perdu.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
foreach (`$ligne in @(git -C `$repo status --porcelain --untracked-files=no)) {
    `$fichier = `$ligne.Substring(3)
    git -C `$repo diff --quiet origin/main -- `$fichier
    if (`$LASTEXITCODE -eq 0) { continue }
    `$uniques = @(git -C `$repo diff --unified=0 origin/main -- `$fichier |
        Where-Object { `$_ -match '^\+' -and `$_ -notmatch '^\+\+\+' })
    Write-Output ('== ' + `$fichier + ' : ' + `$uniques.Count + ' ligne(s) propre(s) au serveur')
    `$uniques | Select-Object -First 60
}
"@
    exit 0
}

if ($Action -eq 'etat_hermes') {
    # Lecture seule : oui/non uniquement, aucune cible SSH ni cle n'est affichee.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Continue'
`$repo = $projetLitteral
Write-Output ('hermes_cli=' + [bool](Get-Command hermes -ErrorAction SilentlyContinue))
Write-Output ('cible_tunnel=' + (Test-Path -LiteralPath (Join-Path `$repo 'logs\hermes-server-target.txt')))
Write-Output ('cle_tunnel=' + (Test-Path -LiteralPath (Join-Path `$env:USERPROFILE '.ssh\jarvis_server_ed25519')))
`$ecoute = Get-NetTCPConnection -State Listen -LocalPort 8642 -ErrorAction SilentlyContinue
Write-Output ('api_8642_ecoute=' + [bool]`$ecoute)
"@
    exit 0
}

if ($Action -eq 'modele_hermes_vm') {
    # Lecture seule : uniquement la section model de la config Hermes de la VM.
    # La cible SSH reste dans le fichier prive du serveur et n'est jamais affichee.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$cible = (Get-Content -LiteralPath (Join-Path `$repo 'logs\hermes-server-target.txt') -Raw).Trim()
`$cle = Join-Path `$env:USERPROFILE '.ssh\jarvis_server_ed25519'
`$distant = 'for f in `$HERMES_HOME/config.yaml ~/.hermes/config.yaml `$(find ~ /opt /srv -maxdepth 4 -name config.yaml -path ''*hermes*'' 2>/dev/null); do [ -f "`$f" ] && echo "== `$f" && grep -iE -A4 ''^ *model'' "`$f" | grep -viE ''key|token|secret|password''; done; exit 0'
& ssh.exe -o BatchMode=yes -o ConnectTimeout=10 -i `$cle `$cible `$distant
"@
    exit 0
}

if ($Action -eq 'tester_hermes_contexte') {
    # Demande de contexte type du Brief Tech & IA, par le transport de production
    # (API Hermes de la VM). Aucune ecriture : affiche la duree et la reponse.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$repo = $projetLitteral
`$py = @'
import sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tools.deleguer_a_hermes import _appeler_hermes_http
prompt = """Nous sommes le 1er octobre 2026. Pour chacun des sujets ci-dessous, trouve avec ta recherche web 2 ou 3 pages de CONTEXTE utiles pour l'analyser : evenements anterieurs, decisions liees, chiffres, reactions des acteurs concernes. Privilegie les sources primaires et les medias reconnus, en francais ou en anglais.
Fais au plus 2 recherches par sujet. N'ouvre pas les pages : choisis a partir des resultats de recherche.
Sujets :
1. Gemini 4 Argon reserve a des defenseurs cyber - recherche : precedents de modeles d'IA a acces restreint pour raisons de securite
2. Plainte contre OpenAI apres l'intrusion de ses modeles dans Hugging Face - recherche : responsabilite juridique des agents d'IA autonomes
3. Huawei Ascend devant Nvidia en Chine - recherche : effets des controles americains a l'export de puces IA
Reponds uniquement par un tableau JSON : [{"sujet": 1, "url": "https://...", "titre": "...", "media": "..."}]"""
debut = time.time()
try:
    resultat = _appeler_hermes_http(prompt, "signal-matin-brief-test")
    print("duree_s=", round(time.time() - debut))
    print(repr(resultat)[:2500])
except Exception as erreur:
    print("duree_s=", round(time.time() - debut), "echec:", type(erreur).__name__, str(erreur)[:300])
'@
`$fichier = Join-Path `$env:TEMP 'jarvis_test_hermes_contexte.py'
Set-Content -LiteralPath `$fichier -Value `$py -Encoding utf8
`$env:PYTHONPATH = `$repo
Set-Location `$repo
& (Join-Path `$repo '.venv\Scripts\python.exe') `$fichier
Remove-Item -LiteralPath `$fichier -Force
"@
    exit 0
}

if ($Action -eq 'definir_heure') {
    if (-not $Heure) {
        throw 'Precise la nouvelle heure avec -Heure HH:mm.'
    }
    $heureLitterale = Convertir-LitteralPowerShell $Heure
    # Seul le declencheur change : action, compte, impression et reglages restent intacts.
    Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$taskName = 'Jarvis - Signal Matin'
`$tache = Get-ScheduledTask -TaskName `$taskName
`$declencheur = New-ScheduledTaskTrigger -Daily -At $heureLitterale
if ($DureeMinutes -gt 0) {
    `$reglages = `$tache.Settings
    `$reglages.ExecutionTimeLimit = 'PT$($DureeMinutes)M'
    Set-ScheduledTask -TaskName `$taskName -Trigger `$declencheur -Settings `$reglages | Out-Null
} else {
    Set-ScheduledTask -TaskName `$taskName -Trigger `$declencheur | Out-Null
}
`$info = Get-ScheduledTaskInfo -TaskName `$taskName
Write-Output ('prochaine_execution=' + `$info.NextRunTime.ToString('s'))
Write-Output ('duree_maximale=' + (Get-ScheduledTask -TaskName `$taskName).Settings.ExecutionTimeLimit)
Write-Output ('action_imprime=' + ([string]@((Get-ScheduledTask -TaskName `$taskName).Actions)[0].Arguments -match '-Imprimer'))
"@
    exit 0
}

Invoke-ServeurH24 @"
`$ErrorActionPreference = 'Stop'
`$taskName = 'Jarvis - Signal Matin'
`$task = Get-ScheduledTask -TaskName `$taskName -ErrorAction SilentlyContinue
if (-not `$task) { throw 'Tache Signal Matin absente.' }
Start-ScheduledTask -TaskName `$taskName
`$limite = (Get-Date).AddMinutes(8)
do {
    Start-Sleep -Seconds 5
    `$task = Get-ScheduledTask -TaskName `$taskName
} while (`$task.State -eq 'Running' -and (Get-Date) -lt `$limite)
`$info = Get-ScheduledTaskInfo -TaskName `$taskName
Write-Output ('etat=' + `$task.State)
Write-Output ('resultat=' + `$info.LastTaskResult)
Write-Output ('execution=' + `$info.LastRunTime.ToString('s'))
if (`$task.State -eq 'Running') { exit 4 }
if (`$info.LastTaskResult -ne 0) { exit 5 }
"@
