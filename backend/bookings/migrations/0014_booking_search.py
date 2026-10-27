"""Fast booking search (admin "Bookings" page) on lakhs of rows.

SQLite: an FTS5 table `booking_search` (rowid = booking id) with the visitor name, organisation, place name,
email and phone (last 10 digits, plus 6-9 digit endings for partial numbers), kept in sync by triggers on
bookings_booking and museums_museum (place renames). The backfill of ~11 lakh rows takes about a minute.

PostgreSQL: pg_trgm GIN indexes, so the ORM's icontains / istartswith / endswith lookups use an index.
(CREATE EXTENSION needs a role allowed to create extensions; on managed Postgres pg_trgm is allow-listed.)

Other databases: nothing (search falls back to plain lookups).
"""
from django.db import migrations

# Phone digits as stored in the FTS row: spaces, +, -, (, ), . removed.
_DIGITS = (
    "replace(replace(replace(replace(replace(replace(coalesce({p}.visitor_phone, ''), ' ', ''), '+', ''), "
    "'-', ''), '(', ''), ')', ''), '.', '')"
)


def _phone(p):
    return f"substr({_DIGITS.format(p=p)}, -10)"


def _tail(p):
    d = _DIGITS.format(p=p)
    return f"substr({d}, -6) || ' ' || substr({d}, -7) || ' ' || substr({d}, -8) || ' ' || substr({d}, -9)"


def _values(p):
    return (
        f"{p}.visitor_name, {p}.organisation_name, "
        f"(SELECT m.name FROM museums_museum m WHERE m.id = {p}.museum_id), "
        f"{p}.visitor_email, {_phone(p)}, {_tail(p)}"
    )


SQLITE_FORWARD = [
    "DROP TABLE IF EXISTS booking_search",
    "CREATE VIRTUAL TABLE booking_search USING fts5("
    "name, org, place, email, phone, tail, tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3')",
    f"INSERT INTO booking_search (rowid, name, org, place, email, phone, tail) SELECT b.id, {_values('b')} "
    "FROM bookings_booking b",
    "CREATE TRIGGER booking_search_ai AFTER INSERT ON bookings_booking BEGIN "
    f"INSERT INTO booking_search (rowid, name, org, place, email, phone, tail) VALUES (new.id, {_values('new')}); END",
    "CREATE TRIGGER booking_search_ad AFTER DELETE ON bookings_booking BEGIN "
    "DELETE FROM booking_search WHERE rowid = old.id; END",
    # Only when a searchable column changed: Django's save() rewrites every column on each status change.
    "CREATE TRIGGER booking_search_au AFTER UPDATE ON bookings_booking WHEN "
    "old.id IS NOT new.id OR old.visitor_name IS NOT new.visitor_name "
    "OR old.organisation_name IS NOT new.organisation_name OR old.visitor_email IS NOT new.visitor_email "
    "OR old.visitor_phone IS NOT new.visitor_phone OR old.museum_id IS NOT new.museum_id BEGIN "
    "DELETE FROM booking_search WHERE rowid = old.id; "
    f"INSERT INTO booking_search (rowid, name, org, place, email, phone, tail) VALUES (new.id, {_values('new')}); END",
    "CREATE TRIGGER booking_search_place AFTER UPDATE OF name ON museums_museum WHEN old.name IS NOT new.name BEGIN "
    "UPDATE booking_search SET place = new.name "
    "WHERE rowid IN (SELECT id FROM bookings_booking WHERE museum_id = new.id); END",
]

SQLITE_BACKWARD = [
    "DROP TRIGGER IF EXISTS booking_search_ai",
    "DROP TRIGGER IF EXISTS booking_search_ad",
    "DROP TRIGGER IF EXISTS booking_search_au",
    "DROP TRIGGER IF EXISTS booking_search_place",
    "DROP TABLE IF EXISTS booking_search",
]

POSTGRES_FORWARD = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS booking_name_trgm ON bookings_booking USING gin (UPPER(visitor_name) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS booking_org_trgm ON bookings_booking USING gin (UPPER(organisation_name) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS booking_email_trgm ON bookings_booking USING gin (UPPER(visitor_email) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS booking_phone_trgm ON bookings_booking USING gin (visitor_phone gin_trgm_ops)",
]

POSTGRES_BACKWARD = [
    "DROP INDEX IF EXISTS booking_name_trgm",
    "DROP INDEX IF EXISTS booking_org_trgm",
    "DROP INDEX IF EXISTS booking_email_trgm",
    "DROP INDEX IF EXISTS booking_phone_trgm",
]


def _run(statements_by_vendor):
    def run(apps, schema_editor):
        for sql in statements_by_vendor.get(schema_editor.connection.vendor, []):
            schema_editor.execute(sql)

    return run


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0013_paid_at_index"),
        ("museums", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            _run({"sqlite": SQLITE_FORWARD, "postgresql": POSTGRES_FORWARD}),
            _run({"sqlite": SQLITE_BACKWARD, "postgresql": POSTGRES_BACKWARD}),
            elidable=False,
        ),
    ]
