"""The plan-template cache had never stored a template, and could not read one.

D75/D76/D77. Three independent defects on one feature, each of which would have
hidden the others, all of them behind `except Exception: logger.debug(...)`:

  D75  `CompletedState` called `save_plan_template(template)` — one positional
       argument — against a repository method declaring four. Every completed
       run raised TypeError into a DEBUG log, so `plan_templates` had never
       held a row.

  D76  `find_matching_templates` called `find_plan_templates_by_hash(hash,
       limit=...)` and `list_all_plan_templates(limit=...)` against methods
       taking neither, then assigned the first result — declared `dict | None`
       — straight out of a function annotated `list[PlanTemplate]`, and called
       `tpl.task_description` on the rows from the second. Every plan creation
       raised TypeError into a DEBUG log, indistinguishable from "no match".

  D77  `PlanTemplateRepo.save` took no `success_score` and left it out of the
       INSERT, against a column declared `NOT NULL DEFAULT 1.0`. Had the write
       ever run, every template would have been stored as a perfect one — which
       is the exact failure P3 fixed one layer up, where the score is computed.

Both sides reach each other through `repo: Any`, so nothing compared the call
to the signature. The feature had no tests at all.

Measured after the fix, driving the real `CompletedState` with the `""` the run
loop hands it (see D74): one row, keyed on the task's hash rather than
`compute_task_hash("") == e3b0c44298fc1c14`, carrying score 0.67 for a plan with
2 of 3 steps COMPLETED.
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import uuid

import pytest

from weebot.domain.models.plan_template import PlanTemplate
from weebot.domain.services.plan_template_cache import (
    compute_task_hash,
    find_matching_templates,
    row_to_template,
)
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _template(task: str, score: float) -> PlanTemplate:
    return PlanTemplate(
        template_id=str(uuid.uuid4()),
        task_hash=compute_task_hash(task),
        task_description=task,
        plan_json=json.dumps({"title": task, "steps": []}),
        success_score=score,
    )


async def _save(repo: SQLiteStateRepository, template: PlanTemplate) -> None:
    """Exactly the call shape `CompletedState` uses."""
    await repo.save_plan_template(
        template.template_id,
        template.task_hash,
        template.task_description,
        template.plan_json,
        template.success_score,
    )


@pytest.fixture
async def repo(tmp_path):
    r = SQLiteStateRepository(db_path=str(tmp_path / "t.db"))
    await r._init_helpers()
    yield r
    await r.close()


@pytest.mark.asyncio
async def test_a_saved_template_is_found_again(repo):
    task = "build a responsive marketing website"
    await _save(repo, _template(task, 1.0))

    found = await find_matching_templates(repo, task)

    assert [t.task_description for t in found] == [task]
    assert all(isinstance(t, PlanTemplate) for t in found), (
        "the repository speaks rows and this module speaks PlanTemplate; returning rows is D76"
    )


@pytest.mark.asyncio
async def test_the_success_score_survives_the_write(repo):
    """The column defaults to 1.0, so a dropped score is invisible at a glance."""
    await _save(repo, _template("write a python parser for csv files", 0.25))

    rows = await repo.list_all_plan_templates()

    assert [r["success_score"] for r in rows] == [0.25], (
        "success_score was not persisted; every template would read as a "
        "perfect one, which is what P3 fixed one layer up"
    )


@pytest.mark.asyncio
async def test_a_better_scoring_template_is_offered_first(repo):
    """Two runs of the same task, one of which mostly failed."""
    task = "build a responsive marketing website"
    await _save(repo, _template(task, 0.25))
    await _save(repo, _template(task, 1.0))

    found = await find_matching_templates(repo, task)

    assert [t.success_score for t in found] == [1.0, 0.25]


@pytest.mark.asyncio
async def test_the_jaccard_fallback_returns_templates_not_rows(repo):
    """The slow path called `tpl.task_description` on whatever `list_all` gave
    it, which was a dict."""
    await _save(repo, _template("write a python parser for csv files", 0.8))

    found = await find_matching_templates(repo, "write a python parser for tsv files")

    assert [t.task_description for t in found] == ["write a python parser for csv files"]


@pytest.mark.asyncio
async def test_a_miss_is_an_empty_list_not_an_exception(repo):
    assert await find_matching_templates(repo, "something else entirely") == []


def test_row_to_template_passes_a_template_through():
    template = _template("t", 0.5)
    assert row_to_template(template) is template


# ── the gates that would have caught the original defects ────────────────


def _call_in(path: pathlib.Path, name: str) -> ast.Call:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == name
    ]
    assert len(calls) == 1, f"expected exactly one {name} call in {path.name}, got {len(calls)}"
    return calls[0]


def test_completed_state_calls_save_with_the_arity_the_repository_declares():
    call = _call_in(
        _ROOT / "weebot" / "application" / "flows" / "states" / "completed.py",
        "save_plan_template",
    )
    signature = inspect.signature(SQLiteStateRepository.save_plan_template)
    # `self` is bound at the call site; the AST sees only the rest.
    signature.bind(
        None,
        *[None] * len(call.args),
        **{kw.arg: None for kw in call.keywords if kw.arg},
    )


@pytest.mark.parametrize(
    "name, method",
    [
        ("find_plan_templates_by_hash", SQLiteStateRepository.find_plan_templates_by_hash),
        ("list_all_plan_templates", SQLiteStateRepository.list_all_plan_templates),
    ],
)
def test_the_cache_calls_the_repository_with_arguments_it_accepts(name, method):
    call = _call_in(_ROOT / "weebot" / "domain" / "services" / "plan_template_cache.py", name)
    inspect.signature(method).bind(
        None,
        *[None] * len(call.args),
        **{kw.arg: None for kw in call.keywords if kw.arg},
    )
