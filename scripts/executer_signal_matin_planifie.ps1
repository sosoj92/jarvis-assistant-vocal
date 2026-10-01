param(
    [string]$Projet = (Split-Path -Parent $PSScriptRoot),
    [string]$UvExe = "",
    [string]$PythonExe = "",
    [string]$Imprimante = "",
    [switch]$Imprimer,
    [switch]$RectoVerso
)

$ErrorActionPreference = "Continue"
$logDirectory = Join-Path $Projet "output\logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$logPath = Join-Path $logDirectory "signal-matin-$stamp.log"

$commandArguments = @()
if ($UvExe) {
    $executable = $UvExe
    $commandArguments += @("run", "--project", $Projet, "generate-morning-paper")
} elseif ($PythonExe) {
    $executable = $PythonExe
    $commandArguments += @("-m", "core.signal_matin.cli")
} else {
    throw "Renseigne -UvExe ou -PythonExe."
}

$commandArguments += $(if ($Imprimer) { @("print", "--confirm") } else { "generate" })
if ($Imprimer -and $Imprimante) {
    $commandArguments += @("--printer", $Imprimante)
}
if ($Imprimer -and $RectoVerso) {
    $commandArguments += "--duplex"
}

Set-Location $Projet
"[$(Get-Date -Format o)] Debut Signal Matin" | Out-File -LiteralPath $logPath -Encoding utf8
$output = & $executable @commandArguments 2>&1
$exitCode = $LASTEXITCODE
$output | Out-File -LiteralPath $logPath -Append -Encoding utf8
"[$(Get-Date -Format o)] Fin Signal Matin - code $exitCode" |
    Out-File -LiteralPath $logPath -Append -Encoding utf8

exit $exitCode
