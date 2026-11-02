"""F4: `file_editor` must not write `.git/hooks/*` or `.git/config`.

`write_target` blocked any path with a `.git` component, but `PathValidator.validate`
(the check `file_editor` uses) did not, and its extension check ran only for a path that
has a suffix, so `.git/hooks/pre-commit` (no suffix) skipped it. A git hook runs on the
operator's next commit, so this was code execution from a model-chosen path. One rule,
`is_protected_path`, now serves both.
"""

from __future__ import annotations

import pytest

from weebot.core.output_path import is_protected_path
from weebot.infrastructure.security.security_validators import PathValidator, ValidationResult
from weebot.tools import file_editor as fe

PROTECTED = [
    ".git/hooks/pre-commit",
    ".GIT/config",
    ".GIT\\config",
    "a/.git/hooks/x",
    "sub/.Git/HEAD",
    ".env",
    "sub/.ENV",
    "keys/ID_RSA",
]


@pytest.mark.parametrize("rel", PROTECTED)
def test_the_rule_names_these_as_protected(rel):
    assert is_protected_path(rel)


@pytest.mark.parametrize("rel", ["README", "docs/notes.md", "src/gitlike/x.py", ".gitignore"])
def test_ordinary_paths_are_not_protected(rel):
    assert not is_protected_path(rel)


@pytest.fixture
def validator(tmp_path):
    return PathValidator(workspace_root=tmp_path.resolve())


@pytest.mark.parametrize("rel", PROTECTED)
@pytest.mark.parametrize("allow_create", [True, False])
def test_the_validator_refuses_protected_paths(validator, tmp_path, rel, allow_create):
    report = validator.validate(str(tmp_path / rel), allow_create=allow_create)
    assert report.result is not ValidationResult.VALID, rel


@pytest.mark.parametrize("name", ["README", "LICENSE", "Makefile", "Dockerfile", ".gitignore"])
def test_a_suffixless_document_can_still_be_created(validator, tmp_path, name):
    assert validator.validate(str(tmp_path / name), allow_create=True).result is ValidationResult.VALID


@pytest.mark.parametrize("name", ["pre-commit", "deploy", "run"])
def test_an_unlisted_suffixless_file_cannot_be_created(validator, tmp_path, name):
    report = validator.validate(str(tmp_path / name), allow_create=True)
    assert report.result is not ValidationResult.VALID


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "WORKSPACE_ROOT", str(tmp_path))
    tool = fe.StrReplaceEditorTool()
    tool._workspace = tmp_path.resolve()
    tool._path_validator = PathValidator(workspace_root=tmp_path.resolve())
    return tool


@pytest.mark.asyncio
@pytest.mark.parametrize("rel", [".git/hooks/pre-commit", ".GIT/config"])
async def test_file_editor_cannot_create_a_git_hook_or_config(editor, tmp_path, rel):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    result = await editor.execute(command="create", path=str(target), file_text="evil")
    assert result.error and not target.exists()


@pytest.mark.asyncio
async def test_file_editor_cannot_insert_or_replace_in_a_git_hook(editor, tmp_path):
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("echo ok\n", encoding="utf-8")
    inserted = await editor.execute(command="insert", path=str(hook), insert_line=0, new_str="evil")
    replaced = await editor.execute(command="str_replace", path=str(hook), old_str="ok", new_str="x")
    assert inserted.error and replaced.error
    assert hook.read_text(encoding="utf-8") == "echo ok\n"
