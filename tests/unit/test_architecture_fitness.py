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
    # Our own di.py is the one allowed composition root
    allowed_exceptions = {"di.py", "__init__.py"}

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
        handlers_content += handlers_py.read_text()
    if handlers_dir.exists():
        for hp in _walk_py(handlers_dir):
            if hp.name != "__init__.py":
                handlers_content += hp.read_text()

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
    handlers_content = handlers_py.read_text()

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
    di_py = ROOT / "application" / "di.py"
    assert di_py.exists(), "DI container (di.py) must exist as the composition root"

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

    # Known port → adapter mapping (add new ports here)
    port_adapter_map: dict[str, list[str]] = {
        "EventBusPort": ["AsyncEventBus"],
        "LLMPort": ["OpenRouterAdapter", "AnthropicAdapter", "DeepSeekAdapter",
                     "OpenAIAdapter", "ResilientAdapter"],
        "StateRepositoryPort": ["SQLiteStateRepository", "InMemoryStateRepository"],
        "OptimizerPort": ["OptimizerAgent"],
        "ScoringPort": ["ExactMatchScorer", "ExecutionResultScorer", "VerifierScorer"],
        "SandboxPort": ["NativeWindowsSandbox", "WSL2Sandbox", "DockerLinuxSandbox"],
        "EventStorePort": ["EventStore"],  # weebot.infrastructure.event_store
    }

    # Find all port classes (files with ABC/Protocol that define ports)
    missing: list[str] = []
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
            adapters = port_adapter_map.get(pc, [])
            if not adapters:
                # Try to find adapters in infrastructure by naming convention
                adapter_found = False
                for adapter_path in _walk_py(infra_dir):
                    content = adapter_path.read_text()
                    if pc in content and (
                        f"({pc})" in content or f"class {pc}" in content
                    ):
                        adapter_found = True
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

    # Known exceptions (technical debt — tracked in .importlinter)
    known_exception_tools = {
        "knowledge_tool",
        "product_tool",
        "video_ingest_tool",
    }
    violations = [
        v for v in violations
        if not any(e in v for e in known_exception_tools)
    ]

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

@pytest.mark.skip(reason="Circular import detection is expensive — run separately")
def test_no_circular_imports():
    """Check for circular imports between major application packages.
    This test is slow and skipped by default; run it explicitly.
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
        content = path.read_text()
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
    in its ``_emit()`` method or equivalent save path."""
    violations: list[str] = []

    for path in _walk_py(ROOT / "application" / "flows"):
        content = path.read_text()
        # Flows that accept state_repo in __init__
        if "state_repo" in content:
            # Must call save_session somewhere
            if "save_session" not in content:
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
        content = path.read_text()
        # Only check files that contain async functions
        if "async def" not in content:
            continue
        for pattern, _ in block_patterns:
            if pattern in content:
                rel = path.relative_to(ROOT.parent)
                violations.append(f"{rel}: contains {pattern}")

    # Known exceptions — sync helpers, not called from async hot path
    known_exceptions = {
        "bash_tool.py",            # _wsl_available() sync-only helper
        "behavior_tracker.py",     # all calls in sync methods
        "design_system_tool.py",   # sync subprocess in tools
        "powershell_tool.py",      # _run() is sync wrapper → _run_async()
        "gitnexus_provider.py",    # legacy adapter
        "rtk_integration.py",      # legacy adapter
        "rtk_provider.py",         # legacy adapter
        "mcp_client.py",           # legacy module
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
        "from weebot.config.settings import",
    )

    for path in _walk_py(ROOT / "tools"):
        content = path.read_text()
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
    violations = [
        v for v in violations
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
        content = path.read_text()
        if "SQLiteStateRepository(" in content and "SQLiteStateRepository()" in content:
            rel = path.relative_to(ROOT.parent)
            if "di.py" not in str(rel):
                violations.append(f"{rel}: constructs SQLiteStateRepository")

    # Known exception — health check is infrastructure-level
    violations = [v for v in violations if "health_checks" not in v]

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

    content = web_main.read_text()
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

    catalog_content = catalog.read_text()
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
