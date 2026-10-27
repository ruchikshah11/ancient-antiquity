#!/usr/bin/env bash
# Ancient Antiquity - one-command install on a fresh Ubuntu 22.04/24.04 server (Docker).
#
#   sudo ./deploy/install.sh --domain tickets.example.in --email you@example.in
#   sudo ./deploy/install.sh --domain 203.0.113.10 --no-https        # quick trial on the server's IP
#
# What it does (safe to run again - every step skips what is already done):
#   1. installs Docker, sets the India time zone, opens ports 22/80/443 if ufw is active
#   2. creates backend/.env with a generated SECRET_KEY and database password (an existing .env is kept)
#   3. builds and starts the stack: PostgreSQL, API, job runner, nginx + React
#   4. first time only: loads the places catalogue and asks for your admin account
#   5. gets a Let's Encrypt certificate and switches nginx to HTTPS
#   6. installs /etc/cron.d/ancient-antiquity: nightly backup + certificate renewal
#
# Options:
#   --domain NAME        site domain (or the server IP together with --no-https)        [required]
#   --email ADDRESS      for Let's Encrypt expiry notices                                [required for HTTPS]
#   --no-https           plain http only (testing); can be re-run later without it
#   --catalogue MODE     full (default: all places, photos, sample add-ons/plans/passes/shows), places, none
#   --skip-admin         don't ask for the admin account (create it later: see the summary)
#
# Secrets you add yourself afterwards in backend/.env (email, Razorpay, SMS...): see DEPLOY.md, then run
#   ./deploy/update.sh --no-pull
set -euo pipefail

DOMAIN="" EMAIL="" HTTPS=1 CATALOGUE=full ASK_ADMIN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --no-https) HTTPS=0; shift ;;
    --catalogue) CATALOGUE="${2:-}"; shift 2 ;;
    --skip-admin) ASK_ADMIN=0; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo: sudo ./deploy/install.sh --domain ... --email ..."
[ -n "$DOMAIN" ] || die "--domain is required (see --help)"
case "$CATALOGUE" in full|places|none) ;; *) die "--catalogue must be full, places or none" ;; esac
if [[ "$DOMAIN" =~ ^[0-9.]+$ ]] && [ "$HTTPS" = 1 ]; then
  die "Let's Encrypt needs a domain name, not an IP. Use --no-https for an IP-only trial."
fi
[ "$HTTPS" = 0 ] || [ -n "$EMAIL" ] || die "--email is required for HTTPS (or use --no-https)"
SCHEME=$([ "$HTTPS" = 1 ] && echo https || echo http)

# Files from a Windows PC can have CRLF line endings, which break bash.
sed -i 's/\r$//' deploy/*.sh && chmod +x deploy/*.sh

# ---------------------------------------------------------------------------------------------- 1. server
step "1/6 Server: Docker, time zone, firewall"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing (apt install docker-compose-plugin)"
systemctl enable --now docker >/dev/null 2>&1 || true
timedatectl set-timezone Asia/Kolkata 2>/dev/null || true
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then usermod -aG docker "$SUDO_USER" || true; fi

# ---------------------------------------------------------------------------------------------- 2. settings
step "2/6 Settings: backend/.env"
ENV=backend/.env
set_env() {  # set_env KEY VALUE - replace or append a line in backend/.env
  if grep -qE "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi
}
if [ ! -f "$ENV" ]; then
  SECRET="$(openssl rand -base64 60 | tr -dc 'A-Za-z0-9' | head -c 60)"
  DBPASS="$(openssl rand -hex 24)"
  cat > "$ENV" <<EOF
# Ancient Antiquity - production settings (created by deploy/install.sh on $(date +%F)). Keep this file private.
DEBUG=False
SECRET_KEY=$SECRET
ALLOWED_HOSTS=$DOMAIN
POSTGRES_PASSWORD=$DBPASS
DATABASE_URL=postgres://ancient:$DBPASS@db:5432/ancient_antiquity
CORS_ALLOWED_ORIGINS=$SCHEME://$DOMAIN
CSRF_TRUSTED_ORIGINS=$SCHEME://$DOMAIN
FRONTEND_URL=$SCHEME://$DOMAIN
SECURE_SSL_REDIRECT=$([ "$HTTPS" = 1 ] && echo True || echo False)
SECURE_HSTS_SECONDS=3600

# ---- Fill these in yourself (see DEPLOY.md), then run: ./deploy/update.sh --no-pull ----
# Without EMAIL_HOST emails are only written to the log; without Razorpay keys the DEMO gateway is used.
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=
SUPPORT_EMAIL=
SUPPORT_PHONE=
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
SMS_PROVIDER=console
SMS_API_KEY=
SMS_SENDER_ID=
INVOICE_SELLER_NAME=
INVOICE_SELLER_ADDRESS=
INVOICE_SELLER_GSTIN=
ADMIN_EMAILS=
SENTRY_DSN=
GOOGLE_MAPS_API_KEY=
ANTHROPIC_API_KEY=
EOF
  echo "created $ENV with a new SECRET_KEY and database password"
else
  echo "keeping the existing $ENV"
  # Re-running with/without HTTPS or a new domain updates only these values.
  set_env ALLOWED_HOSTS "$DOMAIN"
  set_env CORS_ALLOWED_ORIGINS "$SCHEME://$DOMAIN"
  set_env CSRF_TRUSTED_ORIGINS "$SCHEME://$DOMAIN"
  set_env FRONTEND_URL "$SCHEME://$DOMAIN"
  [ "$HTTPS" = 1 ] || set_env SECURE_SSL_REDIRECT False
fi
chmod 600 "$ENV"

# Root .env: read by docker compose itself (domain for the HTTPS template, which compose files to use).
touch .env
sed -i '/^DOMAIN=/d;/^COMPOSE_FILE=/d' .env
echo "DOMAIN=$DOMAIN" >> .env
if [ "$HTTPS" = 1 ] && [ -f "/var/lib/docker/volumes/ancient-antiquity_letsencrypt/_data/live/$DOMAIN/fullchain.pem" ]; then
  echo "COMPOSE_FILE=docker-compose.yml:docker-compose.ssl.yml" >> .env
fi

# ---------------------------------------------------------------------------------------------- 3. start
step "3/6 Build and start (first build takes a few minutes)"
docker compose up -d --build --remove-orphans

wait_healthy() {
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null -H "Host: $DOMAIN" "http://127.0.0.1/api/support/health/"; then return 0; fi
    sleep 5
  done
  docker compose ps; docker compose logs --tail=60 backend
  die "the API did not become healthy (logs above)"
}
wait_healthy
echo "API is healthy"

# ---------------------------------------------------------------------------------------------- 4. first data
step "4/6 Data"
manage() { docker compose exec -T backend python manage.py "$@"; }
PLACES="$(manage shell -c 'from museums.models import Museum; print(Museum.objects.count())' | tail -n1)"
if [ "${PLACES:-0}" = "0" ] && [ "$CATALOGUE" != none ]; then
  echo "Empty database: loading the places catalogue..."
  manage seed_india
  manage enrich_museums
  echo "Adding the other listed museums with their Wikipedia text (takes several minutes)..."
  manage import_listed_museums museums/data/listed_museums.json --wiki || warn "Wikipedia import stopped; re-run later: docker compose exec backend python manage.py import_listed_museums museums/data/listed_museums.json --wiki"
  manage fetch_more_photos
  manage seed_holidays
  manage seed_virtual_tours
  if [ "$CATALOGUE" = full ]; then
    manage seed_addons
    manage seed_memberships
    manage seed_passes
    manage seed_events
    warn "Add-ons, Heritage Card plans, passes and show prices are SAMPLE values - set real ones in the admin before going live."
  fi
  manage rebuild_stats
else
  echo "Database already has $PLACES places - nothing loaded."
fi

ADMINS="$(manage shell -c 'from django.contrib.auth import get_user_model as g; print(g().objects.filter(is_superuser=True).count())' | tail -n1)"
if [ "${ADMINS:-0}" = "0" ]; then
  if [ "$ASK_ADMIN" = 1 ] && [ -t 0 ]; then
    echo "Create your admin account:"
    docker compose exec backend python manage.py createsuperuser
  else
    warn "No admin account yet. Create one with: docker compose exec backend python manage.py createsuperuser"
  fi
fi

# ---------------------------------------------------------------------------------------------- 5. https
step "5/6 HTTPS"
if [ "$HTTPS" = 1 ]; then
  if ! grep -q '^COMPOSE_FILE=' .env; then
    docker compose --profile certbot run --rm certbot certonly --webroot -w /var/www/certbot \
      -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive \
      || die "certificate request failed - check that DNS for $DOMAIN points to this server and port 80 is open, then run this script again"
    echo "COMPOSE_FILE=docker-compose.yml:docker-compose.ssl.yml" >> .env
  fi
  docker compose up -d frontend
  sleep 3
  curl -fsS -o /dev/null "https://$DOMAIN/api/support/health/" && echo "HTTPS works" \
    || warn "https://$DOMAIN did not answer yet - check: docker compose logs frontend"
else
  echo "skipped (--no-https)"
fi

# ---------------------------------------------------------------------------------------------- 6. cron
step "6/6 Nightly backup and certificate renewal"
mkdir -p /var/backups/ancient-antiquity && chmod 700 /var/backups/ancient-antiquity
{
  echo "# Ancient Antiquity (installed by deploy/install.sh). App jobs run in the 'jobs' container, not here."
  echo "SHELL=/bin/bash"
  echo "15 2 * * * root MODE=docker COMPOSE_DIR=$ROOT $ROOT/deploy/backup.sh >> /var/log/ancient-antiquity-backup.log 2>&1"
  if [ "$HTTPS" = 1 ]; then
    echo "17 3,15 * * * root cd $ROOT && docker compose --profile certbot run --rm certbot renew --quiet && docker compose exec -T frontend nginx -s reload >> /var/log/ancient-antiquity-certbot.log 2>&1"
  fi
} > /etc/cron.d/ancient-antiquity
chmod 644 /etc/cron.d/ancient-antiquity
echo "backups go to /var/backups/ancient-antiquity (14 days kept) - copy them off this server too"

cat <<EOF

$(printf '\033[1;32m')Ancient Antiquity is running: $SCHEME://$DOMAIN$(printf '\033[0m')

  Admin:        $SCHEME://$DOMAIN/admin  (and $SCHEME://$DOMAIN/django-admin/)
  Settings:     $ROOT/backend/.env   - add email, Razorpay, SMS keys, then ./deploy/update.sh --no-pull
  Update:       ./deploy/update.sh            Status:  ./deploy/status.sh
  Backup now:   sudo MODE=docker ./deploy/backup.sh      Restore: sudo ./deploy/restore.sh <db-file>
  Logs:         docker compose logs -f backend jobs frontend
  New admin:    docker compose exec backend python manage.py createsuperuser
  Photos:       after adding GOOGLE_MAPS_API_KEY: docker compose exec backend python manage.py find_google_places
EOF
