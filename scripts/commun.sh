#!/usr/bin/env bash
# Fonctions partagées par les lanceurs bash (launch_jarvis.sh & co).
# Ce fichier n'est pas exécutable : il se `source`.

# Titre encadré, comme les .bat sous Windows.
titre() {
  echo "============================================"
  echo "  $1"
  echo "============================================"
  echo
}

# Chemin d'uv. Cherché explicitement car, lancé depuis le Finder ou un élément
# d'ouverture de session, le PATH n'est pas celui du Terminal.
trouver_uv() {
  local c
  for c in "$UV_BIN" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" \
           /opt/homebrew/bin/uv /usr/local/bin/uv; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  c="$(command -v uv 2>/dev/null)" && { echo "$c"; return 0; }
  return 1
}

# Mise à jour du code, sans bruit et sans jamais bloquer le lancement :
# pas de réseau, pas de dépôt git, modifications locales -> on continue.
maj_git_silencieuse() {
  git rev-parse --git-dir >/dev/null 2>&1 || return 0
  git pull --ff-only >/dev/null 2>&1 || true
}

# Garde la fenêtre ouverte quand le script est lancé par double-clic (Finder),
# mais ne bloque jamais un lancement automatique ou un pipeline.
pause_si_interactif() {
  [ -t 0 ] || return 0
  [ -n "${JARVIS_SANS_PAUSE:-}" ] && return 0
  read -r -p "Appuie sur Entrée pour fermer..." _ || true
}

# UV_BIN peut être défini par l'utilisateur pour forcer un uv précis.
: "${UV_BIN:=}"
