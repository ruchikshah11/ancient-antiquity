# Backend tests

The API has an automated test suite built on Django's test runner (no extra packages).

## Safe to run at any time

`manage.py test` creates a **separate, throwaway test database** (`test_<name>`), runs every test against
it and deletes it afterwards. Your real data (`db.sqlite3` / Postgres) is never read or changed.
Emails go to Django's in-memory outbox, payments use a fake Razorpay client and uploaded photos go to a
temporary folder, so nothing leaves the machine.

## Running

From `backend/` (Windows PowerShell):

```powershell
# everything (about 15 seconds)
.\.venv\Scripts\python manage.py test

# one app
.\.venv\Scripts\python manage.py test bookings
.\.venv\Scripts\python manage.py test accounts museums

# one file / class / test
.\.venv\Scripts\python manage.py test bookings.tests.test_payments
.\.venv\Scripts\python manage.py test bookings.tests.test_checkin.GroupCheckinTests
.\.venv\Scripts\python manage.py test bookings.tests.test_checkin.GroupCheckinTests.test_group_arrives_in_parts

# more detail, stop at the first failure, keep the test DB between runs (faster)
.\.venv\Scripts\python manage.py test -v 2 --failfast --keepdb
```

A run ends with `OK` (possibly `OK (expected failures=N)`) or `FAILED`.

## What is covered

| Where | What |
|---|---|
| `accounts/tests.py` | register (duplicate / weak password / Argon2 hash), login + JWT, password reset request + confirm |
| `museums/tests.py` | list filters, facets, availability (closed day, window, started slot, group seats), admin-only edits, staff `assigned=1`, reviews only after a real visit, photo upload validation |
| `bookings/tests/test_booking_rules.py` | online bookings, capacity, 20-ticket limit, seat holds / expiry / `pay_by`, demo payment, group rules (21-60, escorts, discounts, 30% slot share), counter sales, cancellation refund policy |
| `bookings/tests/test_checkin.py` | gate check-in rules, groups arriving in parts, offline `checkin-sync` with `scan_id`, gate manifest |
| `bookings/tests/test_panel.py` | staff vs admin scoping, dashboard, report summary, CSV / Excel exports, GST invoices |
| `bookings/tests/test_payments.py` | Razorpay (faked): order creation, signature checks, webhooks, idempotency, automatic refunds |
| `notifications/tests.py` | confirmation email with inline QR, cancellation email with refund line, resend endpoint + rate limit |
| `grouprequests/tests.py` | large-group request validation, slot plan (20% reserve), approve -> held bookings, mark paid, decline, expiry, scoping |

Shared helpers (places, users, clients, bookings, fixed "now") live in `bookings/tests/factories.py`.

## Expected failures

Tests marked `@unittest.expectedFailure` document **known bugs** that have not been fixed yet; each has a
comment explaining the problem. They show up as `x` in the output and do not fail the run. When the bug is
fixed the test will report "unexpected success" - remove the decorator then.

## Writing new tests

- Build data with the factory helpers (`make_museum`, `make_visitor`, `make_staff(museum)`, `book(...)`,
  `client_for(user)`), not with fixtures.
- Use dates relative to today (`future_open_date(museum)`); for time-of-day rules wrap the code in
  `with frozen_now(at(day, 10, 30)):`.
- Emails sent from signals run after commit: wrap the request in `with self.captureOnCommitCallbacks(execute=True):`.
