#!/usr/bin/env bash
# Ancient Antiquity - nightly backup: PostgreSQL dump + uploaded media, kept for 14 days.
#
# Plain VM:   DATABASE_URL=postgres://ancient:pw@localhost:5432/ancient_antiquity \
#             MEDIA_DIR=/srv/ancient-antiquity/media  ./deploy/backup.sh
# Docker:     MODE=docker COMPOSE_DIR=/srv/ancient-antiquity ./deploy/backup.sh
#
# Options (environment variables):
#   BACKUP_DIR      where archives go               (default /var/backups/ancient-antiquity)
#   KEEP_DAYS       days to keep                    (default 14)
#   MODE            vm | docker                     (default vm)
#   DATABASE_URL    vm mode: Postgres URL           (default: read from backend/.env next to this script)
#   MEDIA_DIR       vm mode: media folder           (default /srv/ancient-antiquity/media)
#   COMPOSE_DIR     docker mode: folder with docker-compose.yml (default: repo root)
#
# Copy the archives off the server too (e.g. rclone/aws s3 sync to object storage) - a backup on the
# same disk does not survive losing the VM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ancient-antiquity}"
KEEP_DAYS="${KEEP_DAYS:-14}"
MODE="${MODE:-vm}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077

DB_FILE="$BACKUP_DIR/db-$STAMP.dump"
MEDIA_FILE="$BACKUP_DIR/media-$STAMP.tar.gz"

log() { echo "$(date '+%F %T') $*"; }

if [ "$MODE" = "docker" ]; then
  COMPOSE_DIR="${COMPOSE_DIR:-$ROOT_DIR}"
  cd "$COMPOSE_DIR"
  log "Dumping database (docker)..."
  docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' > "$DB_FILE"
  log "Archiving media (docker volume)..."
  docker compose exec -T backend tar -C /app -czf - media > "$MEDIA_FILE"
else
  if [ -z "${DATABASE_URL:-}" ] && [ -f "$ROOT_DIR/backend/.env" ]; then
    DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ROOT_DIR/backend/.env" | tail -n1 | cut -d= -f2-)"
  fi
  : "${DATABASE_URL:?Set DATABASE_URL (postgres://user:pass@host:5432/db)}"
  MEDIA_DIR="${MEDIA_DIR:-/srv/ancient-antiquity/media}"
  log "Dumping database..."
  pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --file="$DB_FILE"
  log "Archiving media..."
  tar -C "$(dirname "$MEDIA_DIR")" -czf "$MEDIA_FILE" "$(basename "$MEDIA_DIR")"
fi

# A dump that is suspiciously small usually means something failed.
if [ ! -s "$DB_FILE" ] || [ "$(stat -c %s "$DB_FILE")" -lt 1024 ]; then
  log "ERROR: database dump $DB_FILE is empty or too small" >&2
  exit 1
fi

log "Removing backups older than $KEEP_DAYS days..."
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'media-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete

log "Done: $(du -h "$DB_FILE" | cut -f1) database, $(du -h "$MEDIA_FILE" | cut -f1) media in $BACKUP_DIR"
