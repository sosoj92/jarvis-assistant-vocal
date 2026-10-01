[CmdletBinding()]
param(
    [ValidateSet('etat', 'mettre_a_jour', 'tester_signal_matin', 'definir_heure', 'etat_hermes', 'modele_hermes_vm', 'tester_hermes_contexte')]
    [string]$Action = 'etat',

    [string]$Configuration = '',

    # Utilise uniquement par definir_heure : nouvelle heure quotidienne HH:mm.
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = ''
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
`$null = Get-ScheduledTask -TaskName `$taskName
`$declencheur = New-ScheduledTaskTrigger -Daily -At $heureLitterale
Set-ScheduledTask -TaskName `$taskName -Trigger `$declencheur | Out-Null
`$info = Get-ScheduledTaskInfo -TaskName `$taskName
Write-Output ('prochaine_execution=' + `$info.NextRunTime.ToString('s'))
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
