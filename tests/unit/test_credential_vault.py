"""H19b: a vault handle fills a login field without the model ever holding the value."""

from __future__ import annotations

import json
import types

import pytest

from weebot.application.ports.credential_vault_port import CredentialError
from weebot.application.ports.secret_source_port import ResolvedSecret, SecretSourcePort
from weebot.infrastructure.secrets.vault import MARKER, ConfiguredVault, origin_of
from weebot.tools.advanced_browser import AdvancedBrowserTool

PASSWORD = "hunter2-real-password"


class _Fake(SecretSourcePort):
    scheme = "fake"
    name = "fake-vault"

    def resolve(self, ref):
        return ResolvedSecret(PASSWORD, self.name) if ref == "fake://github" else None


class _Page:
    def __init__(self, url="https://github.com/login"):
        self.url = url
        self.filled: list[tuple[str, str]] = []
        self.fail = False

    async def fill(self, selector, value, timeout=0):
        if self.fail:
            raise RuntimeError(f"locator.fill({selector!r}, {value!r}) timed out")
        self.filled.append((selector, value))

    async def evaluate(self, script):
        return f"value is {self.filled[-1][1]}"

    async def content(self):
        return f"<input value='{self.filled[-1][1]}'>"


def _write(tmp_path, *creds):
    path = tmp_path / "vault.json"
    path.write_text(json.dumps({"credentials": list(creds)}))
    return path


GITHUB = {
    "id": "github",
    "origin": "https://github.com",
    "username": "me@example.com",
    "password": "fake://github",
}


def _vault(tmp_path, *creds):
    return ConfiguredVault.from_file(_write(tmp_path, *(creds or (GITHUB,))), [_Fake()])


def _tool(vault, page):
    return AdvancedBrowserTool(browser=types.SimpleNamespace(page=page), credential_vault=vault)


def test_origin_ignores_path_case_and_default_port():
    assert origin_of("HTTPS://GitHub.com:443/login?x=1") == "https://github.com"
    assert origin_of("http://localhost:3000/a") == "http://localhost:3000"
    assert origin_of("javascript:alert(1)") == ""


def test_a_plain_password_in_the_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not a plain value"):
        _vault(tmp_path, {**GITHUB, "password": PASSWORD})


def test_a_duplicate_id_is_refused(tmp_path):
    with pytest.raises(ValueError, match="twice"):
        _vault(tmp_path, GITHUB, GITHUB)


def test_handles_are_listed_by_origin(tmp_path):
    vault = _vault(tmp_path)

    assert [h.id for h in vault.list_handles("https://github.com/x")] == ["github"]
    assert vault.list_handles("https://github.com.evil.test") == []


async def test_fill_types_the_password_on_the_bound_origin(tmp_path):
    page = _Page()

    await _vault(tmp_path).fill("github", page, selector="#pw")

    assert page.filled == [("#pw", PASSWORD)]


async def test_username_is_a_plain_value_when_not_a_reference(tmp_path):
    page = _Page()

    await _vault(tmp_path).fill("github", page, selector="#user", field="username")

    assert page.filled == [("#user", "me@example.com")]


async def test_a_look_alike_origin_is_refused_and_nothing_is_typed(tmp_path):
    page = _Page("https://github.com.evil.test/login")

    with pytest.raises(CredentialError, match="is for https://github.com"):
        await _vault(tmp_path).fill("github", page, selector="#pw")

    assert page.filled == []


async def test_an_unknown_handle_is_refused(tmp_path):
    with pytest.raises(CredentialError, match="unknown credential handle"):
        await _vault(tmp_path).fill("nope", _Page(), selector="#pw")


async def test_a_playwright_failure_does_not_echo_the_value(tmp_path):
    page = _Page()
    page.fail = True

    with pytest.raises(CredentialError) as err:
        await _vault(tmp_path).fill("github", page, selector="#pw")

    assert PASSWORD not in str(err.value) and "RuntimeError" in str(err.value)


async def test_redact_hides_a_filled_password(tmp_path):
    vault = _vault(tmp_path)
    assert vault.redact(f"x {PASSWORD}") == f"x {PASSWORD}"  # nothing filled yet

    await vault.fill("github", _Page(), selector="#pw")

    assert vault.redact(f"x {PASSWORD} y") == f"x {MARKER} y"


async def test_the_tool_routes_a_vault_reference_and_reports_no_value(tmp_path):
    page = _Page()
    result = await _tool(_vault(tmp_path), page).execute(
        action="fill", selector="#pw", value="vault:github"
    )

    assert page.filled == [("#pw", PASSWORD)]
    assert not result.error and PASSWORD not in result.output and "github" in result.output


async def test_the_tool_selects_the_username_field(tmp_path):
    page = _Page()
    await _tool(_vault(tmp_path), page).execute(
        action="fill", selector="#u", value="vault:github:username"
    )

    assert page.filled == [("#u", "me@example.com")]


async def test_the_tool_refuses_a_vault_reference_on_the_wrong_origin(tmp_path):
    page = _Page("https://evil.test/")
    result = await _tool(_vault(tmp_path), page).execute(
        action="fill", selector="#pw", value="vault:github"
    )

    assert page.filled == [] and "is for https://github.com" in result.error


async def test_the_tool_never_types_the_reference_itself(tmp_path):
    page = _Page()
    no_vault = await _tool(None, page).execute(action="fill", selector="#pw", value="vault:github")
    malformed = await _tool(_vault(tmp_path), page).execute(
        action="fill", selector="#pw", value="vault:git hub"
    )
    typed = await _tool(_vault(tmp_path), page).execute(action="type", text="vault:github")

    assert page.filled == []
    assert "no credential vault" in no_vault.error
    assert "malformed" in malformed.error
    assert "fill action" in typed.error


async def test_a_plain_fill_is_unchanged(tmp_path):
    page = _Page()
    await _tool(_vault(tmp_path), page).execute(action="fill", selector="#q", value="hello")

    assert page.filled == [("#q", "hello")]


async def test_page_reads_cannot_return_a_filled_password(tmp_path):
    page = _Page()
    tool = _tool(_vault(tmp_path), page)
    await tool.execute(action="fill", selector="#pw", value="vault:github")

    evaluated = await tool.execute(action="evaluate", script="document.title")
    content = await tool.execute(action="get_content")

    assert PASSWORD not in evaluated.output and MARKER in evaluated.output
    assert PASSWORD not in content.output and MARKER in content.output
