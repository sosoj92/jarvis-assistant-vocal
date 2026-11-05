param(
    [ValidateSet("horaire", "premier_demarrage")]
    [string]$Mode = "horaire",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = "08:00",
    [string]$NomTache = "Jarvis - Signal Matin",
    [string]$Imprimante = "",
    [switch]$Imprimer,
    [switch]$RectoVerso,
    # Duree maximale de la tache avant arret par Windows. 15 min par defaut ;
    # le brief Tech & IA (redaction puis relecture) peut demander davantage.
    [ValidateRange(5, 240)]
    [int]$DureeMaxMinutes = 15
)

$ErrorActionPreference = "Stop"
$Projet = Split-Path -Parent $PSScriptRoot

if ($Mode -eq "premier_demarrage") {
    Write-Output "Mode premier_demarrage : aucune tache Windows n'est creee."
    Write-Output "Dans config.yaml, configure :"
    Write-Output "signal_matin:"
    Write-Output "  actif: true"
    Write-Output "  declenchement: premier_demarrage"
    Write-Output "  imprimer: true"
    Write-Output "  recto_verso: $($RectoVerso.IsPresent.ToString().ToLower())"
    if ($Imprimante) {
        Write-Output "  imprimante: `"$Imprimante`""
    }
    Write-Output "Jarvis imprimera en arriere-plan avec son premier brief du jour (une seule tentative par jour pour ce mode)."
    # Ce mode ne retire pas une tache horaire deja installee : on la signale
    # sans la modifier, sinon le journal serait imprime deux fois chaque matin.
    $tacheExistante = Get-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue
    $argumentsTache = @($tacheExistante | ForEach-Object { $_.Actions } | ForEach-Object { $_.Arguments }) -join " "
    if ($tacheExistante -and "$($tacheExistante.State)" -ne "Disabled" -and $argumentsTache -match '-Imprimer') {
        Write-Warning "La tache planifiee '$NomTache' imprime deja Signal Matin chaque matin : avec premier_demarrage, le journal serait imprime deux fois."
        Write-Warning "Pour la desactiver : Disable-ScheduledTask -TaskName `"$NomTache`""
        Write-Warning "Pour la supprimer : Unregister-ScheduledTask -TaskName `"$NomTache`" -Confirm:`$false"
    }
    exit 0
}

$uv = Get-Command uv.exe -ErrorAction SilentlyContinue
$python = Get-Command python.exe -ErrorAction SilentlyContinue

if ($uv) {
    $moteur = "-UvExe `"$($uv.Source)`""
} elseif ($python) {
    $moteur = "-PythonExe `"$($python.Source)`""
} else {
    throw "Ni uv.exe ni python.exe n'est disponible dans le PATH."
}

$runner = Join-Path $PSScriptRoot "executer_signal_matin_planifie.ps1"
$executable = (Get-Command powershell.exe -ErrorAction Stop).Source
$printArgs = if ($Imprimer) { " -Imprimer" } else { "" }
$imprimanteArgs = if ($Imprimer -and $Imprimante) { " -Imprimante `"$Imprimante`"" } else { "" }
$duplexArgs = if ($Imprimer -and $RectoVerso) { " -RectoVerso" } else { "" }
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Projet `"$Projet`" $moteur$printArgs$imprimanteArgs$duplexArgs"
$action = New-ScheduledTaskAction -Execute $executable -Argument $arguments -WorkingDirectory $Projet
$trigger = New-ScheduledTaskTrigger -Daily -At $Heure
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $DureeMaxMinutes)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $NomTache `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $(if ($Imprimer) { "Genere et imprime Signal Matin chaque matin." } else { "Genere Signal Matin chaque matin sans imprimer." }) `
    -Force | Out-Null

$actionLabel = if ($Imprimer -and $RectoVerso) {
    "generation + impression recto verso"
} elseif ($Imprimer) {
    "generation + impression recto simple"
} else {
    "generation seule"
}
Write-Output "Tache installee : $NomTache a $Heure ($actionLabel), compte $env:USERNAME"
