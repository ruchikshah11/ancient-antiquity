# Deploying Ancient Antiquity

## Quick start (one command)

You need an Ubuntu 22.04/24.04 server (2 vCPU / 4 GB RAM is plenty) and a domain whose DNS `A` record points to it.

**From your Windows PC** (uses the built-in `ssh`/`scp`; the PC must be able to `ssh ubuntu@<server>`):

```powershell
# first time: installs Docker, creates the settings with generated secrets, loads the places, asks for your admin
# account, gets the HTTPS certificate, sets up nightly backups
.\deploy\windows\deploy-to-server.ps1 -Server ubuntu@203.0.113.10 -Domain tickets.example.in -Email you@example.in

# every later update: backup, upload, rebuild, restart, health check
.\deploy\windows\deploy-to-server.ps1 -Server ubuntu@203.0.113.10
```

**Or on the server itself** (code cloned or copied to `/srv/ancient-antiquity`):

```bash
sudo ./deploy/install.sh --domain tickets.example.in --email you@example.in   # first time
./deploy/update.sh                                                            # later: backup, git pull, rebuild
```

Then put your own secrets in `backend/.env` on the server (email, Razorpay, SMS, invoice details - see the
[checklist](#environment-checklist-backendenv)) and apply them with `./deploy/update.sh --no-pull`.

| Script | What it does |
|---|---|
| `deploy/install.sh` | First install (safe to re-run). `--no-https` for a trial on the server IP, `--catalogue places\|none` to load less data, `--skip-admin`. |
| `deploy/update.sh` | Backup, `git pull` (skip with `--no-pull`), rebuild, restart, health check. |
| `deploy/status.sh` | Containers, API/database, HTTPS and certificate expiry, last backup, disk, last job runs. |
| `deploy/backup.sh` | Database dump + media archive to `/var/backups/ancient-antiquity` (runs nightly at 02:15 via `/etc/cron.d/ancient-antiquity`). |
| `deploy/restore.sh` | Lists backups; `sudo ./deploy/restore.sh <db-file> [media-file]` restores (makes a safety backup first). |
| `deploy/windows/deploy-to-server.ps1` | Packages this folder (never `.env` files, the local database, backups, logs or demo passwords), uploads it and runs install/update. `-PackageOnly` just builds the `.tar.gz`. |
| `deploy/windows/setup-dev.ps1` | Sets up a new Windows development PC (venv, packages, SQLite `.env`, places + demo data, npm, background tasks). |
| `deploy/windows/register-tasks.ps1` | Registers the PC's background jobs in Task Scheduler. They run hidden with `pythonw.exe` (no console window); `-Remove` deletes them. |

**Background jobs.** On a server the `jobs` container (`backend/scripts/run_jobs.py`, India time) runs:
recovery emails every 15 minutes, "visit starts soon" reminders hourly, next-day reminders at 18:00, pending exports
hourly, statistics at 02:30 and session cleanup on Sundays. See them with `docker compose logs -f jobs` or
`docker compose exec jobs python scripts/run_jobs.py --list`.

The rest of this guide explains the same steps by hand.

---

Two ways to run the site in production:

- **A. Docker on a VM** (recommended): PostgreSQL, the Django API and nginx with the React build each run in a container (`docker-compose.yml`).
- **B. Plain Ubuntu VM**: PostgreSQL, gunicorn (systemd) and nginx are installed directly on the server (`deploy/`).

Both serve everything from **one domain**, for example `https://tickets.example.in`:

| Path | Served by |
|---|---|
| `/` and every page | React build (`index.html`, single-page app fallback) |
| `/assets/…` | React build, cached for a year (hashed file names) |
| `/api/…` | Django REST API (gunicorn) |
| `/django-admin/…` | Django admin |
| `/static/…` | Django admin CSS/JS (WhiteNoise / `collectstatic`) |
| `/media/…` | Uploaded place photos |

> **HTTPS is mandatory.** Browsers only allow camera access (QR scanning at the gate) on HTTPS, Razorpay webhooks must be HTTPS, and with `DEBUG=False` Django sends cookies only over HTTPS and redirects HTTP to HTTPS.

---

## 0. Before you start

1. **Server**: Ubuntu 22.04/24.04 VM in India (e.g. Mumbai/Hyderabad region), 2 vCPU / 4 GB RAM / 40 GB disk is plenty to start. Open ports **22, 80, 443** only.
2. **DNS**: create an `A` record (and `AAAA` if you have IPv6) for your domain pointing to the VM's public IP. Wait until `nslookup tickets.example.in` returns the IP; Let's Encrypt needs it.
3. **Accounts you need**: SMTP email (Amazon SES, SendGrid, Zoho, …), Razorpay account with **live** keys (KYC done), optionally an SMS provider (MSG91/Twilio).
4. **Legal pages**: `/terms`, `/privacy`, `/refund-policy` are *templates*. Replace every `[placeholder]` (company name, address, GSTIN, grievance officer…) in `frontend/src/pages/client/Legal.tsx` and have a lawyer review them. Razorpay checks these pages during activation.

### Environment checklist (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and set (see its *Production* section):

| Variable | Production value |
|---|---|
| `DEBUG` | `False` |
| `SECRET_KEY` | 50+ random characters: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`. The app **refuses to start** with the development default or a short key. |
| `ALLOWED_HOSTS` | `tickets.example.in` (comma-separated, no scheme) |
| `DATABASE_URL` | `postgres://ancient:<db-password>@db:5432/ancient_antiquity` (Docker) or `@localhost:5432/…` (VM) |
| `POSTGRES_PASSWORD` | Docker only: same password as in `DATABASE_URL` (used to create the database) |
| `CORS_ALLOWED_ORIGINS` | `https://tickets.example.in` |
| `CSRF_TRUSTED_ORIGINS` | `https://tickets.example.in` (needed for the Django admin login) |
| `FRONTEND_URL` | `https://tickets.example.in` (links in emails) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | your SMTP provider. Without `EMAIL_HOST`, emails are only printed to the log! |
| `SUPPORT_EMAIL`, `SUPPORT_PHONE` | shown on the Contact page; contact-form messages are emailed to `SUPPORT_EMAIL` |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | **live** keys (`rzp_live_…`). Without keys the demo gateway is used — never go live like that. |
| `RAZORPAY_WEBHOOK_SECRET` | from Razorpay → Settings → Webhooks (see below) |
| `SMS_PROVIDER`, `SMS_API_KEY`, `SMS_SENDER_ID` (or `TWILIO_*`) | SMS/WhatsApp provider; `console` only logs |
| `INVOICE_SELLER_NAME`, `INVOICE_SELLER_ADDRESS`, `INVOICE_SELLER_GSTIN`, `INVOICE_GST_PERCENT` | printed on GST invoices |
| `REFUND_FULL_BEFORE_HOURS` | refund cut-off (default 24) — the Refund policy page shows this value automatically |
| `SECURE_SSL_REDIRECT` | `True` (set `False` only while testing over plain HTTP) |
| `SECURE_HSTS_SECONDS` | starts at `3600`; raise to `31536000` once HTTPS works everywhere |
| `GOOGLE_MAPS_API_KEY` | Google Cloud → enable **Places API (New)** → API key restricted to that API and the server IP. Places without a free photo then show Google Maps photos (credited to the photographer); run `docker compose exec backend python manage.py find_google_places` once after adding it. |
| `ADMIN_EMAILS` | optional: where server errors (HTTP 500) are emailed |

**Razorpay webhook**: Razorpay Dashboard → Account & Settings → Webhooks → *Add*: URL `https://tickets.example.in/api/payments/razorpay/webhook/`, events `payment.captured`, `refund.processed`, `refund.failed`, a strong secret → copy it into `RAZORPAY_WEBHOOK_SECRET`. Webhooks only work on a public HTTPS URL.

---

## A. Docker on a VM

### A1. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out and back in
sudo timedatectl set-timezone Asia/Kolkata
```

### A2. Get the code

```bash
sudo mkdir -p /srv/ancient-antiquity && sudo chown $USER /srv/ancient-antiquity
git clone <your-repo-url> /srv/ancient-antiquity      # or copy the folder with scp/rsync
cd /srv/ancient-antiquity
```

### A3. Configure

```bash
cp backend/.env.example backend/.env
nano backend/.env        # fill in the Production section (checklist above); DATABASE_URL host = db
chmod 600 backend/.env
```

Minimum for a first start:

```
DEBUG=False
SECRET_KEY=<generated>
ALLOWED_HOSTS=tickets.example.in
POSTGRES_PASSWORD=<strong-db-password>
DATABASE_URL=postgres://ancient:<strong-db-password>@db:5432/ancient_antiquity
CORS_ALLOWED_ORIGINS=https://tickets.example.in
CSRF_TRUSTED_ORIGINS=https://tickets.example.in
FRONTEND_URL=https://tickets.example.in
```

### A4. Build and start

```bash
docker compose up -d --build
docker compose ps                    # db healthy, backend + frontend running
docker compose logs -f backend       # migrations run automatically on start
```

The site now answers on **http://** (port 80). Django will redirect to https, which does not work yet — that is expected until A6. (To test over plain HTTP first, set `SECURE_SSL_REDIRECT=False` temporarily and `docker compose up -d backend`.)

### A5. First-time data

```bash
docker compose exec backend python manage.py seed_india          # places, states, cities, categories
docker compose exec backend python manage.py createsuperuser     # your real admin account
```

- **Do NOT use `seed_india --demo-users` in production.** If demo accounts were ever created on this database (e.g. it came from a demo machine), delete them or change their passwords in `/django-admin/` → Users.
- Optional: `docker compose exec backend python manage.py enrich_museums` (applies the bundled Wikipedia data).

### A6. HTTPS with Let's Encrypt

```bash
# 1. Issue the certificate (nginx is already serving /.well-known/acme-challenge/ on port 80)
docker compose --profile certbot run --rm certbot certonly --webroot -w /var/www/certbot \
    -d tickets.example.in --email you@example.in --agree-tos --no-eff-email

# 2. Switch nginx to HTTPS: add to the root .env (next to docker-compose.yml)
#      DOMAIN=tickets.example.in
#      COMPOSE_FILE=docker-compose.yml:docker-compose.ssl.yml
docker compose up -d frontend

# 3. Check
curl -I https://tickets.example.in/api/support/health/
```

Renewal: add the certbot line from `deploy/cron.example` to the host crontab (renews and reloads nginx).

*Alternative*: if a cloud load balancer or Cloudflare terminates HTTPS in front of the VM, skip A6 — the container's port-80 config forwards the `X-Forwarded-Proto` header it receives. Make sure only the proxy can reach port 80.

### A7. Updating

```bash
cd /srv/ancient-antiquity
./deploy/backup.sh   # with MODE=docker, see Backups
git pull
docker compose up -d --build          # migrations run on backend start
docker image prune -f
```

The service worker (`sw.js`) is served with `no-cache`, so visitors get the new version on their next visit.

### A8. Useful commands

```bash
docker compose logs -f --tail=200 backend frontend
docker compose exec backend python manage.py shell
docker compose exec db psql -U ancient ancient_antiquity
docker compose restart backend
```

---

## B. Plain Ubuntu VM (no Docker)

### B1. Packages

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-dev nginx certbot \
     postgresql postgresql-contrib git curl
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install -y nodejs
sudo timedatectl set-timezone Asia/Kolkata
```

(Use Python 3.11+; on Ubuntu 22.04 install `python3.12` from the deadsnakes PPA if you want the same version as the Docker image.)

### B2. Database

```bash
sudo -u postgres psql -c "CREATE USER ancient WITH PASSWORD '<strong-db-password>';"
sudo -u postgres psql -c "CREATE DATABASE ancient_antiquity OWNER ancient;"
```

### B3. App user and code

```bash
sudo adduser --system --group --home /srv/ancient-antiquity ancient
sudo usermod -aG www-data ancient
sudo git clone <your-repo-url> /srv/ancient-antiquity/app-tmp && sudo rsync -a /srv/ancient-antiquity/app-tmp/ /srv/ancient-antiquity/ && sudo rm -rf /srv/ancient-antiquity/app-tmp
sudo mkdir -p /srv/ancient-antiquity/media
sudo chown -R ancient:www-data /srv/ancient-antiquity
```

### B4. Backend

```bash
cd /srv/ancient-antiquity/backend
sudo -u ancient python3 -m venv .venv
sudo -u ancient .venv/bin/pip install -r requirements.txt
sudo -u ancient cp .env.example .env && sudo -u ancient nano .env
#   DATABASE_URL=postgres://ancient:<pw>@localhost:5432/ancient_antiquity
#   MEDIA_ROOT=/srv/ancient-antiquity/media      + the checklist above
sudo chmod 600 .env
sudo -u ancient .venv/bin/python manage.py check --deploy
sudo -u ancient .venv/bin/python manage.py migrate
sudo -u ancient .venv/bin/python manage.py collectstatic --noinput
sudo -u ancient .venv/bin/python manage.py seed_india           # NOT --demo-users
sudo -u ancient .venv/bin/python manage.py createsuperuser
```

### B5. gunicorn service

```bash
sudo cp /srv/ancient-antiquity/deploy/systemd/ancient-antiquity.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ancient-antiquity
systemctl status ancient-antiquity
curl -H "Host: tickets.example.in" http://127.0.0.1:8000/api/support/health/
```

Background jobs (recovery emails, visit reminders, statistics, exports):

```bash
sudo cp /srv/ancient-antiquity/deploy/systemd/ancient-antiquity-jobs.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ancient-antiquity-jobs
```

### B6. Frontend build

```bash
cd /srv/ancient-antiquity/frontend
sudo -u ancient npm ci && sudo -u ancient npm run build     # -> frontend/dist
```

### B7. nginx + HTTPS

```bash
# certificate first (the stock "default" nginx site serves /var/www/html on port 80)
sudo certbot certonly --webroot -w /var/www/html -d tickets.example.in \
     --email you@example.in --agree-tos --no-eff-email --deploy-hook "systemctl reload nginx"

sudo cp /srv/ancient-antiquity/deploy/nginx/ancient-antiquity.conf /etc/nginx/sites-available/ancient-antiquity
sudo sed -i 's/tickets.example.in/YOUR-DOMAIN/g' /etc/nginx/sites-available/ancient-antiquity
sudo ln -s /etc/nginx/sites-available/ancient-antiquity /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run
```

On Ubuntu 22.04 (nginx 1.18) change `listen 443 ssl;` + `http2 on;` to `listen 443 ssl http2;`.

### B8. Updating

```bash
cd /srv/ancient-antiquity
sudo -u ancient ./deploy/backup.sh       # see Backups
sudo -u ancient git pull
cd backend && sudo -u ancient .venv/bin/pip install -r requirements.txt \
  && sudo -u ancient .venv/bin/python manage.py migrate \
  && sudo -u ancient .venv/bin/python manage.py collectstatic --noinput
cd ../frontend && sudo -u ancient npm ci && sudo -u ancient npm run build
sudo systemctl restart ancient-antiquity ancient-antiquity-jobs
```

---

## Moving the local demo data (optional)

The development database is SQLite (`backend/db.sqlite3`). You normally start production fresh with `seed_india`. To carry over places you edited locally instead (load into an **empty** database — skip `seed_india` — to avoid ID clashes):

```bash
# on your PC (DEBUG=True, sqlite); reviews are excluded because they belong to (demo) users
python manage.py dumpdata museums --exclude museums.Review --indent 2 -o museums.json
# copy museums.json (and the backend/media/ folder for photos) to the server, then:
docker compose cp museums.json backend:/tmp/museums.json
docker compose exec backend python manage.py loaddata /tmp/museums.json
# VM: sudo -u ancient .venv/bin/python manage.py loaddata museums.json
```

Avoid copying `accounts` (demo users and passwords) and test bookings.

---

## Backups and restore

`deploy/backup.sh` writes a PostgreSQL dump (`db-YYYYmmdd-HHMMSS.dump`, custom format) and a media archive (`media-….tar.gz`) to `/var/backups/ancient-antiquity` and deletes files older than 14 days (`KEEP_DAYS`).

```bash
sudo mkdir -p /var/backups/ancient-antiquity
chmod +x /srv/ancient-antiquity/deploy/backup.sh
MODE=docker /srv/ancient-antiquity/deploy/backup.sh                       # Docker
MEDIA_DIR=/srv/ancient-antiquity/media /srv/ancient-antiquity/deploy/backup.sh   # VM
```

Schedule it with the lines in `deploy/cron.example`, and **copy backups off the VM** (object storage with `rclone`/`aws s3 sync`, or VM snapshots). Test a restore at least once.

**Restore (Docker)**

```bash
docker compose stop backend
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < /var/backups/ancient-antiquity/db-XXXX.dump
docker compose run --rm --no-deps -T backend sh -c 'rm -rf /app/media/* && tar -C /app -xzf -' < /var/backups/ancient-antiquity/media-XXXX.tar.gz
docker compose start backend
```

**Restore (VM)**

```bash
sudo systemctl stop ancient-antiquity
pg_restore --dbname="postgres://ancient:<pw>@localhost:5432/ancient_antiquity" --clean --if-exists --no-owner /var/backups/ancient-antiquity/db-XXXX.dump
sudo tar -C /srv/ancient-antiquity -xzf /var/backups/ancient-antiquity/media-XXXX.tar.gz && sudo chown -R ancient:www-data /srv/ancient-antiquity/media
sudo systemctl start ancient-antiquity
```

---

## Monitoring and operations

- **Health check**: `GET /api/support/health/` returns `{"status":"ok"}` (HTTP 200) when the API and database work, 503 otherwise. Point an uptime monitor (UptimeRobot, Better Stack, …) at `https://tickets.example.in/api/support/health/` and at the home page.
- **Logs**: Docker — `docker compose logs`; VM — `journalctl -u ancient-antiquity` and `/var/log/nginx/ancient-antiquity.*.log`. Set `ADMIN_EMAILS` to receive 500-error emails. Consider Sentry (`sentry-sdk`) later.
- **Disk**: watch free space (`df -h`) — database, media and backups grow. Docker: `docker system df`.
- **Certificates**: Let's Encrypt certificates last 90 days; check renewal works (`certbot renew --dry-run`).
- **Razorpay**: Dashboard → Webhooks shows failed deliveries; compare daily settlements with bookings.
- **Contact messages** arrive in `/django-admin/` → Support → Contact messages (status new / in progress / closed) and by email to `SUPPORT_EMAIL`.
- **Security**: keep the OS updated (`sudo apt install unattended-upgrades`), allow SSH by key only, enable `ufw` (22/80/443), use strong admin passwords, and raise `SECURE_HSTS_SECONDS` to one year once HTTPS is stable.
- **Rate limits**: the contact form allows 5 messages per hour per IP. The limit is shared by the gunicorn workers of one server through a file cache (`CACHE_DIR`).
- **Scaling**: one 2–4 vCPU VM handles a lot of ticket traffic. Tune `GUNICORN_WORKERS` (default `2 × CPU + 1`, max 9). For several API servers, run migrations once (`RUN_MIGRATIONS=0` on the others), use managed PostgreSQL, shared media storage and a shared cache (Redis).

## Quick verification after going live

1. `https://tickets.example.in` loads, and `http://` redirects to `https://`.
2. `/django-admin/` loads with styles and you can log in.
3. Book a ticket with a small real payment, check the email, the ticket QR and the Razorpay webhook delivery; cancel it and check the refund.
4. On a staff phone, open `/admin/checkin` and scan the QR (camera permission prompt appears only on HTTPS).
5. Send a message from `/contact` and check it in the admin and the support inbox.
6. `docker compose exec backend python manage.py check --deploy` (or the VM equivalent) shows no errors.
