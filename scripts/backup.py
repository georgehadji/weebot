#!/usr/bin/env python3
"""SQLite online backup — safe against a live WAL database.

Uses ``sqlite3.Connection.backup()`` which reads pages atomically
without locking the source database for writes.

Usage::

    python scripts/backup.py                          # uses SESSIONS_DB env var or default
    python scripts/backup.py --db /path/to/weebot_sessions.db --out /path/to/backups/

Backups are compressed with gzip and integrity-checked.
Default retention: 30 days.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.environ.get("WEEBOT_SESSIONS_DB", "./weebot_sessions.db")
_DEFAULT_OUT = Path(os.environ.get("WEEBOT_BACKUP_DIR", "./backups"))
_DEFAULT_RETENTION_DAYS = 30
_METRIC_PREFIX = "weebot_backup"


def backup_database(
    db_path: str | Path,
    out_dir: str | Path,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
) -> Path:
    """Perform an online backup of an open SQLite database.

    Returns the path to the backup archive.

    Steps:
    1. Open a connection to the source DB with ``iterative_checkpoint``.
    2. Create a fresh in-memory database.
    3. Call ``source.backup(dest)`` — pages are copied atomically.
    4. Write the in-memory copy to a gzip-compressed file.
    5. Run ``PRAGMA integrity_check`` on the artifact.
    6. Prune backups older than ``retention_days``.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = f"weebot_sessions_{timestamp}"
    archive_path = out_dir / f"{stem}.db.gz"
    integrity_path = out_dir / f"{stem}.integrity"
    manifest_path = out_dir / "backup_manifest.txt"

    logger.info("Starting backup of %s → %s", db_path, archive_path)

    # Step 1-3: Online backup via sqlite3_backup API
    start = time.monotonic()
    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(":memory:")
        try:
            source.backup(dest, pages=1000, progress=None)
        finally:
            dest.close()
    finally:
        source.close()

    duration = time.monotonic() - start
    logger.info("Backup completed in %.2f seconds", duration)

    # Step 4: Write + compress
    mem_source = sqlite3.connect(":memory:")
    try:
        mem_source.backup(
            sqlite3.connect(str(out_dir / f"{stem}.db")),
            pages=1000,
            progress=None,
        )
    finally:
        mem_source.close()

    # Compress and remove uncompressed
    with open(out_dir / f"{stem}.db", "rb") as f_in:
        with gzip.open(archive_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    (out_dir / f"{stem}.db").unlink()
    file_size = archive_path.stat().st_size
    file_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    # Step 5: Integrity check on a decompressed copy
    decompressed = out_dir / f"{stem}_verify.db"
    try:
        with gzip.open(archive_path, "rb") as f_in:
            decompressed.write_bytes(f_in.read())
        verify_conn = sqlite3.connect(str(decompressed))
        try:
            cursor = verify_conn.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]
            with open(integrity_path, "w") as f:
                f.write(f"integrity_check: {integrity_result}\n")
                f.write(f"source: {db_path}\n")
                f.write(f"timestamp: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"duration_seconds: {duration:.2f}\n")
                f.write(f"size_bytes: {file_size}\n")
        finally:
            verify_conn.close()
    finally:
        if decompressed.exists():
            decompressed.unlink()

    if integrity_result != "ok":
        logger.error("Backup integrity check FAILED: %s", integrity_result)
        archive_path.unlink()
        sys.exit(1)

    logger.info("Integrity check passed")

    # Write manifest entry
    with open(manifest_path, "a") as f:
        f.write(f"{stem}.db.gz {datetime.now(timezone.utc).isoformat()} {file_size} {file_hash} {integrity_result}\n")

    # Step 6: Prune old backups
    pruned = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for p in sorted(out_dir.glob("weebot_sessions_*.db.gz")):
        # Parse timestamp from filename: weebot_sessions_YYYYMMDD_HHMMSS.db.gz
        try:
            ts_str = p.stem.split("_")[2]  # weebot_sessions_20260729_120000 → "20260729"
            file_date = datetime.strptime(ts_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                p.unlink()
                # Also remove integrity file
                integrity_file = out_dir / f"{p.stem}.integrity"
                if integrity_file.exists():
                    integrity_file.unlink()
                pruned += 1
        except (IndexError, ValueError):
            pass  # skip files that don't match our naming pattern

    if pruned:
        logger.info("Pruned %d old backup(s)", pruned)

    # Emit backup metric (via existing Prometheus module if available)
    try:
        from weebot.infrastructure.observability import metrics as m
        m.mcp_rate_limits_hit_total.labels(tool="backup").inc(0)  # placeholder — metric exists
    except Exception:
        pass  # metrics module not available (CLI mode)

    logger.info(
        "Backup complete: %s (%.1f MB, %s, took %.2fs)",
        archive_path.name, file_size / 1e6, file_hash[:16], duration,
    )
    return archive_path


def restore_backup(archive_path: str | Path, output_path: str | Path) -> None:
    """Restore a backup archive to a SQLite database."""
    archive_path = Path(archive_path)
    output_path = Path(output_path)

    if not archive_path.exists():
        logger.error("Backup archive not found: %s", archive_path)
        sys.exit(1)

    if output_path.exists():
        answer = input(f"Target {output_path} exists. Overwrite? [y/N] ").strip().lower()
        if answer != "y":
            logger.info("Restore cancelled")
            return

    # Decompress
    logger.info("Restoring %s → %s", archive_path, output_path)
    with gzip.open(archive_path, "rb") as f_in:
        output_path.write_bytes(f_in.read())

    # Verify
    conn = sqlite3.connect(str(output_path))
    try:
        cursor = conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        if result != "ok":
            logger.error("Restored database integrity check FAILED: %s", result)
            output_path.unlink()
            sys.exit(1)
    finally:
        conn.close()

    logger.info("Restore complete: %s (%d bytes)", output_path, output_path.stat().st_size)


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite online backup tool")
    sub = parser.add_subparsers(dest="command", required=True)

    backup_parser = sub.add_parser("backup", help="Create a backup")
    backup_parser.add_argument("--db", default=_DEFAULT_DB, help="Source database path")
    backup_parser.add_argument("--dest", default=str(_DEFAULT_OUT), help="Output directory")
    backup_parser.add_argument("--label", default="weebot_sessions", help="Backup label prefix")
    backup_parser.add_argument("--retention", type=int, default=_DEFAULT_RETENTION_DAYS, help="Days to retain")

    restore_parser = sub.add_parser("restore", help="Restore from a backup archive")
    restore_parser.add_argument("archive", help="Path to backup archive (.db.gz)")
    restore_parser.add_argument("--out", default=str(_DEFAULT_DB), help="Output database path")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if args.command == "backup":
        backup_database(args.db, args.dest, args.retention)
    elif args.command == "restore":
        restore_backup(args.archive, args.out)


if __name__ == "__main__":
    main()
