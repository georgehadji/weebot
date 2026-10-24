"""Golden vectors for API key hashing: stored keys must keep verifying.

Plan item 1.2 of tasks/specs/arch_audit_2026_10_remediation_plan.md moves the
hashing helpers out of ``infrastructure/security/sqlite_api_key_store.py``. A
key hashed before the move is stored in users' databases, so the move must not
change a single output byte. These vectors were computed from the documented
parameters (scrypt N=2**14 r=8 p=1 dklen=32; SHA-256 for the lookup hash), not by
calling the code under test, so they pin the algorithm rather than the module.
"""

from __future__ import annotations

import inspect
import re

from weebot.core import api_key_crypto
from weebot.core.api_key_crypto import generate_raw_key
from weebot.core.api_key_crypto import hash_key as _hash_key
from weebot.core.api_key_crypto import lookup_hash as _lookup_hash
from weebot.core.api_key_crypto import verify_key as _verify_key
from weebot.infrastructure.security.sqlite_api_key_store import SQLiteApiKeyStore

RAW_KEY = "wb_golden-vector-key-0123456789abcdef"
SALT_HEX = bytes(range(32)).hex()
LOOKUP_HASH = "09e34e8a3384e4212435ac1e43348e322a1d7f7675312ab4bbe6f3381cf3249d"
KEY_HASH = "61863cad575b85d73bb3f32687a3132415cf0951ea959e6b1c18cd353cdd79fd"


def test_the_lookup_hash_is_sha256_of_the_raw_key():
    assert _lookup_hash(RAW_KEY) == LOOKUP_HASH


def test_a_stored_key_still_verifies():
    assert _verify_key(RAW_KEY, KEY_HASH, SALT_HEX) is True


def test_a_wrong_key_or_wrong_salt_does_not_verify():
    assert _verify_key(RAW_KEY + "x", KEY_HASH, SALT_HEX) is False
    assert _verify_key(RAW_KEY, KEY_HASH, bytes(32).hex()) is False


def test_hash_key_round_trips_with_a_fresh_salt():
    key_hash, salt_hex = _hash_key(RAW_KEY)
    assert len(bytes.fromhex(salt_hex)) == 32
    assert _verify_key(RAW_KEY, key_hash, salt_hex) is True
    other_hash, other_salt = _hash_key(RAW_KEY)
    assert other_salt != salt_hex, "each key gets its own random salt"
    assert other_hash != key_hash


def test_verification_compares_in_constant_time():
    """A timing oracle on the stored hash would help an attacker with a leaked table."""
    source = inspect.getsource(_verify_key)
    assert "hmac.compare_digest" in source or "compare_digest" in source


def test_generated_keys_have_the_documented_shape():
    key = generate_raw_key()
    assert re.fullmatch(r"wb_[A-Za-z0-9_-]{60,}", key), key
    assert key != generate_raw_key()


def test_the_store_and_the_cli_still_reach_the_same_functions():
    """cli/commands/auth.py and older tests import the underscored names from the store."""
    from weebot.infrastructure.security import sqlite_api_key_store as store

    assert store._hash_key is api_key_crypto.hash_key
    assert store._lookup_hash is api_key_crypto.lookup_hash
    assert store._verify_key is api_key_crypto.verify_key
    assert re.fullmatch(r"wb_.+", SQLiteApiKeyStore.generate_raw_key())
