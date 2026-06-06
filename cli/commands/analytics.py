"""Analytics CLI — query and dashboard for Parquet event exports.

Usage:
    python -m cli.main analytics query "SELECT count(*) FROM events"
    python -m cli.main analytics dashboard
    python -m cli.main analytics export --format csv
"""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def analytics() -> None:
    """Query and visualize agent analytics data."""
    pass


@analytics.command("query")
@click.argument("sql")
@click.option(
    "--dir", "analytics_dir",
    default="./analytics",
    help="Directory containing Parquet files (default: ./analytics).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def analytics_query(sql: str, analytics_dir: str, json_output: bool) -> None:
    """Run a SQL query against the analytics Parquet files.

    Uses DuckDB for fast columnar queries.  Requires ``duckdb`` package.

    Example:
        analytics query "SELECT kind, count(*) as cnt FROM events GROUP BY kind ORDER BY cnt DESC"
    """
    try:
        import duckdb
    except ImportError:
        console.print("[red]duckdb is required. Install with: pip install duckdb[/red]")
        raise SystemExit(1)

    data_dir = Path(analytics_dir)
    if not data_dir.exists():
        console.print(f"[yellow]Analytics directory not found: {data_dir}[/yellow]")
        raise SystemExit(1)

    try:
        # Find all Parquet files recursively
        parquet_files = list(data_dir.glob("**/*.parquet"))
        if not parquet_files:
            console.print(f"[yellow]No Parquet files found in {data_dir}[/yellow]")
            raise SystemExit(0)

        # Build a glob pattern for DuckDB
        glob_pattern = str(data_dir / "**" / "*.parquet")
        result = duckdb.sql(
            f"SELECT * FROM read_parquet('{glob_pattern}', hive_partitioning=true)"
        )
        # Run user query against the view
        final = duckdb.sql(sql)

        if json_output:
            rows = [dict(zip(final.columns, row)) for row in final.fetchall()]
            console.print_json(json.dumps(rows, indent=2, default=str))
        else:
            # Render as rich table
            table = Table(title=f"Analytics Query")
            for col in final.columns:
                table.add_column(col, style="cyan")
            for row in final.fetchmany(50):
                table.add_row(*[str(v)[:80] for v in row])
            console.print(table)
            remaining = final.fetchall()
            if remaining:
                console.print(f"[dim]... and {len(remaining)} more rows[/dim]")

    except Exception as exc:
        console.print(f"[red]Query failed: {exc}[/red]")
        raise SystemExit(1)


@analytics.command("dashboard")
@click.option(
    "--dir", "analytics_dir",
    default="./analytics",
    help="Directory containing Parquet files.",
)
def analytics_dashboard(analytics_dir: str) -> None:
    """Show a summary dashboard of analytics data."""
    try:
        import duckdb
    except ImportError:
        console.print("[red]duckdb is required. Install with: pip install duckdb[/red]")
        raise SystemExit(1)

    data_dir = Path(analytics_dir)
    if not data_dir.exists():
        console.print(f"[yellow]Analytics directory not found. Run the agent first.[/yellow]")
        return

    parquet_files = list(data_dir.glob("**/*.parquet"))
    if not parquet_files:
        console.print(f"[yellow]No data yet. Run the agent to generate events.[/yellow]")
        return

    glob_pattern = str(data_dir / "**" / "*.parquet")

    try:
        # Event counts by kind
        by_kind = duckdb.sql(f"""
            SELECT kind, count(*) as cnt
            FROM read_parquet('{glob_pattern}', hive_partitioning=true)
            GROUP BY kind ORDER BY cnt DESC
        """)

        # Events per project
        by_project = duckdb.sql(f"""
            SELECT project_id, count(*) as cnt
            FROM read_parquet('{glob_pattern}', hive_partitioning=true)
            GROUP BY project_id ORDER BY cnt DESC LIMIT 10
        """)

        # Events over time (daily)
        daily = duckdb.sql(f"""
            SELECT date_trunc('day', timestamp) as day, count(*) as cnt
            FROM read_parquet('{glob_pattern}', hive_partitioning=true)
            GROUP BY day ORDER BY day DESC LIMIT 14
        """)

        console.print()
        console.print("[bold]Analytics Dashboard[/bold]")
        console.print(f"  Data dir: {data_dir}")
        console.print(f"  Parquet files: {len(parquet_files)}")
        console.print()

        # By kind
        t1 = Table(title="Events by Kind")
        t1.add_column("Kind", style="cyan")
        t1.add_column("Count", style="green", justify="right")
        for row in by_kind.fetchall():
            t1.add_row(str(row[0]), str(row[1]))
        console.print(t1)

        # By project
        t2 = Table(title="Top Projects")
        t2.add_column("Project", style="cyan")
        t2.add_column("Events", style="green", justify="right")
        for row in by_project.fetchall():
            t2.add_row(str(row[0])[:40], str(row[1]))
        console.print(t2)

        # Daily
        t3 = Table(title="Daily Events (last 14 days)")
        t3.add_column("Day", style="cyan")
        t3.add_column("Events", style="green", justify="right")
        for row in daily.fetchall():
            t3.add_row(str(row[0])[:10], str(row[1]))
        console.print(t3)

    except Exception as exc:
        console.print(f"[red]Dashboard failed: {exc}[/red]")
        raise SystemExit(1)
