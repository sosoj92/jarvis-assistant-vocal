# Tunnel prive entre le corps Jarvis (Windows) et Hermes (VM Ubuntu).
# - 8642 : Jarvis Windows -> API Hermes Ubuntu
# - 8765 : Hermes Ubuntu -> MCP Jarvis Windows
# - 11434 : Hermes Ubuntu -> Ollama Windows
[CmdletBinding()]
param(
    [string]$Server = $env:JARVIS_HERMES_SERVER,
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\jarvis_server_ed25519"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# La cible contient souvent un nom de compte personnel : elle reste donc dans
# logs/hermes-server-target.txt (gitignore) ou dans la variable d'environnement.
if ([string]::IsNullOrWhiteSpace($Server)) {
    $targetFile = Join-Path $logs "hermes-server-target.txt"
    if (Test-Path -LiteralPath $targetFile) {
        $Server = (Get-Content -LiteralPath $targetFile -Raw).Trim()
    }
}
if ($Server -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$') {
    throw "Cible Hermes absente ou invalide. Definis JARVIS_HERMES_SERVER ou logs/hermes-server-target.txt (utilisateur@hote)."
}

if (-not (Test-Path -LiteralPath $IdentityFile)) {
    throw "Cle SSH introuvable : $IdentityFile"
}

$listener = Get-NetTCPConnection -State Listen -LocalPort 8642 `
    -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.ProcessName -eq "ssh") {
        Write-Output "Tunnel Hermes deja actif (PID $($owner.Id))."
        exit 0
    }
    throw "Le port local 8642 est deja utilise par $($owner.ProcessName)."
}

$arguments = @(
    "-N", "-T",
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-i", $IdentityFile,
    "-L", "127.0.0.1:8642:127.0.0.1:8642",
    "-R", "127.0.0.1:8765:127.0.0.1:8765",
    "-R", "127.0.0.1:11434:127.0.0.1:11434",
    $Server
)

$process = Start-Process -FilePath "$env:WINDIR\System32\OpenSSH\ssh.exe" `
    -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs "hermes-tunnel.log") `
    -RedirectStandardError (Join-Path $logs "hermes-tunnel.err.log")

Start-Sleep -Seconds 2
if ($process.HasExited) {
    $detail = Get-Content (Join-Path $logs "hermes-tunnel.err.log") `
        -Tail 10 -ErrorAction SilentlyContinue
    throw "Le tunnel Hermes n'a pas demarre. $detail"
}

$process.Id | Set-Content -Encoding ascii (Join-Path $logs "hermes-tunnel.pid")
Write-Output "Tunnel Hermes actif (PID $($process.Id))."
