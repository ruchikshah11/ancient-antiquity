# Partners app

Tour operators (agents), place (partner) settlements and self-service kiosks.

## Tour operators

* A signed-in **visitor** applies with `POST /api/agents/apply/` → `AgentProfile` in `pending`.
* An admin approves (`POST /api/admin/agents/<id>/approve/`, optional `credit_limit`, `commission_percent`)
  → the user's role becomes `agent` (not a panel user). Reject/suspend: `POST /api/admin/agents/<id>/reject/`
  (an approved agent is suspended and goes back to role `visitor`; history and balance stay).
* `POST /api/agents/bookings/` takes the normal booking payload (or the group payload when `group_type` is
  sent; group rules apply). `visitor_email`/`visitor_phone` default to the agency's. The booking is created with
  `channel="agent"`, `agent=<user>`, confirmed at once with `payment_method="on_account"`, and
  `commission_amount = total × commission%`.
* **Balance** = net (total − commission) of live on-account bookings − payments received. The credit check is
  `balance + net_of_new_booking ≤ credit_limit`. The balance is recomputed from the ledger on every change
  (a `post_save` signal on `Booking` covers cancellations made through any endpoint).
* Agents cancel with `POST /api/agents/bookings/<ref>/cancel/` up to `REFUND_FULL_BEFORE_HOURS` (24 h) before
  the slot; no gateway refund, the amount simply leaves the balance.
* Statement: `GET /api/agents/statement/?month=YYYY-MM` (admin copy:
  `GET /api/admin/agents/<id>/statement/?month=`). Payments: `GET/POST /api/admin/agents/<id>/payments/`.

## Settlements

`POST /api/admin/settlements/generate/ {"from", "to", "museum"?}` builds a **draft** per place from bookings
**paid** in the period that are still live and not refunded:

| Field | Meaning |
| --- | --- |
| `gross_online`, `gross_kiosk`, `gross_agent` | Collected by the platform (gift-voucher part included) |
| `gross_counter` | Cash/UPI taken at the place's own counter (already with the place) |
| `refunds` | Refunds in the period for bookings paid **before** it (already settled earlier) |
| `platform_fee` | `platform_fee_percent` (from `PartnerAccount`, default 5 %) of all gross |
| `gst_on_fee` | 18 % GST on the platform fee |
| `net_payable` | platform-collected gross − refunds − fee − GST (negative = the place owes the platform) |

Periods must end before today. Re-generating refreshes drafts; approved/paid or overlapping periods are skipped.
Workflow: draft → `approve` → `mark-paid {reference}`. Staff see their own places' settlements read-only via
`GET /api/settlements/` (the partner view); CSV: `GET /api/settlements/export.csv`.

Tour-operator commission is a platform cost: the place is settled on the full ticket value of agent bookings.

## Razorpay Route (future, not wired)

`PartnerAccount.razorpay_account_id` holds each place's **linked account** id (`acc_...`). To pay places
automatically instead of by manual bank transfer:

1. Enable Route on the Razorpay account and create a linked account per place (Dashboard → Route, or
   `POST /v2/accounts` + stakeholder + product configuration). Store the `acc_...` id on `PartnerAccount`.
2. **Settlement payouts** (simplest): when a settlement is approved, call
   `POST /v1/transfers` with `{"account": acc_id, "amount": net_payable_paise, "currency": "INR",
   "notes": {"settlement": id}}` (transfer from the platform balance), save the returned `trf_...` id in
   `paid_reference`, and mark the settlement paid from the `transfer.processed` webhook (handle
   `transfer.failed` by moving it back to approved).
3. **Or split at payment time**: add `transfers` to the order in `bookings.payments.create_order`
   (`[{"account": acc_id, "amount": total − fee − GST, "currency": "INR", "on_hold": true}]`) and release
   the hold after the visit date. Settlements then become a reconciliation report instead of a payout.
4. Refunds on split payments need `reverse_all: true` on the refund call so the linked account's share is
   reversed.

Make the calls idempotent (one transfer per settlement id) and keep everything behind a
`RAZORPAY_ROUTE_ENABLED` setting so manual payouts remain the default.

## Kiosks

Admins create kiosk devices with `POST /api/admin/kiosks/ {name, email, password, museums: [slug]}` (creates a
user with role `kiosk`); `PATCH` changes name/places/password/`is_active` (disabling also blocks sign-in).
The device uses `GET /api/kiosk/me/`, `GET /api/kiosk/session/?museum=<slug>` (today's prices and joinable
slots) and `POST /api/kiosk/bookings/` (today only, `channel="kiosk"`, visitor "Kiosk visitor"), then pays
through the normal `/api/bookings/<ref>/payment-order/` and `/pay/` endpoints.
