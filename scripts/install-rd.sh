#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== RD Monitor Installer =="

# Python & venv
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python3 requis"; exit 1
fi
python3 -m venv "$ROOT/venv"
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
pip install --upgrade pip
pip install -r "$ROOT/requirements.txt"

# Config
mkdir -p "$ROOT/config" "$ROOT/logs"
[[ -f "$ROOT/.env" ]] || cp "$ROOT/.env.example" "$ROOT/.env"
[[ -f "$ROOT/config/config.yaml.local" ]] || cp "$ROOT/config/config.yaml" "$ROOT/config/config.yaml.local"

# Commandes shell (bashrc helper)
if ! grep -q "# RD Monitor function" "$HOME/.bashrc" 2>/dev/null; then
cat >> "$HOME/.bashrc" <<EOF
# RD Monitor function
rd-monitor() {
  local ROOT_DIR="$ROOT"
  if [ -d "\$ROOT_DIR/venv" ]; then
    # shellcheck disable=SC1091
    source "\$ROOT_DIR/venv/bin/activate"
    python "\$ROOT_DIR/rd-monitor.py" "\$@"
  else
    echo "rd-monitor non initialisé (venv manquant dans \$ROOT_DIR)"
  fi
}
EOF
echo "Commandes ajoutées à ~/.bashrc (rd-monitor)"
fi

echo "Installation OK. Lancez: source ~/.bashrc && rd-monitor"
