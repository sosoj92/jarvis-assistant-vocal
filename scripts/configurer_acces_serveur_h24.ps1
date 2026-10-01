[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ClePublique
)

$ErrorActionPreference = "Stop"

$identite = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identite)
$estAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $estAdmin) {
    throw "Ouvre PowerShell avec 'Executer en tant qu'administrateur', puis relance la commande."
}

$ClePublique = $ClePublique.Trim()
if ($ClePublique -notmatch '^ssh-ed25519\s+[A-Za-z0-9+/=]+(?:\s+.*)?$') {
    throw "La cle publique fournie n'est pas une cle Ed25519 valide."
}

$capacite = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
if ($capacite.State -ne 'Installed') {
    Write-Host "Installation d'OpenSSH Server..."
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd

# Un compte administrateur Windows utilise ce fichier commun. Les ACL sont
# imposees par SID pour rester compatibles avec Windows en francais ou en anglais.
$dossierSsh = Join-Path $env:ProgramData 'ssh'
$fichierCles = Join-Path $dossierSsh 'administrators_authorized_keys'
New-Item -ItemType Directory -Force -Path $dossierSsh | Out-Null
if (-not (Test-Path -LiteralPath $fichierCles)) {
    New-Item -ItemType File -Path $fichierCles | Out-Null
}

$cles = @(Get-Content -LiteralPath $fichierCles -ErrorAction SilentlyContinue)
if ($cles -notcontains $ClePublique) {
    Add-Content -LiteralPath $fichierCles -Value $ClePublique -Encoding ascii
}

$acl = [Security.AccessControl.FileSecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
foreach ($sidTexte in @('S-1-5-18', 'S-1-5-32-544')) {
    $sid = [Security.Principal.SecurityIdentifier]::new($sidTexte)
    $regle = [Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($regle)
}
Set-Acl -LiteralPath $fichierCles -AclObject $acl

# Refuse toute authentification par mot de passe. La cle dediee est le seul
# moyen d'entrer, meme depuis une autre machine du reseau domestique.
$fichierSshd = Join-Path $dossierSsh 'sshd_config'
if (-not (Test-Path -LiteralPath $fichierSshd)) {
    throw "Configuration OpenSSH introuvable : $fichierSshd"
}
$configurationSshd = Get-Content -LiteralPath $fichierSshd -Raw
$configurationSshd = [regex]::Replace(
    $configurationSshd,
    '(?im)^\s*#?\s*(PubkeyAuthentication|PasswordAuthentication)\s+.*(?:\r?\n)?',
    ''
)
$configurationSshd = (
    "PubkeyAuthentication yes`r`n" +
    "PasswordAuthentication no`r`n" +
    $configurationSshd.TrimStart()
)
Set-Content -LiteralPath $fichierSshd -Value $configurationSshd -Encoding ascii

# La regle Microsoft par defaut accepte tout le profil associe. On la remplace
# par une regle limitee aux plages IPv4 privees. Cela fonctionne aussi lorsque
# le Wi-Fi, l'Ethernet et les objets connectes utilisent plusieurs sous-reseaux,
# sans exposer le port SSH a Internet.
$regleMicrosoft = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if ($regleMicrosoft) {
    Disable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' | Out-Null
}

$nomRegle = 'Jarvis-OpenSSH-LAN'
$reseauxPrives = @('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
$regleJarvis = Get-NetFirewallRule -Name $nomRegle -ErrorAction SilentlyContinue
if (-not $regleJarvis) {
    $regleJarvis = New-NetFirewallRule `
        -Name $nomRegle `
        -DisplayName 'Jarvis - OpenSSH depuis le reseau local' `
        -Enabled True `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 22 `
        -RemoteAddress $reseauxPrives `
        -Action Allow `
        -Profile Any
} else {
    Enable-NetFirewallRule -Name $nomRegle | Out-Null
    $regleJarvis | Get-NetFirewallAddressFilter |
        Set-NetFirewallAddressFilter -RemoteAddress $reseauxPrives | Out-Null
}

Restart-Service -Name sshd

Write-Host ""
Write-Host "Acces distant Jarvis configure." -ForegroundColor Green
Write-Host "Machine : $env:COMPUTERNAME"
Write-Host "Compte  : $env:USERNAME"
$adresses = @(
    Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred |
        Where-Object {
            $_.IPAddress -notlike '127.*' -and
            $_.IPAddress -notlike '169.254.*'
        } |
        Select-Object -ExpandProperty IPAddress
)
Write-Host "Adresse : $($adresses -join ', ')"
Write-Host "SSH est automatique, sans mot de passe et limite aux reseaux prives."
