"""API key hashing: pure stdlib, no I/O.

Two layers use these functions -- the SQLite key store (``infrastructure``) when it
issues and loads keys, and the web auth dependency (``interfaces``) when it
verifies a presented key -- so they live in ``core``, public, instead of being
private helpers one layer reached into from another (SEC-2 of
``tasks/specs/arch_audit_2026_10_remediation_plan.md``).

A key is stored with two hashes:

1. ``lookup_hash`` -- SHA-256 of the raw key (deterministic, indexed, fast lookup)
2. ``key_hash`` -- scrypt of the raw key and a random salt (for verification,
   brute-force resistant)

The raw key is never persisted. Changing any parameter here invalidates every
stored key; ``tests/unit/security/test_api_key_golden_vectors.py`` pins them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

# scrypt parameters -- balanced for API key verification. API keys have high
# entropy (48 bytes urlsafe base64), so scrypt's primary value is slowing
# brute-force on leaked hashes.
SCRYPT_N = 2**14  # CPU/memory cost (16384)
SCRYPT_R = 8  # block size
SCRYPT_P = 1  # parallelization factor
SCRYPT_DKLEN = 32  # output length in bytes
SALT_BYTES = 32  # salt length for scrypt


def lookup_hash(raw_key: str) -> str:
    """SHA-256 of the raw key -- deterministic, used for record lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_key(raw_key: str) -> tuple[str, str]:
    """Hash an API key with a random salt using scrypt.

    Returns (scrypt_hash_hex, salt_hex).
    """
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.scrypt(
        raw_key.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return dk.hex(), salt.hex()


def verify_key(raw_key: str, stored_hash_hex: str, salt_hex: str) -> bool:
    """Verify a raw key against a stored scrypt hash and salt.

    Uses ``hmac.compare_digest`` for constant-time comparison.
    """
    dk = hashlib.scrypt(
        raw_key.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return hmac.compare_digest(dk.hex(), stored_hash_hex)


def generate_raw_key() -> str:
    """Generate a cryptographically random API key."""
    return f"wb_{secrets.token_urlsafe(48)}"
