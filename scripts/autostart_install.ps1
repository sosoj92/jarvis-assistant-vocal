# Installe le démarrage automatique de Jarvis à l'ouverture de session.
# Essaie d'abord une tâche planifiée (délai 30 s "propre", nécessite l'admin) ;
# sinon REPLI automatique sur le dossier Démarrage de Windows (sans admin).
#
# Usage :  powershell -ExecutionPolicy Bypass -File scripts\autostart_install.ps1
# Retrait : scripts\autostart_uninstall.ps1

$script = Join-Path $PSScriptRoot "demarrer_jarvis_complet.ps1"
$nom = "JarvisAutostart"
if (-not (Test-Path $script)) { Write-Host "Introuvable : $script" -ForegroundColor Red; exit 1 }

# --- 1) Tâche planifiée (login + 30 s). Nécessite des droits admin. ---
$tacheOk = $false
try {
  $action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $trigger.Delay = "PT30S"
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
  Register-ScheduledTask -TaskName $nom -Action $action -Trigger $trigger `
    -Settings $settings -Description "Démarre la chaîne Hermes + le Jarvis vocal au login." `
    -Force -RunLevel Limited -ErrorAction Stop | Out-Null
  $tacheOk = $true
} catch {
  $tacheOk = $false
}

if ($tacheOk) {
  Write-Host "OK : tâche planifiée « $nom » installée (login + 30 s)." -ForegroundColor Green
  Write-Host "Tester : Start-ScheduledTask -TaskName $nom"
  exit 0
}

# --- 2) Repli SANS admin : dossier Démarrage ---
Write-Host "Tâche planifiée refusée (pas d'admin) -> repli dossier Démarrage." -ForegroundColor Yellow
$startup = [Environment]::GetFolderPath('Startup')
$cmd = Join-Path $startup "JarvisAutostart.cmd"
@(
  '@echo off',
  'rem Demarrage auto de Jarvis (sans admin) : delai reseau puis wrapper idempotent.',
  'timeout /t 30 /nobreak >nul',
  ('powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '"')
) | Set-Content -Encoding Oem $cmd
# Oem = page de code de cmd.exe (850 en France). En ascii, un profil accentue
# (C:\Users\Helene avec accents) devenait "H?l?ne" et le demarrage echouait sans
# bruit : on relit donc le fichier et on compare le chemin avant d'annoncer OK.
$relu = if (Test-Path $cmd) { Get-Content -Encoding Oem -Raw $cmd } else { "" }
if ($relu -and -not $relu.Contains($script)) {
  Remove-Item $cmd -Force -ErrorAction SilentlyContinue
  Write-Host "ECHEC : cmd.exe ne sait pas lire ce chemin (caractere hors de sa page de code) :" -ForegroundColor Red
  Write-Host "  $script" -ForegroundColor Red
  Write-Host "Demarrage automatique NON installe : lance ce script en administrateur (tache planifiee)." -ForegroundColor Red
  exit 1
}
if ($relu) {
  Write-Host "OK : lancement au démarrage installé (dossier Démarrage, sans admin)." -ForegroundColor Green
  Write-Host "  -> $cmd"
  Write-Host "Tester maintenant : & `"$script`""
} else {
  Write-Host "ECHEC : impossible d'écrire dans le dossier Démarrage." -ForegroundColor Red
  exit 1
}
