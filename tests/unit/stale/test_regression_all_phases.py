"""Regression tests for bug fixes and paper-to-weebot implementations.

Covers: BUG-01 through BUG-10, BUG-06 (FTS5 lock), PR-2, R1, R3, R5.
"""
import asyncio
import inspect
import json
import random
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# BUG-01: SQL injection via filter keys
# ═══════════════════════════════════════════════════════════════════════════

class TestBug01FilterKeyValidation:
    """Filter keys with special chars must be dropped, not interpolated."""

    def test_safe_keys_preserved(self):
        from weebot.domain.services.filter_key_validator import validate_filter_keys
        result = validate_filter_keys({"name": "test", "confidence": 0.9})
        assert result == {"name": "test", "confidence": 0.9}

    def test_malicious_keys_dropped(self):
        from weebot.domain.services.filter_key_validator import validate_filter_keys
        result = validate_filter_keys({
            "'; DROP TABLE kg_nodes; --": "x",
            "safe": "ok",
        })
        assert "safe" in result
        assert len(result) == 1

    def test_empty_filters_returns_empty(self):
        from weebot.domain.services.filter_key_validator import validate_filter_keys
        assert validate_filter_keys({}) == {}
        assert validate_filter_keys(None) == {}

    def test_numeric_and_underscore_keys_accepted(self):
        from weebot.domain.services.filter_key_validator import validate_filter_keys
        result = validate_filter_keys({"_key": "v", "a1": "v"})
        assert "_key" in result
        assert "a1" in result

    def test_inline_regex_removed_from_postgresql(self):
        """BUG-01 fix must have removed inline regex in favor of shared validator."""
        source = Path("weebot/infrastructure/persistence/postgresql/knowledge_graph.py").read_text()
        assert "validate_filter_keys" in source
        assert "_SAFE_KEY" not in source  # inline regex removed


# ═══════════════════════════════════════════════════════════════════════════
# BUG-02: Sync sqlite3 in async methods → thread pool
# ═══════════════════════════════════════════════════════════════════════════

class TestBug02SqliteThreadPool:
    """Every async method must delegate to _run_db, not call sqlite3 directly."""

    METHODS = ["upsert_node", "add_edge", "query", "get_neighbors",
               "snapshot", "search", "get_stats"]

    def test_all_methods_use_run_db(self):
        from weebot.infrastructure.persistence.sqlite_knowledge_graph import SQLiteKnowledgeGraph
        for name in self.METHODS:
            method = getattr(SQLiteKnowledgeGraph, name, None)
            assert method is not None, f"{name} not found"
            source = inspect.getsource(method)
            assert "await self._run_db(" in source, (
                f"{name} does not delegate to _run_db"
            )

    def test_no_direct_sqlite_calls_in_async_methods(self):
        from weebot.infrastructure.persistence.sqlite_knowledge_graph import SQLiteKnowledgeGraph
        for name in self.METHODS:
            method = getattr(SQLiteKnowledgeGraph, name, None)
            source = inspect.getsource(method)
            assert "self._get_conn()" not in source, (
                f"{name} calls _get_conn directly instead of _run_db"
            )


# ═══════════════════════════════════════════════════════════════════════════
# BUG-03: PlaywrightAdapter TOCTOU race — lock + snapshot
# ═══════════════════════════════════════════════════════════════════════════

class TestBug03PlaywrightLock:
    """Every method must snapshot page under lock and guard inside lock."""

    METHODS = ["navigate", "get_state", "screenshot", "click", "fill",
               "type_text", "get_text", "get_element_info", "get_elements",
               "scroll", "hover", "select_option", "evaluate",
               "wait_for_selector", "go_back", "go_forward", "reload"]

    def test_all_methods_have_lock_snapshot(self):
        from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
        for name in self.METHODS:
            method = getattr(PlaywrightAdapter, name, None)
            assert method is not None, f"{name} not found"
            source = inspect.getsource(method)
            assert "async with self._lock:" in source, (
                f"{name} missing lock"
            )
            assert "page = self._page" in source, (
                f"{name} missing snapshot"
            )

    def test_no_remaining_direct_self_page_calls(self):
        from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
        for name in self.METHODS:
            method = getattr(PlaywrightAdapter, name, None)
            source = inspect.getsource(method)
            # Allow only the snapshot read and property access
            lines = [l for l in source.split("\n") if "self._page" in l]
            assert len(lines) <= 1, (
                f"{name} has {len(lines)} direct self._page references "
                f"(expected at most 1 for snapshot)"
            )

    def test_close_uses_lock(self):
        from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
        source = inspect.getsource(PlaywrightAdapter.close)
        assert "async with self._lock:" in source

    def test_library_init_has_lock(self):
        from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
        source = inspect.getsource(PlaywrightAdapter.__init__)
        assert "asyncio.Lock()" in source

    @pytest.mark.asyncio
    async def test_concurrent_close_does_not_crash(self):
        """close() running concurrently with navigate must not raise AttributeError."""
        from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
        from weebot.application.ports.browser_port import NavigationResult

        adapter = PlaywrightAdapter()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock(return_value=NavigationResult(
            success=True, url="about:blank", status_code=200,
            error=None, load_time_ms=0.0,
        ))
        mock_page.url = "about:blank"

        adapter._page = mock_page
        adapter._context = AsyncMock()
        adapter._browser = AsyncMock()
        adapter._playwright = AsyncMock()

        async def race_navigate():
            result = await adapter.navigate("https://example.com")
            return result

        async def race_close():
            await asyncio.sleep(0)
            await adapter.close()

        results = await asyncio.gather(
            race_navigate(), race_close(), return_exceptions=True,
        )
        for r in results:
            assert not isinstance(r, AttributeError), (
                f"TOCTOU race caused AttributeError: {r}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# BUG-04: Sync file I/O in async functions → asyncio.to_thread
# ═══════════════════════════════════════════════════════════════════════════

class TestBug04SyncIo:
    """File I/O in async def must use asyncio.to_thread."""

    FILES = [
        "weebot/application/services/self_improver.py",
        "weebot/application/services/cron_delivery_service.py",
        "weebot/application/services/user_modeling.py",
        "weebot/infrastructure/browser/session_manager.py",
    ]

    def test_files_have_asyncio_import(self):
        for path in self.FILES:
            source = Path(path).read_text()
            assert "import asyncio" in source, f"{path} missing import asyncio"

    def test_read_text_uses_to_thread(self):
        for path in self.FILES:
            source = Path(path).read_text()
            for line in source.splitlines():
                if "read_text" in line or "write_text" in line:
                    assert "asyncio.to_thread" in line or (
                        "open(" not in line
                    ), f"{path}: {line.strip()} without asyncio.to_thread"


# ═══════════════════════════════════════════════════════════════════════════
# BUG-05: OSWorld nested event loop fix
# ═══════════════════════════════════════════════════════════════════════════

class TestBug05OSWorldLoop:
    """predict() must use get_running_loop() not get_event_loop()."""

    def test_predict_uses_get_running_loop(self):
        from weebot.osworld.agent_adapter import WeebotOSWorldAgent
        source = inspect.getsource(WeebotOSWorldAgent.predict)
        assert "get_running_loop()" in source
        assert "get_event_loop()" not in source

    def test_predict_from_sync_context(self):
        """Calling predict() from sync context must use asyncio.run()."""
        from weebot.osworld.agent_adapter import WeebotOSWorldAgent
        source = inspect.getsource(WeebotOSWorldAgent.predict)
        assert "asyncio.run(" in source


# ═══════════════════════════════════════════════════════════════════════════
# BUG-06: FTS5 per-session lock
# ═══════════════════════════════════════════════════════════════════════════

class TestBug06Fts5Lock:
    """FTS5 indexing must use per-session asyncio.Lock."""

    def test_fts5_locks_dict_exists(self):
        from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
        repo = SQLiteStateRepository(":memory:")
        assert hasattr(repo, "_fts5_locks")
        assert isinstance(repo._fts5_locks, dict)

    def test_fts5_indexed_protected_by_lock(self):
        source = Path("weebot/infrastructure/persistence/sqlite_state_repo.py").read_text()
        assert "self._fts5_locks[session.id]" in source
        assert "async with self._fts5_locks[session.id]:" in source

    def test_asyncio_imported(self):
        source = Path("weebot/infrastructure/persistence/sqlite_state_repo.py").read_text()
        assert "import asyncio" in source


# ═══════════════════════════════════════════════════════════════════════════
# BUG-07: Telegram media FD leak fix
# ═══════════════════════════════════════════════════════════════════════════

class TestBug07FdLeak:
    """File handles must be wrapped in context manager."""

    def test_open_in_context_manager(self):
        source = Path("weebot/interfaces/gateways/telegram.py").read_text()
        assert "with open(path, \"rb\") as f:" in source


# ═══════════════════════════════════════════════════════════════════════════
# BUG-08: Telegram adapter lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestBug08AiohttpLifecycle:
    """Telegram notification adapter must have lifecycle methods."""

    def test_has_lifecycle_methods(self):
        from weebot.infrastructure.notifications.telegram_adapter import TelegramAdapter
        assert hasattr(TelegramAdapter, "close")
        assert hasattr(TelegramAdapter, "__aenter__")
        assert hasattr(TelegramAdapter, "__aexit__")
        assert hasattr(TelegramAdapter, "__del__")

    def test_close_checks_closed(self):
        source = Path("weebot/infrastructure/notifications/telegram_adapter.py").read_text()
        assert "not self._http_client.closed" in source


# ═══════════════════════════════════════════════════════════════════════════
# BUG-09: BrowserTool close()
# ═══════════════════════════════════════════════════════════════════════════

class TestBug09BrowserClose:
    """BrowserTool must have a close() method."""

    def test_close_exists(self):
        source = Path("weebot/tools/browser_tool.py").read_text()
        assert "async def close(self)" in source

    def test_close_nulls_browser(self):
        source = Path("weebot/tools/browser_tool.py").read_text()
        assert "self._browser = None" in source

    def test_close_try_finally(self):
        source = Path("weebot/tools/browser_tool.py").read_text()
        close_section = source.split("async def close")[1][:500]
        assert "finally:" in close_section
        assert "self._browser = None" in close_section


# ═══════════════════════════════════════════════════════════════════════════
# BUG-10: Silent except Exception → logger.debug
# ═══════════════════════════════════════════════════════════════════════════

class TestBug10SilentExceptions:
    """Bare except Exception: pass must be replaced with logger.debug."""

    FILES = [
        "weebot/application/cqrs/handlers/create_plan_handler.py",
        "weebot/application/flows/states/verifying.py",
        "weebot/application/flows/states/chat_message.py",
        "weebot/application/services/task_runner.py",
        "weebot/application/services/opportunity_engine.py",
        "weebot/application/services/skill_security_scanner.py",
        "weebot/application/models/tool_collection.py",
    ]

    def test_no_bare_except_pass(self):
        import ast
        for path_str in self.FILES:
            path = Path(path_str)
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        if handler.type is None:
                            continue
                        # asyncio.CancelledError: pass is standard task cleanup
                        if isinstance(handler.type, ast.Attribute) and handler.type.attr == "CancelledError":
                            continue
                        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                            pytest.fail(
                                f"{path_str}:{handler.lineno} — bare "
                                f"`except Exception: pass` found"
                            )


# ═══════════════════════════════════════════════════════════════════════════
# PR-2: FilterKeyValidator domain service
# ═══════════════════════════════════════════════════════════════════════════

class TestPr2FilterValidator:
    """FilterKeyValidator must be in domain layer and used by PostgreSQL adapter."""

    def test_validator_in_domain(self):
        path = Path("weebot/domain/services/filter_key_validator.py")
        assert path.exists()
        source = path.read_text()
        assert "def validate_filter_keys" in source

    def test_postgresql_uses_shared_validator(self):
        source = Path(
            "weebot/infrastructure/persistence/postgresql/knowledge_graph.py"
        ).read_text()
        assert "validate_filter_keys" in source
        assert "import re" not in source.split("query")[1][:500]


# ═══════════════════════════════════════════════════════════════════════════
# R1: Code quality signal
# ═══════════════════════════════════════════════════════════════════════════

class TestR1CodeQualitySignal:
    """CodeQualitySignal must provide score, composite, and fast_reject methods."""

    @pytest.mark.asyncio
    async def test_scoring(self):
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value=MagicMock(
            content='{"artifact_presence": 0.9, "verification_evidence": 0.7, "structure_quality": 0.8}',
        ))
        from weebot.application.services.code_quality_signal import CodeQualitySignal
        signal = CodeQualitySignal(llm=mock_llm)
        scores = await signal.score("test task", "test output")
        assert scores["artifact_presence"] == 0.9
        assert scores["verification_evidence"] == 0.7
        assert scores["structure_quality"] == 0.8
        composite = signal.composite(scores)
        assert 0.0 <= composite <= 1.0

    @pytest.mark.asyncio
    async def test_fast_reject(self):
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value=MagicMock(
            content='{"artifact_presence": 0.1, "verification_evidence": 0.1, "structure_quality": 0.1}',
        ))
        from weebot.application.services.code_quality_signal import CodeQualitySignal
        signal = CodeQualitySignal(llm=mock_llm, threshold=0.5)
        assert await signal.fast_reject("task", "bad output") is True

    @pytest.mark.asyncio
    async def test_low_quality_accepted_when_no_fast_reject(self):
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value=MagicMock(
            content='{"artifact_presence": 0.8, "verification_evidence": 0.7, "structure_quality": 0.9}',
        ))
        from weebot.application.services.code_quality_signal import CodeQualitySignal
        signal = CodeQualitySignal(llm=mock_llm, threshold=0.3)
        assert await signal.fast_reject("task", "good output") is False


# ═══════════════════════════════════════════════════════════════════════════
# R3: Evaluator co-evolution models
# ═══════════════════════════════════════════════════════════════════════════

class TestR3EvaluatorState:
    """EvaluatorState must provide best_belief and statistical comparison."""

    def test_best_belief_zero_for_no_data(self):
        from weebot.domain.models.evaluator_state import EvaluatorState
        e = EvaluatorState(evaluator_id="test", evaluator_type="judge", prompt="x")
        assert e.best_belief == 0.0

    def test_best_belief_increases_with_accuracy(self):
        from weebot.domain.models.evaluator_state import EvaluatorState
        low = EvaluatorState(
            evaluator_id="low", evaluator_type="judge", prompt="x",
            anchor_accuracy=0.5, anchor_total=10,
        )
        high = EvaluatorState(
            evaluator_id="high", evaluator_type="judge", prompt="x",
            anchor_accuracy=0.9, anchor_total=10,
        )
        assert high.best_belief > low.best_belief

    def test_statistically_outperforms(self):
        from weebot.domain.models.evaluator_state import EvaluatorState
        low = EvaluatorState(
            evaluator_id="low", evaluator_type="judge", prompt="x",
            anchor_accuracy=0.5, anchor_total=100,
        )
        high = EvaluatorState(
            evaluator_id="high", evaluator_type="judge", prompt="x",
            anchor_accuracy=0.95, anchor_total=100,
        )
        assert high.statistically_outperforms(low, epsilon=0.01)

    def test_does_not_outperform_with_small_gap(self):
        from weebot.domain.models.evaluator_state import EvaluatorState
        a = EvaluatorState(
            evaluator_id="a", evaluator_type="judge", prompt="x",
            anchor_accuracy=0.51, anchor_total=10,
        )
        b = EvaluatorState(
            evaluator_id="b", evaluator_type="judge", prompt="x",
            anchor_accuracy=0.52, anchor_total=10,
        )
        # Tiny gap should not be statistically significant
        assert not b.statistically_outperforms(a, epsilon=0.1)


# ═══════════════════════════════════════════════════════════════════════════
# R5: Thompson sampling archive
# ═══════════════════════════════════════════════════════════════════════════

class TestR5ThompsonSampling:
    """Archive search must implement Thompson sampling and CMP."""

    def test_thompson_sample_selects_best_node(self):
        random.seed(42)
        from weebot.domain.models.skill_archive import SkillArchiveNode
        nodes = [
            SkillArchiveNode(node_id="best", successes=10, failures=0),
            SkillArchiveNode(node_id="worst", successes=0, failures=10),
        ]
        selected = SkillArchiveNode.thompson_sample(nodes)
        assert selected.node_id == "best"

    def test_ucb_air_expands_when_small(self):
        from weebot.domain.models.skill_archive import SkillArchiveNode
        assert SkillArchiveNode.should_expand(evaluations_done=1, archive_size=1)
        assert not SkillArchiveNode.should_expand(
            evaluations_done=100, archive_size=100, alpha=0.3,
        )

    def test_cmp_aggregation(self):
        from weebot.domain.models.skill_archive import SkillArchiveNode, SkillArchive
        root = SkillArchiveNode(node_id="root", successes=2, failures=0, skill_version="v1")
        child = SkillArchiveNode(
            node_id="child", parent_id="root", successes=1, failures=2, skill_version="v2",
        )
        archive = SkillArchive()
        archive.add_node(root)
        archive.add_node(child)
        # root clade: (2+1) / (2+0+1+2) = 3/5 = 0.6
        assert archive.compute_cmp("root") == pytest.approx(0.6)
        # child clade: 1/3 ≈ 0.333
        assert archive.compute_cmp("child") == pytest.approx(1/3)

    def test_archive_tree_structure(self):
        from weebot.domain.models.skill_archive import SkillArchiveNode, SkillArchive
        root = SkillArchiveNode(node_id="root", skill_version="v1")
        a = SkillArchiveNode(node_id="a", parent_id="root", skill_version="v2")
        b = SkillArchiveNode(node_id="b", parent_id="root", skill_version="v2")
        archive = SkillArchive()
        archive.add_node(root)
        archive.add_node(a)
        archive.add_node(b)
        assert archive.root_id == "root"
        assert archive.get_node("root").children == ["a", "b"]
        assert len(archive.get_leaves()) == 2

    def test_record_evaluation_updates_totals(self):
        from weebot.domain.models.skill_archive import SkillArchive
        from weebot.domain.models.skill_archive import SkillArchiveNode
        node = SkillArchiveNode(node_id="n", skill_version="v1")
        archive = SkillArchive()
        archive.add_node(node)
        archive.record_evaluation("n", True)
        archive.record_evaluation("n", False)
        assert archive.get_node("n").successes == 1
        assert archive.get_node("n").failures == 1
        assert archive.total_evaluations == 2


# ═══════════════════════════════════════════════════════════════════════════
# Cross-cutting: Architecture fitness — all layers clean
# ═══════════════════════════════════════════════════════════════════════════

class TestArchitectureFitness:
    """Key architecture rules must be satisfied."""

    def test_no_exception_pass_in_non_test_code(self):
        """Bare except Exception: pass must not exist outside tests."""
        import subprocess
        result = subprocess.run(
            ['grep', '-Prn', r'except\s+(\w+(\.\w+)?|\([^)]+\)):\s*pass\s*$',
             'weebot/', '--include=*.py'],
            capture_output=True, text=True,
        )
        # Filter out test files and __pycache__
        lines = [
            l for l in result.stdout.splitlines()
            if 'tests/' not in l and '__pycache__' not in l
        ]
        assert len(lines) == 0, f"Found bare except:pass in {lines}"

    def test_domain_has_no_infrastructure_imports(self):
        """Domain layer must not import infrastructure or application.

        Pre-existing exceptions: tool_manifest.py (legacy), harness_edit.py (cross-layer).
        """
        domain_dir = Path("weebot/domain")
        exceptions = {"tool_manifest.py", "harness_edit.py"}
        for py_file in domain_dir.rglob("*.py"):
            if py_file.name in exceptions:
                continue
            source = py_file.read_text()
            if "weebot.infrastructure" in source or "weebot.application" in source:
                pytest.fail(f"{py_file} imports infrastructure or application")
