"""Rebuild the database from the parts in this folder (made by export_database.py). Needs only Python 3.

    python database/restore_database.py            # backend/db.sqlite3 (asks before replacing one)
    python database/restore_database.py --force    # replace without asking
    python database/restore_database.py --sql      # database/ancient_antiquity.sql (plain SQL text)

Then: cd backend && python manage.py migrate   (applies any newer migrations), and start the site as usual.
The SQL file can also be loaded with the sqlite3 tool: sqlite3 db.sqlite3 < database/ancient_antiquity.sql
"""
import hashlib
import json
import lzma
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"


def database_path():
    """Where the site expects its SQLite file: DATABASE_URL in backend/.env, else backend/db.sqlite3."""
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL=sqlite:///"):
                path = Path(line.split("sqlite:///", 1)[1].strip())
                return path if path.is_absolute() else BACKEND / path
    return BACKEND / "db.sqlite3"


def unpack(info, target):
    parts = [HERE / p["name"] for p in info["parts"]]
    missing = [p.name for p in parts if not p.exists()]
    if missing:
        sys.exit(f"Missing parts: {', '.join(missing)}")
    if target.exists() and "--force" not in sys.argv:
        if input(f"{target} exists. Replace it? [y/N] ").strip().lower() != "y":
            sys.exit("Cancelled.")
    print(f"Restoring {info['file']} ({info['size'] / 1e9:.2f} GB) from {len(parts)} parts...", flush=True)
    decompressor = lzma.LZMADecompressor()
    digest = hashlib.sha256()
    tmp = target.with_name(target.name + ".restoring")
    with open(tmp, "wb") as out:
        for part in parts:
            with open(part, "rb") as f:
                for block in iter(lambda: f.read(8 << 20), b""):
                    data = decompressor.decompress(block)
                    digest.update(data)
                    out.write(data)
            print(f"  {part.name}", flush=True)
    if digest.hexdigest() != info["sha256"]:
        tmp.unlink()
        sys.exit("Checksum mismatch - a part is damaged or incomplete. Download the parts again.")
    tmp.replace(target)
    print(f"Restored {target}")


def main():
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    formats = manifest.get("formats") or {"sqlite": manifest}  # older single-format manifest
    if "--sql" in sys.argv:
        unpack(formats["sql"], HERE / "ancient_antiquity.sql")
        return
    target = database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    for extra in (target.with_name("db.sqlite3-wal"), target.with_name("db.sqlite3-shm")):
        extra.unlink(missing_ok=True)
    unpack(formats["sqlite"], target)
    print("Next: cd backend && python manage.py migrate")


if __name__ == "__main__":
    main()
