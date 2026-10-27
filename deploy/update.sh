#!/usr/bin/env bash
# Ancient Antiquity - update a Docker install to the latest code (backup first, migrations run automatically).
#
#   ./deploy/update.sh               # backup, git pull, rebuild, restart, health check
#   ./deploy/update.sh --no-pull     # code already copied (deploy/windows/deploy-to-server.ps1) or only .env changed
#   ./deploy/update.sh --no-backup   # skip the backup (not recommended)
set -euo pipefail

PULL=1 BACKUP=1
for a in "$@"; do
  case "$a" in
    --no-pull) PULL=0 ;;
    --no-backup) BACKUP=0 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
SUDO=$([ "$(id -u)" -eq 0 ] && echo "" || echo sudo)

sed -i 's/\r$//' deploy/*.sh 2>/dev/null && chmod +x deploy/*.sh || true

if [ "$BACKUP" = 1 ] && docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  step "Backup"
  $SUDO env MODE=docker COMPOSE_DIR="$ROOT" "$ROOT/deploy/backup.sh"
fi

if [ "$PULL" = 1 ]; then
  if [ -d .git ]; then
    step "Get the latest code"
    git pull --ff-only
  else
    echo "Not a git checkout - copy the new code here first (or use --no-pull)."
  fi
fi

step "Rebuild and restart (database migrations run on start)"
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null

step "Health check"
DOMAIN="$(grep -E '^DOMAIN=' .env 2>/dev/null | cut -d= -f2- || true)"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null -H "Host: ${DOMAIN:-localhost}" "http://127.0.0.1/api/support/health/"; then
    docker compose ps
    printf '\n\033[1;32mUpdated and healthy.\033[0m\n'
    exit 0
  fi
  sleep 5
done
docker compose ps
docker compose logs --tail=80 backend
echo "The API is not healthy (logs above). To go back: sudo ./deploy/restore.sh <latest db-*.dump in /var/backups/ancient-antiquity>" >&2
exit 1
