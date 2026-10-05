@echo off
title Jarvis
rem Lanceur de l'assistant vocal. Se place dans le dossier du projet, recupere
rem la derniere version si Git est la, puis demarre jarvis14.py via uv. uv est
rem cherche par chemin absolu pour fonctionner aussi au demarrage de Windows,
rem ou le PATH peut differer.
cd /d "%~dp0"
git pull --ff-only 2>nul
call "%~dp0scripts\trouver_uv.bat"
if not defined UV (
    echo [ERREUR] uv est introuvable : lance d'abord INSTALLER_JARVIS.bat.
    goto :fin
)
"%UV%" run python jarvis14.py
:fin
echo.
echo Jarvis s'est arrete. Vous pouvez fermer cette fenetre.
pause
