#!/usr/bin/env bash
# Envoie tes dernières modifications sur GitHub en une commande (macOS / Linux).
# Équivalent de sauvegarder_jarvis.bat.
#
# Ajoute tout, crée un commit daté, puis pousse. Les fichiers sensibles
# (config.yaml, memoire.json, voix...) restent exclus via .gitignore.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

# shellcheck source=commun.sh
source "./scripts/commun.sh"

titre "Sauvegarde de Jarvis sur GitHub"

echouer() {
  echo
  echo "Échec de la sauvegarde (pas d'internet ? connexion GitHub expirée ?)."
  echo "Tes fichiers locaux sont intacts. Tu peux réessayer plus tard."
  pause_si_interactif
  exit 1
}

git add -A || echouer

# S'il n'y a rien de nouveau, on s'arrête proprement.
if git diff --cached --quiet; then
  echo "Rien de nouveau à sauvegarder. Tout est déjà à jour."
  pause_si_interactif
  exit 0
fi

git commit -m "Sauvegarde du $(date '+%d/%m/%Y %H:%M:%S')" || echouer

echo
echo "Envoi vers GitHub..."
git push || echouer

echo
echo "Sauvegarde terminée avec succès."
pause_si_interactif
