"""Export the full development database (backend/db.sqlite3) into GitHub-sized files in this folder.

    backend\\.venv\\Scripts\\python database\\export_database.py            # both formats
    backend\\.venv\\Scripts\\python database\\export_database.py --sql      # only the SQL dump
    backend\\.venv\\Scripts\\python database\\export_database.py --sqlite   # only the database file

1. takes a consistent, compacted copy (VACUUM INTO) - the running site can stay up
2. clears short-lived security rows only: login sessions, one-time login codes, staff 2FA secrets
3. writes, compressed (xz) and split into 24 MB parts (GitHub website uploads allow 25 MB per file):
   - ancient_antiquity.sqlite3.xz.part01, ...   the SQLite database file
   - ancient_antiquity.sql.xz.part01, ...       the same data as SQL (CREATE TABLE + INSERT statements)
   - schema.sql                                 table definitions only (readable on GitHub)
   - manifest.json                              sizes + SHA-256 of everything

Restore with: python database/restore_database.py [--sql]
"""
import datetime
import hashlib
import json
import lzma
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"


def database_path():
    """The SQLite file the site uses: DATABASE_URL in backend/.env (it may live outside the project folder)."""
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL=sqlite:///"):
                path = Path(line.split("sqlite:///", 1)[1].strip())
                return path if path.is_absolute() else BACKEND / path
    return BACKEND / "db.sqlite3"


SOURCE = database_path()
NAME = "ancient_antiquity.sqlite3"
SQL_NAME = "ancient_antiquity.sql"
PART_SIZE = 24 * 1024 * 1024  # under GitHub's 25 MB limit for website uploads (git itself allows 100 MB)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class SplitXzWriter:
    """Compress a stream with xz and write it as <name>.xz.part01, .part02, ... of at most PART_SIZE bytes."""

    def __init__(self, name):
        self.name = name
        for old in HERE.glob(f"{name}.xz.part*"):
            old.unlink()
        self.compressor = lzma.LZMACompressor(preset=6)
        self.digest = hashlib.sha256()
        self.size = 0
        self.parts = []
        self.out = None
        self.written = PART_SIZE

    def write(self, data):
        self.digest.update(data)
        self.size += len(data)
        self._emit(self.compressor.compress(data))

    def _emit(self, data):
        while data:
            if self.written >= PART_SIZE:
                if self.out:
                    self.out.close()
                path = HERE / f"{self.name}.xz.part{len(self.parts) + 1:02d}"
                self.parts.append(path)
                self.out = open(path, "wb")
                self.written = 0
            chunk = data[:PART_SIZE - self.written]
            self.out.write(chunk)
            self.written += len(chunk)
            data = data[len(chunk):]

    def close(self):
        self._emit(self.compressor.flush())
        self.out.close()
        return {
            "file": self.name,
            "size": self.size,
            "sha256": self.digest.hexdigest(),
            "parts": [{"name": p.name, "size": p.stat().st_size, "sha256": sha256(p)} for p in self.parts],
        }


def clean_copy(target):
    src = sqlite3.connect(SOURCE)
    src.execute("VACUUM INTO ?", (str(target),))
    src.close()
    db = sqlite3.connect(target)
    tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    # login sessions, one-time login codes, issued JWT refresh tokens
    for table in tables:
        if table in ("django_session", "accounts_loginotp") or table.startswith("token_blacklist_"):
            db.execute(f'DELETE FROM "{table}"')
    db.execute("UPDATE accounts_user SET totp_secret = '', totp_enabled = 0, totp_backup_codes = '[]'")
    db.commit()
    db.execute("VACUUM")
    db.close()


def export_sqlite(copy):
    print(f"  compressing the database file ({copy.stat().st_size / 1e9:.2f} GB)...", flush=True)
    writer = SplitXzWriter(NAME)
    with open(copy, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            writer.write(block)
    return writer.close()


def export_sql(copy):
    print("  writing the SQL dump (all tables, CREATE + INSERT)...", flush=True)
    db = sqlite3.connect(copy)
    schema = [
        f"{sql};" for (sql,) in db.execute(
            "select sql from sqlite_master where sql is not null and name not like 'sqlite_%' "
            "order by case type when 'table' then 0 when 'index' then 1 else 2 end, name")
    ]
    (HERE / "schema.sql").write_text(
        "-- Ancient Antiquity database schema (SQLite). Data: ancient_antiquity.sql.xz.part* (see README.md)\n\n"
        + "\n\n".join(schema) + "\n", encoding="utf-8")
    writer = SplitXzWriter(SQL_NAME)
    buffer, rows = [], 0
    for line in db.iterdump():
        buffer.append(line)
        rows += 1
        if len(buffer) >= 20000:
            writer.write(("\n".join(buffer) + "\n").encode("utf-8"))
            buffer = []
        if rows % 1_000_000 == 0:
            print(f"    {rows:,} statements", flush=True)
    writer.write(("\n".join(buffer) + "\n").encode("utf-8"))
    db.close()
    return writer.close()


def main():
    if not SOURCE.exists():
        sys.exit(f"Not found: {SOURCE}")
    want_sql = "--sqlite" not in sys.argv
    want_sqlite = "--sql" not in sys.argv
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("formats", {})
    if "file" in manifest:  # older single-format manifest
        manifest["formats"]["sqlite"] = {k: manifest.pop(k) for k in ("file", "size", "sha256", "parts")}

    with tempfile.TemporaryDirectory(dir=HERE) as tmp:
        copy = Path(tmp) / NAME
        print(f"1/3 Copying {SOURCE.name} ({SOURCE.stat().st_size / 1e9:.2f} GB) and clearing sessions/codes...", flush=True)
        clean_copy(copy)
        print("2/3 Compressing (takes several minutes)...", flush=True)
        if want_sqlite:
            manifest["formats"]["sqlite"] = export_sqlite(copy)
        if want_sql:
            manifest["formats"]["sql"] = export_sql(copy)

    print("3/3 Writing manifest...", flush=True)
    manifest["exported_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    for kind, info in manifest["formats"].items():
        total = sum(p["size"] for p in info["parts"])
        print(f"  {kind}: {len(info['parts'])} parts, {total / 1e6:.0f} MB compressed ({info['size'] / 1e9:.2f} GB unpacked)")


if __name__ == "__main__":
    main()
