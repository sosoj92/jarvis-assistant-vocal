[CmdletBinding(DefaultParameterSetName = "Dans")]
param(
    [Parameter(Mandatory, ParameterSetName = "Dans")]
    [ValidateRange(1, 10080)]
    [int]$DansMinutes,

    [Parameter(Mandatory, ParameterSetName = "Heure")]
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Heure,

    [string]$TacheSource = "Jarvis - Signal Matin",
    [string]$NomTache = "Jarvis - Signal Matin - impression ponctuelle"
)

$ErrorActionPreference = "Stop"

$source = Get-ScheduledTask -TaskName $TacheSource -ErrorAction Stop
$sourceAction = @($source.Actions)[0]
if (-not $sourceAction) {
    throw "La tache source ne contient aucune action."
}
if ([string]$sourceAction.Arguments -notmatch '(?i)(^|\s)-Imprimer(\s|$)') {
    throw "La tache source n'est pas configuree pour imprimer."
}

$maintenant = Get-Date
if ($PSCmdlet.ParameterSetName -eq "Dans") {
    $execution = $maintenant.AddMinutes($DansMinutes)
} else {
    $morceaux = $Heure.Split(':')
    $execution = Get-Date -Hour ([int]$morceaux[0]) -Minute ([int]$morceaux[1]) -Second 0
    if ($execution -le $maintenant.AddSeconds(10)) {
        $execution = $execution.AddDays(1)
    }
}

# Copier l'action reelle evite une tache imbriquee qui peut echouer sous un
# jeton Windows limite tout en renvoyant un faux code de succes.
$actionParams = @{
    Execute = [string]$sourceAction.Execute
}
if ($sourceAction.Arguments) {
    $actionParams.Argument = [string]$sourceAction.Arguments
}
if ($sourceAction.WorkingDirectory) {
    $actionParams.WorkingDirectory = [string]$sourceAction.WorkingDirectory
}
$action = New-ScheduledTaskAction @actionParams

$trigger = New-ScheduledTaskTrigger -Once -At $execution
$trigger.EndBoundary = $execution.AddHours(1).ToString('s')
# Meme duree maximale que la tache quotidienne (allongee pour le Brief Tech & IA) ;
# 15 min si elle est absente, illisible ou illimitee (PT0S).
$dureeMax = New-TimeSpan -Minutes 15
$limiteSource = [string]$source.Settings.ExecutionTimeLimit
if ($limiteSource) {
    try {
        $lue = [System.Xml.XmlConvert]::ToTimeSpan($limiteSource)
        if ($lue -gt [TimeSpan]::Zero) {
            $dureeMax = $lue
        }
    } catch {
        # Valeur illisible : on garde 15 min.
    }
}
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DeleteExpiredTaskAfter (New-TimeSpan -Minutes 10) `
    -ExecutionTimeLimit $dureeMax

Register-ScheduledTask `
    -TaskName $NomTache `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $source.Principal `
    -Description "Impression ponctuelle de Signal Matin." `
    -Force | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $NomTache
[pscustomobject]@{
    Tache = $NomTache
    Execution = $info.NextRunTime
    RectoVerso = [bool]([string]$sourceAction.Arguments -match '(?i)(^|\s)-RectoVerso(\s|$)')
}
