#!/usr/bin/env bash
# Jarvis 24/7 sur macOS : installe un LaunchAgent launchd.
#
#   ./scripts/autostart_mac.sh            installe (ou met a jour)
#   ./scripts/autostart_mac.sh --remove   retire le service
#
# Effet : Jarvis demarre au login et est RELOANCE automatiquement s'il
# plante ou s'arrete (KeepAlive). Le service tourne sous ton compte, sans
# privilegier, et ecrit ses journaux dans ~/Library/Logs/Jarvis/.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

LABEL="com.jarvis.assistant"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/Jarvis"
PROJET="$(pwd)"

mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"

if [ "${1:-}" = "--remove" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "OK : Jarvis 24/7 retire. Relance ./launch_jarvis.sh a la main si besoin."
  exit 0
fi

UV="$(command -v uv || true)"
[ -z "$UV" ] && for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" \
    /opt/homebrew/bin/uv /usr/local/bin/uv; do
  [ -x "$c" ] && UV="$c" && break
done
if [ -z "$UV" ]; then
  echo "uv est introuvable. Installe-le : curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string>
    <string>run</string>
    <string>--no-sync</string>
    <string>python</string>
    <string>jarvis14.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJET</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOGDIR/jarvis.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/jarvis.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF

# Recharge le service si deja present.
launchctl unload "$PLIST" 2>/dev/null || true
if launchctl load "$PLIST" 2>/dev/null; then
  echo "OK : Jarvis tourne des maintenant, 24h/24."
else
  echo "Echec launchctl load — verifie : launchctl list | grep jarvis"
  exit 1
fi

cat <<EOF

Service   : $LABEL
Journaux  : $LOGDIR/jarvis.log  (+ .err.log)
Commandes :
  tail -f $LOGDIR/jarvis.log        # suivre en direct
  launchctl list | grep jarvis      # etat du service
  ./scripts/autostart_mac.sh --remove   # arreter le 24/7
EOF
