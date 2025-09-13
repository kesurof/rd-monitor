#!/usr/bin/env bash
# Wrapper to run rd_single_fix.py using an isolated venv.
# Preference order for Python executable:
# 1) $RD_VENV_PATH if set and executable
# 2) $HOME/.venvs/rd-monitor/bin/python
# 3) ./ .venv/bin/python (project venv)
# 4) system python3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="${SCRIPT_DIR%/scripts}"

PYTHON=${RD_VENV_PATH:-}
if [ -n "$PYTHON" ] && [ -x "$PYTHON" ]; then
    echo "Using RD_VENV_PATH: $PYTHON" >&2
else
    CAND="$HOME/.venvs/rd-monitor/bin/python"
    if [ -x "$CAND" ]; then
        PYTHON="$CAND"
    else
        CAND="$ROOT_DIR/.venv/bin/python"
        if [ -x "$CAND" ]; then
            PYTHON="$CAND"
        else
            PYTHON=$(command -v python3 || true) || PYTHON=/usr/bin/python3
        fi
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "No python interpreter found" >&2
    exit 2
fi

# execute the script with passed args
exec "$PYTHON" "$ROOT_DIR/scripts/rd_single_fix.py" "$@"
