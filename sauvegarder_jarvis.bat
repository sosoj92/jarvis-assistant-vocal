@echo off
title Sauvegarder Jarvis
rem Envoie tes dernieres modifications sur GitHub en un clic :
rem ajoute tout, cree un commit date, puis pousse. Les fichiers sensibles
rem (config.yaml, .env, memoire.json, notes/, voix/...) restent exclus via
rem .gitignore ; verifie quand meme le diff (git status) avant de pousser.
cd /d "%~dp0"

echo ============================================
echo   Sauvegarde de Jarvis sur GitHub
echo ============================================
echo.

git add -A

rem S'il n'y a rien de nouveau, on s'arrete proprement.
git diff --cached --quiet
if not errorlevel 1 (
    echo Rien de nouveau a sauvegarder. Tout est deja a jour.
    echo.
    pause
    exit /b 0
)

git commit -m "Sauvegarde du %DATE% %TIME%"
if errorlevel 1 goto erreur

echo.
echo Envoi vers GitHub...
git push
if errorlevel 1 goto erreur

echo.
echo Sauvegarde terminee avec succes.
echo.
pause
exit /b 0

:erreur
echo.
echo Echec de la sauvegarde (pas d'internet ? connexion GitHub expiree ?).
echo Tes fichiers locaux sont intacts. Tu peux reessayer plus tard.
echo.
pause
exit /b 1
