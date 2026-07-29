#!/usr/bin/env python3
"""Restore a Weebot SQLite database from a backup created by ``backup.py``.

Usage:
    # Interactive (prompts before overwriting):
    python scripts/restore.py --backup /backup/weebot_sessions_20260728T120000Z.sqlite \
        --dest /data/weebot_sessions.db

    # Force (no prompt):
    python scripts/restore.py --backup <path> --dest <path> --force

Safety:
    - Requires explicit ``--force`` or interactive confirmation.
    - Verifies the backup's ``PRAGMA integrity_check`` before restoring.
    - The destination database is backed up to ``<dest>.pre-restore-bak`` before
      overwriting, so a mistaken restore is recoverable.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore Weebot SQLite database from a backup.",
    )
    parser.add_argument(
        "--backup", required=True,
        help="Path to the backup .sqlite file.",
    )
    parser.add_argument(
        "--dest", required=True,
        help="Destination path for the restored database (overwrites!).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip confirmation prompt.",
    )
    return parser.parse_args(argv)


def verify_backup(backup_path: Path) -> bool:
    """Run integrity_check on the backup file."""
    conn = sqlite3.connect(str(backup_path))
    try:
        cursor = conn.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        return bool(result and result[0] == "ok")
    finally:
        conn.close()


def restore(backup_path: Path, dest_path: Path) -> Path | None:
    """Restore *backup_path* to *dest_path*, creating a .pre-restore-bak first.

    Returns the path to the backup of the old destination.
    """
    # Backup the current destination if it exists
    pre_bak = None
    if dest_path.exists():
        pre_bak = dest_path.with_suffix(dest_path.suffix + ".pre-restore-bak")
        dest_path.rename(pre_bak)
        print(f"Existing database backed up to: {pre_bak}")

    # Copy the backup to the destination
    import shutil
    shutil.copy2(str(backup_path), str(dest_path))
    print(f"Restored: {backup_path} -> {dest_path}")

    # Verify the restored copy
    conn = sqlite3.connect(str(dest_path))
    try:
        cursor = conn.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        if result and result[0] == "ok":
            print("Restored database integrity check: PASSED")
        else:
            print(f"Restored database integrity check: FAILED -- {result}")
    finally:
        conn.close()

    return pre_bak


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    backup_path = Path(args.backup).resolve()
    if not backup_path.exists():
        print(f"ERROR: Backup file not found: {backup_path}", file=sys.stderr)
        return 1

    try:
        dest_path = Path(args.dest).resolve()
    except OSError as exc:
        print(f"ERROR: Invalid destination path: {args.dest} — {exc}", file=sys.stderr)
        return 1

    # Advisory
    print("NOTE: Stop the Weebot server before restoring, then restart it after.")
    print("      A running process holding the old inode won't see the new file.")

    # Verify backup integrity first
    if not verify_backup(backup_path):
        print(f"ERROR: Backup failed integrity check: {backup_path}", file=sys.stderr)
        return 2

    # Confirmation
    if not args.force:
        print(f"About to restore: {backup_path}")
        print(f"Destination:     {dest_path}")
        if dest_path.exists():
            print(f"Current size:    {dest_path.stat().st_size / 1024 / 1024:.1f} MiB")
        confirm = input("Proceed? [y/N] ").strip().lower()
        if confirm != "y":
            print("Restore cancelled.")
            return 0

    restore(backup_path, dest_path)
    print("Restore completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
