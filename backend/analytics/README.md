# Analytics: booking funnel and abandoned-booking recovery

## Funnel events

The website sends anonymous funnel steps to `POST /api/analytics/events/` (fire-and-forget, batched by
`src/api/analytics.ts`, a random `session_id` kept in the browser's localStorage). Bots (by user agent),
staff and admins are ignored; the endpoint is throttled per IP (60 requests/minute) and the same step is stored
once per session/place/booking within 30 minutes.

Client steps: `view_place`, `select_slot`, `view_checkout` (also accepted: `start_booking`, `payment_started`,
`paid`, `cancelled`). The report does **not** trust the client for money steps: "Started a booking",
"Started payment" (a gateway order was created), "Paid" and "Cancelled" come from online, non-group `Booking`
rows created in the range.

Report: `GET /api/admin/funnel/?from=YYYY-MM-DD&to=YYYY-MM-DD&museum=<slug>` (panel users; staff only see their
assigned places). Session steps count distinct browser sessions; booking steps count bookings.

## Abandoned-booking recovery emails (cron)

`python manage.py send_recovery_emails` emails one reminder ("Your tickets for X are waiting") for each unpaid
online booking that:

- is `pending` (hold expired) or `expired`, created 30 minutes to 24 hours ago, visit date today or later;
- has an email address (booking email, else the account email) that has not opted out;
- has no paid booking (or a newer, still-open attempt) by the same user for the same place and date;
- is the newest attempt for that user/place/date, and the user got no recovery email for that place in 7 days.

The email links to the place page with the date and slot prefilled (`/museums/<slug>?date=YYYY-MM-DD&slot=<id>`,
plus `utm_source=recovery`) and to a signed opt-out link `/api/analytics/unsubscribe/<token>/` (also sent as a
one-click `List-Unsubscribe` header). Opt-outs are stored in `EmailOptOut`. Every email is logged in
`notifications.NotificationLog` (kind `recovery`) and `RecoveryEmail`; a recovery counts as converted when the same
user pays for the same place within 7 days of the email (computed by the command and the funnel report).

Run it every 15 minutes:

```cron
*/15 * * * * cd /srv/ancient-antiquity/backend && .venv/bin/python manage.py send_recovery_emails >> /var/log/aa-recovery.log 2>&1
```

With the Docker image: `docker compose exec backend python manage.py send_recovery_emails`.
Use `--dry-run` to list who would be emailed. Windows Task Scheduler: run
`.venv\Scripts\python manage.py send_recovery_emails` every 15 minutes in the `backend` folder.
