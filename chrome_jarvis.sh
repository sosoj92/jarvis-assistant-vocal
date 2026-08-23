#!/usr/bin/env bash
# Lance Chrome avec le port de débogage pour que Jarvis puisse t'assister
# (macOS / Linux). Équivalent de « Chrome + Jarvis.bat » / Chrome-Jarvis.ps1.
#
# Depuis Chrome 136+, le débogage est interdit sur le profil par défaut : on
# utilise donc un profil dédié « ChromeJarvis ». Connecte-toi une fois à tes
# sites dedans, ça reste mémorisé.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

PORT="${JARVIS_CHROME_PORT:-9222}"

if [ "$(uname -s)" = "Darwin" ]; then
  PROFIL="${JARVIS_CHROME_PROFIL:-$HOME/Library/Application Support/ChromeJarvis}"
  CANDIDATS=(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "/Applications/Chromium.app/Contents/MacOS/Chromium"
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  )
else
  PROFIL="${JARVIS_CHROME_PROFIL:-${XDG_DATA_HOME:-$HOME/.local/share}/ChromeJarvis}"
  CANDIDATS=()
  for nom in google-chrome google-chrome-stable chromium chromium-browser; do
    chemin="$(command -v "$nom" 2>/dev/null)" && CANDIDATS+=("$chemin")
  done
fi

CHROME=""
for c in "${CANDIDATS[@]:-}"; do
  [ -n "$c" ] && [ -x "$c" ] && { CHROME="$c"; break; }
done

if [ -z "$CHROME" ]; then
  echo "Chrome introuvable. Installe Google Chrome, ou modifie ce script." >&2
  exit 1
fi

# Déjà lancé ? (port de débogage déjà ouvert)
if command -v nc >/dev/null 2>&1 && nc -z localhost "$PORT" 2>/dev/null; then
  echo "Chrome + Jarvis tourne déjà (port $PORT). Rien à faire."
  exit 0
fi

echo "Lancement de Chrome + Jarvis (profil dédié, port $PORT)..."
"$CHROME" --remote-debugging-port="$PORT" --user-data-dir="$PROFIL" &
disown 2>/dev/null || true
