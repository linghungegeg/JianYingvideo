#!/usr/bin/env bash
set -euo pipefail

ADMIN_USERNAME="admin"
ADMIN_EMAIL="admin@example.com"
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage: bash scripts/bootstrap_server.sh --admin admin --email admin@example.com

Creates venv, installs requirements.server.txt, copies server_auth.env.example
when .env is missing, validates required secrets, runs migrations, and creates
an admin user. It does not restart systemd or modify Nginx.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --admin)
      ADMIN_USERNAME="${2:-}"
      shift 2
      ;;
    --email)
      ADMIN_EMAIL="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

step() {
  echo
  echo "==> $1"
}

env_value() {
  local key="$1"
  local line
  if [[ ! -f .env ]]; then
    return 0
  fi
  line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
  printf "%s" "${line#*=}"
}

is_placeholder() {
  local key="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    return 0
  fi
  case "${value}" in
    your-*|base64-32-byte-urlsafe-key|*USER:PASSWORD*|*change-in-production*)
      return 0
      ;;
  esac
  return 1
}

step "Create virtual environment"
if [[ ! -x "venv/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv venv
else
  echo "venv already exists, skipped."
fi

VENV_PYTHON="${ROOT_DIR}/venv/bin/python"

step "Install server dependencies"
"${VENV_PYTHON}" -m pip install -r requirements.server.txt

step "Prepare .env"
if [[ ! -f .env ]]; then
  cp env.presets/server_auth.env.example .env
  echo ".env created from env.presets/server_auth.env.example."
  echo "Edit .env with real secrets and database URL, then run this script again."
fi

step "Validate required server configuration"
missing=0
for key in SECRET_KEY VIDEOFACTORY_KEY_ENCRYPTION_KEY DATABASE_URL; do
  value="$(env_value "${key}")"
  if is_placeholder "${key}" "${value}"; then
    echo "Invalid or placeholder value: ${key}" >&2
    missing=1
  fi
done
if [[ "${missing}" -ne 0 ]]; then
  echo "Server .env is not ready. Fill real values before migrations or admin creation." >&2
  exit 1
fi

step "Run database migrations"
"${VENV_PYTHON}" -m flask db upgrade

step "Create or repair admin user"
"${VENV_PYTHON}" scripts/create_admin.py --username "${ADMIN_USERNAME}" --email "${ADMIN_EMAIL}"

echo
echo "Server bootstrap complete. Start behind Nginx with:"
echo "venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app"
