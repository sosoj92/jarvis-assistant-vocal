@echo off
title Jarvis
rem Lanceur de l'assistant vocal. Le venv local est prioritaire ; uv reste
rem disponible comme solution de compatibilite pour les installations existantes.
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0jarvis14.py"
) else if exist "%USERPROFILE%\.local\bin\uv.exe" (
    "%USERPROFILE%\.local\bin\uv.exe" run python jarvis14.py
) else (
    echo [ERREUR] Jarvis n'est pas installe.
    echo Lance d'abord INSTALLER_JARVIS.bat.
)
echo.
echo Jarvis s'est arrete. Vous pouvez fermer cette fenetre.
pause
