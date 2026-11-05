"""Adapters for ``SecretSourcePort``: the environment, 1Password and Bitwarden Secrets (H19).

The two command-line adapters run the tool once, without a shell, with a 5 s timeout and an
environment built by ``build_child_env``: the platform allowlist plus the tool's own login
variables. They only read.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Mapping, Sequence

from weebot.application.ports.secret_source_port import (
    ResolvedSecret,
    SecretSourceError,
    SecretSourcePort,
)
from weebot.config.secret_accessor import SecretAccessor
from weebot.core.child_env import build_child_env

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


class EnvSource(SecretSourcePort):
    """``env://OTHER_NAME``: another variable of this process (an alias)."""

    scheme = "env"
    name = "environment"

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    def resolve(self, ref: str) -> ResolvedSecret | None:
        value = self._environ.get(ref.removeprefix("env://"))
        return ResolvedSecret(value, self.name) if value else None


class _CliSource(SecretSourcePort):
    binary: str
    login_vars: Sequence[str] = ()

    def _args(self, ref: str) -> list[str]:
        raise NotImplementedError

    def _parse(self, stdout: str) -> str:
        return stdout

    def resolve(self, ref: str) -> ResolvedSecret | None:
        exe = shutil.which(self.binary)
        if exe is None:
            raise SecretSourceError(f"'{self.binary}' is not on PATH")
        env = build_child_env(SecretAccessor.environ_view(), passthrough=self.login_vars)
        try:
            done = subprocess.run(  # noqa: S603 - argument list, no shell
                [exe, *self._args(ref)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                env=env,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise SecretSourceError(f"'{self.binary}' timed out after {TIMEOUT_SECONDS}s") from None
        except OSError as exc:
            raise SecretSourceError(f"'{self.binary}' could not run: {exc.strerror}") from None
        if done.returncode != 0:
            # stderr names the reference, never the value; still cut it short.
            lines = (done.stderr or "").strip().splitlines()
            raise SecretSourceError(f"'{self.binary}' failed: {(lines[0] if lines else '')[:200]}")
        try:
            value = self._parse(done.stdout)
        except (ValueError, KeyError):
            raise SecretSourceError(f"'{self.binary}' output is not a secret") from None
        return ResolvedSecret(value, self.name) if value else None


class OnePasswordSource(_CliSource):
    """``op://vault/item/field`` through ``op read``."""

    scheme = "op"
    name = "1password"
    binary = "op"
    login_vars = ("OP_SERVICE_ACCOUNT_TOKEN", "OP_CONNECT_HOST", "OP_CONNECT_TOKEN", "OP_ACCOUNT")

    def _args(self, ref: str) -> list[str]:
        return ["read", "--no-newline", ref]


class BitwardenSource(_CliSource):
    """``bws://<secret-id>`` through ``bws secret get``."""

    scheme = "bws"
    name = "bitwarden"
    binary = "bws"
    login_vars = ("BWS_ACCESS_TOKEN", "BWS_SERVER_URL")

    def _args(self, ref: str) -> list[str]:
        return ["secret", "get", ref.removeprefix("bws://"), "--output", "json"]

    def _parse(self, stdout: str) -> str:
        return str(json.loads(stdout)["value"])
