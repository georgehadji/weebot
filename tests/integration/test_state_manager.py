"""Integration tests for StateManager (real SQLite, no mocks)."""
import pytest
import asyncio
from datetime import datetime
from weebot.state_manager import StateManager, ProjectState, ProjectStatus, ResumableTask


@pytest.fixture
def sm(tmp_db):
    """StateManager backed by a temp SQLite database."""
    return StateManager(db_path=str(tmp_db))


class TestCreateAndLoad:
    def test_create_project_returns_state(self, sm):
        state = sm.create_project("proj-001", "Test project")
        assert isinstance(state, ProjectState)
        assert state.project_id == "proj-001"

    def test_created_state_is_pending(self, sm):
        state = sm.create_project("proj-002", "Test")
        assert state.status == ProjectStatus.PENDING

    def test_load_returns_none_for_unknown_project(self, sm):
        assert sm.load_state("nonexistent") is None

    def test_save_and_load_roundtrip(self, sm):
        sm.create_project("proj-003", "Roundtrip test")
        loaded = sm.load_state("proj-003")
        assert loaded is not None
        assert loaded.project_id == "proj-003"

    def test_save_updates_existing_state(self, sm):
        state = sm.create_project("proj-004", "Update test")
        state.status = ProjectStatus.RUNNING
        sm.save_state(state)
        loaded = sm.load_state("proj-004")
        assert loaded.status == ProjectStatus.RUNNING


class TestListProjects:
    def test_empty_list_when_no_projects(self, sm):
        assert sm.list_projects() == []

    def test_lists_all_created_projects(self, sm):
        sm.create_project("p1", "first")
        sm.create_project("p2", "second")
        projects = sm.list_projects()
        ids = [p["project_id"] for p in projects]
        assert "p1" in ids
        assert "p2" in ids

    def test_list_returns_dicts_with_required_keys(self, sm):
        sm.create_project("p3", "third")
        projects = sm.list_projects()
        assert "project_id" in projects[0]
        assert "updated_at" in projects[0]


class TestCheckpoints:
    def test_add_checkpoint_returns_id(self, sm):
        sm.create_project("cp-proj", "checkpoint test")
        checkpoint_id = sm.add_checkpoint("cp-proj", "Review needed")
        assert isinstance(checkpoint_id, str)
        assert checkpoint_id.startswith("chk_")

    def test_pending_checkpoints_listed(self, sm):
        sm.create_project("cp-proj2", "test")
        sm.add_checkpoint("cp-proj2", "Review step 1")
        pending = sm.get_pending_checkpoints("cp-proj2")
        assert len(pending) == 1

    def test_resolved_checkpoint_not_in_pending(self, sm):
        sm.create_project("cp-proj3", "test")
        chk_id = sm.add_checkpoint("cp-proj3", "Review step 2")
        sm.resolve_checkpoint(chk_id, "yes")
        pending = sm.get_pending_checkpoints("cp-proj3")
        assert len(pending) == 0

    def test_multiple_checkpoints_tracked(self, sm):
        sm.create_project("cp-proj4", "test")
        sm.add_checkpoint("cp-proj4", "Step A")
        sm.add_checkpoint("cp-proj4", "Step B")
        pending = sm.get_pending_checkpoints("cp-proj4")
        assert len(pending) == 2


class TestResumableTask:
    @pytest.mark.asyncio
    async def test_task_marked_complete_on_success(self, sm):
        sm.create_project("rt-proj", "resumable test")
        async with ResumableTask(sm, "rt-proj", "task_alpha") as task:
            assert task is not None  # not already completed

        state = sm.load_state("rt-proj")
        assert "task_alpha" in state.completed_tasks

    @pytest.mark.asyncio
    async def test_already_completed_task_returns_none(self, sm):
        sm.create_project("rt-proj2", "resumable test 2")
        # Complete it once
        async with ResumableTask(sm, "rt-proj2", "task_beta"):
            pass
        # Second entry should return None (skip)
        async with ResumableTask(sm, "rt-proj2", "task_beta") as ctx:
            assert ctx is None

    @pytest.mark.asyncio
    async def test_failed_task_logs_error(self, sm):
        sm.create_project("rt-proj3", "error test")
        try:
            async with ResumableTask(sm, "rt-proj3", "task_gamma"):
                raise RuntimeError("Simulated failure")
        except RuntimeError:
            pass

        state = sm.load_state("rt-proj3")
        assert state.status == ProjectStatus.FAILED
        assert any("Simulated failure" in e for e in state.error_log)

    @pytest.mark.asyncio
    async def test_raises_for_unknown_project(self, sm):
        with pytest.raises(ValueError, match="not found"):
            async with ResumableTask(sm, "ghost-project", "task"):
                pass


class TestSubSessions:
    def test_create_project_has_empty_sub_sessions(self, sm):
        state = sm.create_project("ss-proj", "sub-session test")
        assert state.sub_sessions == []

    def test_start_sub_session_adds_entry(self, sm):
        sm.create_project("ss-proj2", "test")
        sm.start_sub_session("ss-proj2", "task_a", activity_kind="exec")
        state = sm.load_state("ss-proj2")
        assert len(state.sub_sessions) == 1
        assert state.sub_sessions[0].name == "task_a"
        assert state.sub_sessions[0].activity_kind == "exec"

    def test_end_sub_session_sets_ended_at(self, sm):
        sm.create_project("ss-proj3", "test")
        sm.start_sub_session("ss-proj3", "task_b", activity_kind="read")
        sm.end_sub_session("ss-proj3", "task_b", status="completed")
        state = sm.load_state("ss-proj3")
        assert state.sub_sessions[0].ended_at is not None
        assert state.sub_sessions[0].status == "completed"

    def test_multiple_sub_sessions_tracked(self, sm):
        sm.create_project("ss-proj4", "test")
        sm.start_sub_session("ss-proj4", "step1", activity_kind="job")
        sm.start_sub_session("ss-proj4", "step2", activity_kind="write")
        state = sm.load_state("ss-proj4")
        assert len(state.sub_sessions) == 2

    def test_start_sub_session_unknown_project_raises(self, sm):
        import pytest
        with pytest.raises(ValueError, match="not found"):
            sm.start_sub_session("nonexistent", "task", activity_kind="job")
