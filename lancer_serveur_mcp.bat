@echo off
title Serveur MCP Jarvis
rem Lance le serveur MCP de Jarvis en mode HTTP (serveur autonome : les clients
rem MCP distants s'y connectent). Pour Claude Desktop en local, pas besoin de ce
rem raccourci : Claude Desktop lance le serveur lui-meme (stdio). Voir docs/mcp.md.
rem uv est cherche comme dans les autres lanceurs (installateur Astral, winget, PATH).
cd /d "%~dp0"
git pull --ff-only 2>nul
set JARVIS_MCP_TRANSPORT=http
call "%~dp0scripts\trouver_uv.bat"
rem Pas d'etiquette goto ici : sans CRLF, cmd.exe saute parfois les etiquettes.
if not defined UV (
    echo [ERREUR] uv est introuvable : lance d'abord INSTALLER_JARVIS.bat.
) else (
    "%UV%" run python -m jarvis.mcp_server
)
echo.
echo Le serveur MCP s'est arrete. Vous pouvez fermer cette fenetre.
pause
