param(
    [switch]$NoStart,
    [switch]$SkipGestures
)

$ErrorActionPreference = "Stop"
$AgentDir = $PSScriptRoot
$Config = Join-Path $AgentDir "config.yaml"
$Python = Join-Path $AgentDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Config)) {
    throw "Copie d'abord config.example.yaml en config.yaml et renseigne les deux tokens."
}
if (-not (Test-Path -LiteralPath $Python)) {
    py -3.12 -m venv (Join-Path $AgentDir ".venv")
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $AgentDir "requirements.txt")

# Les gestes utilisent volontairement un Python/venv séparé : MediaPipe ne doit
# pas imposer ses contraintes au micro, à l'overlay ou à l'agent principal.
if (-not $SkipGestures) {
    $env:Path = (Join-Path $AgentDir ".venv\Scripts") + ";" + $env:Path
    & $Python (Join-Path $AgentDir "..\scripts\setup_gestes.py")
}

$Startup = [Environment]::GetFolderPath("Startup")
$Launcher = Join-Path $Startup "Jarvis-Bureau.cmd"
$LogDir = Join-Path $AgentDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Commande = '@echo off' + "`r`n" +
    'cd /d "' + $AgentDir + '"' + "`r`n" +
    '"' + $Python + '" "' + (Join-Path $AgentDir "jarvis_desktop_agent.py") +
    '" >> "' + (Join-Path $LogDir "agent.log") + '" 2>&1' + "`r`n"
[IO.File]::WriteAllText($Launcher, $Commande, [Text.UTF8Encoding]::new($false))
Write-Host "Agent installe au demarrage de Windows : $Launcher"

if (-not $NoStart) {
    Start-Process -FilePath $Launcher -WindowStyle Hidden
    Write-Host "Agent Jarvis Bureau lance."
}
