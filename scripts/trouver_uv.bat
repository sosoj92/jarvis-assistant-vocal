@echo off
rem Renseigne UV avec le chemin de uv.exe, ou le laisse vide s'il est absent.
rem Appele par les .bat du projet (call), sans setlocal pour que UV leur revienne.
rem Ordre : installateur officiel d'Astral, puis winget, puis le PATH.
set "UV="
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" (
    set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
    exit /b 0
)
for /f "delims=" %%i in ('where uv 2^>nul') do (
    set "UV=%%i"
    exit /b 0
)
exit /b 0
