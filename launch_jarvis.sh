#!/usr/bin/env bash
# Lanceur de l'assistant vocal (macOS / Linux). Équivalent de lancer_jarvis.bat.
#
#   ./launch_jarvis.sh
#
# Se place dans le dossier du projet, met à jour le code si possible, puis
# démarre jarvis14.py via uv. Le chemin d'uv est cherché explicitement : lancé
# depuis le Finder ou un élément d'ouverture, le PATH n'est pas celui du
# Terminal et « uv » seul serait introuvable.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

# shellcheck source=commun.sh
source "./scripts/commun.sh"

titre "Jarvis"
maj_git_silencieuse

UV="$(trouver_uv)" || {
  echo "uv est introuvable. Installe-le :"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "Puis relance ce script."
  pause_si_interactif
  exit 1
}

"$UV" run python jarvis14.py
code=$?

echo
if [ $code -eq 0 ]; then
  echo "Jarvis s'est arrêté. Tu peux fermer cette fenêtre."
else
  echo "Jarvis s'est arrêté avec le code $code."
  echo "Diagnostic :  $UV run python scripts/doctor.py"
fi
pause_si_interactif
exit $code
