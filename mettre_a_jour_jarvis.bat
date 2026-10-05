@echo off
title Mise a jour de Jarvis
rem Met a jour les bibliotheques Python du projet vers leurs dernieres
rem versions compatibles, puis synchronise l'environnement. A lancer
rem quand on le souhaite (pas a chaque demarrage : une nouvelle version
rem peut demander internet et parfois casser quelque chose).
cd /d "%~dp0"

echo ============================================
echo   Mise a jour des dependances de Jarvis
echo ============================================
echo.

call "%~dp0scripts\trouver_uv.bat"
if not defined UV (
    echo uv est introuvable : lance d'abord INSTALLER_JARVIS.bat.
    goto erreur
)

echo [1/2] Recherche des dernieres versions...
"%UV%" lock --upgrade
if errorlevel 1 goto erreur

echo.
echo [2/2] Installation...
"%UV%" sync
if errorlevel 1 goto erreur

echo.
echo Mise a jour terminee. Vous pouvez relancer Jarvis.
echo.
pause
exit /b 0

:erreur
echo.
echo Echec de la mise a jour (pas d'internet ? conflit de versions ?).
echo L'ancienne version reste utilisable : Jarvis fonctionne toujours.
echo.
pause
exit /b 1
