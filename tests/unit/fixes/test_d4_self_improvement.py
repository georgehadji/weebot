"""D4: `improve` proposes edits to rule and contract files; a human applies them.

SelfImprover had no proposer and no caller, and three defects made it unsafe to
wire: its path check was a bare `startswith` (so `builtin/../../x.md` and
`builtin_evil/` passed), it validated the file on disk rather than the patch, and
its allowlist let it edit its own evaluation set (weebot/config/harness). Revert
re-applied a hand-reversed diff. Now (WEEBOT_SELF_EDIT_CONFIG, off):
- a patch carries the file's original and new content; apply refuses if the file
  changed since the proposal, revert puts the original bytes back;
- a model proposes the new content from recent failures (`improve propose`);
- proposals are held as pending; `improve apply ID` is the human approval, and
  every apply and revert is written to the meta-improvement log.
"""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from weebot.application.services.self_improver import SelfImprover


@pytest.mark.parametrize(
    "target",
    [
        "weebot/skills/builtin/../../../etc/x.md",
        "weebot/skills/builtin_evil/x.md",
        "/abs/weebot/skills/builtin/x.md",
        "weebot/config/harness/eval_tasks.yaml",
    ],
)
def test_unsafe_targets_are_refused(target):
    assert SelfImprover._is_allowed_target(target) is False


def test_a_rule_file_is_allowed():
    assert SelfImprover._is_allowed_target("weebot/config/prompts/rules/coding.md") is True


def _project(tmp_path, text="a: 1\n"):
    target = tmp_path / "weebot/config/contracts/bash.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    return SelfImprover(project_root=tmp_path), target


async def _patch(improver, new="a: 2\n"):
    return await improver.propose_patch(
        {
            "target_file": "weebot/config/contracts/bash.yaml",
            "current_content": "a: 1\n",
            "new_content": new,
        }
    )


async def test_the_patched_content_is_what_gets_validated(tmp_path):
    improver, _ = _project(tmp_path)
    patch = await _patch(improver)
    patch.new_content = "a: [unclosed\n"
    assert await improver.validate_patch(patch) == 0.0


async def test_apply_then_revert_restores_the_original_bytes(tmp_path):
    improver, target = _project(tmp_path)
    patch = await _patch(improver)
    assert await improver.apply_patch(patch) is True
    assert target.read_text(encoding="utf-8") == "a: 2\n"
    assert await improver.revert_patch(patch) is True
    assert target.read_text(encoding="utf-8") == "a: 1\n"


async def test_a_file_changed_since_the_proposal_is_not_overwritten(tmp_path):
    improver, target = _project(tmp_path)
    patch = await _patch(improver)
    target.write_text("a: 99\n", encoding="utf-8")
    assert await improver.apply_patch(patch) is False
    assert target.read_text(encoding="utf-8") == "a: 99\n"


async def test_the_proposer_turns_failures_into_a_patch(tmp_path):
    from weebot.application.services.self_improvement_proposer import SelfImprovementProposer

    improver, _ = _project(tmp_path)
    llm = SimpleNamespace(
        chat=AsyncMock(return_value=SimpleNamespace(content="Here:\n```yaml\na: 3\n```\n"))
    )
    failures = SimpleNamespace(
        recent_failures=AsyncMock(
            return_value=[SimpleNamespace(task_text="t", failure_modes=["timeout"])]
        )
    )
    proposer = SelfImprovementProposer(llm=llm, improver=improver, trajectory_repo=failures)
    patch = await proposer.propose("weebot/config/contracts/bash.yaml")
    assert patch.new_content == "a: 3\n" and patch.original_content == "a: 1\n"
    assert "timeout" in llm.chat.await_args.kwargs["messages"][-1]["content"]


async def test_the_patch_store_round_trips(tmp_path):
    from weebot.infrastructure.persistence.patch_store import FilePatchStore

    improver, _ = _project(tmp_path)
    patch = await _patch(improver)
    store = FilePatchStore(tmp_path / "patches")
    await store.save(patch)
    assert (await store.get(patch.id)).new_content == "a: 2\n"
    assert [p.id for p in await store.list()] == [patch.id]


def _cli(monkeypatch, tmp_path, enabled=True):
    import weebot.config.feature_flags as flags
    from cli.commands import improve as module

    if enabled:
        monkeypatch.setenv("WEEBOT_SELF_EDIT_CONFIG", "1")
    else:
        monkeypatch.delenv("WEEBOT_SELF_EDIT_CONFIG", raising=False)
    importlib.reload(flags)
    monkeypatch.setattr(module, "_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(module, "_project_root", lambda: tmp_path)
    return module


def test_apply_is_refused_while_the_flag_is_off(monkeypatch, tmp_path):
    module = _cli(monkeypatch, tmp_path, enabled=False)
    try:
        result = CliRunner().invoke(module.improve, ["apply", "nope"])
        assert result.exit_code != 0 and "WEEBOT_SELF_EDIT_CONFIG" in result.output
    finally:
        importlib.reload(__import__("weebot.config.feature_flags", fromlist=["x"]))


async def _held_patch(tmp_path):
    from weebot.infrastructure.persistence.patch_store import FilePatchStore

    improver, target = _project(tmp_path)
    patch = await _patch(improver)
    await FilePatchStore(tmp_path / "data" / "self_improvement_patches").save(patch)
    return patch, target


def test_apply_and_revert_through_the_cli_are_logged(monkeypatch, tmp_path):
    import asyncio
    import sqlite3

    patch, target = asyncio.run(_held_patch(tmp_path))
    module = _cli(monkeypatch, tmp_path)
    try:
        listed = CliRunner().invoke(module.improve, ["list"])
        assert patch.id[:8] in listed.output and "pending" in listed.output
        assert CliRunner().invoke(module.improve, ["apply", patch.id]).exit_code == 0
        assert target.read_text(encoding="utf-8") == "a: 2\n"
        assert CliRunner().invoke(module.improve, ["revert", patch.id]).exit_code == 0
        assert target.read_text(encoding="utf-8") == "a: 1\n"
        db = tmp_path / "data" / "meta_improvement_log.db"
        with sqlite3.connect(db) as conn:
            rows = conn.execute("SELECT change_summary FROM meta_edits").fetchall()
        assert len(rows) == 2
        assert json.loads(
            (tmp_path / "data" / "self_improvement_patches" / f"{patch.id}.json").read_text()
        )["reverted"] is True
    finally:
        importlib.reload(__import__("weebot.config.feature_flags", fromlist=["x"]))
