# Ancient Antiquity — Museum Booking across India

Django REST API + React (TypeScript) app with a **client panel** (browse, book, pay, QR e-ticket)
and an **admin panel** (dashboard, bookings, gate check-in, museums, users), plus the built-in Django admin.

```
AncientAntiquity/
  backend/    Django 5 + DRF + JWT   (accounts, museums, bookings apps)
  frontend/   React 18 + TS + Vite   (pages/client, pages/admin)
  database/   full database export (compressed parts) + restore script
  deploy/     one-command server install / update / backup scripts (see DEPLOY.md)
  docs/       screenshots, demo login details, testing notes
  start.ps1   starts both servers and opens the browser
```

## Screenshots

**Visitor site**

| Home | Explore 1,242 places |
|---|---|
| ![Home](docs/screenshots/visitor/home.png) | ![Explore](docs/screenshots/visitor/explore.png) |
| **Place page with photos and booking** | **Reviews (sort, filter by stars) and time slots** |
| ![Place](docs/screenshots/visitor/place.png) | ![Reviews](docs/screenshots/visitor/reviews.png) |
| **Events and light & sound shows** | **Heritage map** |
| ![Events](docs/screenshots/visitor/events.png) | ![Map](docs/screenshots/visitor/heritage-map.png) |
| **Combo passes** | **Heritage Card membership** |
| ![Passes](docs/screenshots/visitor/passes.png) | ![Membership](docs/screenshots/visitor/membership.png) |
| **8 Indian languages (Hindi shown)** | **Login: password, email / mobile OTP, Google** |
| ![Hindi](docs/screenshots/visitor/hindi.png) | ![Login](docs/screenshots/visitor/login.png) |
| **My bookings** | **Mobile** |
| ![My bookings](docs/screenshots/visitor/my-bookings.png) | <img src="docs/screenshots/visitor/mobile.png" alt="Mobile" width="260"> |

**Admin panel**

| Dashboard | Bookings |
|---|---|
| ![Dashboard](docs/screenshots/admin/dashboard.png) | ![Bookings](docs/screenshots/admin/bookings.png) |
| **Places** | **Place editor** |
| ![Places](docs/screenshots/admin/places.png) | ![Place editor](docs/screenshots/admin/place-editor.png) |
| **Ticket counter (walk-in sales)** | **Gate check-in (QR scan)** |
| ![Counter](docs/screenshots/admin/counter.png) | ![Check-in](docs/screenshots/admin/checkin.png) |
| **Reports** | **Users (export Excel / PDF / CSV)** |
| ![Reports](docs/screenshots/admin/reports.png) | ![Users](docs/screenshots/admin/users.png) |
| **Site settings (booking switches, footer)** | **Pricing insights** |
| ![Settings](docs/screenshots/admin/settings.png) | ![Pricing](docs/screenshots/admin/pricing.png) |

Retake them with `cd frontend && node scripts/screenshots.mjs` while both dev servers run.

## Quick start from GitHub (with the full sample database)

```powershell
git clone <your-repo-url> AncientAntiquity
cd AncientAntiquity
python database\restore_database.py            # rebuilds backend\db.sqlite3 (1.5 GB) from database\*.part*
.\deploy\windows\setup-dev.ps1                 # venv + packages + backend\.env + npm + background tasks
.\start.ps1
```

`setup-dev.ps1` creates `backend\.env` from `.env.example` (SQLite). Demo logins and passwords for the sample
database are in [docs/LOGIN_DETAILS.md](docs/LOGIN_DETAILS.md); add the `DEMO_*_PASSWORD` lines from there to
`backend\.env` for the browser tests. Without the database export, `setup-dev.ps1` builds a fresh database with the
places catalogue instead. See [database/README.md](database/README.md).

## Run (after first-time setup)

```powershell
.\start.ps1
```

- Visitor site: http://127.0.0.1:5173
- Admin panel: http://127.0.0.1:5173/admin
- Django admin: http://127.0.0.1:8000/django-admin/

Demo logins (created by `seed_india --demo-users`, change before going live):

| Role | Email |
|---|---|
| Admin | admin@ancientantiquity.in |
| Staff (bookings + check-in only) | staff@ancientantiquity.in |
| Visitor | visitor@ancientantiquity.in |

Passwords are set in `backend/.env` (`DEMO_ADMIN_PASSWORD`, `DEMO_STAFF_PASSWORD`, `DEMO_VISITOR_PASSWORD`) and listed in
`docs/LOGIN_DETAILS.md`. If they are not set, `seed_india --demo-users` generates random ones and prints them.

## First-time setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env           # set DATABASE_URL
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_india --demo-users

cd ..\frontend
npm install
```

### Switching from SQLite to PostgreSQL

The local `.env` currently uses `DATABASE_URL=sqlite:///db.sqlite3`. For PostgreSQL:

```sql
CREATE DATABASE ancient_antiquity;
```
```
DATABASE_URL=postgres://postgres:<password>@localhost:5432/ancient_antiquity
```
then run `migrate` and `seed_india` again.

## How booking works

1. Visitor picks a museum, date, slot and quantity per ticket type (Indian / Foreigner / Student / Child).
2. `POST /api/bookings/` locks the slot row, checks remaining capacity, and creates a **pending** booking
   that holds seats for `BOOKING_HOLD_MINUTES` (15).
3. `POST /api/bookings/<ref>/pay/` confirms it (mock gateway in `bookings/services.py`; swap in Razorpay/PayU).
   Free bookings confirm immediately.
4. The ticket page shows a QR code of the reference. Staff check in at `/admin/checkin`; it is only valid on the visit date.
5. Unpaid holds become **expired** automatically; confirmed bookings can be cancelled until the visit date.

## Real payments (Razorpay)

Without keys the site uses a **demo gateway**: nothing is charged. To take real payments:

1. Create an account at https://dashboard.razorpay.com. Test mode works immediately, with no KYC.
2. Go to **Account & Settings → API Keys → Generate test key**, then add the keys to `backend/.env` yourself. Never commit or share the secret:
   ```
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
   RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
   ```
3. Restart the backend. Checkout now opens the Razorpay window (UPI, cards, net banking, wallets).
   In test mode, use UPI ID `success@razorpay` or Razorpay's test cards.
4. **Webhook** (recommended): Razorpay Dashboard → Webhooks → add `https://<your-domain>/api/payments/razorpay/webhook/`
   with the events `payment.captured`, `refund.processed` and `refund.failed`, and put its secret in `RAZORPAY_WEBHOOK_SECRET`.
   The webhook confirms bookings even if the visitor closes the browser right after paying. It needs a public URL; for local
   testing use a tunnel such as ngrok.
5. Going live: complete KYC in Razorpay (PAN, bank account, GST if applicable, and a website with Terms, Privacy,
   Refund and Contact pages), then switch to the `rzp_live_` keys.

How it's secured: the server creates the order and fixes the amount, then verifies Razorpay's HMAC signature before it
confirms a ticket. If a seat hold expires while the visitor is paying, the booking is still confirmed when seats are free,
and otherwise the payment is **refunded automatically**.

**Cancellation and refunds:** a full refund to the original payment method if the visitor cancels at least
`REFUND_FULL_BEFORE_HOURS` (default 24) before the slot, and no refund after that. Counter (cash) sales are refunded at the counter.

## Group bookings

Groups of 21–60 paying people (schools, colleges, tour operators, companies, NGOs) book online with one QR ticket:
- **Discounts:** 25% for schools and colleges and 10% for other groups. Each place can change these in Admin → Places → Edit.
- **Escorts:** one free escort (teacher) per 10 students for school and college groups.
- **Slot share:** groups may use at most 30% of a slot, so individuals and walk-ins still get tickets.
- **At the gate:** staff enter how many people are coming in (for example 38 of 44), and latecomers can enter later on
  the same ticket. This also works offline.
- The sizes, share and escort ratio are in `settings.py` (`GROUP_*`).

## Online + offline (ticket counter and gate)

| Flow | Where | Internet |
|---|---|---|
| Online booking + payment | Visitor site | Needed |
| E-ticket (QR) | Visitor's phone / printout / PDF | Not needed |
| **Ticket counter** (walk-ins, cash/UPI/card) | `/admin/counter` | Needed (shares slot capacity with online sales) |
| **Gate check-in** | `/admin/checkin` | Works offline |

Gate offline mode: the gate device keeps today's ticket list for its museum (auto-refreshed every 5 minutes while online).
If the connection drops, scans are verified against that list and queued; they upload automatically when the
connection returns (`POST /api/bookings/checkin-sync/`). Conflicts, such as the same ticket used at two offline gates
or a ticket cancelled after the list was downloaded, show up as **Sync warnings**.
To reload the page with no internet, serve the production build (`npm run build`). It registers a service worker
that caches the app. In `npm run dev` mode, keep the tab open.

## Museum data

`seed_india` loads 18 detailed museums plus `backend/museums/data/india_museums.csv` (161 more), covering all
36 states/UTs: ASI site museums, national and state museums, science centres, palaces and memorials.
Names and locations are curated. **Timings, closed days and prices are typical defaults per operator type and must
be confirmed with each museum.** Add more with Admin → Museums → *Import CSV*, or:

```powershell
.\.venv\Scripts\python manage.py import_museums my_museums.csv [--update]
```

### Forts, palaces and monuments

Every place has a type: museum, fort, palace or monument. `museums/data/india_heritage_sites.csv` adds 87 ticketed forts, palaces
and monuments (ASI World Heritage sites, Rajasthan hill forts, Deccan forts, the Northeast and more). Where one ticket covers a
fort and its museum, they are a single place, such as "Mehrangarh Fort & Museum". A museum never reuses the article and photo of the
fort or monument it sits in. Selling ASI or state monument tickets for real needs their permission or a tie-up.

### Fast loading (IndexedDB + service worker)

Public data (places, states, categories, cities) is cached in the browser's IndexedDB (`src/api/cache.ts`). Pages render
instantly from the saved copy, then refresh from the API in the background. Entries expire after 7 days, and admin edits clear the
cache. Bookings, availability, reviews and login are never cached. In production builds, the service worker also caches
place photos (up to 400) and the app shell.

### Photos and detailed descriptions

Descriptions and photos come from Wikipedia and Wikimedia Commons. The site shows the required attribution:
text is CC BY-SA 4.0 with a link to the article, and each photo shows its author, licence and source link.
Results are cached in `museums/data/wiki_cache.json`, so `seed_india` applies them without internet.

```powershell
.\.venv\Scripts\python manage.py enrich_museums           # apply the cache
.\.venv\Scripts\python manage.py enrich_museums --fetch   # look up new museums (needs internet)
```

Check `museums/data/wiki_matches.csv` for wrong matches. Fix them in `WIKI_TITLES` in
`enrich_museums.py` and rerun with `--refetch`. Descriptions or images you edit by hand are kept unless you pass `--force`.
For production, replace the photos with the museums' own licensed images where possible.

## API overview

| Endpoint | Who |
|---|---|
| `POST /api/auth/register/`, `login/`, `refresh/`, `GET/PATCH me/` | anyone / self |
| `GET /api/states/`, `cities/?state=`, `categories/` | public |
| `GET /api/museums/?search=&state=&city=&category=&featured=` | public |
| `GET /api/museums/<slug>/availability/?date=YYYY-MM-DD` | public |
| `POST/PUT/PATCH/DELETE /api/museums/…` (nested ticket types + slots) | admin |
| `GET/POST /api/bookings/`, `POST …/<ref>/pay/`, `…/<ref>/cancel/` | owner (staff/admin see all) |
| `POST /api/bookings/checkin/` | staff, admin |
| `POST /api/bookings/counter/` (walk-in sale) | staff, admin |
| `GET /api/bookings/gate-manifest/?museum=&date=`, `POST /api/bookings/checkin-sync/` | staff, admin |
| `POST /api/museums/import/` (CSV upload) | admin |
| `GET /api/admin/dashboard/` | staff, admin |
| `GET/PATCH /api/auth/users/` | admin |

Seeded museum prices, timings and capacities are **sample data**; verify them with each museum before going live.
