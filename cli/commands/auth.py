"""CLI commands for API key management (multi-principal auth).

Usage::

    weebot auth create-key --principal user-1 --expires 90d
    weebot auth list-keys --principal user-1
    weebot auth revoke-key --key-id <id>
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, UTC

import click

from weebot.infrastructure.security.sqlite_api_key_store import (
    SQLiteApiKeyStore,
    _lookup_hash,
    _hash_key,
)


@click.group(name="auth")
def auth_group() -> None:
    """Manage API keys for multi-principal authentication."""


@auth_group.command(name="create-key")
@click.option("--principal", required=True, help="Principal ID (e.g. user-1, metrics-bot)")
@click.option("--scopes", default="", help="Comma-separated scopes (e.g. api,admin)")
@click.option("--expires", default="365d", help="Expiration (e.g. 90d, 12h, never)")
def create_key(principal: str, scopes: str, expires: str) -> None:
    """Generate a new API key for the given principal."""
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]

    expires_at: datetime | None = None
    if expires != "never":
        unit = expires[-1]
        try:
            amount = int(expires[:-1])
        except ValueError:
            click.echo(f"Invalid expires format: {expires} (e.g. 90d, 12h, 365d)", err=True)
            sys.exit(1)
        if unit == "d":
            expires_at = datetime.now(UTC) + timedelta(days=amount)
        elif unit == "h":
            expires_at = datetime.now(UTC) + timedelta(hours=amount)
        elif unit == "m":
            expires_at = datetime.now(UTC) + timedelta(minutes=amount)
        else:
            click.echo(f"Unknown time unit: {unit} (use d, h, m)", err=True)
            sys.exit(1)

    raw_key = SQLiteApiKeyStore.generate_raw_key()
    lookup = _lookup_hash(raw_key)
    key_hash, salt = _hash_key(raw_key)

    key_id = f"key_{principal}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    async def _do_save():
        store = SQLiteApiKeyStore()
        await store.save(key_id, principal, lookup, key_hash, salt, scope_list, expires_at)
        await store.close()

    asyncio.run(_do_save())

    click.echo("Key created:")
    click.echo(f"  ID:         {key_id}")
    click.echo(f"  Principal:  {principal}")
    click.echo(f"  Scopes:     {', '.join(scope_list) if scope_list else '(none)'}")
    click.echo(f"  Expires:    {expires_at.isoformat() if expires_at else 'never'}")
    click.echo("")
    click.echo("  Raw key (SAVE THIS — will not be shown again):")
    click.echo(f"  {raw_key}")


@auth_group.command(name="list-keys")
@click.option("--principal", default=None, help="Filter by principal ID")
def list_keys(principal: str | None) -> None:
    """List API keys, optionally filtered by principal."""
    store = SQLiteApiKeyStore()

    async def _do_list():
        if principal:
            records = await store.list_by_principal(principal)
        else:
            conn = await store._ensure_open()
            cursor = await conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            records = [store._row_to_record(r) for r in rows]
        await store.close()
        return records

    records = asyncio.run(_do_list())

    if not records:
        click.echo("No keys found.")
        return

    click.echo(
        f"{'ID':50s} {'Principal':20s} {'Scopes':25s} {'Created':25s} {'Expires':25s} {'Status':10s}"
    )
    click.echo("-" * 155)
    for r in records:
        status = "active" if r.is_valid else "revoked" if r.revoked_at else "expired"
        click.echo(
            f"{r.id:50s} {r.principal_id:20s} "
            f"{','.join(r.scopes):25s} "
            f"{r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else str(r.created_at):25s} "
            f"{r.expires_at.isoformat()[:19] if r.expires_at else 'never':25s} "
            f"{status:10s}"
        )


@auth_group.command(name="revoke-key")
@click.option("--key-id", required=True, help="Key ID to revoke")
def revoke_key(key_id: str) -> None:
    """Revoke an API key."""
    store = SQLiteApiKeyStore()

    async def _do_revoke():
        result = await store.revoke(key_id)
        await store.close()
        return result

    if asyncio.run(_do_revoke()):
        click.echo(f"Key {key_id} revoked.")
    else:
        click.echo(f"Key {key_id} not found or already revoked.", err=True)
        sys.exit(1)
