# Configure la VM Hyper-V Jarvis pour demarrer avec Windows et conserver son
# etat lors de l'arret de l'hote. Ce script doit etre execute en administrateur.
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$VmName = "Jarvis-Server"
)

if ($VmName -notmatch '^[A-Za-z0-9._ -]{1,64}$') {
    throw "Nom de VM invalide."
}

$logs = Join-Path (Split-Path $PSScriptRoot -Parent) "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$resultFile = Join-Path $logs "hyperv-autostart-result.txt"

try {
    $ErrorActionPreference = "Stop"
    Import-Module Hyper-V

    $vm = Get-VM -Name $VmName -ErrorAction Stop
    $fallbackTask = ""
    try {
        Set-VM -VM $vm `
            -AutomaticStartAction Start `
            -AutomaticStartDelay 30
        Unregister-ScheduledTask -TaskName "JarvisServerVMStart" `
            -Confirm:$false -ErrorAction SilentlyContinue
    } catch {
        # Certains hotes Hyper-V renvoient 0x80041001 pour Set-VM alors que la
        # VM fonctionne. Dans ce cas, une tache SYSTEM bornee a Start-VM fournit
        # le meme resultat sans modifier le stockage ou le reseau de la VM.
        $taskName = "JarvisServerVMStart"
        $command = "Import-Module Hyper-V; Start-VM -Name '$VmName' -ErrorAction SilentlyContinue"
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
            "-NoProfile -WindowStyle Hidden -Command `"$command`"")
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = "PT30S"
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
            -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $taskName -Action $action `
            -Trigger $trigger -Principal $principal -Settings $settings `
            -Description "Demarre uniquement la VM Hyper-V Jarvis-Server au boot." `
            -Force | Out-Null
        $fallbackTask = $taskName
    }

    $updated = Get-VM -Name $VmName
    $result = @(
        "VM=$($updated.Name)"
        "STATE=$($updated.State)"
        "AUTO_START=$($updated.AutomaticStartAction)"
        "START_DELAY=$($updated.AutomaticStartDelay)"
        "AUTO_STOP=$($updated.AutomaticStopAction)"
        "FALLBACK_TASK=$fallbackTask"
    )
    $result | Set-Content -Encoding utf8 $resultFile
    $result
} catch {
    "ERROR=$($_.Exception.Message)" | Set-Content -Encoding utf8 $resultFile
    throw
}
