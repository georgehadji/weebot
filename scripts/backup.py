#!/usr/bin/env python3
"""Online backup of Weebot's SQLite databases using SQLite's backup API.

Safe against live WAL-mode databases (unlike ``cp`` / ``rsync``).
Runs ``PRAGMA integrity_check`` on each artifact after creation.

Usage:
    python scripts/backup.py --db path/to/weebot_sessions.db --dest /backup/weebot/

    # From a cron job (retention 14 days, no metrics):
    python scripts/backup.py --db /data/weebot_sessions.db --dest /backup/ \
        --retention 14 --no-metrics

Requires:
    - The source database must exist.
    - The destination directory must exist or be creatable.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Online backup of Weebot SQLite databases.",
    )
    parser.add_argument(
        "--db", required=True,
        help="Path to the source SQLite database file.",
    )
    parser.add_argument(
        "--dest", required=True,
        help="Destination directory for backup artifacts.",
    )
    parser.add_argument(
        "--retention", type=int, default=30,
        help="Number of days to retain backups (default 30). 0 = infinite.",
    )
    parser.add_argument(
        "--no-metrics", action="store_true",
        help="Skip Prometheus metric emission (local mode).",
    )
    parser.add_argument(
        "--label", default="weebot_sessions",
        help="Label for naming the backup file (default 'weebot_sessions').",
    )
    return parser.parse_args(argv)


def backup_database(src_path: Path, dest_dir: Path, label: str) -> Path:
    """Perform an online backup of *src_path* to *dest_dir*.

    Uses ``sqlite3.backup()`` which is safe against live WAL-mode databases:
    it copies page-by-page under a shared lock, consistent with the state at
    the time ``backup_start()`` was called.

    Returns the path to the created backup file.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_path = dest_dir / f"{label}_{timestamp}.sqlite"

    src_conn = None
    dest_conn = None
    try:
        src_conn = sqlite3.connect(str(src_path))
        dest_conn = sqlite3.connect(str(dest_path))
        with src_conn:
            src_conn.execute("PRAGMA journal_mode=WAL;")
        # backup() copies FROM this connection TO target
        src_conn.backup(dest_conn)
    except Exception:
        # Clean up partial file on failure (disk full, backup interrupted)
        if dest_path.exists():
            try:
                dest_path.unlink()
            except OSError:
                pass
        raise
    finally:
        if src_conn:
            src_conn.close()
        if dest_conn:
            dest_conn.close()

    print(f"Backup created: {dest_path} ({dest_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    return dest_path


def verify_backup(backup_path: Path) -> bool:
    """Run integrity_check on *backup_path*. Returns True if clean."""
    conn = sqlite3.connect(str(backup_path))
    try:
        cursor = conn.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        if result and result[0] == "ok":
            print(f"Integrity check passed: {backup_path}")
            return True
        print(f"INTEGRITY CHECK FAILED: {backup_path} — {result}")
        try:
            backup_path.unlink()
        except OSError:
            pass
        return False
    finally:
        conn.close()


def prune_old_backups(dest_dir: Path, label: str, retention_days: int) -> int:
    """Remove backups older than *retention_days* for the given *label*."""
    if retention_days <= 0:
        return 0

    cutoff = time.time() - (retention_days * 86400)
    pruned = 0
    for f in sorted(dest_dir.glob(f"{label}_*.sqlite")):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            pruned += 1
            print(f"Pruned: {f}")

    if pruned:
        print(f"Pruned {pruned} backup(s) older than {retention_days} days")
    return pruned


def report_metrics(label: str, backup_path: Path, ok: bool) -> None:
    """Emit backup metrics if Prometheus is available."""
    status = "ok" if ok else "FAILED"
    size_kb = backup_path.stat().st_size / 1024
    print(
        f"[METRIC] weebot_backup label={label} status={status} "
        f"size_kb={size_kb:.0f} timestamp={datetime.now(timezone.utc).isoformat()}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    src_path = Path(args.db).resolve()
    if not src_path.exists():
        print(f"ERROR: Source database not found: {src_path}", file=sys.stderr)
        return 1

    dest_dir = Path(args.dest).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Backup
    backup_path = backup_database(src_path, dest_dir, args.label)

    # 2. Verify
    ok = verify_backup(backup_path)

    # 3. Metrics
    if not args.no_metrics:
        report_metrics(args.label, backup_path, ok)

    # 4. Prune
    prune_old_backups(dest_dir, args.label, args.retention)

    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
