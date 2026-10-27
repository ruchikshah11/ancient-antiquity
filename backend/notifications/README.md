# Notifications

Booking emails, SMS, WhatsApp, web push and visit reminders. Every attempt is recorded in
`NotificationLog` (Django admin → Notifications); a failing provider never breaks a booking.

| Event | Email | SMS | WhatsApp | Web push |
|---|---|---|---|---|
| Booking confirmed | yes (with QR) | yes | yes | – |
| Booking cancelled | yes | yes | – | – |
| Visit reminder (day before / N hours before) | yes (with QR) | yes | yes | yes (if subscribed) |

## Visit reminders (cron)

`send_visit_reminders` reminds every **confirmed** booking. Each booking gets each reminder kind at most
once (`NotificationLog.kind` = `reminder` / `reminder_soon`), so re-running is safe.

```cron
# Day-before reminder, every day at 18:00 IST
0 18 * * *  cd /app/backend && python manage.py send_visit_reminders >> /var/log/aa-reminders.log 2>&1
# Optional "starts soon" reminder, hourly, for slots starting within 2 hours
0 * * * *   cd /app/backend && python manage.py send_visit_reminders --hours-before 2 >> /var/log/aa-reminders.log 2>&1
```

(Set the server's cron time zone accordingly; with the Docker image use `docker compose exec backend ...`.)
Options: `--date YYYY-MM-DD` (remind a specific visit date), `--dry-run` (list only).

## Web push

1. Generate keys once: `python manage.py generate_vapid_keys` and paste the three lines into `.env`
   (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`). Changing keys invalidates all subscriptions.
2. The site must be served over HTTPS (localhost is fine for testing).
3. Visitors enable "Remind me the day before" on their ticket (`ReminderSettings` component); the browser
   subscription is saved via the API below. Subscriptions that the push service reports as gone (404/410)
   are deleted automatically.

API:
- `GET  /api/notifications/push/public-key/` → `{ "public_key": "..." | null }` (null = push not configured)
- `POST /api/notifications/push/subscribe/` (auth) body = `PushSubscription.toJSON()`
- `POST /api/notifications/push/unsubscribe/` (auth) body `{ "endpoint": "..." }` (no endpoint = all of the user's)

## WhatsApp

`WHATSAPP_PROVIDER`:
- `console` (default) – messages are only written to the log;
- `meta` – WhatsApp Cloud API (`POST https://graph.facebook.com/v20.0/<WHATSAPP_PHONE_NUMBER_ID>/messages`)
  with `WHATSAPP_TOKEN` (a permanent System User token);
- `off` – disabled.

**Important:** Meta delivers free-form text messages only within 24 hours of the customer messaging you.
Business-initiated messages such as tickets and reminders must use a **pre-approved message template**
(WhatsApp Manager → Message templates, category "Utility"). Before going live, create templates for
"booking confirmed" and "visit reminder" with the ticket link as a parameter and switch
`_send_whatsapp_meta()` in `services.py` to send `"type": "template"`.

## SMS

`SMS_PROVIDER` = `console` | `msg91` | `twilio` (see settings.py). Indian transactional SMS needs DLT
registered templates; the texts are built in `_booking_sms_text()`.
