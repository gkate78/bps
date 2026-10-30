#!/usr/bin/env bash
# Run BPS for everyday local use, with data kept outside the project folder.
#   ./scripts/run_local.sh            start the app on http://127.0.0.1:8000
#   ./scripts/run_local.sh backup     back up the database only
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

echo "Data folder: $DATA_DIR"
echo "Open: http://127.0.0.1:$PORT/auth/signin"
exec "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port "$PORT"
