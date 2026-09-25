#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '\n[Jarvis Server] %s\n' "$*"
}

fail() {
  printf '\n[Jarvis Server] ERREUR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || fail "Lance ce script avec sudo."

TARGET_USER="${SUDO_USER:-}"
[[ -n ${TARGET_USER} && ${TARGET_USER} != root ]] || \
  fail "Lance ce script avec sudo depuis le compte applicatif (pas directement en root)."
getent passwd "${TARGET_USER}" >/dev/null || fail "Utilisateur introuvable: ${TARGET_USER}"
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"

# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == "ubuntu" ]] || fail "Ce script attend Ubuntu."
CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
[[ -n ${CODENAME} ]] || fail "Version Ubuntu impossible a determiner."

export DEBIAN_FRONTEND=noninteractive

log "Installation des outils de base"
apt-get update
apt-get install -y \
  ca-certificates \
  curl \
  git \
  gnupg \
  jq \
  ufw \
  fail2ban \
  unattended-upgrades \
  avahi-daemon

log "Ajout du depot officiel Docker"
install -m 0755 -d /etc/apt/keyrings
docker_key_tmp="$(mktemp)"
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "${docker_key_tmp}"
install -m 0644 "${docker_key_tmp}" /etc/apt/keyrings/docker.asc
rm -f "${docker_key_tmp}"

cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

log "Ajout du depot officiel Tailscale"
tailscale_key_tmp="$(mktemp)"
tailscale_list_tmp="$(mktemp)"
curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${CODENAME}.noarmor.gpg" -o "${tailscale_key_tmp}"
curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${CODENAME}.tailscale-keyring.list" -o "${tailscale_list_tmp}"
install -m 0644 "${tailscale_key_tmp}" /usr/share/keyrings/tailscale-archive-keyring.gpg
install -m 0644 "${tailscale_list_tmp}" /etc/apt/sources.list.d/tailscale.list
rm -f "${tailscale_key_tmp}" "${tailscale_list_tmp}"

log "Installation de Docker Engine, Compose et Tailscale"
apt-get update
apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin \
  tailscale

if [[ ! -e /etc/docker/daemon.json ]]; then
  cat >/etc/docker/daemon.json <<'EOF'
{
  "live-restore": true,
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
else
  log "Configuration Docker existante conservee: /etc/docker/daemon.json"
fi

log "Creation de l'arborescence /opt/jarvis"
install -d -m 0755 /opt/jarvis
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 0755 /opt/jarvis/code
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 0700 /opt/jarvis/config
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 0750 /opt/jarvis/data
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 0750 /opt/jarvis/backups
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 0750 /opt/jarvis/logs

cat >/opt/jarvis/SERVER_LAYOUT.md <<'EOF'
# Jarvis Server

- `code/` : code deploye, sans secrets
- `config/` : configuration locale privee, jamais versionnee
- `data/` : donnees persistantes
- `backups/` : sauvegardes locales temporaires
- `logs/` : journaux applicatifs avec rotation

Le PC Windows conserve le micro, la camera, l'ecran, la domotique et les
identifiants. Cette VM execute uniquement les services de fond compatibles
Linux. Aucun port Docker ne doit etre publie sur toutes les interfaces sans
regle explicite.
EOF
chown root:root /opt/jarvis/SERVER_LAYOUT.md
chmod 0644 /opt/jarvis/SERVER_LAYOUT.md

log "Activation des mises a jour de securite sans redemarrage automatique"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
cat >/etc/apt/apt.conf.d/52jarvis-no-auto-reboot <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
EOF

log "Pare-feu et services"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

systemctl enable --now ssh
systemctl enable --now fail2ban
systemctl enable --now avahi-daemon
systemctl enable --now containerd
systemctl enable --now docker
systemctl enable --now tailscaled
systemctl restart docker

log "Installation systeme terminee"
printf 'Utilisateur applicatif : %s\n' "${TARGET_USER}"
printf 'Dossier serveur         : /opt/jarvis\n'
printf 'Docker                  : %s\n' "$(docker --version)"
printf 'Docker Compose          : %s\n' "$(docker compose version)"
printf 'Tailscale               : %s\n' "$(tailscale version | head -n 1)"
printf 'Etape suivante          : connexion Tailscale, puis installation Python 3.13\n'
