param(
    [ValidateSet("horaire", "premier_demarrage")]
    [string]$Mode = "horaire",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure = "08:00",
    [string]$NomTache = "Jarvis - Signal Matin",
    [string]$Imprimante = "",
    [switch]$Imprimer,
    [switch]$RectoVerso
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
    Write-Output "Jarvis imprimera en arriere-plan avec son premier brief du jour, une seule fois."
    exit 0
}

$uv = Get-Command uv.exe -ErrorAction SilentlyContinue
$python = Get-Command python.exe -ErrorAction SilentlyContinue

if ($uv) {
    $executable = $uv.Source
    $commande = if ($Imprimer) { "print --confirm" } else { "generate" }
    $imprimanteArgs = if ($Imprimer -and $Imprimante) { " --printer `"$Imprimante`"" } else { "" }
    $duplexArgs = if ($Imprimer -and $RectoVerso) { " --duplex" } else { "" }
    $arguments = "run --project `"$Projet`" generate-morning-paper $commande$imprimanteArgs$duplexArgs"
} elseif ($python) {
    $executable = $python.Source
    $commande = if ($Imprimer) { "print --confirm" } else { "generate" }
    $imprimanteArgs = if ($Imprimer -and $Imprimante) { " --printer `"$Imprimante`"" } else { "" }
    $duplexArgs = if ($Imprimer -and $RectoVerso) { " --duplex" } else { "" }
    $arguments = "-m core.signal_matin.cli $commande$imprimanteArgs$duplexArgs"
} else {
    throw "Ni uv.exe ni python.exe n'est disponible dans le PATH."
}

$action = New-ScheduledTaskAction -Execute $executable -Argument $arguments -WorkingDirectory $Projet
$trigger = New-ScheduledTaskTrigger -Daily -At $Heure
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
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
