# Database export

The full development database is stored here in two formats, each compressed (xz) and split into 24 MB parts (under the 25 MB limit of GitHub's website upload,
so any upload method works). It contains everything: 1,242 places with photos and descriptions, events, passes,
memberships, add-ons, site settings, the demo accounts, about 1 lakh sample users, about 11 lakh sample bookings,
1.1 lakh reviews and statistics.

| Files | What |
|---|---|
| `ancient_antiquity.sqlite3.xz.part*` | The SQLite database file the site uses (`backend/db.sqlite3`) |
| `ancient_antiquity.sql.xz.part*` | The same data as SQL: `CREATE TABLE` + `INSERT` statements for every table |
| `schema.sql` | Table definitions only (open it right here on GitHub) |
| `manifest.json` | Size and SHA-256 of every part, checked on restore |

All people in it are **sample data** (flagged `is_sample`, gmail/yahoo-style addresses that are never emailed or
texted). Removed on export: login sessions, one-time login codes and staff 2FA secrets.

## Restore

```bash
python database/restore_database.py          # rebuilds the database (1.5 GB) where backend/.env DATABASE_URL points, checks SHA-256
cd backend
python manage.py migrate                     # applies migrations newer than the export, if any
```

SQL text instead:

```bash
python database/restore_database.py --sql    # writes database/ancient_antiquity.sql (not committed: several GB)
sqlite3 backend/db.sqlite3 < database/ancient_antiquity.sql     # optional: load it with the sqlite3 tool
```

Then start the site as described in the main [README](../README.md). Demo logins: [docs/LOGIN_DETAILS.md](../docs/LOGIN_DETAILS.md).

## Export again (after the data changed)

```bash
backend\.venv\Scripts\python database\export_database.py          # both formats
backend\.venv\Scripts\python database\export_database.py --sql    # only the SQL dump
```

It takes a consistent copy while the site keeps running and rewrites the parts and `manifest.json`.

## Production

Do not use this database in production. Start production with `deploy/install.sh` (a fresh PostgreSQL database
with the places catalogue), or move only the places with `dumpdata museums` as explained in [DEPLOY.md](../DEPLOY.md).
