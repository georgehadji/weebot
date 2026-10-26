"""Every concrete tool declares what it trusts, and the reviewed LOCAL list is pinned.

History: ``UNTRUSTED_OUTPUT_TOOLS`` was a hand-kept set of tool names, and it
drifted three times (module file names instead of ``BaseTool.name``, missing
Apify presets, missing registered tools). Each drift left a real tool unfenced
and untainted for the egress trifecta check, and each one passed every test that
asserted a *string* was in the set.

SEC-1 removed the list: trust is an ``output_trust`` attribute on the tool type
and a tool nobody classified defaults to ``EXTERNAL``. What can still go wrong
is a tool declared ``LOCAL`` (or ``FIXED_SCHEMA``) that should not be. So this
file pins those two sets. Adding a name to either is a security decision and
shows up as an edit here, in review.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from weebot.core.egress_guard import _BROWSER_EGRESS_TOOLS
from weebot.core.trust_boundary import must_fence, must_taint, trust_of

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_TOOLS_DIR = _ROOT / "weebot" / "tools"
_MCP_DIR = _ROOT / "weebot" / "infrastructure" / "mcp"

# Reviewed 2026-10-24 (plan 1.1). A tool is LOCAL only if no third party can choose the
# text it returns. The review moved six tools to EXTERNAL because they relay third-party
# text: swarm, dispatch_parallel_tasks, workflow_orchestrator and debate run sub-agents
# that have tools (and may have browsed), design_system scrapes remote sites, and
# desktop_a11y returns other applications' UI text. What stays LOCAL, and why:
#   bash, python_execute, powershell -- stdout can carry fetched text, but the network
#       is gated separately (sandbox network off by default, EgressGuard on every send);
#       EXTERNAL would taint nearly every session and train users to disable the guard.
#   computer_use, screen_capture -- action confirmations and images of the user's own
#       screen, no text a tool fetched; screenshot_ocr and ocr are EXTERNAL.
#   voice_input -- the user's own microphone.
#   mixture_of_agents, reasoner -- model text, no tools.
#   persistent_memory, knowledge, todo_write, schedule, product, berb, audit_session --
#       the agent's own records.
#   image_gen, video_gen, voice_output, remotion_video, ask_human, terminate,
#       detect_elements -- generated or local artifacts and control signals.
REVIEWED_LOCAL = frozenset(
    {
        "audit_session",
        "ask_human",
        "bash",
        "berb",
        "computer_use",
        "detect_elements",
        "image_gen",
        "knowledge",
        "mixture_of_agents",
        "persistent_memory",
        "powershell",
        "product",
        "python_execute",
        "reasoner",
        "remotion_video",
        "schedule",
        "screen_capture",
        "terminate",
        "todo_write",
        "video_gen",
        "voice_input",
        "voice_output",
    }
)

# Fixed-schema, single-origin endpoints whose text no third party chooses.
REVIEWED_FIXED_SCHEMA = frozenset({"weather"})


def _declared_trust(cls: ast.ClassDef) -> str | None:
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "output_trust"
            and isinstance(stmt.value, ast.Attribute)
        ):
            return stmt.value.attr
    return None


def _tool_name(cls: ast.ClassDef) -> str | None:
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "name"
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
            and stmt.value.value
        ):
            return stmt.value.value
    return None


def _tool_classes() -> list[tuple[str, str, str | None, str | None]]:
    """``(file, class, tool name, declared trust)`` for each concrete tool.

    Parsed rather than imported: importing every tool drags in optional
    third-party dependencies that need not be installed to read a class body.
    A class is a tool if it derives from ``BaseTool`` or carries a ``name``
    string (the duck-typed ``BrowserTool`` has no base).
    """
    found = []
    for directory in (_TOOLS_DIR, _MCP_DIR):
        for path in sorted(directory.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {
                    b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                    for b in node.bases
                }
                name = _tool_name(node)
                if "BaseTool" in bases or name is not None:
                    found.append((path.name, node.name, name or node.name, _declared_trust(node)))
    return found


class TestEveryToolDeclaresItsTrust:
    def test_the_parse_finds_the_tools(self):
        """Guard the guard: a parser returning nothing would pass everything."""
        names = {name for _, _, name, _ in _tool_classes()}
        assert len(names) > 30, f"tool parse looks broken: {sorted(names)}"
        assert {"bash", "browser_navigator", "web_search", "weather"} <= names

    def test_every_concrete_tool_assigns_output_trust_explicitly(self):
        missing = [f"{file}:{cls}" for file, cls, _, trust in _tool_classes() if trust is None]
        assert not missing, (
            "these tools rely on the inherited default (EXTERNAL). That is safe, but "
            "the default is for tools nobody has looked at: state the choice with "
            f"`output_trust: ClassVar[OutputTrust] = OutputTrust.X`.\n{missing}"
        )

    def test_the_local_list_is_pinned(self):
        local = {name for _, _, name, trust in _tool_classes() if trust == "LOCAL"}
        assert local == REVIEWED_LOCAL, (
            "LOCAL output is neither fenced nor tainting. Adding a tool to it is a "
            "security decision: update REVIEWED_LOCAL with the reasoning in review.\n"
            f"added: {sorted(local - REVIEWED_LOCAL)}  removed: {sorted(REVIEWED_LOCAL - local)}"
        )

    def test_the_fixed_schema_list_is_pinned(self):
        fixed = {name for _, _, name, trust in _tool_classes() if trust == "FIXED_SCHEMA"}
        assert fixed == REVIEWED_FIXED_SCHEMA, (
            "FIXED_SCHEMA exempts a tool from the egress trifecta check. It requires "
            "a fixed-schema, single-origin endpoint whose text no third party can choose."
        )


class TestRuntimeAgreesWithTheSource:
    def test_every_imported_tool_subclass_declares_it_in_its_own_body(self):
        """The AST pass can miss an aliased base; the class hierarchy cannot."""
        import importlib

        from weebot.domain.models.base_tool import BaseTool

        for path in sorted(_TOOLS_DIR.glob("*.py")):
            if path.stem.startswith("_"):
                continue
            try:
                importlib.import_module(f"weebot.tools.{path.stem}")
            except Exception:  # optional dependency missing: the AST test covers the file
                continue

        undeclared = []
        stack = list(BaseTool.__subclasses__())
        while stack:
            cls = stack.pop()
            stack.extend(cls.__subclasses__())
            if cls.__module__.startswith(("weebot.tools", "weebot.infrastructure.mcp")):
                if "output_trust" not in cls.__dict__ and "output_trust" not in getattr(
                    cls, "__annotations__", {}
                ):
                    undeclared.append(f"{cls.__module__}.{cls.__name__}")
        assert not undeclared, f"BaseTool subclasses without their own output_trust: {undeclared}"


class TestRelayToolsAreExternal:
    """The 2026-10-24 review: tools that relay third-party text must not be LOCAL."""

    @pytest.mark.parametrize(
        "name",
        [
            "swarm",
            "dispatch_parallel_tasks",
            "workflow_orchestrator",
            "debate",
            "design_system",
            "desktop_a11y",
        ],
    )
    def test_relay_tools_fence_and_taint(self, name):
        declared = {n: t for _, _, n, t in _tool_classes()}
        assert declared[name] == "EXTERNAL", f"{name!r} relays text a third party can write"


class TestKnownTools:
    @pytest.mark.parametrize(
        "name",
        [
            "web_search",
            "vane_search",
            "advanced_browser",
            "browser_navigator",
            "browser_inspector",
            "web_scraper",
            "moli_fetch",
            "agent_reach",
            "camofox_browser",
            "spacescraper",
            "search_images",
            "video_ingest",
            "youtube_download",
            "ocr",
            "ocr_structured",
            "screenshot_ocr",
            "atomic_mail",
            "file_editor",
            "search_history",
        ],
    )
    def test_attacker_authored_sources_are_external(self, name):
        declared = {n: t for _, _, n, t in _tool_classes()}
        assert declared[name] == "EXTERNAL", (
            f"{name!r} returns content a third party can write; it must fence and taint"
        )


def test_apify_preset_output_is_untrusted():
    """The presets are named apify_<actor>; they inherit the class declaration (F46)."""
    from weebot.tools.apify_presets import create_apify_preset_tools

    tools = create_apify_preset_tools(object())
    assert tools and all(t.name.startswith("apify_") for t in tools)
    for tool in tools:
        trust = trust_of(tool)
        assert must_fence(trust) and must_taint(trust, False), tool.name


def test_browser_egress_set_names_real_tools():
    """EgressGuard carried the same stale spelling as the trust boundary did."""
    registered = {name for _, _, name, _ in _tool_classes()}
    assert "browser_navigator" in _BROWSER_EGRESS_TOOLS
    # "browser_tool" is the module-name spelling, kept deliberately: an unmatched
    # egress name over-gates nothing.
    assert _BROWSER_EGRESS_TOOLS - registered <= {"browser_tool"}
