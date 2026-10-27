#!/usr/bin/env bash
# Ancient Antiquity - restore a backup made by deploy/backup.sh into the Docker install.
# REPLACES the current database (and media, when a media archive is given).
#
#   sudo ./deploy/restore.sh                                   # list the available backups
#   sudo ./deploy/restore.sh /var/backups/ancient-antiquity/db-20261026-021500.dump [media-20261026-021500.tar.gz]
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/ancient-antiquity}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ $# -eq 0 ]; then
  echo "Backups in $BACKUP_DIR (newest first):"
  ls -1t "$BACKUP_DIR" 2>/dev/null | head -20 || echo "  none"
  echo; echo "Usage: sudo ./deploy/restore.sh <db-*.dump> [media-*.tar.gz]"
  exit 0
fi

DB_FILE="$1"; MEDIA_FILE="${2:-}"
[ -f "$DB_FILE" ] || DB_FILE="$BACKUP_DIR/$1"
[ -f "$DB_FILE" ] || { echo "Not found: $1" >&2; exit 1; }
if [ -n "$MEDIA_FILE" ]; then
  [ -f "$MEDIA_FILE" ] || MEDIA_FILE="$BACKUP_DIR/$MEDIA_FILE"
  [ -f "$MEDIA_FILE" ] || { echo "Not found: $2" >&2; exit 1; }
fi

echo "This REPLACES the live database with $(basename "$DB_FILE")${MEDIA_FILE:+ and the media with $(basename "$MEDIA_FILE")}."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = RESTORE ] || { echo "Cancelled."; exit 1; }

echo "Safety backup of the current state first..."
MODE=docker COMPOSE_DIR="$ROOT" "$ROOT/deploy/backup.sh" || echo "(safety backup failed - continuing)"

docker compose stop backend jobs
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$DB_FILE"
if [ -n "$MEDIA_FILE" ]; then
  docker compose run --rm --no-deps -T --user root backend sh -c 'rm -rf /app/media/* && tar -C /app -xzf - && chown -R app:app /app/media' < "$MEDIA_FILE"
fi
docker compose start backend jobs
echo "Restored. Migrations run on start; check with ./deploy/status.sh"
