#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE}")/.." && pwd)"

echo "== RD Monitor Uninstall =="

# service
if systemctl list-units | grep -q rd-monitor.service; then
  sudo systemctl stop rd-monitor.service || true
  sudo systemctl disable rd-monitor.service || true
  sudo rm -f /etc/systemd/system/rd-monitor.service
  sudo systemctl daemon-reload
fi

# remove bashrc helper
sed -i '/^# RD Monitor function$/,/^}$/d' "$HOME/.bashrc" || true

# delete install dir if it's under scripts path (adjust to your layout)
echo "Suppression non automatique du répertoire (sécurité). Supprimez à la main si nécessaire."
echo "Désinstallation terminée."
