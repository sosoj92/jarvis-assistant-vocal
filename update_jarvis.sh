#!/usr/bin/env bash
# Met à jour les bibliothèques Python du projet vers leurs dernières versions
# compatibles, puis synchronise l'environnement (macOS / Linux).
# Équivalent de mettre_a_jour_jarvis.bat.
#
# À lancer quand on le souhaite — pas à chaque démarrage : une nouvelle version
# demande internet et peut parfois casser quelque chose.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

# shellcheck source=commun.sh
source "./scripts/commun.sh"

titre "Mise à jour des dépendances de Jarvis"

UV="$(trouver_uv)" || {
  echo "uv est introuvable. Installe-le :"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  pause_si_interactif
  exit 1
}

echouer() {
  echo
  echo "Échec de la mise à jour (pas d'internet ? conflit de versions ?)."
  echo "L'ancienne version reste utilisable : Jarvis fonctionne toujours."
  pause_si_interactif
  exit 1
}

echo "[1/2] Recherche des dernières versions..."
"$UV" lock --upgrade || echouer

echo
echo "[2/2] Installation..."
"$UV" sync || echouer

echo
echo "Mise à jour terminée. Tu peux relancer Jarvis."
pause_si_interactif
