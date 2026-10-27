"""Skills learn from successful runs, ON by default.

Before: the main flow never received the distiller or the review gate, candidate skills
were never injected, no step recorded which skills it used, and nothing in a live run
counted a use, so the candidate -> trusted promotion never fired. These tests pin each
seam of the loop: distil (successes only) -> review -> inject as candidate -> count uses
per session -> promote after three, quarantine after two failures.
"""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.domain.models.skill import Skill, SkillMatch, SkillMetadata, SkillProvenance

# ── flags ───────────────────────────────────────────────────────────────────

_ON_BY_DEFAULT = {
    "LIVE_SKILL_DISTILLATION_ENABLED": "WEEBOT_LIVE_SKILL_DISTILLATION",
    "SKILL_REVIEW_GATE_ENABLED": "WEEBOT_SKILL_REVIEW_GATE",
    "SKILL_MATERIALIZE_ENABLED": "WEEBOT_SKILL_MATERIALIZE",
    "SKILL_GAP_TRIGGER_ENABLED": "WEEBOT_SKILL_GAP_TRIGGER",
    "SEMANTIC_SKILL_RETRIEVAL_ENABLED": "WEEBOT_SEMANTIC_SKILL_RETRIEVAL",
    "CURATION_ACTIONS_ENABLED": "WEEBOT_CURATION_ACTIONS",
}


def _reloaded_flags_without(env_names):
    import weebot.config.feature_flags as flags

    env = {k: v for k, v in os.environ.items() if k not in env_names}
    with patch.dict("os.environ", env, clear=True):
        return importlib.reload(flags)


def test_the_skill_flags_are_on_by_default():
    import weebot.config.feature_flags as flags

    try:
        reloaded = _reloaded_flags_without(set(_ON_BY_DEFAULT.values()))
        off = [name for name in _ON_BY_DEFAULT if getattr(reloaded, name) is not True]
        assert not off, f"default OFF: {off}"
    finally:
        importlib.reload(flags)


def test_self_editing_stays_off_by_default():
    import weebot.config.feature_flags as flags

    try:
        reloaded = _reloaded_flags_without({"WEEBOT_METACOGNITIVE_IMPROVEMENT"})
        assert reloaded.METACOGNITIVE_IMPROVEMENT_ENABLED is False
    finally:
        importlib.reload(flags)


@pytest.mark.parametrize("name,env", list(_ON_BY_DEFAULT.items()))
def test_each_flag_can_still_be_turned_off(name, env):
    import weebot.config.feature_flags as flags

    try:
        with patch.dict("os.environ", {env: "false"}):
            assert getattr(importlib.reload(flags), name) is False
    finally:
        importlib.reload(flags)


# ── a candidate is injected, a quarantined skill is not ─────────────────────


def _skill(name="s", trust="candidate", positive=0) -> Skill:
    return Skill(
        name=name,
        description=f"how to {name}",
        content=f"steps for {name}",
        metadata=SkillMetadata(
            trust=trust,
            provenance=SkillProvenance(origin="distilled", positive_uses=positive),
        ),
    )


def test_a_candidate_is_injectable_and_a_quarantined_skill_is_not():
    assert _skill(trust="candidate").is_injectable is True
    assert _skill(trust="trusted").is_injectable is True
    assert _skill(trust="quarantined").is_injectable is False


async def test_bm25_matches_carry_the_skill_trust():
    from weebot.application.services.bm25_skill_retriever import BM25SkillRetriever

    registry = MagicMock()
    registry.list_all.return_value = {"deploy-site": _skill("deploy-site", trust="candidate")}
    retriever = BM25SkillRetriever(registry)
    retriever.refresh()

    matches = await retriever.retrieve("deploy site steps", top_k=1)
    assert matches and matches[0].trust == "candidate"


async def test_the_prompt_injects_one_candidate_and_records_it():
    from weebot.application.agents.executor._prompt_builder import build_executor_prompt

    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[
            SkillMatch(skill_name="cand-a", content_preview="A", score=0.9, trust="candidate"),
            SkillMatch(skill_name="cand-b", content_preview="B", score=0.8, trust="candidate"),
            SkillMatch(skill_name="human-c", content_preview="C", score=0.7, trust="trusted"),
        ]
    )
    used: list[str] = []
    prompt = await build_executor_prompt(
        "do the thing", base_prompt="base", skill_retriever=retriever, skills_used=used
    )
    assert "cand-a" in prompt and "cand-b" not in prompt
    assert used == ["cand-a"]  # only candidates are counted; trusted skills need no counting


# ── the main flow gets the distiller and the review gate ────────────────────


def test_the_main_flow_receives_the_distiller_and_the_review_gate():
    from weebot.application.flows.flow_builder import build_flow
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

    distiller, gate = object(), object()
    known = {"skill_distiller": distiller, "skill_review_gate": gate}

    flow = build_flow(
        resolve=lambda key: known.get(key) if isinstance(key, str) else None,
        flow_type="plan_act",
        session=Session(id="s-flow", user_id="u", agent_id="a"),
        llm=MagicMock(),
        tools=ToolCollection(),
        mediator=MagicMock(),
    )
    assert flow._skill_distiller is distiller
    assert flow._skill_review_gate is gate


# ── distil only from successes, never over an existing skill ────────────────


def _plan(*statuses):
    from weebot.domain.models.plan import Plan, Step, StepStatus

    return Plan(
        title="t",
        message="m",
        steps=[
            Step(id=str(i), description=f"s{i}", status=StepStatus(st))
            for i, st in enumerate(statuses)
        ],
    )


def _context(plan):
    session = SimpleNamespace(id="sess-1", context=SimpleNamespace(original_task="task"))
    return SimpleNamespace(
        _skill_distiller=SimpleNamespace(analyze_session=AsyncMock(return_value=None)),
        _skill_review_gate=None,
        _session=session,
        _plan=plan,
        _event_bus=None,
        _log=MagicMock(),
    )


async def test_a_failed_run_is_not_distilled():
    from weebot.application.flows.states.meta_analysis import _maybe_distil_skill

    ctx = _context(_plan("completed", "failed"))
    await _maybe_distil_skill(ctx, [("0", "s0")], ["boom"], 1)
    ctx._skill_distiller.analyze_session.assert_not_awaited()


async def test_a_successful_run_is_distilled():
    from weebot.application.flows.states.meta_analysis import _maybe_distil_skill

    ctx = _context(_plan("completed", "completed"))
    await _maybe_distil_skill(ctx, [("0", "s0"), ("1", "s1")], [], 2)
    ctx._skill_distiller.analyze_session.assert_awaited_once()


class _Store:
    def __init__(self, *skills):
        self.skills = {s.name: s for s in skills}
        self.saved: list[Skill] = []

    async def load(self, name):
        return self.skills.get(name)

    async def save(self, skill):
        self.saved.append(skill)
        self.skills[skill.name] = skill

    async def list_names(self):
        return list(self.skills)

    async def delete(self, name):
        return self.skills.pop(name, None) is not None


async def test_distillation_never_overwrites_an_existing_skill():
    from weebot.application.services.autonomous_learning import AutonomousSkillCreator

    existing = _skill("deploy-site", trust="trusted")
    store = _Store(existing)
    tracker = MagicMock()
    tracker.record_and_check.return_value = True
    creator = AutonomousSkillCreator(llm=MagicMock(), skill_store=store, proposal_tracker=tracker)
    creator._call_distiller = AsyncMock(return_value=("deploy-site", "d", "new content"))
    result = await creator.analyze_session("sess-1", "x" * 600)
    assert result is None
    assert store.saved == [] and store.skills["deploy-site"] is existing


# ── uses are counted per session; three promote, two failures quarantine ────


def _use_handler(store):
    from weebot.application.cqrs.handlers.validation_handler import RecordSkillUseHandler

    return RecordSkillUseHandler(skill_store=store)


def _use(name, session, passed=True):
    from weebot.application.cqrs.commands.validation_commands import RecordSkillUseCommand

    return RecordSkillUseCommand(skill_name=name, session_id=session, step_id="1", passed=passed)


async def test_three_successful_sessions_promote_a_candidate():
    store = _Store(_skill("deploy-site"))
    handler = _use_handler(store)
    for session in ("s1", "s1", "s2"):  # the repeat in s1 is not a second use
        await handler.handle(_use("deploy-site", session))
    assert store.skills["deploy-site"].metadata.trust == "candidate"
    assert store.skills["deploy-site"].metadata.provenance.positive_uses == 2
    await handler.handle(_use("deploy-site", "s3"))
    assert store.skills["deploy-site"].metadata.trust == "trusted"


async def test_two_failed_sessions_quarantine_a_candidate():
    store = _Store(_skill("deploy-site"))
    handler = _use_handler(store)
    await handler.handle(_use("deploy-site", "s1", passed=False))
    await handler.handle(_use("deploy-site", "s1", passed=False))
    assert store.skills["deploy-site"].metadata.trust == "candidate"
    await handler.handle(_use("deploy-site", "s2", passed=False))
    assert store.skills["deploy-site"].metadata.trust == "quarantined"


async def test_a_trusted_or_unknown_skill_is_left_alone():
    store = _Store(_skill("human", trust="trusted"))
    handler = _use_handler(store)
    await handler.handle(_use("human", "s1", passed=False))
    await handler.handle(_use("not-stored", "s1"))
    assert store.saved == []


def test_the_live_mediator_counts_skill_uses():
    from weebot.application.cqrs.commands.validation_commands import RecordSkillUseCommand
    from weebot.application.cqrs.handlers import register_default_handlers
    from weebot.application.cqrs.mediator import Mediator

    mediator = Mediator()
    register_default_handlers(mediator, MagicMock(), llm=MagicMock(), skill_store=_Store())
    assert RecordSkillUseCommand in mediator._command_handlers


async def test_a_step_reports_its_used_skills_to_the_mediator():
    from weebot.application.flows.states._step_run import record_skill_uses

    sent = []

    async def send(command):
        sent.append(command)

    ctx = SimpleNamespace(_mediator=SimpleNamespace(send=send), _session=SimpleNamespace(id="s9"))
    run = SimpleNamespace(skills_used=["cand-a"])
    await record_skill_uses(ctx, SimpleNamespace(id="2"), run, passed=True)
    assert [(c.skill_name, c.session_id, c.step_id, c.passed) for c in sent] == [
        ("cand-a", "s9", "2", True)
    ]


def test_executing_state_reports_skill_uses_on_both_outcomes():
    src = Path("weebot/application/flows/states/executing.py").read_text(encoding="utf-8")
    assert src.count("record_skill_uses(") == 2


# ── promoted and demoted skills reach the disk the retriever reads ──────────


def _materializer(already_written: bool):
    return SimpleNamespace(materialize=AsyncMock(), is_materialized=lambda _n: already_written)


async def test_a_candidate_save_is_materialized():
    from weebot.application.services.materializing_skill_store import MaterializingSkillStore

    materializer = _materializer(False)
    await MaterializingSkillStore(store=_Store(), materializer=materializer).save(
        _skill("cand", trust="candidate")
    )
    materializer.materialize.assert_awaited_once()


async def test_a_demoted_skill_is_rewritten_so_it_leaves_the_index():
    from weebot.application.services.materializing_skill_store import MaterializingSkillStore

    materializer = _materializer(True)
    await MaterializingSkillStore(store=_Store(), materializer=materializer).save(
        _skill("cand", trust="quarantined")
    )
    materializer.materialize.assert_awaited_once()


async def test_a_fresh_quarantined_skill_is_not_written():
    from weebot.application.services.materializing_skill_store import MaterializingSkillStore

    materializer = _materializer(False)
    await MaterializingSkillStore(store=_Store(), materializer=materializer).save(
        _skill("cand", trust="quarantined")
    )
    materializer.materialize.assert_not_awaited()


# ── semantic retrieval falls back to BM25 without an embedding backend ──────


def test_semantic_retrieval_without_embeddings_falls_back_to_bm25(monkeypatch):
    import weebot.config.learning as learning
    from weebot.application.services.bm25_skill_retriever import BM25SkillRetriever
    from weebot.qmd_integration import embeddings

    monkeypatch.setattr(learning, "SEMANTIC_SKILL_RETRIEVAL_ENABLED", True)
    monkeypatch.setattr(embeddings, "semantic_embeddings_available", lambda: False)

    from weebot.application.di import Container

    retriever = Container()._create_skill_retriever()
    base = getattr(retriever, "_base", retriever)
    assert isinstance(base, BM25SkillRetriever)


# ── curation archives only learned skills, and never a pinned one ───────────


async def _curate(tmp_path, monkeypatch, recommendation, under_learned=True):
    from weebot.application.services import skill_curator as sc

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sc, "CURATION_ACTIONS_ENABLED", True, raising=False)
    root = tmp_path / ".weebot" / "skills" if under_learned else tmp_path / "builtin"
    skill_dir = root / "old-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: old-skill\n---\nbody", encoding="utf-8")
    skill = Skill(
        name="old-skill", description="d", content="body", source_path=str(skill_dir / "SKILL.md")
    )
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=SimpleNamespace(content=f"{recommendation}\nreason"))
    curator = sc.SkillCurator(registry=MagicMock(), llm=llm, cheap_model="m")
    await curator._review_and_log(skill, "archive-candidate", datetime.now(UTC))
    return skill_dir, tmp_path / ".weebot" / "skills" / "_archived" / "old-skill"


async def test_an_archive_recommendation_moves_a_learned_skill(tmp_path, monkeypatch):
    src, dest = await _curate(tmp_path, monkeypatch, "ARCHIVE")
    assert not src.exists() and (dest / "SKILL.md").exists()


async def test_a_pinned_skill_stays(tmp_path, monkeypatch):
    src, dest = await _curate(tmp_path, monkeypatch, "PIN")
    assert src.exists() and not dest.exists()


async def test_a_builtin_skill_is_never_moved(tmp_path, monkeypatch):
    src, dest = await _curate(tmp_path, monkeypatch, "ARCHIVE", under_learned=False)
    assert src.exists() and not dest.exists()


# ── the promotion job that could never run is gone ──────────────────────────


def test_the_dead_promotion_job_is_removed():
    import yaml

    jobs = yaml.safe_load(Path("weebot/config/jobs.yaml").read_text(encoding="utf-8"))["jobs"]
    assert "skill_promotion_check" not in {j["job_id"] for j in jobs}


# ── a held-out validation with nothing measured is not a use ────────────────


async def test_a_bootstrap_validation_pass_records_no_use():
    from weebot.application.cqrs.commands.validation_commands import ValidateSkillCommand
    from weebot.application.cqrs.handlers.validation_handler import ValidateSkillHandler
    from weebot.application.services.validation_runner import ValidationResult

    store = _Store(_skill("deploy-site"))
    result = ValidationResult(
        passed=True, candidate_score=0.1, current_score=-1.0, n_tasks=1, details={}
    )
    runner = SimpleNamespace(validate=AsyncMock(return_value=result))
    handler = ValidateSkillHandler(validation_runner=runner, skill_store=store)
    await handler.handle(
        ValidateSkillCommand(
            skill_name="deploy-site", candidate_content="c", validation_task_ids=["t"]
        )
    )
    assert store.saved == []  # a bootstrap "pass" at score 0.1 proves nothing


# ── the self-editing flag actually blocks self-edits ────────────────────────


def test_self_improver_cannot_target_itself_while_its_flag_is_off(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.services.self_improver import SelfImprover

    target = "weebot/application/services/self_improver.py"
    monkeypatch.setattr(flags, "METACOGNITIVE_IMPROVEMENT_ENABLED", False)
    assert SelfImprover._is_allowed_target(target) is False
    monkeypatch.setattr(flags, "METACOGNITIVE_IMPROVEMENT_ENABLED", True)
    assert SelfImprover._is_allowed_target(target) is True
