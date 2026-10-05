@echo off
setlocal EnableExtensions
title Installation de Jarvis
cd /d "%~dp0"
rem Installation de Jarvis sur Windows 11, en double-clic.
rem  1. uv (gestionnaire Python officiel d'Astral) via winget s'il manque ;
rem  2. Python 3.13 et les dependances aux versions exactes de uv.lock (uv sync) ;
rem  3. Chromium pour les fonctions navigateur ;
rem  4. l'assistant de configuration (scripts\setup.py), qui garde config.yaml.
rem Rien d'autre n'est telecharge : uniquement des paquets winget officiels et
rem les dependances declarees par le projet. Aucune cle n'est demandee ici.

echo.
echo ============================================================
echo              INSTALLATION DE JARVIS
echo ============================================================
echo.

set "ARM64=0"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARM64=1"
if /I "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "ARM64=1"
if "%ARM64%"=="1" call :note_arm64

call "%~dp0scripts\trouver_uv.bat"
if defined UV goto :uv_pret
where winget >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] uv est absent et winget est indisponible.
    echo Installe uv depuis https://docs.astral.sh/uv/ puis relance ce fichier.
    goto :echec
)
echo uv est absent : installation avec winget ^(paquet officiel astral-sh.uv^)...
winget install --id astral-sh.uv -e --source winget --accept-source-agreements --accept-package-agreements
call "%~dp0scripts\trouver_uv.bat"
if not defined UV (
    echo [ERREUR] uv vient peut-etre d'etre installe, mais Windows ne le trouve pas encore.
    echo Ferme cette fenetre puis relance INSTALLER_JARVIS.bat.
    goto :echec
)

:uv_pret
echo [OK] uv : %UV%

where git >nul 2>&1
if not errorlevel 1 goto :git_pret
where winget >nul 2>&1
if errorlevel 1 (
    echo [AVERTISSEMENT] Git est absent : les mises a jour automatiques seront impossibles.
    goto :git_pret
)
echo Git est absent : installation avec winget ^(paquet officiel Git.Git^)...
winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
if errorlevel 1 echo [AVERTISSEMENT] Git n'a pas pu etre installe. L'installation continue.

:git_pret
echo.
echo [1/3] Python 3.13 et dependances (plusieurs minutes la premiere fois)...
"%UV%" sync
if errorlevel 1 (
    echo [ERREUR] Les dependances n'ont pas pu etre installees.
    echo Verifie ta connexion Internet, puis relance ce fichier.
    goto :echec
)

echo.
echo [2/3] Chromium pour les fonctions navigateur...
"%UV%" run playwright install chromium
if errorlevel 1 echo [AVERTISSEMENT] Chromium absent : seules les fonctions web en dependent.

echo.
echo [3/3] Configuration (mode, cles, test du micro et de la voix)...
"%UV%" run python scripts\setup.py --suite
if errorlevel 1 (
    echo [ERREUR] La configuration s'est interrompue. Relance ce fichier pour la reprendre.
    goto :echec
)

echo.
echo ============================================================
echo Installation terminee. Pour lancer Jarvis : lancer_jarvis.bat
echo ============================================================
choice /C ON /N /M "Lancer Jarvis maintenant ? [O]ui/[N]on : "
if errorlevel 2 goto :fin
call "%~dp0lancer_jarvis.bat"
goto :fin

:note_arm64
echo [INFO] Processeur ARM ^(Snapdragon^) : la reconnaissance vocale locale n'existe pas
echo        pour ce PC. Jarvis transcrira ta voix avec OpenAI : il faudra une cle
echo        openai.cle et un mode autre que local. La voix Piper et la recherche web
echo        DuckDuckGo sont indisponibles ici. Details : issue #14 du projet.
echo.
exit /b 0

:echec
echo.
echo Installation incomplete. Corrige le point ci-dessus puis relance ce fichier.
pause
exit /b 1

:fin
pause
exit /b 0
