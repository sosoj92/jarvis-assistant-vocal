# Démarre TOUTE la stack à l'ouverture de session : la chaîne Hermes existante
# (Docker -> MCP Jarvis 8765 -> gateway 8642) PUIS le Jarvis vocal.
# Idempotent + anti-doublon : ne relance rien qui tourne déjà.
# Lancé par la tâche planifiée « JarvisAutostart » (cf. autostart_install.ps1),
# ou à la main pour tout démarrer d'un coup.
$ErrorActionPreference = "SilentlyContinue"
$jarvis = Split-Path $PSScriptRoot -Parent          # racine du dépôt jarvis-vocal
$ws = "$env:USERPROFILE\hermes-workspace"
New-Item -ItemType Directory -Force "$jarvis\logs" | Out-Null
function Log($m) { "$("{0:HH:mm:ss}" -f (Get-Date)) $m" | Add-Content "$jarvis\logs\autostart.log" }

Log "=== autostart ==="

# 1) Chaîne Hermes (si présente et pas déjà en écoute sur 8642). On réutilise le
#    mécanisme existant plutôt que d'en créer un second.
$chain = "$ws\start-hermes-chain.ps1"
if (Test-Path $chain) {
  $up = [bool](Get-NetTCPConnection -State Listen -LocalPort 8642 -ErrorAction SilentlyContinue)
  if (-not $up) {
    # EN ARRIÈRE-PLAN : la chaîne attend Docker (parfois plusieurs minutes). On ne
    # BLOQUE PAS le démarrage du Jarvis vocal derrière ça -> il démarre tout de suite,
    # Hermes suit quand Docker est prêt.
    Log "lancement de la chaîne Hermes (arrière-plan)"
    Start-Process powershell -WindowStyle Hidden `
      -ArgumentList "-NoProfile","-WindowStyle","Hidden","-ExecutionPolicy","Bypass","-File",$chain
  } else { Log "chaîne Hermes déjà UP (8642)" }
} else { Log "start-hermes-chain.ps1 absent -> Jarvis vocal seul" }

# 2) Jarvis vocal — ANTI-DOUBLON : ne lance que s'il ne tourne pas déjà.
$deja = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'jarvis14\.py' }
if ($deja) {
  Log "Jarvis vocal déjà lancé (PID $($deja.ProcessId -join ', ')) -> rien à faire"
} else {
  $uv = "$env:USERPROFILE\.local\bin\uv.exe"
  if (-not (Test-Path $uv)) { $uv = "uv" }          # repli sur le PATH
  Log "lancement du Jarvis vocal via $uv"
  Start-Process $uv -ArgumentList "run","python","jarvis14.py" `
    -WorkingDirectory $jarvis -WindowStyle Minimized
}
Log "=== fait ==="
