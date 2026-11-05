"""H19: secret references in the environment are resolved once, from a source, and fail closed."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from weebot.application.ports.secret_source_port import (
    ResolvedSecret,
    SecretSourceError,
    SecretSourcePort,
)
from weebot.core.secret_provenance import SecretProvenance, provenance
from weebot.infrastructure.secrets import sources as src
from weebot.infrastructure.secrets.resolver import default_sources, resolve_env_refs


class _Fake(SecretSourcePort):
    scheme = "fake"
    name = "fake-vault"

    def __init__(self, values=None, error=None):
        self.values, self.error = values or {}, error

    def resolve(self, ref):
        if self.error:
            raise SecretSourceError(self.error)
        value = self.values.get(ref)
        return ResolvedSecret(value, self.name) if value else None


def _resolve(environ, *sources):
    report = SecretProvenance()
    resolve_env_refs(environ, sources, report)
    return report


def test_a_reference_is_replaced_by_its_value_and_the_source_is_recorded():
    environ = {"OPENROUTER_API_KEY": "fake://k", "PLAIN": "value"}

    report = _resolve(environ, _Fake({"fake://k": "sk-real"}))

    assert environ == {"OPENROUTER_API_KEY": "sk-real", "PLAIN": "value"}
    assert report.resolved == {"OPENROUTER_API_KEY": "fake-vault"} and not report.failed


def test_a_failed_reference_leaves_the_key_absent_and_says_why():
    environ = {"K": "fake://k", "OTHER": "kept"}

    report = _resolve(environ, _Fake(error="'op' is not on PATH"))

    assert "K" not in environ and environ["OTHER"] == "kept"
    assert report.failed == {"K": "'op' is not on PATH"} and not report.resolved


def test_a_reference_the_source_has_no_value_for_is_absent_too():
    environ = {"K": "fake://missing"}

    report = _resolve(environ, _Fake())

    assert "K" not in environ and "no value" in report.failed["K"]


def test_urls_and_unknown_schemes_are_left_alone():
    environ = {"A": "https://example.com/x", "B": "postgres://u:p@h/db", "C": "not a ref"}

    report = _resolve(environ, _Fake())

    assert environ == {
        "A": "https://example.com/x",
        "B": "postgres://u:p@h/db",
        "C": "not a ref",
    }
    assert not report.resolved and not report.failed


def test_an_env_reference_aliases_another_variable():
    environ = {"REAL": "sk-1", "ALIAS": "env://REAL"}

    report = _resolve(environ, *default_sources(environ))

    assert environ["ALIAS"] == "sk-1" and report.resolved == {"ALIAS": "environment"}


def test_the_resolved_secret_never_shows_in_its_repr():
    assert "sk-real" not in repr(ResolvedSecret("sk-real", "x"))


def _install_fake(tmp_path: Path, monkeypatch, name: str, stdout: str, code=0, stderr=""):
    """Put a fake command-line tool first on PATH."""
    if sys.platform == "win32":
        path = tmp_path / f"{name}.cmd"
        lines = ["@echo off"]
        if stderr:
            lines.append(f"echo {stderr} 1>&2")
        if stdout:
            lines.append(f"<nul set /p={stdout}")
        lines.append(f"exit /b {code}")
        path.write_text("\r\n".join(lines) + "\r\n")
    else:
        path = tmp_path / name
        err = f"echo '{stderr}' >&2\n" if stderr else ""
        path.write_text(f"#!/bin/sh\n{err}printf '%s' '{stdout}'\nexit {code}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])


def test_an_op_reference_resolves_through_the_op_binary_on_path(tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "op", "sk-from-op")
    environ = {"K": "op://vault/item/field"}

    report = _resolve(environ, src.OnePasswordSource())

    assert environ["K"] == "sk-from-op" and report.resolved == {"K": "1password"}


def test_a_bws_secret_is_the_value_field_of_the_json():
    source = src.BitwardenSource()

    assert source._parse(json.dumps({"id": "1", "value": "sk-from-bws"})) == "sk-from-bws"
    with pytest.raises(ValueError):
        source._parse("not json")
    assert source._args("bws://abc") == ["secret", "get", "abc", "--output", "json"]


def test_a_failing_binary_fails_closed_and_names_its_first_stderr_line(tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "op", "", code=1, stderr="item not found")
    environ = {"K": "op://v/i/f"}

    report = _resolve(environ, src.OnePasswordSource())

    assert "K" not in environ and "item not found" in report.failed["K"]


def test_a_missing_binary_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    environ = {"K": "op://v/i/f"}

    report = _resolve(environ, src.OnePasswordSource())

    assert "K" not in environ and "not on PATH" in report.failed["K"]


def test_a_slow_binary_times_out(tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "op", "x")

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="op", timeout=5)

    monkeypatch.setattr(src.subprocess, "run", slow)
    environ = {"K": "op://v/i/f"}

    report = _resolve(environ, src.OnePasswordSource())

    assert "K" not in environ and "timed out" in report.failed["K"]


def test_the_child_environment_has_the_login_variable_and_no_provider_key(tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "op", "x")
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "ops-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    seen = {}

    def run(args, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, stdout="v", stderr="")

    monkeypatch.setattr(src.subprocess, "run", run)
    src.OnePasswordSource().resolve("op://v/i/f")

    assert seen["env"]["OP_SERVICE_ACCOUNT_TOKEN"] == "ops-token"
    assert "OPENROUTER_API_KEY" not in seen["env"]


def test_doctor_reports_a_failed_reference():
    from weebot.interfaces.cli.support import run_doctor

    report = provenance()
    report.clear()
    report.failed["OPENROUTER_API_KEY"] = "'op' is not on PATH"
    try:
        checks = {c.name: c for c in run_doctor(Path.cwd()).checks}
    finally:
        report.clear()

    assert checks["secret_sources"].status == "error"
    assert "OPENROUTER_API_KEY" in checks["secret_sources"].details
