#!/usr/bin/env python3
"""Weebot CLI commands for behavior tracking and trust management."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click

from weebot.core.behavior_tracker import (
    BehaviorTracker,
    create_tracker,
    get_tracker,
    stop_tracker,
    stop_all_trackers,
    WEEBOT_DIR,
)
from weebot.core.behavior_reporting import BehaviorReporter, SelfKnowledgeGenerator


@click.group(name="behavior")
def behavior_cli():
    """Behavior tracking and trust management."""
    pass


@behavior_cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--session-id", required=True, help="Session ID to track")
@click.option("--background", is_flag=True, help="Run in background")
def watch(directory: str, session_id: str, background: bool):
    """Start watching a directory for agent actions."""
    watch_path = Path(directory).resolve()
    
    if background:
        # Run in background using asyncio subprocess
        import subprocess
        
        cmd = [
            sys.executable, "-m", "weebot.interfaces.cli.behavior_commands",
            "watch", str(watch_path), "--session-id", session_id
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        # Save PID
        pid_file = WEEBOT_DIR / "watch.pid"
        pid_file.write_text(str(process.pid))
        
        click.echo(f"Started background watcher (PID: {process.pid})")
        click.echo(f"Watching: {watch_path}")
        click.echo(f"Session: {session_id}")
        return
    
    # Interactive mode
    def on_event(event):
        color = {
            "created": "green",
            "modified": "yellow",
            "deleted": "red",
            "moved": "cyan"
        }.get(event.event_type, "white")
        
        click.secho(
            f"[{event.timestamp[11:19]}] {event.event_type:10} {event.path}",
            fg=color
        )
    
    tracker = create_tracker(session_id, watch_path, on_event)
    
    click.secho(f"Starting behavior tracker...", fg="blue")
    click.secho(f"Session: {session_id}", fg="blue")
    click.secho(f"Watching: {watch_path}", fg="blue")
    click.secho("Press Ctrl+C to stop\n", fg="dim")
    
    tracker.start()
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        click.secho("\nStopping tracker...", fg="yellow")
        tracker.stop()
        
        # Show final stats
        stats = tracker.get_stats()
        click.secho(f"\nFinal trust score: {stats['trust_score']}%", fg="green")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Keep running
    try:
        while tracker.is_running():
            import time
            time.sleep(0.1)
    except KeyboardInterrupt:
        signal_handler(None, None)


@behavior_cli.command()
def status():
    """Show tracker status."""
    import psutil
    
    pid_file = WEEBOT_DIR / "watch.pid"
    
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                click.secho(f"Active watcher (PID: {pid})", fg="green")
                click.echo(f"  Started: {datetime.fromtimestamp(process.create_time())}")
                click.echo(f"  Status: {process.status()}")
            else:
                click.secho("No active watcher (stale PID file)", fg="yellow")
                pid_file.unlink()
        except (ValueError, psutil.NoSuchProcess):
            click.secho("No active watcher", fg="red")
            pid_file.unlink()
    else:
        click.secho("No active watcher", fg="red")


@behavior_cli.command()
def stop():
    """Stop the background watcher."""
    import psutil
    
    pid_file = WEEBOT_DIR / "watch.pid"
    
    if not pid_file.exists():
        click.secho("No watcher to stop", fg="yellow")
        return
    
    try:
        pid = int(pid_file.read_text().strip())
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            process.terminate()
            try:
                process.wait(timeout=5)
                click.secho(f"Stopped watcher (PID: {pid})", fg="green")
            except psutil.TimeoutExpired:
                process.kill()
                click.secho(f"Killed watcher (PID: {pid})", fg="red")
        else:
            click.secho("Watcher not running (removing stale PID file)", fg="yellow")
    except Exception as e:
        click.secho(f"Error stopping watcher: {e}", fg="red")
    finally:
        if pid_file.exists():
            pid_file.unlink()


@behavior_cli.command()
@click.option("--date", help="Date to report on (YYYY-MM-DD), defaults to today")
def report(date: Optional[str]):
    """Show behavioral report."""
    reporter = BehaviorReporter()
    
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    click.echo(reporter.format_console_report(date))


@behavior_cli.command()
def trust():
    """Show trust score."""
    reporter = BehaviorReporter()
    trust_data = reporter.get_trust_report()
    
    color = "green" if trust_data['score_percentage'] >= 90 else "yellow" if trust_data['score_percentage'] >= 70 else "red"
    
    click.secho(f"\nTrust Score: {trust_data['score_percentage']}%", fg=color, bold=True)
    click.echo(f"Status: {trust_data['status']}")
    click.echo(f"Total Actions: {trust_data['total_actions']:,}")
    click.echo(f"Overrides: {trust_data['overrides']}")
    click.echo(f"Last Updated: {trust_data['last_updated'][:19] if trust_data['last_updated'] else 'Never'}")
    click.echo()


@behavior_cli.command()
@click.option("--count", default=10, help="Number of actions to show")
@click.option("--session", help="Filter by session ID")
def log(count: int, session: Optional[str]):
    """Show recent actions."""
    reporter = BehaviorReporter()
    actions = reporter.get_recent_actions(count, session)
    
    if not actions:
        click.secho("No actions recorded.", fg="yellow")
        return
    
    click.secho(f"\nRecent Actions (last {len(actions)}):\n", fg="blue", bold=True)
    
    for i, action in enumerate(actions, 1):
        color = {
            "created": "green",
            "modified": "yellow",
            "deleted": "red",
            "moved": "cyan"
        }.get(action.action, "white")
        
        override_marker = " [OVERRIDE]" if action.is_override else ""
        
        click.echo(f"{i:3}. ", nl=False)
        click.secho(f"[{action.timestamp}]{override_marker}", fg="dim", nl=False)
        click.echo(f" {action.action:10} ", nl=False)
        click.secho(action.path, fg=color)
        
        if action.override_reason:
            click.secho(f"      Reason: {action.override_reason}", fg="red")


@behavior_cli.command()
@click.option("--timestamp", required=True, help="Timestamp of action to override")
@click.option("--reason", required=True, help="Reason for override")
def override(timestamp: str, reason: str):
    """Mark an action as unsanctioned."""
    from weebot.core.behavior_tracker import TrustManager
    
    trust = TrustManager()
    
    if trust.mark_override(timestamp, reason):
        click.secho(f"Marked action as override", fg="yellow")
        click.echo(f"Timestamp: {timestamp}")
        click.echo(f"Reason: {reason}")
        
        # Show updated trust score
        new_trust = trust.load()
        click.secho(f"\nNew trust score: {new_trust.percentage}%", fg="green")
    else:
        click.secho(f"Action not found: {timestamp}", fg="red")


@behavior_cli.command()
@click.option("--output", "-o", help="Output file (default: ~/.weebot/WEEBOT_SELF.md)")
def reflect(output: Optional[str]):
    """Generate self-knowledge file."""
    gen = SelfKnowledgeGenerator()
    
    click.secho("Generating self-knowledge...", fg="blue")
    
    if output:
        path = Path(output)
        path.write_text(gen.generate())
    else:
        path = gen.save()
    
    click.secho(f"Saved to: {path}", fg="green")
    click.echo(f"\nInclude this file in your agent context to improve behavior.")


@behavior_cli.command()
@click.option("--days", default=7, help="Number of days to include")
def summary(days: int):
    """Show multi-day summary."""
    reporter = BehaviorReporter()
    
    click.secho(f"\nLast {days} Days Summary\n", fg="blue", bold=True)
    
    today = datetime.now(timezone.utc)
    for i in range(days):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        report = reporter.get_date_report(date)
        
        if report['total_actions'] > 0:
            click.echo(f"{date}: {report['total_actions']:3} actions - {report['summary'][:60]}...")


@behavior_cli.command()
@click.confirmation_option(prompt="This will delete all ledger data. Are you sure?")
def reset():
    """Reset all behavior data."""
    import shutil
    
    # Stop any active watchers
    stop_all_trackers()
    
    # Remove data
    if WEEBOT_DIR.exists():
        shutil.rmtree(WEEBOT_DIR)
    
    click.secho("All behavior data has been reset.", fg="yellow")


@behavior_cli.command()
def doctor():
    """Check behavior tracking health."""
    import subprocess
    
    click.secho("\nWeebot Behavior Tracker Health Check\n", fg="blue", bold=True)
    
    checks = []
    
    # Check ledger directory
    if LEDGER_DIR.exists():
        git_dir = LEDGER_DIR / ".git"
        if git_dir.exists():
            checks.append(("Ledger git repository", True, "Initialized"))
        else:
            checks.append(("Ledger git repository", False, "Not initialized"))
    else:
        checks.append(("Ledger directory", False, "Does not exist"))
    
    # Check trust file
    trust_file = WEEBOT_DIR / "trust.json"
    if trust_file.exists():
        checks.append(("Trust file", True, "Exists"))
    else:
        checks.append(("Trust file", False, "Will be created on first action"))
    
    # Check ignore file
    ignore_file = WEEBOT_DIR / "ignore.conf"
    if ignore_file.exists():
        checks.append(("Ignore patterns", True, "Configured"))
    else:
        checks.append(("Ignore patterns", False, "Will be created with defaults"))
    
    # Check git availability
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        checks.append(("Git availability", True, "Available"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        checks.append(("Git availability", False, "Not found - ledger commits will fail"))
    
    # Check watchdog
    try:
        import watchdog
        checks.append(("Watchdog library", True, f"Version {watchdog.__version__}"))
    except ImportError:
        checks.append(("Watchdog library", False, "Not installed"))
    
    # Display results
    for name, ok, message in checks:
        color = "green" if ok else "red"
        symbol = "✓" if ok else "✗"
        click.secho(f"{symbol} {name:25} {message}", fg=color)
    
    all_ok = all(ok for _, ok, _ in checks)
    
    click.echo()
    if all_ok:
        click.secho("All systems operational!", fg="green", bold=True)
    else:
        click.secho("Some issues detected. Run 'weebot behavior watch' to initialize.", fg="yellow")


# Entry point for direct execution
if __name__ == "__main__":
    behavior_cli()
