# Démarre TOUTE la stack à l'ouverture de session : MCP Jarvis 8765, tunnel SSH
# privé vers Hermes dans la VM Ubuntu, puis Jarvis vocal.
# Idempotent + anti-doublon : ne relance rien qui tourne déjà.
# Lance par le dossier Demarrage Windows ou par la tache planifiee optionnelle
# creee par autostart_install.ps1, ou a la main pour tout demarrer d'un coup.
$ErrorActionPreference = "SilentlyContinue"
$jarvis = Split-Path $PSScriptRoot -Parent          # racine du dépôt jarvis-vocal
New-Item -ItemType Directory -Force "$jarvis\logs" | Out-Null
function Log($m) { "$("{0:HH:mm:ss}" -f (Get-Date)) $m" | Add-Content "$jarvis\logs\autostart.log" }
function Listening($port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
function WaitPort($port, $timeout = 40) {
  for ($i=0; $i -lt $timeout; $i++) {
    if (Listening $port) { return $true }
    Start-Sleep 1
  }
  return $false
}

Log "=== autostart ==="

# uv est utilise par le MCP et par Jarvis vocal.
$uv = "$env:USERPROFILE\.local\bin\uv.exe"
if (-not (Test-Path $uv)) { $uv = "uv" }

# 1) Serveur MCP local : seul point d'acces d'Hermes aux outils explicitement
#    marques mcp_expose, toujours en loopback.
if (-not (Listening 8765)) {
  $env:JARVIS_MCP_TRANSPORT = "http"
  $p = Start-Process $uv `
    -ArgumentList "run","--directory",$jarvis,"python","-m","jarvis.mcp_server" `
    -WindowStyle Hidden -PassThru -WorkingDirectory $jarvis `
    -RedirectStandardOutput "$jarvis\logs\jarvis-mcp-http.log" `
    -RedirectStandardError "$jarvis\logs\jarvis-mcp-http.err.log"
  Remove-Item Env:JARVIS_MCP_TRANSPORT -ErrorAction SilentlyContinue
  $p.Id | Set-Content -Encoding ascii "$jarvis\logs\jarvis-mcp-http.pid"
  Log "Jarvis MCP lance PID $($p.Id)"
}
$mcpUp = WaitPort 8765 40
Log "Jarvis MCP 8765: $(if($mcpUp){'UP'}else{'DOWN'})"

# 2) Tunnel privé : 8642 vers l'API Hermes de la VM, plus les deux retours
#    loopback permettant a Hermes de joindre le MCP et Ollama sur Windows.
$tunnel = Join-Path $PSScriptRoot "start_hermes_server_tunnel.ps1"
if ($mcpUp -and (Test-Path $tunnel)) {
  try {
    $message = (& $tunnel | Out-String).Trim()
    Log $(if($message){$message}else{"tunnel Hermes lance"})
  } catch {
    Log "tunnel Hermes ECHEC: $($_.Exception.Message)"
  }
} elseif (-not $mcpUp) {
  Log "tunnel Hermes non lance : MCP indisponible"
} else {
  Log "script de tunnel Hermes absent"
}

# 3) Jarvis vocal — ANTI-DOUBLON : ne lance que s'il ne tourne pas déjà.
$deja = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'jarvis14\.py' }
if ($deja) {
  Log "Jarvis vocal déjà lancé (PID $($deja.ProcessId -join ', ')) -> rien à faire"
} else {
  Log "lancement du Jarvis vocal via $uv"
  Start-Process $uv -ArgumentList "run","python","jarvis14.py" `
    -WorkingDirectory $jarvis -WindowStyle Minimized
}
Log "=== fait ==="
