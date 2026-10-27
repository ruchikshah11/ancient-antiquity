#!/usr/bin/env bash
# Ancient Antiquity - one-screen health report for a Docker install.
#   ./deploy/status.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DOMAIN="$(grep -E '^DOMAIN=' .env 2>/dev/null | cut -d= -f2-)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ancient-antiquity}"
ok() { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; }

echo "Containers:"
docker compose ps --format 'table {{.Service}}\t{{.Status}}'

echo; echo "Checks:"
curl -fsS -o /dev/null -H "Host: ${DOMAIN:-localhost}" http://127.0.0.1/api/support/health/ && ok "API + database" || bad "API + database (docker compose logs backend)"
if grep -q '^COMPOSE_FILE=.*ssl' .env 2>/dev/null; then
  curl -fsS -o /dev/null "https://$DOMAIN/" && ok "https://$DOMAIN" || bad "https://$DOMAIN (docker compose logs frontend)"
  END="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMAIN" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
  [ -n "$END" ] && ok "certificate valid until $END"
else
  echo "  --   HTTPS not set up (plain http)"
fi
LAST="$(ls -1t "$BACKUP_DIR"/db-*.dump 2>/dev/null | head -1)"
if [ -n "$LAST" ] && [ -n "$(find "$LAST" -mtime -2 2>/dev/null)" ]; then ok "last backup $(basename "$LAST")"; else bad "no backup in the last 2 days ($BACKUP_DIR)"; fi
FREE="$(df -h / | awk 'NR==2 {print $4 " free (" $5 " used)"}')"
USED="$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')"
[ "${USED:-0}" -lt 85 ] && ok "disk $FREE" || bad "disk $FREE"

echo; echo "Last job runs:"
docker compose logs --no-log-prefix --tail=8 jobs 2>/dev/null | sed 's/^/  /'
