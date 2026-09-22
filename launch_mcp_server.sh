#!/usr/bin/env bash
# Serveur MCP de Jarvis en mode HTTP (macOS / Linux).
# Équivalent de lancer_serveur_mcp.bat.
#
# Serveur autonome : les clients MCP distants s'y connectent. Pour Claude
# Desktop en local, pas besoin de ce script — Claude Desktop lance le serveur
# lui-même (stdio). Voir docs/mcp.md.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

# shellcheck source=commun.sh
source "./scripts/commun.sh"

titre "Serveur MCP Jarvis"
maj_git_silencieuse

UV="$(trouver_uv)" || {
  echo "uv est introuvable. Installe-le :"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  pause_si_interactif
  exit 1
}

export JARVIS_MCP_TRANSPORT=http
"$UV" run python -m jarvis.mcp_server
code=$?

echo
echo "Le serveur MCP s'est arrêté (code $code)."
pause_si_interactif
exit $code
