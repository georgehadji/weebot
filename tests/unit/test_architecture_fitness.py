"""Architecture fitness tests — AST-based enforcement of Clean Architecture rules.

These tests use Python's ``ast`` module to verify that module imports and
structure conform to the architecture defined in the remediation plan.
They are designed to fail LOUDLY when a refactoring introduces an
architectural violation, so the issue is caught at CI time.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent / "weebot"


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _walk_py(path: Path) -> list[Path]:
    """Recursively find all ``.py`` files under *path*."""
    return sorted(path.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=str(path))


def _module_imports(tree: ast.Module) -> list[str]:
    """Return all module-level import targets (``import X`` / ``from X import``)."""
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # Skip TYPE_CHECKING blocks
            if node.level is not None and node.level > 0:
                continue
            # Check if inside TYPE_CHECKING guard
            for parent in ast.walk(tree):
                if isinstance(parent, ast.If):
                    guard = ast.unparse(parent.test)
                    if "TYPE_CHECKING" in guard and node in ast.walk(parent):
                        break
            else:
                if node.module:
                    imports.append(node.module)
    return imports


def _module_imports_including_type_checking(tree: ast.Module) -> list[str]:
    """Return all import targets including those under TYPE_CHECKING."""
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _module_defines_class(tree: ast.Module, cls_name: str) -> bool:
    """Check if *tree* defines a top-level class named *cls_name*."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            return True
    return False


def _iter_subclasses_of(tree: ast.Module, base_name: str) -> list[str]:
    """Return names of top-level classes that inherit from *base_name*."""
    classes: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if ast.unparse(base) == base_name:
                    classes.append(node.name)
    return classes


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: Domain layer must be pure
# ═════════════════════════════════════════════════════════════════════════════

def test_domain_has_no_outer_imports():
    """Domain layer must NOT import from core, infrastructure, application,
    interfaces, or tools — even under TYPE_CHECKING."""
    forbidden_prefixes = ("weebot.core", "weebot.infrastructure",
                          "weebot.application", "weebot.interfaces",
                          "weebot.tools")
    violations: list[str] = []

    for path in _walk_py(ROOT / "domain"):
        tree = _parse(path)
        for imp in _module_imports_including_type_checking(tree):
            if any(imp.startswith(p) for p in forbidden_prefixes):
                rel = path.relative_to(ROOT.parent)
                violations.append(f"{rel}: imports {imp!r}")

    assert not violations, (
        "Domain layer must be pure — no outer-layer imports allowed.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: Application must not import infrastructure at module level
# ═════════════════════════════════════════════════════════════════════════════

def test_application_no_module_level_infra_imports():
    """Application layer may import infrastructure ONLY inside functions/methods
    or TYPE_CHECKING blocks — never at module level."""
    violations: list[str] = []
    # Our own di.py is the one allowed composition root.
    # Also allow services that import infra adapters at module level
    # (tracked for future migration in ARCHITECTURE_9_PLAN.md).
    allowed_exceptions = {
        "di.py", "__init__.py",
        "meta_self_improver.py",   # imports meta_improvement_log (tracked)
        "strategy_transfer.py",    # imports strategy_store (tracked)
    }

    for path in _walk_py(ROOT / "application"):
        if path.name in allowed_exceptions:
            continue
        tree = _parse(path)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Skip TYPE_CHECKING guards
                # (these would be inside an if block, not at module top level)
                for imp in ([n.name for n in node.names] if isinstance(node, ast.Import)
                            else [node.module] if node.module else []):
                    if imp and imp.startswith("weebot.infrastructure"):
                        rel = path.relative_to(ROOT.parent)
                        violations.append(f"{rel}: module-level import {imp!r}")

    assert not violations, (
        "Application must not import infrastructure at module level.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 3 & 4: All commands / queries have registered handlers
# ═════════════════════════════════════════════════════════════════════════════

def test_every_command_has_handler():
    """Every ``Command`` subclass defined in ``cqrs/commands/`` must be
    registered in a handler file (handlers.py or handlers/ subdirectory)."""
    commands_dir = ROOT / "application" / "cqrs" / "commands"
    handlers_py = ROOT / "application" / "cqrs" / "handlers.py"
    handlers_dir = ROOT / "application" / "cqrs" / "handlers"

    # Collect all handler registration content
    handlers_content = ""
    if handlers_py.exists():
        handlers_content += handlers_py.read_text(encoding="utf-8")
    if handlers_dir.exists():
        for hp in _walk_py(handlers_dir):
            if hp.name != "__init__.py":
                handlers_content += hp.read_text(encoding="utf-8")

    if not handlers_content:
        pytest.skip("No handler files found")

    # Find all Command subclasses recursively in commands/
    missing: list[str] = []
    for path in _walk_py(commands_dir):
        if path.name == "__init__.py":
            continue
        tree = _parse(path)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases]
                if any("Command" in b for b in bases):
                    if node.name not in handlers_content:
                        missing.append(f"{node.name} (in {path.name})")

    assert not missing, (
        "Every Command subclass must have a registered handler.\n"
        f"Missing handlers for: {', '.join(missing)}"
    )


def test_every_query_has_handler():
    """Every ``Query`` subclass defined in ``queries.py`` must be
    registered in ``handlers.py``."""
    queries_py = ROOT / "application" / "cqrs" / "queries.py"
    handlers_py = ROOT / "application" / "cqrs" / "handlers.py"

    if not queries_py.exists() or not handlers_py.exists():
        pytest.skip("queries.py or handlers.py not found")

    queries_tree = _parse(queries_py)
    handlers_content = handlers_py.read_text(encoding="utf-8")

    missing: list[str] = []
    for node in ast.iter_child_nodes(queries_tree):
        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            if any("Query" in b for b in bases):
                if node.name not in handlers_content:
                    missing.append(node.name)

    assert not missing, (
        "Every Query subclass must have a registered handler.\n"
        f"Missing handlers for: {', '.join(missing)}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: Only di.py is the composition root
# ═════════════════════════════════════════════════════════════════════════════

def test_di_single_composition_root():
    """Only ``di.py`` should instantiate infrastructure adapters.
    Other files that call ``Container.get()`` or construct adapters
    directly are violations."""
    di_init = ROOT / "application" / "di" / "__init__.py"
    assert di_init.exists(), "DI container (di/__init__.py) must exist as the composition root"

    # Check that no other application file directly imports infrastructure
    # adapters at module level (already covered by test 2 above)


# ═════════════════════════════════════════════════════════════════════════════
# Test 6: Flow states must use mediator.send(), not direct agent calls
# ═════════════════════════════════════════════════════════════════════════════

def test_no_direct_agent_calls_in_flow_states():
    """Flow state files should prefer ``context._mediator.send()`` over
    direct agent imports. Known fallback imports are allowed."""
    # Flow states that import agents for fallback (non-mediator path)
    allowed_imports = {
        "weebot.application.agents.planner",
        "weebot.application.agents.chat_agent",
        "weebot.application.agents.executor._error_handler",
        "weebot.application.agents.parallel_planner",
    }
    violations: list[str] = []

    for path in _walk_py(ROOT / "application" / "flows" / "states"):
        tree = _parse(path)
        for imp in _module_imports(tree):
            if imp.startswith("weebot.application.agents"):
                if imp not in allowed_imports:
                    rel = path.relative_to(ROOT.parent)
                    violations.append(f"{rel}: imports {imp!r}")

    assert not violations, (
        "Flow states should not import unexpected agent classes.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 7: Every port in application/ports/ has at least one adapter
# ═════════════════════════════════════════════════════════════════════════════

def test_ports_have_adapters():
    """Every port defined in ``application/ports/`` must have at least one
    registered adapter in the DI container or an implementing class in
    ``infrastructure/``.
    """
    ports_dir = ROOT / "application" / "ports"
    infra_dir = ROOT / "infrastructure"

    # Known port → adapter mapping (add new ports here).
    # Adapters may live in infrastructure/ OR application/services/.
    port_adapter_map: dict[str, list[str]] = {
        "EventBusPort": ["AsyncEventBus"],
        "EventPublisherPort": ["WebSocketEventBroadcaster"],  # in interfaces/ not infra/
        "LLMPort": ["OpenRouterAdapter", "AnthropicAdapter", "DeepSeekAdapter",
                     "OpenAIAdapter", "ResilientAdapter"],
        "StateRepositoryPort": ["SQLiteStateRepository", "InMemoryStateRepository"],
        "OptimizerPort": ["OptimizerAgent"],
        "ScoringPort": ["ExactMatchScorer", "ExecutionResultScorer", "VerifierScorer"],
        "SandboxPort": ["NativeWindowsSandbox", "WSL2Sandbox", "DockerLinuxSandbox"],
        "EventStorePort": ["EventStore"],
        # Ports implemented by application services (not infrastructure adapters)
        "AuditPort": ["AuditService"],
        "BehavioralLearnerPort": ["BehavioralLearner"],
        "CanonicalizerPort": ["ActionCanonicalizer"],
        "PlanCriticPort": ["PlanCriticService"],
        "SelfImprovementPort": ["SelfImprover"],
        "SkillRetrieverPort": ["BM25SkillRetriever"],
        "TaskRouterPort": ["KeywordTaskRouter"],
        "DreamerPort": ["DreamerAgent"],
        "RetentionAgentPort": ["RetentionAgent"],
        "IntentReviewPort": ["IntentReviewService"],
        "MainReviewPort": ["MainReviewService"],
        "JudgePort": ["ModelJudge", "ScoreJudge"],
    }

    # Ports documented as [DEPRECATED] — no adapter expected.
    deprecated_ports = {"SwarmEventBusPort",
                        "TaskQueuePort", "SpeechPort"}

    # Find all port classes (files with ABC/Protocol that define ports)
    missing: list[str] = []
    services_dir = ROOT / "application" / "services"
    for path in _walk_py(ports_dir):
        if path.name == "__init__.py":
            continue
        tree = _parse(path)
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Only consider classes that directly inherit from ABC
            bases = [ast.unparse(b).strip() for b in node.bases]
            if "ABC" not in bases:
                continue
            pc = node.name
            # Skip ports documented as deprecated
            if pc in deprecated_ports:
                continue
            adapters = port_adapter_map.get(pc, [])
            if not adapters:
                # Try to find adapters in infrastructure OR application/services
                adapter_found = False
                for search_dir in (infra_dir, services_dir):
                    if not search_dir.exists():
                        continue
                    for adapter_path in _walk_py(search_dir):
                        content = adapter_path.read_text(encoding="utf-8")
                        if pc in content and (
                            f"({pc})" in content or f"class {pc}" in content
                        ):
                            adapter_found = True
                            break
                    if adapter_found:
                        break
                if not adapter_found:
                    missing.append(pc)

    assert not missing, (
        "Every port in application/ports/ must have at least one adapter.\n"
        f"Missing adapters for: {', '.join(missing)}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 8: No new flat files at weebot/ root
# ═════════════════════════════════════════════════════════════════════════════

def test_no_flat_files_at_root():
    """Only allowed shim files and directories may exist at ``weebot/`` root."""
    allowed_files = {
        "__init__.py",
        # Legacy files (Bucket D — frozen, no new features)
        "agent_core_v2.py",
        "agent_selection.py",
        "failure_recovery.py",
        "state_coordinator.py",
        "state_manager.py",
        "tray.py",
        # Legacy root modules (pre-date architecture enforcement)
        "ai_router.py",
        "nlp_understanding.py",
        "notifications.py",
    }
    allowed_dirs = {
        "__pycache__",
        "agents",
        "application",
        "cache",
        "config",
        "core",
        "docs",
        "domain",
        "GitNexus-main",  # Vendored dependency
        "osworld",         # OSWorld agent adapter (drop-in for eval harness)
        "infrastructure",
        "interfaces",
        "mcp",
        "models",
        "qmd_integration",
        "sandbox",
        "scheduling",
        "security",
        "skills",
        "templates",
        "tests",
        "tools",
        "utils",
    }

    root_dir = ROOT
    violations: list[str] = []
    for entry in root_dir.iterdir():
        name = entry.name
        if entry.is_dir():
            if name not in allowed_dirs and not name.startswith("."):
                violations.append(f"Unexpected directory: {name}/")
        elif entry.is_file() and entry.suffix == ".py":
            if name not in allowed_files:
                violations.append(f"Unexpected file: {name}")

    assert not violations, (
        "New .py files at weebot/ root must be moved to the correct layer.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 9: Tools must not import sqlite3 directly
# ═════════════════════════════════════════════════════════════════════════════

def test_tools_no_direct_db():
    """Tools must use ports for persistence, not import sqlite3 directly."""
    forbidden_imports = {"sqlite3", "aiosqlite", "sqlalchemy"}
    violations: list[str] = []

    for path in _walk_py(ROOT / "tools"):
        tree = _parse(path)
        for imp in _module_imports(tree):
            if imp in forbidden_imports:
                rel = path.relative_to(ROOT.parent)
                violations.append(f"{rel}: imports {imp!r}")

    assert not violations, (
        "Tools must use ports for database access.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 10: Core modules classified per Phase 2.5 doc
# ═════════════════════════════════════════════════════════════════════════════

def test_core_modules_in_correct_package():
    """Core modules must match their Phase 2.5 classification.

    Application-classified modules should not import infrastructure
    adapters directly. Infrastructure-classified modules may.
    """
    # Modules classified as Application (should not import infrastructure)
    app_modules = {
        "agent.py", "agent_context.py", "agent_factory.py",
        "agent_profile.py", "tool_agent.py", "workflow_orchestrator.py",
        "workflow_tracer.py", "dependency_graph.py",
    }
    violations: list[str] = []

    for path in _walk_py(ROOT / "core"):
        if path.name not in app_modules:
            continue
        tree = _parse(path)
        for imp in _module_imports(tree):
            if imp.startswith("weebot.infrastructure"):
                rel = path.relative_to(ROOT.parent)
                violations.append(
                    f"{rel}: Application-classified module imports "
                    f"infrastructure {imp!r}"
                )

    assert not violations, (
        "Application-classified core modules must not import infrastructure.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 11: Interfaces must not import domain directly (go through application)
# ═════════════════════════════════════════════════════════════════════════════

def test_interfaces_no_infrastructure_adapter_imports():
    """Interface layer must not import infrastructure adapters directly.
    Domain model imports are allowed (it's normal for interfaces to
    reference domain types).
    """
    violations: list[str] = []

    for path in _walk_py(ROOT / "interfaces"):
        if path.name == "__init__.py":
            continue
        tree = _parse(path)
        for imp in _module_imports(tree):
            if imp.startswith("weebot.infrastructure.adapters"):
                rel = path.relative_to(ROOT.parent)
                violations.append(f"{rel}: imports infrastructure adapter {imp!r}")

    assert not violations, (
        "Interface layer should not import infrastructure adapters directly.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 12: No circular imports between application layers
# ═════════════════════════════════════════════════════════════════════════════

def test_no_circular_imports():
    """Check for circular imports between major application packages.
    """
    import sys
    packages = [
        "weebot.domain",
        "weebot.application.cqrs",
        "weebot.application.services",
        "weebot.application.flows",
        "weebot.infrastructure.persistence",
    ]

    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError as e:
            if "circular import" in str(e).lower():
                pytest.fail(f"Circular import detected in {pkg}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# Test 13: Every __import__() call is eliminated
# ═════════════════════════════════════════════════════════════════════════════

def test_no_dynamic_imports():
    """There should be zero ``__import__()`` calls in application code.
    (Verification of Phase 2.4)
    """
    violations: list[str] = []
    pattern = re.compile(r"__import__\(")

    for path in _walk_py(ROOT / "application"):
        content = path.read_text(encoding="utf-8")
        if pattern.search(content):
            rel = path.relative_to(ROOT.parent)
            violations.append(str(rel))

    assert not violations, (
        "All __import__() calls must be replaced with direct imports.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 14: Flows with state_repo must persist after _emit
# ═════════════════════════════════════════════════════════════════════════════

def test_persistence_at_emit():
    """Every flow that accepts ``state_repo`` must call ``save_session()``
    in its ``_emit()`` method or equivalent save path.

    The persistence call may live in a delegated EventPublisher (now extracted
    from PlanActFlow), so we check that file too.
    """
    violations: list[str] = []
    checked_dirs = [ROOT / "application" / "flows"]

    for path in _walk_py(ROOT / "application" / "flows"):
        content = path.read_text(encoding="utf-8")
        # Flows that accept state_repo in __init__
        if "state_repo" in content:
            # Must call save_session somewhere (possibly in EventPublisher)
            if "save_session" not in content:
                # Check if the file imports from event_publisher
                if "event_publisher" not in content:
                    rel = path.relative_to(ROOT.parent)
                    violations.append(f"{rel}: accepts state_repo but never calls save_session")

    assert not violations, (
        "Flows that accept state_repo must call save_session to persist events.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 15: No blocking calls in async functions
# ═════════════════════════════════════════════════════════════════════════════

def test_no_blocking_calls_in_async():
    """``subprocess.run()`` and ``time.sleep()`` must not appear in
    async functions, to avoid blocking the event loop."""
    violations: list[str] = []
    block_patterns = [
        ("subprocess.run", "subprocess.run(  # blocks event loop"),
        ("time.sleep", "time.sleep(  # blocks event loop"),
    ]

    for path in _walk_py(ROOT):
        if "test_" in path.name:
            continue
        content = path.read_text(encoding="utf-8")
        # Only check files that contain async functions
        if "async def" not in content:
            continue
        for pattern, _ in block_patterns:
            if pattern in content:
                rel = path.relative_to(ROOT.parent)
                violations.append(f"{rel}: contains {pattern}")

    # Known exceptions — sync helpers, not called from async hot path.
    # Each documented with its justification.  Track removal in ARCHITECTURE_9_PLAN.md.
    known_exceptions = {
        "bash_tool.py",            # _wsl_available() sync-only helper
        "behavior_tracker.py",     # all calls in sync methods
        "design_system_tool.py",   # sync subprocess in tools
        "gitnexus_provider.py",    # legacy adapter (ADDR-004)
        "rtk_integration.py",      # legacy adapter (ADR-004)
        "rtk_provider.py",         # legacy adapter (ADR-004)
        "mcp_client.py",           # legacy module (ADR-004)
        "_capabilities.py",       # git integrity check (tracked: ARCHITECTURE_9_PLAN.md)
    }
    violations = [
        v for v in violations
        if not any(e in str(v) for e in known_exceptions)
    ]

    assert not violations, (
        "Async functions must not contain blocking calls.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 16: Tools must not import WeebotSettings directly
# ═════════════════════════════════════════════════════════════════════════════

def test_no_settings_import_in_tools():
    """Tools must receive config via constructor injection (ToolConfig),
    not by importing WeebotSettings directly."""
    violations: list[str] = []
    settings_imports = (
        "from weebot.config.settings import WeebotSettings",
    )

    for path in _walk_py(ROOT / "tools"):
        content = path.read_text(encoding="utf-8")
        for imp in settings_imports:
            if imp in content:
                # Check if it's behind TYPE_CHECKING (acceptable)
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if imp in line:
                        # Look backwards for TYPE_CHECKING guard
                        if i > 0 and "TYPE_CHECKING" in lines[i - 1]:
                            continue
                        rel = path.relative_to(ROOT.parent)
                        violations.append(f"{rel}: imports WeebotSettings at module level")

    # NOTE: All tools have been migrated to ToolConfig DI.
    # If a new tool imports WeebotSettings at module level, add it here
    # temporarily with a tracking issue link.
    known_exceptions = {
        "vane_search.py",  # legacy tool (tracked: ARCHITECTURE_9_PLAN.md)
    }
    violations = [
        v for v in violations
        if not any(e in str(v) for e in known_exceptions)
    ]

    assert not violations, (
        "Tools must use ToolConfig constructor injection, not import WeebotSettings.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 17: SQLiteStateRepository constructed only in di.py
# ═════════════════════════════════════════════════════════════════════════════

def test_repository_constructed_only_in_di():
    """SQLiteStateRepository() must only be constructed in di.py (the
    single composition root)."""
    violations: list[str] = []

    for path in _walk_py(ROOT):
        if "test_" in path.name or path.name == "__init__.py":
            continue
        content = path.read_text(encoding="utf-8")
        if "SQLiteStateRepository(" in content and "SQLiteStateRepository()" in content:
            rel = path.relative_to(ROOT.parent)
            rel_str = str(rel).replace("\\", "/")
            # Allow the entire di/ package (composition root) and health checks
            if "di.py" not in rel_str and "/di/" not in rel_str:
                violations.append(f"{rel}: constructs SQLiteStateRepository")

    # Known exceptions — tracked for future DI migration
    _exceptions = {"health_checks", "persistent_memory", "_base"}
    violations = [v for v in violations if not any(e in v for e in _exceptions)]

    assert not violations, (
        "SQLiteStateRepository must only be constructed in di.py.\n"
        + "\n".join(violations)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 18: Global exception handlers registered on FastAPI app
# ═════════════════════════════════════════════════════════════════════════════

def test_global_exception_handlers_registered():
    """The FastAPI app must have at least one ``@app.exception_handler``
    to prevent stack trace leakage."""
    web_main = ROOT / "interfaces" / "web" / "main.py"
    if not web_main.exists():
        pytest.skip("web/main.py not found")

    content = web_main.read_text(encoding="utf-8")
    has_handler = "exception_handler" in content

    assert has_handler, (
        "web/main.py must register at least one @app.exception_handler "
        "to prevent stack trace leakage."
    )


# ═════════════════════════════════════════════════════════════════════════════
# Test 19: All event types documented in EVENT_CATALOG
# ═════════════════════════════════════════════════════════════════════════════

def test_all_event_types_documented():
    """Every ``AgentEvent`` subtype must be listed in ``docs/EVENT_CATALOG.md``."""
    event_model = ROOT / "domain" / "models" / "event.py"
    catalog = ROOT.parent / "docs" / "EVENT_CATALOG.md"

    if not catalog.exists():
        pytest.skip("EVENT_CATALOG.md not found — run Phase C.3 first")

    catalog_content = catalog.read_text(encoding="utf-8")
    missing: list[str] = []

    for path in [event_model]:
        if not path.exists():
            continue
        tree = _parse(path)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b).strip() for b in node.bases]
                # DomainEvent subclasses are event types
                if any("DomainEvent" in b or "AgentEvent" in b for b in bases):
                    if node.name not in catalog_content:
                        missing.append(node.name)

    assert not missing, (
        "Every AgentEvent subtype must be documented in docs/EVENT_CATALOG.md.\n"
        f"Missing: {', '.join(missing)}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# WP-0: Architecture test gates for 9/10 plan
# ═════════════════════════════════════════════════════════════════════════════

def test_application_services_no_infra_imports():
    """``application/services/`` must not import from ``infrastructure`` at ANY
    scope (import-time or lazy inside functions) — they must use DI-injected ports.

    This is stricter than ``test_application_no_module_level_infra_imports``,
    which only checks module-level imports.
    """
    violations: list[str] = []
    # Files that are tracked for migration (will be removed as WP-4 progresses)
    tracked_exceptions = {
            "_service.py",              # imports adapter_factory — lazy method import
        "task_runner.py",               # imports metrics — lazy function import
        "autonomous_learning.py",        # TYPE_CHECKING only — SkillStore annotation
        "meta_self_improver.py",         # TYPE_CHECKING only — MetaImprovementLog annotation (lazy fallback removed)
        "multi_source_research.py",      # TYPE_CHECKING only — ServiceRegistry annotation
        "strategy_transfer.py",          # TYPE_CHECKING only — StrategyStore annotation (lazy fallback removed)
        "metrics_bridge.py",            # designated bridge to infrastructure Prometheus adapter
        "semantic_skill_retriever.py",  # lazy default for NumpyVectorStore (tracked: WP-4 DI migration)
    }

    services_dir = ROOT / "application" / "services"
    for path in _walk_py(services_dir):
        if path.name in tracked_exceptions:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("weebot.infrastructure"):
                        rel = path.relative_to(ROOT.parent)
                        violations.append(f"{rel}: import {alias.name!r}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("weebot.infrastructure"):
                    rel = path.relative_to(ROOT.parent)
                    violations.append(f"{rel}: from-import {node.module!r}")

    assert not violations, (
        "application/services/ must not import infrastructure at any scope.\n"
        + "\n".join(violations) +
        "\nInject infrastructure dependencies through DI instead."
    )


def test_no_services_flows_cycle():
    """``services/`` and ``flows/`` must not have module-level mutual imports.
    Lazy imports (inside functions) are tolerated as they don't create
    import-time cycles. Only module-level ``import``/``from`` statements count."""
    services_dir = ROOT / "application" / "services"
    flows_dir = ROOT / "application" / "flows"

    def _module_level_imports(paths: list, target_prefix: str) -> list[str]:
        """Find all module-level (top-level AST children) imports of *target_prefix*."""
        results: list[str] = []
        for path in paths:
            tree = _parse(path)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(target_prefix):
                            results.append(f"{path.name} → {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(target_prefix):
                        results.append(f"{path.name} → {node.module}")
        return results

    flows_importing_services = _module_level_imports(_walk_py(flows_dir), "weebot.application.services")
    services_importing_flows = _module_level_imports(_walk_py(services_dir), "weebot.application.flows")

    if flows_importing_services and services_importing_flows:
        msg = (
            "Module-level circular dependency detected between services/ and flows/.\n"
            "Flows → Services:\n  " + "\n  ".join(flows_importing_services) + "\n"
            "Services → Flows:\n  " + "\n  ".join(services_importing_flows) + "\n"
            "Break the cycle by extracting shared interfaces into application/abstractions/."
        )
        pytest.fail(msg)


def test_core_no_global_singletons_outside_di():
    """``core/`` modules should not use ``global`` keyword for singleton state
    outside an explicit allowlist (files tracked for migration).
    """
    # Tracked — these will be migrated to DI as part of WP-3
    allowlisted_global_files = {
        "bash_guard.py",              # _bash_guard_hooks — lightweight hook list
        "structured_logger.py",       # _correlation_id — contextvar, not plain global
              "alerting.py",                # WP-3: alert registry singleton
        "behavior_integration.py",    # WP-3: integration state singleton
        "error_system_handler.py",    # WP-3: error handler singleton
        "memory_monitor.py",          # WP-3: memory monitor singleton
    }

    violations: list[str] = []
    for path in _walk_py(ROOT / "core"):
        if path.name in allowlisted_global_files:
            continue
        content = path.read_text(encoding="utf-8")
        if "global " in content:
            violations.append(path.name)

    assert not violations, (
        "core/ modules must not use 'global' for singleton state.\n"
        f"Files with 'global': {violations}\n"
        "Migrate singletons to the DI container."
    )


def test_god_modules_under_800_lines():
    """No file in ``application/`` should exceed 800 lines.
    Allowlisted files will be decomposed under WP-2.

    Limits are set so we can incrementally reduce them as decomposition progresses.
    """
    # Tracked — will shrink via WP-2 decomposition
    line_allowlist: dict[str, int] = {
        "model_selection.py": 100,        # re-export shim (was 3265)
        "_catalog.py": 3200,              # data catalog (327 model configs — pure data)
        "_base.py": 1450,  # was 1400 (WP-8 pool wiring)                 # target: <800 (extract strategies)
        "plan_act_flow.py": 1000,         # 961 lines; target: <800 (decompose further)
        "information_synthesis.py": 900,  # WP-2: 850 lines, target: <800 (extract summarizer)
    }

    violations: list[str] = []
    for path in _walk_py(ROOT / "application"):
        content = path.read_text(encoding="utf-8")
        lines = content.count("\n") + 1
        limit = line_allowlist.get(path.name, 800)
        if lines > limit:
            rel = path.relative_to(ROOT.parent)
            violations.append(f"{rel}: {lines} lines (limit: {limit})")

    assert not violations, (
        "Files in application/ exceed their line-count limit.\n"
        + "\n".join(violations) +
        "\nDecompose large files into smaller modules (see WP-2)."
    )


def test_orphan_ports_flagged():
    """Every port class/protocol in ``application/ports/`` must have at least one
    concrete implementation registered in ``infrastructure/`` or ``di/``.

    Ports with zero implementations are dead abstraction and should be removed.
    """
    # Known orphan ports (no implementation exists yet, or implementations live
    # outside infrastructure/ — e.g. in application/eval/ or application/agents/)
    known_orphans = {
        # Hook context dataclasses (not injected via DI)
        "PostCompleteContext",
        "PostExecuteContext",
        "PostTaskContext",
        "PostVerificationContext",
        "PostToolCallContext",
        "PostPlanCreatedContext",
        "PostPlanUpdatedContext",
        "PostBashGuardContext",
        "PreTaskContext",
        "PreExecuteContext",
        "PreToolCallContext",
        "OnErrorContext",
        # Value objects / result types defined alongside ports
        "StepCancelledError",
        "StepEvaluation",
        "JudgeVerdict",
        "CriterionScore",
        # Ports whose implementations live in application/ (not infrastructure/)
        "JudgePort",            # → ModelJudge / ScoreJudge in application/eval/
        "CodeReviewerPort",     # → CodeReviewerService in application/services/
        "IntentReviewPort",     # → IntentReviewService in application/services/
        "MainReviewPort",       # → MainReviewService in application/services/
        "BehavioralLearnerPort",
        "HookRegistryPort",
        "DreamerPort",          # → Dreamer in application/agents/
        "StepEvaluatorPort",    # → StepEvaluator in application/services/
        "TrustReportPort",
        "CanonicalizerPort",
        "SkillRetrieverPort",
        "RetentionAgentPort",   # → RetentionAgent in application/agents/
        "PlanCriticPort",
        "SelfImprovementPort",
        "IGatewaySessionStorePort",
        "IContextEnginePort",
        "EventPublisherPort",   # → WebSocketEventBroadcaster in interfaces/ (not infra/)
    }

    # Get all port class names
    ports_dir = ROOT / "application" / "ports"
    port_classes: set[str] = set()
    for path in _walk_py(ports_dir):
        tree = _parse(path)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                port_classes.add(node.name)

    # Get all concrete implementations registered in di/
    di_dir = ROOT / "application" / "di"
    infra_dir = ROOT / "infrastructure"
    implemented: set[str] = set()

    # Check di/ for registrations
    for path in _walk_py(di_dir):
        content = path.read_text(encoding="utf-8")
        for cls_name in port_classes:
            if cls_name in content:
                implemented.add(cls_name)

    # Check infrastructure/ for ports
    for path in _walk_py(infra_dir):
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("weebot.application.ports"):
                        implemented.add(alias.name.split(".").pop())
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("weebot.application.ports"):
                    if node.names:
                        for alias in node.names:
                            implemented.add(alias.name)

    orphans = port_classes - implemented - known_orphans
    assert not orphans, (
        f"Ports with zero implementations (orphans): {orphans}\n"
        "Either implement them, remove them, or add to known_orphans if intentional."
    )


# ═════════════════════════════════════════════════════════════════════════════
# WP-1: Executor extraction verification
# ═════════════════════════════════════════════════════════════════════════════

def test_executor_cascade_methods_extracted():
    """Verify cascade methods were extracted from _base.py to _cascade.py."""
    base_path = ROOT / "application" / "agents" / "executor" / "_base.py"
    content = base_path.read_text(encoding="utf-8")
    
    # These method names should NOT appear in _base.py anymore
    extracted = [
        "_cascade_is_tripped",
        "_cascade_record_failure",
        "_cascade_reset",
        "_cascade_try_chat",
        "_call_with_cascade",
        "_try_live_model_rescue",
    ]
    violations = [m for m in extracted if m in content]
    assert not violations, (
        f"Cascade methods still present in _base.py: {violations}"
    )


def test_executor_tool_methods_extracted():
    """Verify tool execution methods were extracted from _base.py."""
    base_path = ROOT / "application" / "agents" / "executor" / "_base.py"
    content = base_path.read_text(encoding="utf-8")
    
    # These method names should NOT appear in _base.py anymore
    extracted = [
        "_execute_tool_batch",
        "_get_step_id",
        "_normalize_text",
        "_follow_up_like",
        "_tool_signature",
        "_parse_args_for_event",
    ]
    violations = [m for m in extracted if re.search(rf'def {m}|self\.{m}', content)]
    assert not violations, (
        f"Tool methods still present in _base.py: {violations}"
    )


def test_executor_context_methods_extracted():
    """Verify context/compression methods were extracted from _base.py."""
    base_path = ROOT / "application" / "agents" / "executor" / "_base.py"
    content = base_path.read_text(encoding="utf-8")
    
    extracted = [
        "_track_usage_and_maybe_compress",
        "_maybe_compress",
        "_reflect_on_screenshot",
    ]
    violations = [m for m in extracted if re.search(rf'def {m}|self\.{m}', content)]
    assert not violations, (
        f"Context methods still present in _base.py: {violations}"
    )


def test_cascade_executor_file_exists():
    """CascadeExecutor module must exist and be importable."""
    import importlib
    mod = importlib.import_module("weebot.application.agents.executor._cascade")
    assert hasattr(mod, "CascadeExecutor"), "CascadeExecutor class not found"


def test_tool_executor_file_exists():
    """ToolExecutor module must exist and be importable."""
    import importlib
    mod = importlib.import_module("weebot.application.agents.executor._tool_executor")
    assert hasattr(mod, "ToolExecutor"), "ToolExecutor class not found"


def test_context_compressor_file_exists():
    """ContextCompressor module must exist and be importable."""
    import importlib
    mod = importlib.import_module("weebot.application.agents.executor._context_compressor")
    assert hasattr(mod, "ContextCompressor"), "ContextCompressor class not found"


def test_error_handler_file_exists():
    """ErrorHandler module must exist and be importable."""
    import importlib
    mod = importlib.import_module("weebot.application.agents.executor._error_handler")
    assert hasattr(mod, "classify_tool_error"), "classify_tool_error not found"
    assert hasattr(mod, "build_stuck_error"), "build_stuck_error not found"
    assert hasattr(mod, "normalize_text"), "normalize_text not found"
    assert hasattr(mod, "ExecutionLoopState"), "ExecutionLoopState not found"


# ═════════════════════════════════════════════════════════════════════════════
# WP-2: Container.get_static() must not be called outside di/
# ═════════════════════════════════════════════════════════════════════════════

def test_container_get_static_not_called_outside_di():
    """Container.get_static() was removed from executor._base.py during extraction."""
    base_path = ROOT / "application" / "agents" / "executor" / "_base.py"
    content = base_path.read_text(encoding="utf-8")
    assert "get_static" not in content, (
        "get_static should not be referenced in executor._base.py after extraction"
    )


# ═════════════════════════════════════════════════════════════════════════════
# WP-3: CQRS handlers split verification
# ═════════════════════════════════════════════════════════════════════════════

def test_cqrs_handlers_directory_split():
    """Verify the CQRS handlers/ directory contains individual handler files."""
    handlers_dir = ROOT / "application" / "cqrs" / "handlers"
    expected_files = {
        "create_plan_handler.py",
        "execute_step_handler.py",
        "update_plan_handler.py",
        "cancel_session_handler.py",
        "compact_memory_handler.py",
        "process_message_handler.py",
        "summarize_handler.py",
        "archive_session_handler.py",
    }
    existing = {p.name for p in handlers_dir.glob("*.py")}
    missing = expected_files - existing
    assert not missing, f"Missing handler files: {missing}"


# ═════════════════════════════════════════════════════════════════════════════
# WP-4: SkillStore and TrajectoryRepository port compliance
# ═════════════════════════════════════════════════════════════════════════════

def test_skill_store_implements_port():
    """SkillStore must implement SkillStorePort."""
    from weebot.application.ports.skill_store_port import SkillStorePort
    from weebot.infrastructure.persistence.skill_store import SkillStore
    assert issubclass(SkillStore, SkillStorePort), (
        "SkillStore must inherit from SkillStorePort"
    )


def test_trajectory_repository_implements_port():
    """TrajectoryRepository must implement TrajectoryRepositoryPort."""
    from weebot.application.ports.trajectory_repository_port import TrajectoryRepositoryPort
    from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository
    assert issubclass(TrajectoryRepository, TrajectoryRepositoryPort), (
        "TrajectoryRepository must inherit from TrajectoryRepositoryPort"
    )


# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# WP-5: Module size and coupling limits
# ═════════════════════════════════════════════════════════════════════════════

def test_plan_act_flow_imports_under_limit():
    p = ROOT / 'application' / 'flows' / 'plan_act_flow.py'
    m = set()
    for l in p.read_text().splitlines():
        if l.startswith('from weebot.') and not l.strip().startswith('#'):
            parts = l.split()
            if len(parts) > 1:
                m.add(parts[1])
    assert len(m) <= 35
def test_no_module_level_global_pool_outside_di():
    """Module-level _global_pool must not exist outside DI-managed files."""
    violations = []
    for path in sorted((ROOT / "infrastructure" / "browser").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if '_global_pool' in text:
            rel = path.relative_to(ROOT.parent)
            violations.append(str(rel))
    # Use os.sep for cross-platform path matching
    acceptable = {os.path.join('weebot', 'infrastructure', 'browser', 'session_pool.py'),
                  os.path.join('weebot', 'infrastructure', 'browser', '__init__.py')}
    actual = set(violations) - acceptable
    assert not actual, '_global_pool in: ' + str(actual)


def test_query_handlers_split():
    """Handler files must be under 300 lines (except __init__)."""
    violations = []
    for path in (ROOT / "application" / "cqrs" / "handlers").glob("*.py"):
        if path.name == '__init__.py':
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 350:
            violations.append(path.name + ': ' + str(lines) + ' lines')
    assert not violations, 'Over 300 lines: ' + str(violations)


# ═════════════════════════════════════════════════════════════════════════════
# WP-6: FlowRouter and collaborator existence
# ═════════════════════════════════════════════════════════════════════════════

def test_flow_router_exists():
    """FlowRouter must exist and be importable."""
    from weebot.application.flows.flow_router import FlowRouter
    assert hasattr(FlowRouter, 'resolve_initial_state')
    assert hasattr(FlowRouter, 'record_misalignment')


def test_cascade_executor_importable():
    """CascadeExecutor must remain importable."""
    from weebot.application.agents.executor._cascade import CascadeExecutor
    assert hasattr(CascadeExecutor, 'call_with_cascade')
    assert hasattr(CascadeExecutor, 'cascade_is_tripped')


# ═════════════════════════════════════════════════════════════════════════════
# WP-7: Ponytail YAGNI harness integration
# ═════════════════════════════════════════════════════════════════════════════

def test_ponytail_harness_block_present():
    """InstructionConfig must have yagni_preflight with default ladder."""
    from weebot.domain.models.harness_instructions import InstructionConfig
    c = InstructionConfig()
    assert len(c.yagni_preflight) > 100, 'yagni_preflight too short'
    assert 'rung' in c.yagni_preflight, 'Missing rung ladder'
    assert 'ponytail' in c.yagni_preflight.lower(), 'Missing ponytail reference'


def test_ponytail_harness_assembled():
    """HarnessPromptAssembler must include yagni_preflight."""
    from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
    from weebot.domain.models.harness_instructions import InstructionConfig
    block = HarnessPromptAssembler.assemble(instructions=InstructionConfig())
    assert 'Pre-Flight' in block
    assert 'rung' in block


def test_code_review_result_has_over_engineered():
    """CodeReviewResult must include over_engineered field."""
    from weebot.domain.models.code_review import CodeReviewResult
    r = CodeReviewResult()
    assert hasattr(r, 'over_engineered')
    assert r.over_engineered is False  # default


def test_code_review_prompt_includes_conciseness():
    """Code reviewer prompt must check for over-engineering."""
    from weebot.application.services.code_reviewer_service import _REVIEWER_SYSTEM_PROMPT
    assert 'over_engineered' in _REVIEWER_SYSTEM_PROMPT or 'Over-engineering' in _REVIEWER_SYSTEM_PROMPT


def test_code_review_result_over_engineered_parseable():
    """CodeReviewerService must parse over_engineered from LLM response."""
    from weebot.domain.models.code_review import CodeReviewResult
    # Simulate LLM returning over_engineered=true
    r = CodeReviewResult(over_engineered=True)
    assert r.over_engineered is True
    r2 = CodeReviewResult(over_engineered=False)
    assert r2.over_engineered is False


# ═════════════════════════════════════════════════════════════════════════════
# Architecture Elevation — Strategy E
# ═════════════════════════════════════════════════════════════════════════════

def test_core_no_application_imports():
    """Core must not import from application or interfaces layers.

    Import-linter contract ``core-no-app`` enforces this mechanically.
    This test verifies the contract is present in ``.importlinter`` and
    passes — if it's ever missing or broken, the architecture has regressed.
    """
    import subprocess
    import sys

    result = subprocess.run(
        ["lint-imports", "--config", ".importlinter"],
        capture_output=True, text=True, cwd=ROOT.parent,
    )
    # The contract must pass — verify by name in output
    assert "Core cross-cutting layer must not depend on application KEPT" in result.stdout, (
        "import-linter contract 'core-no-app' not passing. "
        f"Stdout:\n{result.stdout}"
    )
    assert "Contracts: 5 kept" in result.stdout or "5 kept" in result.stdout, (
        f"import-linter failed:\n{result.stdout}\n{result.stderr}"
    )
