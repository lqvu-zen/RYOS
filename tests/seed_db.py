# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Populates scripts.db with all test scripts.
Run from the project root:  uv run tests/seed_db.py
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH  = Path(__file__).resolve().parents[1] / "scripts.db"
TESTS    = Path(__file__).resolve().parent

ENTRIES = [
    # (name,                    filename,               params,  interpreter)
    ("Hello – Python",          "hello_python.py",      "",      ""),
    ("Hello – Node.js",         "hello_node.js",        "",      ""),
    ("Hello – PowerShell",      "hello_powershell.ps1", "",      ""),
    ("Hello – Batch",           "hello_batch.bat",      "",      ""),
    ("Hello – CMD",             "hello_cmd.cmd",        "",      ""),
    ("Hello – Bash",            "hello_bash.sh",        "",      ""),
    ("Args Echo (try: hello world)", "args_echo.py",    "hello world", ""),
    ("Slow Counter (30 s)",     "slow_counter.py",      "",      ""),
    ("Exit with Error (code 2)","exit_error.py",        "2",     ""),
    ("Environment Info",        "env_info.py",          "",      ""),
    ("Flood Output (500 lines)","flood_output.py",      "",      ""),
]

def main():
    now = datetime.now().isoformat(timespec="seconds")
    added = skipped = 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, path TEXT NOT NULL,
                params TEXT DEFAULT '', interpreter TEXT DEFAULT '',
                created_at TEXT NOT NULL, last_run_at TEXT
            )
        """)

        existing_paths = {r[0] for r in conn.execute("SELECT path FROM scripts")}

        for name, filename, params, interp in ENTRIES:
            path = str(TESTS / filename)
            if path in existing_paths:
                print(f"  skip  {name}")
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO scripts (name, path, params, interpreter, created_at) VALUES (?,?,?,?,?)",
                (name, path, params, interp, now),
            )
            print(f"  added {name}")
            added += 1

        conn.commit()

    print(f"\nDone — {added} added, {skipped} already present.")
    print(f"Database: {DB_PATH}")

if __name__ == "__main__":
    main()
