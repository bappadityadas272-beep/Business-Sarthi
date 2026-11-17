"""SQLite backup and restore for the prototype database (RUNBOOK). Run from the repo root inside the container:

    python scripts/db_tool.py backup                     -> backend/data/backups/sarthi-YYYYmmdd-HHMMSS.db
    python scripts/db_tool.py restore <backup file>      -> replaces backend/data/sarthi.db (stop the API first)

Backups use SQLite's online backup API, so they are consistent even while the API is running. Backups hold real
owner data once real owners exist: they are git-ignored (*.db) and must be deleted with the data (B-11).
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "backend" / "data" / "sarthi.db"
BACKUPS = ROOT / "backend" / "data" / "backups"


def backup() -> Path:
    if not DB.exists():
        raise SystemExit(f"no database at {DB.relative_to(ROOT)}; start the API once or run `make migrate`")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    out = BACKUPS / f"sarthi-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(DB), sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return out


def restore(path: str) -> Path:
    p = Path(path) if Path(path).is_absolute() else ROOT / path
    if not p.is_file():
        raise SystemExit(f"no such backup file: {path}")
    with sqlite3.connect(p) as c:
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit(f"{path} failed the SQLite integrity check; not restored")
    shutil.copyfile(p, DB)
    return p


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "backup":
        print(f"backup written to {backup().relative_to(ROOT)}")
        return 0
    if len(argv) == 2 and argv[0] == "restore" and argv[1]:
        restore(argv[1])
        print(f"restored {argv[1]} to {DB.relative_to(ROOT)}; restart the API: docker compose restart backend")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
