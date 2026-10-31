#!/usr/bin/env bash
# Run BPS for everyday local use, with data kept outside the project folder.
#   ./scripts/run_local.sh            start the app on http://127.0.0.1:8000 (this computer only)
#   ./scripts/run_local.sh lan        also accept other computers on the shop network
#   ./scripts/run_local.sh backup     back up the database only
# "lan" needs the one-time Windows setup in scripts/windows-network-setup.ps1.
# Data folder defaults to ~/bps-data (override with BPS_DATA_DIR).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${BPS_DATA_DIR:-$HOME/bps-data}"
PORT="${PORT:-8000}"
PYTHON="$PROJECT_DIR/venv/bin/python"

mkdir -p "$DATA_DIR"
cd "$PROJECT_DIR"

if [[ ! -x "$PYTHON" ]]; then
    echo "venv not found. Run: python3 -m venv venv && venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# Settings live in $DATA_DIR/.env; create it once with a random session secret.
if [[ ! -f "$DATA_DIR/.env" ]]; then
    {
        echo "SESSION_SECRET=$("$PYTHON" -c 'import secrets; print(secrets.token_hex(32))')"
        echo "OTP_PROVIDER=local"
        echo "COMMS_PROVIDER=local"
    } > "$DATA_DIR/.env"
    chmod 600 "$DATA_DIR/.env"
    echo "Created $DATA_DIR/.env"
fi
set -a
# shellcheck disable=SC1091
source "$DATA_DIR/.env"
set +a
export DATABASE_DIR="$DATA_DIR"

"$PYTHON" scripts/backup_db.py --db "$DATA_DIR/bills_admin.db" --keep "${BPS_BACKUP_KEEP:-30}"

if [[ "${1:-}" == "backup" ]]; then
    exit 0
fi

HOST=127.0.0.1
if [[ "${1:-}" == "lan" ]]; then
    HOST=0.0.0.0
fi

echo "Data folder: $DATA_DIR"
echo "Open on this computer: http://127.0.0.1:$PORT/auth/signin"
if [[ "$HOST" == "0.0.0.0" ]]; then
    if command -v wslinfo >/dev/null && [[ "$(wslinfo --networking-mode 2>/dev/null)" != "mirrored" ]]; then
        # In WSL's default NAT mode the addresses here are internal and unreachable from other devices.
        echo "Note: WSL is not in mirrored networking mode, so other devices can't connect yet."
        echo "      Run scripts/windows-network-setup.ps1 as Administrator once, then 'wsl --shutdown'."
    else
        for ip in $(hostname -I 2>/dev/null); do
            case "$ip" in
                100.*) echo "Open from your Tailscale devices: http://$ip:$PORT/auth/signin" ;;
                10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) echo "Open from shop computers:        http://$ip:$PORT/auth/signin" ;;
            esac
        done
    fi
fi
exec "$PYTHON" -m uvicorn main:app --host "$HOST" --port "$PORT"
