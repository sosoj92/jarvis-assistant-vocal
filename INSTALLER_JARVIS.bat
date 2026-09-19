@echo off
setlocal EnableExtensions
title Installation de Jarvis
cd /d "%~dp0"

set "ERREUR=0"
set "PYTHON="
set "PYTHON_ARGS="
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

echo.
echo ============================================================
echo              INSTALLATION DE JARVIS
echo ============================================================
echo Ce script prepare Jarvis sans modifier tes cles ni ton config.yaml.
echo Les erreurs restent affichees dans cette fenetre.
echo.

call :trouver_python
if defined PYTHON goto :python_trouve

echo Python est absent. Tentative d'installation avec winget...
where winget >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] winget est indisponible. Installe Python 3.13 depuis https://www.python.org/downloads/windows/
    set "ERREUR=1"
    goto :fin
)
winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo [ERREUR] L'installation de Python a echoue.
    set "ERREUR=1"
    goto :fin
)
call :trouver_python
if not defined PYTHON (
    echo [ERREUR] Python vient peut-etre d'etre installe, mais Windows ne le trouve pas encore.
    echo Ferme puis relance ce fichier, ou redemarre ta session Windows.
    set "ERREUR=1"
    goto :fin
)

:python_trouve
echo [OK] Python detecte.

where git >nul 2>&1
if not errorlevel 1 (
    echo [OK] Git detecte.
) else (
    echo Git est absent. Tentative d'installation avec winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo [AVERTISSEMENT] winget est indisponible : Git sera necessaire pour les mises a jour.
    ) else (
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
        if errorlevel 1 (
            echo [AVERTISSEMENT] Git n'a pas pu etre installe. L'installation continue.
        ) else (
            echo [OK] Git installe.
        )
    )
)

if exist "%~dp0config.yaml" (
    echo [OK] config.yaml existe deja : il est conserve.
) else (
    if not exist "%~dp0config.example.yaml" (
        echo [ERREUR] config.example.yaml est introuvable.
        set "ERREUR=1"
        goto :fin
    )
    copy /Y "%~dp0config.example.yaml" "%~dp0config.yaml" >nul
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer config.yaml.
        set "ERREUR=1"
        goto :fin
    )
    echo [OK] config.yaml cree depuis config.example.yaml.
    echo     Tu peux ajouter tes cles plus tard dans config.yaml.
)

if not exist "%VENV_PY%" (
    echo Creation de l'environnement Python local .venv...
    "%PYTHON%" %PYTHON_ARGS% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer .venv.
        set "ERREUR=1"
        goto :fin
    )
)
echo [OK] Environnement Python pret.

echo Mise a jour de pip...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERREUR] Mise a jour de pip echouee.
    set "ERREUR=1"
    goto :fin
)

echo Installation des dependances (cela peut prendre plusieurs minutes)...
if not exist "%~dp0requirements.txt" (
    echo [ERREUR] requirements.txt est introuvable.
    set "ERREUR=1"
    goto :fin
)
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERREUR] Certaines dependances n'ont pas pu etre installees.
    echo Verifie ta connexion Internet, puis relance ce script.
    set "ERREUR=1"
    goto :fin
)
echo [OK] Dependances Python installees.

echo Installation du navigateur Playwright Chromium...
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 (
    echo [AVERTISSEMENT] Chromium n'a pas pu etre installe.
    echo Le navigateur est necessaire uniquement pour les fonctions web.
) else (
    echo [OK] Chromium installe.
)

:fin
echo.
if "%ERREUR%"=="1" (
    echo ============================================================
    echo Installation incomplete : corrige l'erreur ci-dessus puis
    echo relance INSTALLER_JARVIS.bat.
    echo ============================================================
    pause
    exit /b 1
)

echo ============================================================
echo Installation terminee.
echo ============================================================
echo Tu peux modifier config.yaml si tu veux utiliser une cle API.
choice /C ON /N /M "Lancer Jarvis maintenant ? [O]ui/[N]on : "
if errorlevel 2 goto :ne_pas_lancer
if errorlevel 1 (
    echo.
    echo Demarrage de Jarvis. Appuie sur Ctrl+C pour l'arreter.
    "%VENV_PY%" "%~dp0jarvis14.py"
    if errorlevel 1 echo [ERREUR] Jarvis s'est arrete avec une erreur.
    pause
    exit /b
)

:ne_pas_lancer
echo.
echo Pour lancer Jarvis plus tard : lancer_jarvis.bat
pause
exit /b 0

:trouver_python
set "PYTHON="
set "PYTHON_ARGS="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.13 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py"
        set "PYTHON_ARGS=-3.13"
        exit /b 0
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python"
        exit /b 0
    )
)
exit /b 0
